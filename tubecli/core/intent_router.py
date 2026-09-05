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
    # Set by defer_to_model(): the branch this turn WOULD have taken before the
    # desk overruled it. Kept for the log/meta, never acted on.
    deferred_from: str = ""


# ── When the keyword router must stand down ──────────────────────────
#
# Everything classify() decides above comes out of hard-coded keyword tables —
# and those tables are Vietnamese. The product ships in nine languages, so on
# eight of them these branches are simply wrong, and on the ninth they are
# still guesses ("tin tức" lands in SEARCH, "tin mới nhất" does not).
#
# That is tolerable while the agent owns nothing but generic skills. It is not
# tolerable once the agent has a DESK — a browser profile, a workbook, a Sheet,
# a script someone deliberately put in front of it. There the guess actively
# takes the decision away from the one component that IS multilingual: the
# model. So the pipeline asks a purely structural question ("does this group
# expose an actionable kind?", core.group_context.actionable_kinds) and, when
# the answer is yes, hands the guessed branches back to the model.
#
# Two kinds of result survive that, because neither is a guess about meaning:
LITERAL_INTENTS = frozenset({
    # The user typed a skill's command string, character for character
    # (_match_skill_command). Language-independent by construction: it is the
    # owner's own command, in whatever language the owner wrote it.
    "skill_command",
    # The content_video extension's command phrase ("làm video từ những gì
    # đã đọc hôm nay"). Not a guess about meaning: it is the phrase the
    # extension's SKILL.md hands the model, and the handler only queues an
    # approval-gated codex task. Left to the model on a desk with browser
    # tools, this turn wandered into a browser session and timed out.
    "content_video",
})
PASSTHROUGH_INTENTS = frozenset({
    # Costs no action and picks no tool — it only buys a cheaper reply.
    "greeting",
})


def defer_to_model(intent: Optional[IntentResult], reason: str = "desk") -> Optional[IntentResult]:
    """Neutralise a GUESSED classification so the model decides instead.

    Returns the intent untouched when there is nothing to defer (a literal
    command match, a greeting, or no intent at all). Otherwise returns a fresh
    complex_action intent: no skip_llm shortcut, no pre-picked skill, no
    specialist to hand the turn to — just "call the model and let it read the
    desk". The extracted URL travels along, being a fact rather than a guess.

    NOTE what this function does NOT do: it adds no keyword, in any language.
    The decision to call it is made from the shape of the group, not the words
    of the message.
    """
    if intent is None:
        return None
    was = intent.intent_type or ""
    if was in LITERAL_INTENTS or was in PASSTHROUGH_INTENTS:
        return intent
    return IntentResult(
        intent_type="complex_action",
        confidence=0.0,
        matched_skills=[],
        extracted_data=dict(intent.extracted_data or {}),
        target_agent_id=None,
        skip_llm=False,
        deferred_from=was or reason,
    )


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

# Google Sheets/Docs/Drive là tài nguyên cloud, KHÔNG phải file trên đĩa.
# "tạo file sheet" từng khớp FILE_OPS → file_action → lỗi sandbox; còn
# "tạo google sheet" khớp SEARCH (chữ "google") → đi Google Search. Cả hai
# đều phải được chặn và trả về complex_action để pipeline inject SKILL.md
# (nơi duy nhất có cú pháp create_sheet cho model).
CLOUD_DOC_RE = re.compile(
    r"(sheet|spread\s*sheet|spreadsheet|bảng\s*tính|bang\s*tinh|trang\s*tính|"
    r"google\s*(sheet|doc|drive)|\bdocs?\b|\bdrive\b|excel\s*online|gg\s*sheet)", re.I)

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

