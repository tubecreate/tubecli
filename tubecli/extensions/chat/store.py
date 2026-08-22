"""
Chat conversation store — durable, multi-session.

The existing web chat keeps a single history per agent inside
`agent.history_log` (api/server.py:1908), so every browser tab shares one
thread and there is no way to keep separate conversations. This store gives
each conversation its own file, like a normal chat app.

    data/extensions_data/chat/sessions.json          {id: session_meta}
    data/extensions_data/chat/messages/<id>.jsonl    append-only turns
"""
import datetime
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

try:
    from uuid_extensions import uuid7 as _uuid7
except ImportError:  # pragma: no cover
    import uuid

    _uuid7 = uuid.uuid4

from tubecli.config import EXTENSIONS_DATA_DIR

logger = logging.getLogger("Chat")

CHAT_DATA_DIR = os.path.join(str(EXTENSIONS_DATA_DIR), "chat")
SESSIONS_FILE = os.path.join(CHAT_DATA_DIR, "sessions.json")
MESSAGES_DIR = os.path.join(CHAT_DATA_DIR, "messages")

MAX_MESSAGES_PER_SESSION = 400
TITLE_MAX = 60


def _now() -> str:
    return datetime.datetime.now().isoformat()


class ConversationStore:
    """Sessions + messages, one lock, atomic writes."""

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    # ── Persistence ──────────────────────────────────────────────

    def _ensure_dirs(self):
        os.makedirs(CHAT_DATA_DIR, exist_ok=True)
        os.makedirs(MESSAGES_DIR, exist_ok=True)

    def _ensure_loaded(self):
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._ensure_dirs()
            try:
                if os.path.exists(SESSIONS_FILE):
                    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._sessions = data
            except Exception as e:
                logger.error(f"[Chat] Failed to load sessions.json: {e}")
                self._sessions = {}
            self._loaded = True

    def _save(self):
        """Atomic. Caller must hold the lock."""
        self._ensure_dirs()
        tmp = SESSIONS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._sessions, f, indent=2, ensure_ascii=False)
            os.replace(tmp, SESSIONS_FILE)
        except Exception as e:
            logger.error(f"[Chat] Failed to save sessions.json: {e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _messages_path(self, session_id: str) -> str:
        return os.path.join(MESSAGES_DIR, f"{session_id}.jsonl")

    # ── Sessions ─────────────────────────────────────────────────

    def create_session(
        self, title: str = "", agent_id: str = "", agent_name: str = "",
        model: str = "", provider: str = "", group_id: str = "",
    ) -> Dict[str, Any]:
        self._ensure_loaded()
        session = {
            "id": str(_uuid7()),
            "title": (title or "").strip()[:TITLE_MAX] or "Cuộc trò chuyện mới",
            "agent_id": agent_id,
            "agent_name": agent_name,
            # Per-conversation model override; "" = use the agent's own model.
            # `provider` is stored alongside because a model id alone is
            # ambiguous (9router serves OpenRouter-shaped ids like "ag/...").
            "model": model,
            "provider": provider,
            # Flow Builder group of the agent node that opened this chat; ""
            # = none. The message body may carry a newer one (the node can be
            # dragged into another group), which the route then stores here.
            "group_id": group_id or "",
            "created_at": _now(),
            "updated_at": _now(),
            "message_count": 0,
            "last_preview": "",
            "pinned": False,
        }
        with self._lock:
            self._sessions[session["id"]] = session
            self._save()
        return dict(session)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        with self._lock:
            s = self._sessions.get(session_id)
            return dict(s) if s else None

    def list_sessions(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        with self._lock:
            items = [dict(s) for s in self._sessions.values()]
        # Pinned first, newest first inside each group.
        pinned = sorted([s for s in items if s.get("pinned")],
                        key=lambda s: s.get("updated_at", ""), reverse=True)
        rest = sorted([s for s in items if not s.get("pinned")],
                      key=lambda s: s.get("updated_at", ""), reverse=True)
        ordered = pinned + rest
        return ordered[:limit] if limit else ordered

    def update_session(self, session_id: str, **updates) -> Optional[Dict[str, Any]]:
        self._ensure_loaded()
        editable = {"title", "agent_id", "agent_name", "pinned", "model", "provider", "group_id"}
        with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                return None
            for k, v in updates.items():
                if k in editable and v is not None:
                    s[k] = (v[:TITLE_MAX] if k == "title" and isinstance(v, str) else v)
            s["updated_at"] = _now()
            self._save()
            return dict(s)

    def delete_session(self, session_id: str) -> bool:
        self._ensure_loaded()
        with self._lock:
            if session_id not in self._sessions:
                return False
            del self._sessions[session_id]
            self._save()
        try:
            path = self._messages_path(session_id)
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"[Chat] Could not delete messages for {session_id}: {e}")
        return True

    def clear_messages(self, session_id: str) -> bool:
        self._ensure_loaded()
        try:
            path = self._messages_path(session_id)
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"[Chat] Could not clear messages for {session_id}: {e}")
            return False
        with self._lock:
            s = self._sessions.get(session_id)
            if s:
                s["message_count"] = 0
                s["last_preview"] = ""
                s["updated_at"] = _now()
                self._save()
        return True

    # ── Messages ─────────────────────────────────────────────────

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        msg = {
            "id": str(_uuid7()),
            "role": role,
            "content": content,
            "ts": _now(),
        }
        if meta:
            msg["meta"] = meta
        self._ensure_dirs()
        with self._lock:
            try:
                with open(self._messages_path(session_id), "a", encoding="utf-8") as f:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"[Chat] Failed to append message: {e}")
            s = self._sessions.get(session_id)
            if s:
                s["message_count"] = int(s.get("message_count") or 0) + 1
                s["updated_at"] = msg["ts"]
                s["last_preview"] = (content or "").strip().replace("\n", " ")[:120]
                # First user line names the conversation, like ChatGPT.
                if role == "user" and s.get("title") in ("", "Cuộc trò chuyện mới"):
                    s["title"] = (content or "").strip().replace("\n", " ")[:TITLE_MAX] or s["title"]
                self._save()
        return msg

    def get_messages(self, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        path = self._messages_path(session_id)
        if not os.path.exists(path):
            return []
        out: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"[Chat] Failed to read messages for {session_id}: {e}")
            return []
        return out[-limit:] if limit else out

    def get_history_for_llm(self, session_id: str, turns: int = 10) -> List[Dict[str, str]]:
        """Recent turns in the {role, content} shape AgentBrain expects."""
        msgs = self.get_messages(session_id, limit=turns * 2)
        return [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in msgs
            if m.get("role") in ("user", "assistant") and m.get("content")
        ][-(turns * 2):]

    def prune(self, session_id: str):
        """Keep the transcript from growing without bound."""
        path = self._messages_path(session_id)
        if not os.path.exists(path):
            return
        try:
            with self._lock:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) <= MAX_MESSAGES_PER_SESSION:
                    return
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.writelines(lines[-MAX_MESSAGES_PER_SESSION:])
                os.replace(tmp, path)
        except Exception as e:
            logger.error(f"[Chat] Failed to prune {session_id}: {e}")


conversation_store = ConversationStore()
