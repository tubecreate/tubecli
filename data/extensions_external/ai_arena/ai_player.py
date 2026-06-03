"""
AI Player Adapter — Kết nối AI model với game engine.
Hỗ trợ: Ollama, DeepSeek, Gemini, OpenAI, Claude, Grok, GitHub Models.
Theo dõi token usage per turn.

QUAN TRỌNG: Nếu AI fail hết retry → chọn nước đi ngẫu nhiên (KHÔNG forfeit).
"""
import logging
import random
import re
import time
import requests
from typing import Any, Optional

logger = logging.getLogger("AIArena.AIPlayer")


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English, ~2 for CJK."""
    return max(1, len(text) // 4)


class AIPlayer:
    """Adapter: AI Model → Game Player."""

    def __init__(
        self,
        player_id: str,
        name: str,
        provider: str,
        model: str,
        api_key: str = "",
        emoji: str = "🤖",
        agent_id: str = "",
        skill_block: str = "",
    ):
        self.player_id = player_id
        self.name = name
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.emoji = emoji
        self.agent_id = agent_id          # linked Agent in agent manager (optional)
        self.skill_block = skill_block    # learned chess principles, injected into prompts
        self.elo = 1500
        self.total_tokens_used = 0
        self.total_api_calls = 0
        self.stats = {
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "games_played": 0,
        }

    def decide_move(self, game, state: dict, retry_count: int = 5) -> dict:
        """Call AI to decide a move. Returns dict with move + metadata.
        
        Nếu AI fail hết retry → random move thay vì forfeit.
        """
        prompt = game.render_state_for_ai(state, self.player_id)
        # Inject the agent's learned chess principles, if any.
        if self.skill_block:
            prompt = prompt + "\n" + self.skill_block
        prompt_tokens = _estimate_tokens(prompt)

        last_error = None
        for attempt in range(retry_count):
            start_time = time.time()
            raw_response = self._call_ai(prompt)
            elapsed = time.time() - start_time

            response_tokens = _estimate_tokens(raw_response)
            turn_tokens = prompt_tokens + response_tokens
            self.total_tokens_used += turn_tokens
            self.total_api_calls += 1

            logger.info(f"[{self.name}] Attempt {attempt+1}: got {len(raw_response)} chars in {elapsed:.1f}s")

            # Check for API errors
            if raw_response.startswith("[ERROR]") or raw_response.startswith("[QUOTA_ERROR]"):
                last_error = raw_response
                logger.warning(f"[{self.name}] API error (attempt {attempt + 1}/{retry_count}): {raw_response[:200]}")
                time.sleep(1)  # Small delay before retry
                continue

            try:
                move = game.parse_ai_move(raw_response, state, self.player_id)
                # Generate chat message from AI
                chat_msg = self._extract_chat(raw_response)

                logger.info(f"[{self.name}] ✅ Move: {move} (attempt {attempt+1})")
                return {
                    "move": move,
                    "raw_response": raw_response[:500],
                    "thinking_time": round(elapsed, 2),
                    "tokens_used": turn_tokens,
                    "prompt_tokens": prompt_tokens,
                    "response_tokens": response_tokens,
                    "total_tokens": self.total_tokens_used,
                    "api_calls": self.total_api_calls,
                    "chat_message": chat_msg,
                    "attempt": attempt + 1,
                }
            except ValueError as e:
                last_error = str(e)
                logger.warning(f"[{self.name}] Parse error (attempt {attempt + 1}/{retry_count}): {e}")
                logger.warning(f"[{self.name}] Raw response was: {raw_response[:300]}")
                # Add hint to retry
                prompt += f"\n\n[SYSTEM: Your previous response was invalid: {e}. Please respond with ONLY the move, nothing else.]\n"

        # ═══ FALLBACK: Random legal move instead of forfeit ═══
        logger.warning(f"[{self.name}] All {retry_count} retries failed! Picking random move.")
        try:
            valid_moves = game.get_valid_moves(state, self.player_id)
            if valid_moves:
                random_move = random.choice(valid_moves)
                logger.info(f"[{self.name}] 🎲 Random fallback move: {random_move}")
                return {
                    "move": random_move,
                    "raw_response": f"[RANDOM FALLBACK] AI failed: {last_error}",
                    "thinking_time": 0,
                    "tokens_used": 0,
                    "prompt_tokens": prompt_tokens,
                    "response_tokens": 0,
                    "total_tokens": self.total_tokens_used,
                    "api_calls": self.total_api_calls,
                    "chat_message": "🎲 Tôi bối rối quá... đi bừa vậy!",
                    "attempt": retry_count + 1,
                    "is_random": True,
                }
        except Exception as fallback_err:
            logger.error(f"[{self.name}] Random fallback also failed: {fallback_err}")

        # Truly no valid moves — forfeit
        return {
            "move": None,
            "error": f"Failed after {retry_count} attempts + random fallback: {last_error}",
            "tokens_used": self.total_tokens_used,
            "total_tokens": self.total_tokens_used,
            "api_calls": self.total_api_calls,
            "chat_message": "😵 Tôi không thể đi được nữa...",
        }

    def _call_ai(self, prompt: str) -> str:
        """Call the AI provider. Uses direct HTTP requests — no external SDK needed."""
        try:
            # ── Get API key ──
            api_key = self.api_key
            if not api_key and self.provider != "ollama":
                api_key = self._get_cloud_key()

            if self.provider == "ollama":
                return self._call_ollama(prompt)
            elif self.provider == "gemini":
                return self._call_gemini(prompt, api_key)
            elif self.provider == "deepseek":
                return self._call_openai_compat(prompt, api_key,
                    base_url="https://api.deepseek.com/chat/completions",
                    default_model="deepseek-chat")
            elif self.provider in ("openai", "chatgpt"):
                return self._call_openai_compat(prompt, api_key,
                    base_url="https://api.openai.com/v1/chat/completions",
                    default_model="gpt-4o-mini")
            elif self.provider == "claude":
                return self._call_claude(prompt, api_key)
            elif self.provider == "grok":
                return self._call_openai_compat(prompt, api_key,
                    base_url="https://api.x.ai/v1/chat/completions",
                    default_model="grok-3")
            elif self.provider == "openrouter":
                return self._call_openai_compat(prompt, api_key,
                    base_url="https://openrouter.ai/api/v1/chat/completions",
                    default_model=self.model or "openai/gpt-4o-mini")
            elif self.provider == "9router":
                # 9Router is a local OpenAI-compatible proxy (no real key needed).
                return self._call_openai_compat(prompt, api_key or "9router",
                    base_url="http://localhost:20128/v1/chat/completions",
                    default_model=self.model or "deepseek-chat")
            elif self.provider == "github":
                return self._call_openai_compat(prompt, api_key,
                    base_url="https://models.inference.ai.azure.com/chat/completions",
                    default_model=self.model)
            else:
                return f"[ERROR] Unknown provider: {self.provider}"

        except Exception as e:
            logger.error(f"[{self.name}] _call_ai exception: {e}", exc_info=True)
            return f"[ERROR] {self.provider}: {e}"

    def _get_cloud_key(self) -> str:
        """Get API key from cloud_api_keys.json or key_manager."""
        try:
            # Method 1: key_manager from cloud_api extension
            from tubecli.extensions.cloud_api.extension import key_manager
            key = key_manager.get_active_key(self.provider) or ""
            if key:
                return key
        except Exception:
            pass

        try:
            # Method 2: Read from cloud_api_keys.json directly
            import os, json
            from tubecli.config import DATA_DIR
            keys_file = os.path.join(str(DATA_DIR), "cloud_api_keys.json")
            if os.path.exists(keys_file):
                with open(keys_file, "r", encoding="utf-8") as f:
                    keys_data = json.load(f)
                provider_keys = keys_data.get(self.provider, {})
                for label, info in provider_keys.items():
                    if isinstance(info, dict) and info.get("active", True):
                        key = info.get("key", "") or info.get("api_key", "")
                        if key:
                            return key
        except Exception:
            pass

        return ""

    # ── Provider-specific calls (all using requests, no SDK) ──

    def _call_ollama(self, prompt: str) -> str:
        """Call Ollama local API."""
        try:
            from tubecli.config import OLLAMA_BASE_URL
            base = OLLAMA_BASE_URL
        except ImportError:
            base = "http://localhost:11434"

        r = requests.post(
            f"{base}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=180,
        )
        if r.status_code == 200:
            return r.json().get("response", "")
        return f"[ERROR] Ollama {r.status_code}: {r.text[:200]}"

    def _call_gemini(self, prompt: str, api_key: str) -> str:
        """Call Gemini via REST API."""
        if not api_key:
            return "[ERROR] Gemini: No API key configured"

        model = self.model or "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 512},
        }
        r = requests.post(url, json=payload, timeout=120)
        if r.status_code == 429:
            return "[QUOTA_ERROR] Gemini: Rate limit exceeded"
        if r.status_code != 200:
            return f"[ERROR] Gemini {r.status_code}: {r.text[:200]}"
        data = r.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        return "[ERROR] Gemini: No candidates in response"

    def _call_openai_compat(self, prompt: str, api_key: str,
                            base_url: str, default_model: str) -> str:
        """Call any OpenAI-compatible API (DeepSeek, OpenAI, Grok, GitHub)."""
        if not api_key:
            return f"[ERROR] {self.provider}: No API key configured"

        model = self.model or default_model
        r = requests.post(
            base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
                "max_tokens": 512,
                "stream": False,
            },
            timeout=120,
        )
        if r.status_code == 429:
            return f"[QUOTA_ERROR] {self.provider}: Rate limit exceeded"
        if r.status_code != 200:
            return f"[ERROR] {self.provider} {r.status_code}: {r.text[:200]}"
        data = r.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return f"[ERROR] {self.provider}: No choices in response"

    def _call_claude(self, prompt: str, api_key: str) -> str:
        """Call Claude (Anthropic) API."""
        if not api_key:
            return "[ERROR] Claude: No API key configured"

        model = self.model or "claude-sonnet-4-20250514"
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        if r.status_code == 429:
            return "[QUOTA_ERROR] Claude: Rate limit exceeded"
        if r.status_code != 200:
            return f"[ERROR] Claude {r.status_code}: {r.text[:200]}"
        data = r.json()
        blocks = data.get("content", [])
        return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    def _extract_chat(self, response: str) -> str:
        """Extract or generate a short chat message from AI response."""
        # Remove thinking tags
        text = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

        # If response is very short (just a move), generate fun comment
        if len(text) < 10:
            return ""

        # Look for any non-move text
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) > 10 and not re.match(r'^[a-h][1-8][a-h][1-8]', line):
                return line[:100]

        return ""

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "emoji": self.emoji,
            "agent_id": self.agent_id,
            "elo": self.elo,
            "total_tokens_used": self.total_tokens_used,
            "total_api_calls": self.total_api_calls,
            "stats": self.stats,
        }