# "Phân tích kênh + đề xuất ý tưởng" — chạy skill Analyze Channel. Trước đây
# "bạn vào kênh <url> phân tích nội dung" không khớp lệnh "phân tích kênh"
# (không đứng đầu câu) → rơi vào LLM → deepseek bịa "không có browser skill".
CHANNEL_ANALYZE_VERBS = [
    "phân tích kênh", "phân tích nội dung kênh", "analyze channel",
    "analyse channel", "channel analysis", "ý tưởng kênh", "channel ideas",
    "kênh tương tự", "similar channel", "tạo kênh tương tự", "phân tích channel",
    "分析频道", "频道分析",
]
# URL kênh (KHÔNG phải video/live). Scheme optional để bắt cả "youtube.com/@x".
# Bỏ /watch /shorts /live /video/ (những cái đó đi nhánh video).
_CHANNEL_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:"
    r"youtube\.com/(?:@[\w.-]+|channel/[\w-]+|c/[\w.-]+|user/[\w.-]+)"
    r"|tiktok\.com/@[\w.-]+"
    r"|douyin\.com/user/[\w-]+"
    r")(?:/?\??\S*)?", re.I)

# Động từ "đọc/mở/tóm tắt một trang cụ thể" — dùng cho intent read_page.
# CJK giữ substring; Latin/tiếng Việt chốt whole-word qua _kw_hit.
READ_PAGE_VERBS = [
    "xem trang", "xem web", "đọc trang", "đọc báo", "vào trang", "vào web",
    "mở trang", "mở web", "truy cập", "tóm tắt", "lấy tin", "lấy nội dung",
    "lấy bài", "trích nội dung", "đọc", "xem", "crawl", "scrape", "cào",
    "read", "browse", "open", "summarize", "summary", "fetch", "visit",
    "打开", "阅读", "总结", "抓取",
]

# TLD phổ biến — chặn "file.txt", "v1.2" khỏi bị nhận nhầm là domain.
_TLD = (r"(?:com|net|org|vn|io|co|info|news|tv|me|edu|gov|biz|xyz|dev|app|ai|"
        r"cn|jp|kr|uk|us|de|fr|ru|com\.vn|edu\.vn|gov\.vn|org\.vn)")
_BARE_DOMAIN_RE = re.compile(
    r"\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+" + _TLD + r")(/\S*)?\b", re.I)

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
    # Non-douyin hosts the downloader handles just as well. This list used to
    # stop at douyin/tiktok, so "download <youtube link>" never hit the 0-token
    # download path — it fell through to an LLM that sometimes invented a broken
    # run_api call. Each pattern pins a VIDEO page shape: channel/profile URLs
    # (youtube.com/@handle, tiktok.com/@user) must keep flowing to channel
    # analysis, not download.
    r'https?://(?:www\.|m\.)?youtube\.com/(?:watch\?\S*v=|shorts/|live/)\S+',
    r'https?://youtu\.be/\S+',
    r'https?://(?:www\.|m\.|web\.)?facebook\.com/(?:\S+/videos/|reel/|watch/?\?\S*v=|share/[vr]/)\S+',
    r'https?://fb\.watch/\S+',
    r'https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/\S+',
    r'https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/[^/\s]+/status/\S+',
    r'https?://(?:www\.)?vimeo\.com/\d+\S*',
    r'https?://(?:www\.)?dailymotion\.com/video/\S+',
    r'https?://(?:www\.)?bilibili\.com/video/\S+',
    r'https?://(?:www\.)?twitch\.tv/videos/\S+',
    r'https?://(?:www\.)?kuaishou\.com/short-video/\S+',
]

# "Please download …" in every shipped language. Word-boundary matched via
# _kw_hit, so "postal" ≠ "post" style false hits cannot come back.
DOWNLOAD_KEYWORDS = [
    "tải", "tải về", "tai video", "download", "save video", "lưu video",
    "下载", "下載", "ダウンロード", "保存して", "다운로드", "받아줘",
    "скачать", "скачай", "загрузи видео", "indir", "descargar", "descarga",
]

