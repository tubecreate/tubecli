"""
Intent Router — Tier 1: Zero-token intent classification.
Classifies user messages by keyword/regex BEFORE calling LLM.
Inspired by claw-code-main's PortRuntime.route_prompt() scoring system.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


# Scripts that do not separate words with spaces — keyword matching there has to
# stay a substring test, since there is no word boundary to anchor to.
_CJK_RE = re.compile(
    "[　-〿"      # CJK punctuation
    "぀-ヿ"       # Hiragana + Katakana
    "㐀-䶿"       # CJK ext A
    "一-鿿"       # CJK unified ideographs
    "가-힯"       # Hangul syllables
    "＀-￯]"      # Halfwidth/Fullwidth forms
)
_KW_CACHE: Dict[str, Any] = {}


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent_type: str          # greeting, video_download, calendar, etc.
    confidence: float         # 0.0 - 1.0
    matched_skills: List[str] = field(default_factory=list)  # skill IDs to inject
    extracted_data: Dict[str, Any] = field(default_factory=dict)  # url, params, etc.
    target_agent_id: Optional[str] = None  # for team delegation
    skip_llm: bool = False    # True = no LLM call needed at all


# ── Intent Patterns ──────────────────────────────────────────────

# TubeCLI ships in 9 languages (en, vi, zh, zh-TW, ja, ko, es, tr, ru). Patterns
# used to be Vietnamese/English only, so every other locale fell through to the
# expensive full-LLM path and never got a cheap greeting reply.
GREETING_PATTERNS = [
    # vi / en
    r"^(xin\s+)?ch[àa]o",
    r"^h[ie]llo",
    r"^hi\b",
    r"^hey\b",
    r"^/start$",
    r"^bạn\s+(là|tên|ơi)",
    r"^(tôi|mình)\s+l[àa]\s+",
    r"^good\s+(morning|afternoon|evening)",
    r"^chào\s+buổi",
    # zh / zh-TW
    r"^(你好|您好|哈囉|哈罗|嗨|早安|午安|晚安)",
    # ja
    r"^(こんにちは|こんばんは|おはよう|やあ|はじめまして)",
    # ko
    r"^(안녕|반갑|안녕하세요)",
    # ru
    r"^(привет|здравствуй|добрый\s+(день|вечер|утро)|доброе\s+утро)",
    # tr
    r"^(merhaba|selam|g[üu]nayd[ıi]n|iyi\s+(g[üu]nler|ak[şs]amlar))",
    # es
    r"^(hola|buenos\s+d[íi]as|buenas\s+(tardes|noches)|qu[ée]\s+tal)",
]

CALENDAR_PATTERNS = [
    r"lập\s+lịch",
    r"đặt\s+lịch",
    r"tạo\s+sự\s+kiện",
    r"schedule",
    r"nhắc\s+nhở",
    r"lên\s+lịch",
    r"hẹn\s+giờ",
    r"reminder",
]

FILE_OPS_PATTERNS = [
    r"tạo\s+(thư\s+mục|folder|file)",
    r"xóa\s+(thư\s+mục|folder|file)",
    r"di\s+chuyển\s+file",
    r"liệt\s+kê\s+file",
    r"đọc\s+file",
    r"sao\s+chép\s+file",
    r"create\s+(folder|file|dir)",
    r"delete\s+(folder|file)",
    r"move\s+file",
    r"list\s+(files|dir)",
]

SEARCH_PATTERNS = [
    r"tìm\s+kiếm",
    r"google",
    r"search",
    r"tra\s+cứu",
    r"tìm\s+giúp",
    r"xu\s+hướng",
    r"trending",
    r"tin\s+tức",
    r"thời\s+tiết",
    r"weather",
]

TEAM_PATTERNS = [
    r"tạo\s+team",
    r"create\s+team",
    r"tạo\s+nhóm",
    r"lập\s+đội",
]

BROWSER_PATTERNS = [
    r"(list|danh\s*sách)\s*(browser|trình\s*duyệt|profile)",
    r"(mở|open|launch)\s*(browser|trình\s*duyệt|profile)",
    r"(tạo|create|thêm|add)\s*(browser|trình\s*duyệt|profile)",
    r"(đóng|close|stop|tắt|kill)\s*(browser|trình\s*duyệt|profile)",
    r"(xóa|delete|remove)\s*(browser|trình\s*duyệt|profile)",
    r"browser\s*(profile|status|list|mở|đóng|tạo|xóa)",
    r"trình\s*duyệt\s*(profile|status|list|mở|đóng|tạo|xóa)",
    r"^(mở|open|launch)\s+\d+$",  # "mở 39" — open by index
    r"^(đóng|close|stop|tắt)\s+\d+$",  # "đóng 5"
]

VIDEO_URL_PATTERNS = [
    r'https?://(?:www\.)?douyin\.com/video/\S+',
    r'https?://(?:www\.)?tiktok\.com/@[^/]+/video/\S+',
    r'https?://vm\.tiktok\.com/\S+',
    r'https?://(?:www\.)?iesdouyin\.com/share/(?:video|note|slides)/\S+',
    r'https?://v\.douyin\.com/\S+',
]

UPLOAD_KEYWORDS = [
    "upload", "đăng", "lên kênh", "đăng mmo", "post",
    "上传", "上傳", "アップロード", "投稿", "업로드", "загрузить", "загрузи",
    "yükle", "subir", "publicar",
]
REUP_KEYWORDS = [
    "reup", "re-up", "re up", "xào", "gương", "mirror", "chống gậy", "lật",
    "flip", "template",
    "二次创作", "搬运", "転載", "리업", "перезалив", "yeniden yükle", "resubir",
]
TEMPLATE_PATTERN = r'template\s*(\d+)'
TRACKER_KEYWORDS = [
    "mới nhất", "theo dõi", "tracker", "kích hoạt", "video mới nhất",
    "最新", "追踪", "监控", "最新の", "追跡", "최신", "추적",
    "отслеживать", "последнее видео", "takip et", "seguir", "rastrear",
]
LIVE_KEYWORDS = [
    "tạo phiên live", "live", "直播", "phát live", "restream", "livestream",
    "live stream", "go live", "tạo live",
    "ライブ", "生放送", "라이브", "생방송", "прямой эфир", "стрим",
    "canlı yayın", "en vivo", "transmisión en vivo",
]

# Live source URL patterns (Douyin live, TikTok live, m3u8, RTMP).
# The generic `https?://\S+` fallback that used to close this list is gone: it
# made EVERY link look like a livestream source. _extract_live_url() has always
# used its own stricter copy, so the entry was dead weight — and a landmine for
# anyone who reused this constant.
LIVE_URL_PATTERNS = [
    r'https?://live\.douyin\.com/\S+',
    r'https?://(?:www\.)?tiktok\.com/@[^/]+/live',
    r'https?://\S+\.m3u8\S*',
    r'rtmp://\S+',
    r'https?://v\.douyin\.com/\S+',
]

# Standalone live patterns (no URL needed in message body)
LIVE_STANDALONE_PATTERNS = [
    r"tạo\s+(phiên\s+)?live",
    r"(phát|bắt đầu)\s+live",
    r"live\s*stream",
    r"restream",
    r"go\s+live",
    r"tạo\s+luồng\s+live",
]
SUBTITLE_KEYWORDS = [
    "tách sub", "subtitle", "phụ đề", "caption", "字幕", "tách phụ đề",
    "lấy sub", "extract sub", "transcribe",
    "자막", "субтитры", "altyazı", "subtítulos", "subtitulos",
]
TTS_KEYWORDS = [
    "lồng tiếng", "voiceover", "voice over", "tts", "đọc text",
    "text to speech", "narrate", "giọng đọc",
    "配音", "音声合成", "ナレーション", "더빙", "음성 합성",
    "озвучка", "seslendirme", "locución", "voz en off",
]

# Only an EXPLICIT "show me my connected channels" request belongs here.
# The old pattern was `(list|danh sách|xem).*?(kênh|youtube|...)`, which is both
# too broad and too narrow: "xem" is an everyday Vietnamese verb, so
# "xem thử kênh này nói về gì" (a question ABOUT one channel) was treated as
# "list my channels"; meanwhile plain "list channels" and "liệt kê kênh" were
# missed because the pattern required the Vietnamese word "kênh" right after.
LIST_CHANNELS_PATTERNS = [
    r"(danh\s*sách|liệt\s*kê)\s*(các\s*)?(kênh|channel|fanpage|page)",
    r"\b(list|show)\s+(all\s+|my\s+)?(channels?|kênh|fanpages?|pages?)\b",
    r"xem\s+danh\s*sách\s*(các\s*)?(kênh|channel)",
    r"(kênh|channel)\s+(nào|của\s+tôi|đã\s+kết\s+nối)",
    r"có\s+(những\s+)?(kênh|channel)\s+nào",
]

LIST_TEMPLATES_PATTERNS = [
    r"(list|danh\s*sách|xem).*?template",
    r"template.*(list|danh\s*sách)",
    r"có\s+template\s+nào",
    r"list\s+template",
]


class IntentRouter:
    """Tier 1: Zero-token intent classification using keyword/regex matching."""

    def classify(self, message: str, agent: Dict = None, skills: List[Dict] = None) -> IntentResult:
        """
        Classify intent WITHOUT calling LLM.
        Returns IntentResult with type, confidence, and relevant data.
        
        Routing priority:
        1. Video URL detection (fast-path, skip LLM entirely)
        2. Exact skill command match (skip LLM)
        3. Greeting detection (quick_reply, minimal LLM)
        4. Calendar / File / Search / Team (targeted skill, small LLM)
        5. Fallback → general_chat or complex_action (full LLM with filtered skills)
        """
        text = message.strip()
        text_lower = text.lower()

        # ── 0. Live Stream URL Detection ────────────────────────
        # Check for live-specific URLs first (douyin live, m3u8, rtmp)
        live_url = self._extract_live_url(text, text_lower)
        if live_url or (self._kw_hit(text_lower, LIVE_KEYWORDS) and self._has_any_url(text)):
            source = live_url or self._extract_any_url(text)
            if source:
                return IntentResult(
                    intent_type="live_action",
                    confidence=0.97,
                    extracted_data={"url": source, "original_message": text},
                    skip_llm=False,
                )

        # ── 1. Video URL Detection ───────────────────────────────
        video_url = self._extract_video_url(text, text_lower)
        if video_url:
            # Check for tracker/live bypass
            if self._kw_hit(text_lower, TRACKER_KEYWORDS):
                return IntentResult(
                    intent_type="tracker_action",
                    confidence=0.95,
                    extracted_data={"url": video_url},
                )
            if self._kw_hit(text_lower, LIVE_KEYWORDS):
                return IntentResult(
                    intent_type="live_action",
                    confidence=0.95,
                    extracted_data={"url": video_url},
                )
            # Check for reup intent (download + ffmpeg + upload)
            if self._kw_hit(text_lower, REUP_KEYWORDS):
                extracted = {"url": video_url}
                # Detect template index (e.g. "template 1", "template 3")
                tpl_match = re.search(TEMPLATE_PATTERN, text_lower)
                if tpl_match:
                    extracted["template_index"] = int(tpl_match.group(1))
                return IntentResult(
                    intent_type="reup_action",
                    confidence=0.95,
                    extracted_data=extracted,
                    skip_llm=False,
                )
            # Check for subtitle pipeline (download + subtitle + optional burn/tts/upload)
            if self._kw_hit(text_lower, SUBTITLE_KEYWORDS):
                has_upload = self._kw_hit(text_lower, UPLOAD_KEYWORDS)
                has_burn = self._kw_hit(text_lower, [
                    "burn", "ghi sub", "ghi phụ đề", "thêm sub", "thêm phụ đề", "ghép sub",
                    "烧录字幕", "字幕焼き込み", "자막 삽입", "вшить субтитры",
                    "altyazı göm", "incrustar subtítulos",
                ])
                has_tts = self._kw_hit(text_lower, TTS_KEYWORDS)
                return IntentResult(
                    intent_type="subtitle_pipeline",
                    confidence=0.96,
                    extracted_data={
                        "url": video_url,
                        "needs_burn": has_burn,  # only burn if explicitly requested
                        "needs_tts": has_tts,
                        "needs_upload": has_upload,
                        "original_message": text,
                    },
                    skip_llm=False,
                )
            # Check for upload intent
            if self._kw_hit(text_lower, UPLOAD_KEYWORDS):
                # Smart provider detection: keywords + context from last listed channels
                try:
                    from tubecli.core.channel_cache import channel_cache
                    upload_provider = channel_cache.infer_provider(text)
                except Exception:
                    upload_provider = "youtube"
                return IntentResult(
                    intent_type="video_upload",
                    confidence=0.95,
                    extracted_data={"url": video_url, "provider": upload_provider},
                    skip_llm=False,  # Need LLM for title optimization
                )
            return IntentResult(
                intent_type="video_download",
                confidence=0.99,
                extracted_data={"url": video_url},
                skip_llm=True,
            )

        # ── 2. Exact Skill Command Match ─────────────────────────
        if skills:
            matched_skill = self._match_skill_command(text_lower, skills)
            if matched_skill:
                return IntentResult(
                    intent_type="skill_command",
                    confidence=0.99,
                    matched_skills=[matched_skill["id"]],
                    extracted_data={"skill": matched_skill},
                    skip_llm=True,
                )

        # ── 2b. Standalone Live Command ────────────────────────
        if self._matches_any(text_lower, LIVE_STANDALONE_PATTERNS):
            # User wants to create a live stream but may not have included URL
            # Extract URL if present in the message
            url = self._extract_any_url(text)
            return IntentResult(
                intent_type="live_action",
                confidence=0.92,
                extracted_data={"url": url or "", "original_message": text},
                skip_llm=False,
            )

        # ── 3. Greeting Detection ────────────────────────────────
        if self._matches_any(text_lower, GREETING_PATTERNS):
            return IntentResult(
                intent_type="greeting",
                confidence=0.90,
                skip_llm=False,  # Use quick_reply with cloud LLM
            )

        # ── 4. Calendar ──────────────────────────────────────────
        if self._matches_any(text_lower, CALENDAR_PATTERNS):
            calendar_skills = self._find_skills_by_category(skills, ["calendar", "lịch", "schedule"])
            return IntentResult(
                intent_type="calendar",
                confidence=0.85,
                matched_skills=[s["id"] for s in calendar_skills[:1]],
            )

        # ── 5. File Operations ───────────────────────────────────
        if self._matches_any(text_lower, FILE_OPS_PATTERNS):
            return IntentResult(
                intent_type="file_ops",
                confidence=0.90,
            )

        # ── 6. Search ────────────────────────────────────────────
        if self._matches_any(text_lower, SEARCH_PATTERNS):
            search_skills = self._find_skills_by_category(skills, ["search", "tìm kiếm", "tra cứu"])
            return IntentResult(
                intent_type="search",
                confidence=0.80,
                matched_skills=[s["id"] for s in search_skills[:1]],
            )

        # ── 7. Team Creation ─────────────────────────────────────
        if self._matches_any(text_lower, TEAM_PATTERNS):
            return IntentResult(
                intent_type="team_create",
                confidence=0.90,
            )

        # ── 7a. List Channels / Pages ────────────────────────────
        # A message carrying a URL is asking about that ONE thing, never for a
        # listing of the user's own connected channels.
        if self._matches_any(text_lower, LIST_CHANNELS_PATTERNS) and not re.search(r"https?://", text):
            provider = "youtube"
            if "facebook" in text_lower or "fanpage" in text_lower or "page" in text_lower:
                provider = "facebook"
            elif "tiktok" in text_lower:
                provider = "tiktok"

            return IntentResult(
                intent_type="list_channels_action",
                confidence=0.95,
                extracted_data={
                    "action_data": {
                        "action": "list_channels",
                        "provider": provider
                    }
                },
                skip_llm=True,
            )

        # ── 7a2. List Templates ──────────────────────────────────
        if self._matches_any(text_lower, LIST_TEMPLATES_PATTERNS):
            return IntentResult(
                intent_type="list_templates_action",
                confidence=0.95,
                extracted_data={
                    "action_data": {
                        "action": "list_templates"
                    }
                },
                skip_llm=True,
            )

        # ── 7b. Browser Management ───────────────────────────────
        if self._matches_any(text_lower, BROWSER_PATTERNS):
            # Determine sub-action from keywords
            sub_action = "list"
            if any(re.search(p, text_lower) for p in [r"(mở|open|launch)", r"browser\s*mở"]):
                sub_action = "launch"
            elif any(re.search(p, text_lower) for p in [r"(tạo|create|thêm|add)", r"browser\s*tạo"]):
                sub_action = "create"
            elif any(re.search(p, text_lower) for p in [r"(đóng|close|stop|tắt|kill)", r"browser\s*đóng"]):
                sub_action = "stop"
            elif any(re.search(p, text_lower) for p in [r"(xóa|delete|remove)", r"browser\s*xóa"]):
                sub_action = "delete"
            
            # 1. Match numeric shorthands first ("mở 39", "đóng 5")
            num_match = re.search(r"^(mở|open|launch|đóng|close|stop|tắt|xóa|delete)\s+(\d+)$", text_lower)
            if num_match:
                candidate = num_match.group(2)
                if candidate:
                    profile_name = candidate
            else:
                # 2. Extract profile name by stripping known keywords
                skip_words = {"browser", "profile", "profiles", "trình", "duyệt", "list", "danh", "sách", 
                              "status", "mở", "đóng", "tạo", "xóa", "mới", "new", "open", "close", 
                              "launch", "stop", "create", "delete", "remove", "add", "thêm", "tắt", "kill"}
                words = text_lower.split()
                remaining = [w for w in words if w not in skip_words]
                if remaining:
                    profile_name = remaining[-1]  # Take last non-keyword word as profile name
            
            return IntentResult(
                intent_type="browser_action",
                confidence=0.95,
                extracted_data={"sub_action": sub_action, "profile_name": profile_name},
                skip_llm=True,
            )
        # ── 7c. Subtitle Extraction ──────────────────────────────
        if self._kw_hit(text_lower, SUBTITLE_KEYWORDS):
            sub_skills = self._find_skills_by_category(skills, ["subtitle", "phụ đề", "sub", "caption"])
            return IntentResult(
                intent_type="subtitle_action",
                confidence=0.90,
                matched_skills=[s["id"] for s in sub_skills[:1]],
                extracted_data={"original_message": text},
            )

        # ── 8. Team Delegation ───────────────────────────────────
        if agent:
            team_result = self._try_team_delegation(text_lower, agent, skills)
            if team_result:
                return team_result

        # ── 9. Fallback: Check if short/casual vs complex ────────
        word_count = len(text.split())
        has_question_mark = "?" in text or "？" in text
        
        if word_count <= 10 and not has_question_mark and not self._has_action_keywords(text_lower):
            return IntentResult(
                intent_type="general_chat",
                confidence=0.50,
            )

        # ── 10. Complex action → LLM with top 3 skills ──────────
        if skills:
            top_skills = self._score_skills(text_lower, skills, limit=3)
            return IntentResult(
                intent_type="complex_action",
                confidence=0.40,
                matched_skills=[s["id"] for s in top_skills],
            )

        return IntentResult(
            intent_type="general_chat",
            confidence=0.30,
        )

    # ── Helpers ───────────────────────────────────────────────────

    def _extract_live_url(self, text: str, text_lower: str) -> Optional[str]:
        """Extract live stream URL (Douyin live, TikTok live, m3u8, RTMP)."""
        live_patterns = [
            r'https?://live\.douyin\.com/\S+',
            r'https?://(?:www\.)?tiktok\.com/@[^/]+/live',
            r'https?://\S+\.m3u8\S*',
            r'rtmp://\S+',
        ]
        for pattern in live_patterns:
            m = re.search(pattern, text)
            if m:
                return m.group(0).rstrip('.,;?!')
        return None

    def _has_any_url(self, text: str) -> bool:
        """Check if text contains any URL."""
        return bool(re.search(r'https?://\S+|rtmp://\S+', text))

    def _extract_any_url(self, text: str) -> Optional[str]:
        """Extract any URL from text."""
        m = re.search(r'(https?://\S+|rtmp://\S+)', text)
        return m.group(0).rstrip('.,;?!') if m else None

    def _extract_video_url(self, text: str, text_lower: str) -> Optional[str]:
        """Extract video URL from message, respecting bypass keywords."""
        for pattern in VIDEO_URL_PATTERNS:
            m = re.search(pattern, text)
            if m:
                url = m.group(0).rstrip('.,;?!')
                if "/user/" in url:
                    continue
                return url
        return None

    def _match_skill_command(self, msg_lower: str, skills: List[Dict]) -> Optional[Dict]:
        """Check for exact skill command match."""
        msg_clean = re.sub(r'[?!.,;]+$', '', msg_lower).strip()
        for skill in skills:
            commands = skill.get("commands", [])
            for cmd in commands:
                if not cmd or len(cmd.strip()) < 3:
                    continue
                cmd_clean = cmd.strip().lower()
                if msg_clean == cmd_clean or msg_clean.startswith(cmd_clean + " "):
                    return skill
        return None

    def _matches_any(self, text: str, patterns: List[str]) -> bool:
        """Check if text matches any regex pattern."""
        return any(re.search(p, text) for p in patterns)

    def _kw_hit(self, text_lower: str, keywords: List[str]) -> bool:
        """Whole-word keyword match.

        Replaces the plain `any(k in text_lower ...)` these lists used to use,
        which matched inside unrelated words: "live" hit "deliver"/"alive",
        "post" hit "postal", so an ordinary sentence containing a URL was
        routed to the livestream or upload pipeline.

        Scripts written without spaces (Chinese, Japanese, Korean) have no word
        boundaries to anchor to, so those keywords stay substring matches.
        """
        for kw in keywords:
            rx = self._kw_regex(kw)
            if rx and rx.search(text_lower):
                return True
        return False

    @staticmethod
    def _kw_regex(keyword: str):
        """Compile (and cache) the matcher for one keyword."""
        kw = (keyword or "").strip().lower()
        if not kw:
            return None
        cached = _KW_CACHE.get(kw)
        if cached is None:
            if _CJK_RE.search(kw):
                cached = re.compile(re.escape(kw))
            else:
                cached = re.compile(r"(?<!\w)" + re.escape(kw) + r"(?!\w)")
            _KW_CACHE[kw] = cached
        return cached

    def _has_action_keywords(self, text_lower: str) -> bool:
        """Check if text contains action-oriented keywords."""
        action_words = [
            "giúp", "làm", "tạo", "xóa", "tải", "gửi", "mở",
            "chạy", "cài", "thêm", "sửa", "cập nhật", "help",
            "create", "delete", "download", "send", "run", "install",
        ]
        return any(w in text_lower for w in action_words)

    def _find_skills_by_category(self, skills: List[Dict], keywords: List[str]) -> List[Dict]:
        """Find skills matching category keywords."""
        if not skills:
            return []
        results = []
        for s in skills:
            name = (s.get("name", "") or "").lower()
            desc = (s.get("description", "") or "").lower()
            cmds = " ".join(s.get("commands", []) or []).lower()
            haystack = f"{name} {desc} {cmds}"
            if any(k in haystack for k in keywords):
                results.append(s)
        return results

    def _score_skills(self, text_lower: str, skills: List[Dict], limit: int = 3) -> List[Dict]:
        """Score and return top N relevant skills (claw-code RoutedMatch pattern)."""
        scored = []
        tokens = set(w for w in text_lower.split() if len(w) > 2)
        
        for s in skills:
            score = 0
            name = (s.get("name", "") or "").lower()
            desc = (s.get("description", "") or "").lower()
            cmds = s.get("commands", []) or []
            
            # Command match: highest score
            for cmd in cmds:
                if cmd and cmd.lower() in text_lower:
                    score += 5
                    break
            
            # Name word match
            for w in name.split():
                if len(w) > 2 and w in tokens:
                    score += 3
            
            # Description word match
            for w in desc.split():
                if len(w) > 3 and w in tokens:
                    score += 1
            
            if score > 0:
                scored.append((score, s))
        
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:limit]]

    def _try_team_delegation(self, text_lower: str, agent: Dict, skills: List[Dict]) -> Optional[IntentResult]:
        """Phase 2: Try to delegate to a specialist agent in a team."""
        from tubecli.core.agent import agent_manager
        
        all_agents = agent_manager.get_all()
        if len(all_agents) <= 1:
            return None  # No team exists
        
        # Find specialist agents by their specialties
        for ag in all_agents:
            specialties = getattr(ag, "specialties", []) or []
            role = getattr(ag, "role", "general") or "general"
            if role != "specialist" or not specialties:
                continue
            
            # Check if message matches this specialist's domain
            for specialty in specialties:
                if specialty.lower() in text_lower:
                    relevant_skills = []
                    if ag.allowed_skills:
                        relevant_skills = [s for s in (skills or []) if s.get("id") in ag.allowed_skills]
                    
                    return IntentResult(
                        intent_type="team_delegate",
                        confidence=0.80,
                        matched_skills=[s["id"] for s in relevant_skills[:3]],
                        target_agent_id=ag.id,
                    )
        
        return None


# Global singleton
intent_router = IntentRouter()