# Words that mark the request as being about a video at all — the no-URL ask
# below must not fire on "download the excel report".
VIDEO_WORDS = [
    "video", "clip", "youtube", "tiktok", "douyin", "shorts", "reel", "phim",
    "视频", "影片", "動画", "영상", "видео", "ролик", "vídeo",
]

# "làm video từ những gì đã đọc hôm nay" — the content_video extension's own
# command phrase (its SKILL.md documents the same one for the model). It takes
# a make-verb, a video word and a cue that the material is the agent's OWN
# corpus (or explicitly given links). A bare "làm video" never matches, and a
# download / subtitle request never does — those keep their own branches.
CONTENT_VIDEO_VERBS = [
    "làm", "lam", "tạo", "tao", "dựng", "dung", "sản xuất", "biến", "make", "create",
    "build", "produce", "generate", "turn", "制作", "作成", "만들어", "сделай", "создай",
    "yap", "haz", "crea",
    # "tổng hợp tin tức hôm nay thành video" — compile/summarise INTO a video
    "tổng hợp", "tong hop", "summarize", "summarise", "compile",
]
CONTENT_VIDEO_CORPUS_CUES = [
    "đã đọc", "da doc", "đã xem", "da xem", "hôm nay", "hom nay", "hôm qua", "hom qua",
    "những gì", "nhung gi", "tổng hợp", "tong hop", "đã cào", "da cao", "tin tức", "tin tuc",
    # CỐ Ý không có "tất cả" trần: "làm video quảng cáo cho tất cả sản phẩm" sẽ
    # khớp nhầm. Chỉ những cụm nói rõ là NỘI DUNG ĐÃ THU mới vào đây.
    "đã thu", "da thu", "thu thập", "thu thap",
    "from what", "i read", "i've read", "i have read", "have read", "we read", "watched",
    "everything i", "all the content", "collected", "today", "yesterday",
    "digest", "round-up", "roundup", "recap", "오늘", "сегодня", "bugün", "hoy",
]
CONTENT_VIDEO_SOURCE_CUES = [
    "link", "links", "bài viết", "bai viet", "bài này", "bai nay", "articles", "article",
    "nguồn", "nguon", "sources", "source", "trang này", "trang nay", "url",
]
CONTENT_VIDEO_YESTERDAY = ["hôm qua", "hom qua", "yesterday", "어제", "вчера", "dün", "ayer"]
# "tất cả những gì đã đọc" → bỏ hẳn bộ lọc ngày. Mặc định của lệnh là CHỈ
# hôm nay, nên một agent thu thập tối qua mà sáng nay chưa chạy lượt nào sẽ
# bị báo "không có gì mới" dù kho đầy. Đặt TRƯỚC "hôm qua" khi cả hai cùng
# khớp: "tất cả" rộng hơn nên nó thắng.
CONTENT_VIDEO_ALLTIME = [
    "tất cả", "tat ca", "toàn bộ", "toan bo", "mọi thứ", "moi thu", "từ trước", "tu truoc",
    "đã thu được", "da thu duoc", "all of", "everything", "all the", "so far",
    "全部", "すべて", "전체", "всё", "все", "tümü", "todo",
]
# "video 5 phút" / "dài 10 phút" / "a 3 minute video" → độ dài kịch bản.
# Trước đây không có cách nào nói độ dài từ chat: mọi video ra ~90 giây, kể cả
# khi mẫu Content Studio đã chọn "Long > 10 phút".
CONTENT_VIDEO_MINUTES_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s*(?:phút|phut|p|minutes?|mins?|分|분)", re.I)

CONTENT_VIDEO_VERTICAL = ["reels", "reel", "shorts", "short", "tiktok", "dọc", "9:16", "vertical"]
# "theo mẫu Tin nhanh" / "with the template "News Flash"" → the Content Studio
# wizard preset the video follows. Matched on the ORIGINAL text so the name
# keeps its case: preset names are looked up verbatim on the server.
CONTENT_VIDEO_PRESET_RES = [
    # Có cả dạng không dấu (dung/bang/voi/mau) như mọi bảng cue khác của content_video.
    re.compile(r"(?<!\w)(?:theo|dùng|dung|bằng|bang|với|voi)\s+(?:template|mẫu|mau|preset)\s+(.+)", re.I | re.S),
    re.compile(r"(?<!\w)(?:with|using|from|in)\s+(?:the\s+)?(?:template|preset)\s+(.+)", re.I | re.S),
]
_QUOTE_CHARS = "\"'“”‘’«»"
# Nháy mở nào đóng bằng nháy nấy: "Ben's picks" không được cắt ở dấu nháy đơn.
_QUOTE_PAIRS = {'"': '"', "'": "'", "“": "”", "‘": "’", "«": "»"}
# Chữ đuôi của câu chat, không phải một phần của tên mẫu. Tra tên ở Studio là so
# khớp đúng chữ, nên "Tin nhanh nhé" mà giữ nguyên là cả lượt chạy hỏng.
_PRESET_TAILS = ("nhé", "nha", "nhá", "đi", "giúp", "giùm", "với", "hộ",
                 "giúp tôi", "giúp mình", "giùm tôi", "giùm mình", "hộ tôi", "hộ mình",
                 "cho tôi", "cho mình", "please", "pls", "plz", "thanks", "thank you", "ok")

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

# Đọc lại kho ĐÃ cào, khác hẳn với đi cào thêm. Ranh giới nằm ở thì của động
# từ — "đã cào"/"scraped" là quá khứ, "đi cào <url>" là mệnh lệnh — nên mẫu
# dưới đây luôn buộc phải có dấu hiệu quá khứ hoặc một danh từ chỉ cái kho,
# không bao giờ chỉ mỗi từ "cào".
SCRAPED_DATA_PATTERNS = [
    r"(dữ\s*liệu|du\s*lieu|nội\s*dung|noi\s*dung|bài|bai|tin)\s*(nào\s*)?(đã|da)\s*(cào|cao|thu\s*thập|thu\s*thap|crawl|scrape)",
    r"(đã|da)\s*(cào|cao|crawl|scrape)\w*\s*(được|duoc)?\s*(gì|gi|những\s*gì|nhung\s*gi|bao\s*nhiêu|bao\s*nhieu)",
    r"\b(scraped|crawled)\s+(data|articles?|content|pages?)\b",
    r"\b(kho|corpus)\s*(dữ\s*liệu|du\s*lieu|bài|bai)\b",
    r"(lấy|lay|xem|liệt\s*kê|liet\s*ke|danh\s*sách|danh\s*sach|show|list|get)\s+.{0,20}(đã|da)\s*(cào|cao|crawl|scrape)",
    r"(bài|bai|articles?)\s+.{0,15}(cào|cao|scrape[d]?|crawl(ed)?)\s+.{0,15}(hôm\s*nay|hom\s*nay|hôm\s*qua|hom\s*qua|today|yesterday)",
]

# "đọc full/toàn văn" → trả kèm nội dung, không chỉ tiêu đề.
SCRAPED_FULLTEXT_PATTERNS = [
    r"\b(full|toàn\s*văn|toan\s*van|đầy\s*đủ|day\s*du|chi\s*tiết|chi\s*tiet|nguyên\s*văn|nguyen\s*van)\b",
    r"\b(kèm|kem|cả|ca|với|voi)\s*(nội\s*dung|noi\s*dung|content|body)\b",
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

        # ── 0a. Content video from the agent's own corpus ──────────
        # Before URL detection on purpose: "làm video từ bài này <url>" must
        # reach the content_video extension, not the downloader.
        cv = self._content_video_intent(text, text_lower)
        if cv is not None:
            return cv

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
        if not video_url and self._kw_hit(text_lower, DOWNLOAD_KEYWORDS):
            # An explicit download request vouches for the link, whatever the
            # host — the downloader supports ~1800 sites, far more than any
            # hand-kept pattern list. The URL then flows through the SAME
            # keyword checks below (tracker/live/reup/subtitle/upload), so
            # "tải video mới nhất của <channel>" still reaches the tracker.
            candidate = self._extract_any_url(text)
            if candidate and not candidate.startswith("rtmp://") and ".m3u8" not in candidate:
                video_url = candidate
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

        # ── 1b. Video request with NO link ───────────────────────
        # "Download this YouTube video and give me the transcript" carries no
        # URL. Left to the LLM, the Video Agent once answered by running its
        # capabilities skill and dumping raw JSON. Deterministic instead: ask
        # for the link, zero tokens.
        if (
            (self._kw_hit(text_lower, DOWNLOAD_KEYWORDS) or self._kw_hit(text_lower, SUBTITLE_KEYWORDS))
            and self._kw_hit(text_lower, VIDEO_WORDS)
            and not self._extract_any_url(text)
        ):
            return IntentResult(
                intent_type="video_request_no_url",
                confidence=0.9,
                extracted_data={"original_message": text},
                skip_llm=True,
            )

        # ── 1c. Phân tích kênh (Analyze Channel) ──────────────────
        # Đặt TRƯỚC skill_command để "bạn vào kênh <url> phân tích..." và
        # "phân tích kênh <url>" cùng đi một đường (channel_analyze) — cả 2
        # dispatcher đều xử lý, không lệch web/telegram. URL kênh + động từ
        # phân tích → chạy skill Analyze Channel deterministic (0-token).
        channel_url = None
        cm = _CHANNEL_URL_RE.search(text)
        if cm:
            channel_url = cm.group(0).rstrip(".,;?!)")
            if not re.match(r"^https?://", channel_url, re.I):
                channel_url = "https://" + channel_url  # endpoint cần URL đầy đủ
        if channel_url and (
            self._kw_hit(text_lower, CHANNEL_ANALYZE_VERBS)
            or self._kw_hit(text_lower, ["phân tích", "analyze", "analyse", "ý tưởng", "分析"])
        ):
            analyze_skill = self._find_skill_by_command(
                skills, ["phân tích kênh", "analyze channel", "channel ideas", "ý tưởng kênh"]
            )
            return IntentResult(
                intent_type="channel_analyze",
                confidence=0.96,
                matched_skills=[analyze_skill["id"]] if analyze_skill else [],
                extracted_data={"url": channel_url, "task": text},
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
        if self._matches_any(text_lower, FILE_OPS_PATTERNS) and not CLOUD_DOC_RE.search(text_lower):
            return IntentResult(
                intent_type="file_ops",
                confidence=0.90,
            )

        # ── 5a. Google Sheets/Docs/Drive — tài nguyên cloud ──────
        # Đặt TRƯỚC read_page/SEARCH: "tạo google sheet" có chữ "google" sẽ bị
        # SEARCH cướp nếu để rơi xuống. complex_action ⇒ pipeline inject
        # EXTENSION SKILL DOCS (cú pháp create_sheet) vào system prompt.
        if CLOUD_DOC_RE.search(text_lower):
            sheet_skills = self._find_skills_by_category(
                skills, ["sheet", "spreadsheet", "bảng tính", "drive"])
            return IntentResult(
                intent_type="complex_action",
                confidence=0.88,
                matched_skills=[s["id"] for s in sheet_skills[:1]],
            )

        # ── 5b. Read a SPECIFIC page ─────────────────────────────
        # "xem trang vnexpress.net xong tóm tắt", "đọc <url> lấy tin"... phải
        # được hiểu là ĐỌC trang đó — không phải Google Search. Đặt TRƯỚC
        # SEARCH vì câu có "tin tức" sẽ khớp SEARCH_PATTERNS và cướp mất.
        page_url = self._extract_readable_url(text, text_lower)
        if page_url and self._kw_hit(text_lower, READ_PAGE_VERBS):
            return IntentResult(
                intent_type="read_page",
                confidence=0.92,
                extracted_data={"url": page_url, "task": text},
                skip_llm=True,
            )

        # ── 5c. Đọc kho dữ liệu ĐÃ cào ───────────────────────────
        # "lấy dữ liệu đã cào hôm nay" là đọc kho trên đĩa, KHÔNG phải đi cào
        # tiếp. Phải đặt TRƯỚC cả SEARCH lẫn BROWSER: câu có "cào"/"dữ liệu"
        # khớp BROWSER_PATTERNS, nên để rơi xuống dưới thì agent sẽ mở trình
        # duyệt đi cào lại đúng thứ nó đã có sẵn.
        if self._matches_any(text_lower, SCRAPED_DATA_PATTERNS):
            return IntentResult(
                intent_type="scraped_data",
                confidence=0.93,
                extracted_data={"query": text, "with_content": bool(
                    self._matches_any(text_lower, SCRAPED_FULLTEXT_PATTERNS))},
                skip_llm=True,
            )

        # ── 6. Search ────────────────────────────────────────────
        # Chỉ là Google Search khi KHÔNG trỏ tới một trang cụ thể — nếu có
        # URL/domain + động từ đọc thì nhánh read_page ở trên đã xử lý.
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
            
            # No profile named is the NORMAL case ("mở trình duyệt", "close the
            # browser"): every word of those sentences is a keyword, so neither
            # branch below assigns anything. Without this default the return
            # below read an unbound local and the whole turn died with
            # UnboundLocalError — the user got no answer at all.
            profile_name = ""
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

    def _extract_readable_url(self, text: str, text_lower: str) -> Optional[str]:
        """URL/domain của một trang ĐỌC ĐƯỢC (không phải video/channel URL đã
        xử lý ở nhánh trước). Trả full URL, hoặc bare domain (sẽ thêm https://)."""
        # 1. URL đầy đủ — nhưng bỏ qua nếu là video URL (đã có nhánh riêng)
        m = re.search(r'https?://\S+', text)
        if m:
            url = m.group(0).rstrip('.,;?!)')
            for pat in VIDEO_URL_PATTERNS:
                if re.match(pat, url):
                    return None  # để nhánh video xử lý
            return url
        # 2. Bare domain (vnexpress.net, vietnamnet.vn/...)
        dm = _BARE_DOMAIN_RE.search(text)
        if dm:
            domain = dm.group(1)
            path = dm.group(2) or ""
            # loại email (có @ ngay trước)
            start = dm.start()
            if start > 0 and text[start - 1] == "@":
                return None
            return domain + path
        return None

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

    def _content_video_intent(self, text: str, text_lower: str) -> Optional[IntentResult]:
        """"làm video từ những gì đã đọc hôm nay" → content_video, zero tokens.

        Verb + video word + a corpus cue; or verb + video word + a source cue
        WITH at least one URL. Download/subtitle wording is left to its own
        branches so "tải video hôm nay" still downloads.
        """
        if not self._kw_hit(text_lower, CONTENT_VIDEO_VERBS):
            return None
        if not self._kw_hit(text_lower, VIDEO_WORDS):
            return None
        if self._kw_hit(text_lower, DOWNLOAD_KEYWORDS) or self._kw_hit(text_lower, SUBTITLE_KEYWORDS):
            return None
        urls = [u.rstrip(".,;?!)") for u in re.findall(r"https?://\S+", text)]
        corpus_cue = self._kw_hit(text_lower, CONTENT_VIDEO_CORPUS_CUES)
        source_cue = self._kw_hit(text_lower, CONTENT_VIDEO_SOURCE_CUES)
        if not corpus_cue and not (source_cue and urls):
            return None
        data: Dict[str, Any] = {"sources": urls, "original_message": text}
        # Độ dài: đổi ra số chữ ngay tại đây để pipeline chỉ phải hiểu MỘT đơn
        # vị. 150 chữ/phút là nhịp đọc thành tiếng, khớp WORDS_PER_MINUTE.
        m_len = CONTENT_VIDEO_MINUTES_RE.search(text_lower)
        if m_len:
            try:
                mins = int(m_len.group(1))
                if 1 <= mins <= 30:
                    data["target_words"] = mins * 150
            except ValueError:
                pass
        if self._kw_hit(text_lower, CONTENT_VIDEO_ALLTIME):
            data["day"] = "all"
        elif self._kw_hit(text_lower, CONTENT_VIDEO_YESTERDAY):
            data["day"] = "yesterday"
        if self._kw_hit(text_lower, CONTENT_VIDEO_VERTICAL):
            data["aspect_ratio"] = "9:16"
        preset = self._content_video_preset(text)
        if preset:
            data["preset"] = preset
        return IntentResult(
            intent_type="content_video",
            confidence=0.97,
            extracted_data=data,
            skip_llm=True,
        )

    @staticmethod
    def _content_video_preset(text: str) -> str:
        """The template name in "… theo mẫu <name>" / "… with the template <name>",
        "" when the sentence names none.

        A quoted name runs to the closing quote (commas inside survive); a bare
        one runs to the end of the sentence, a comma or a period — the user
        types the name the way the wizard shows it, nothing more structured.
        """
        for rx in CONTENT_VIDEO_PRESET_RES:
            m = rx.search(text or "")
            if not m:
                continue
            rest = m.group(1).strip()
            if rest and rest[0] in _QUOTE_PAIRS:
                close = rest.find(_QUOTE_PAIRS[rest[0]], 1)
                name = rest[1:close if close != -1 else len(rest)]
            else:
                name = re.split(r"[,.\n]", rest, 1)[0]
                # Bỏ dấu câu cuối và chữ đuôi ("nhé", "please"…), lặp vì có thể chồng nhau.
                name = name.rstrip(" ?!…")
                changed = True
                while changed:
                    changed = False
                    low = name.lower()
                    for tail in _PRESET_TAILS:
                        if low == tail:
                            name = ""
                            changed = False
                            break
                        if low.endswith(" " + tail):
                            name = name[: -len(tail)].rstrip(" ?!…")
                            changed = True
            name = name.strip().strip(_QUOTE_CHARS).strip()
            if name:
                return name
        return ""

    def _match_skill_command(self, msg_lower: str, skills: List[Dict]) -> Optional[Dict]:
        """Check for exact skill command match.

        Mirrors AgentBrain.match_skill_command: skip skills that cannot run,
        so dead sop-shells never hijack commands from live skills."""
        from tubecli.core.brain import is_skill_runnable

        msg_clean = re.sub(r'[?!.,;]+$', '', msg_lower).strip()
        for skill in skills:
            if not is_skill_runnable(skill):
                continue
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

    def _find_skill_by_command(self, skills: List[Dict], commands: List[str]) -> Optional[Dict]:
        """Tìm skill CHẠY ĐƯỢC có một trong các command cho trước (khớp chính
        xác một lệnh, không cần message bắt đầu bằng lệnh)."""
        from tubecli.core.brain import is_skill_runnable
        wanted = {c.strip().lower() for c in commands}
        for s in skills or []:
            if not is_skill_runnable(s):
                continue
            for cmd in (s.get("commands") or []):
                if (cmd or "").strip().lower() in wanted:
                    return s
        return None

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
            
            # Check if message matches this specialist's domain.
            # Whole-word match (same fix as _kw_hit): plain substring made
            # "live" hit "deliver", "web" hit "website", "edit" hit "credit".
            for specialty in specialties:
                if self._kw_hit(text_lower, [specialty.lower()]):
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
