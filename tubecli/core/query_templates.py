"""Câu tìm kiếm của agent: theo CHỦ ĐỀ của nó, và theo ĐÚNG NGÔN NGỮ của nó.

VÌ SAO CÓ FILE NÀY
    Bản trước để toàn bộ mẫu câu bằng tiếng Anh ngay trong server.py, nên một agent
    tiếng Việt vẫn đi gõ "learn X from scratch" và rơi vào kết quả tiếng Anh — có
    lượt lạc hẳn sang learningresources.com, một cửa hàng đồ chơi (người dùng chụp
    ảnh 9/9/2026). Hành vi "lướt tin" thì tệ hơn: nó bỏ qua chủ đề, vào thẳng trang
    chủ tờ báo, nên agent nào cũng đọc y hệt nhau bất kể quan tâm cái gì.

    Ở đây mỗi hành vi chỉ là một lớp TIỀN TỐ/HẬU TỐ quấn quanh chủ đề: học thì
    "học … từ đầu", tin thì "tin tức … hôm nay". Chủ đề luôn là của agent.

CÁCH TRA
    zh-TW → zh → en: một ngôn ngữ thiếu mẫu thì lùi về ngôn ngữ gốc rồi mới tới
    tiếng Anh, chứ không nhảy thẳng sang tiếng Anh và làm agent nói hai thứ tiếng.
"""
from __future__ import annotations

# Mỗi hành vi ≥ 4 mẫu để hai lượt liền nhau không ra cùng một câu.
TEMPLATES: dict[str, dict[str, list[str]]] = {
    "vi": {
        "work": ["cách {topic}", "{topic} hiệu quả", "tin mới về {topic}",
                 "hướng dẫn {topic} chuyên sâu", "công cụ {topic} tốt nhất",
                 "kinh nghiệm {topic}"],
        "research": ["nghiên cứu mới về {topic}", "xu hướng {topic} sắp tới",
                     "{topic} là gì", "phân tích chuyên sâu {topic}",
                     "đột phá trong {topic}"],
        "study": ["học {topic} từ đầu", "{topic} cho người mới bắt đầu",
                  "tài liệu học {topic}", "khoá học {topic} miễn phí",
                  "lộ trình học {topic}", "bài giảng {topic}"],
        "morningCheck": ["tin tức {topic} hôm nay", "tin mới nhất về {topic}",
                         "{topic} có gì mới", "cập nhật tình hình {topic}",
                         "diễn biến {topic}"],
        "entertainment": ["{topic} hay nhất", "khoảnh khắc {topic} đáng nhớ",
                          "video {topic} thú vị", "tổng hợp {topic}"],
        "watchVideos": ["{topic} hay nhất", "review {topic}",
                        "phim tài liệu về {topic}", "{topic} giải thích dễ hiểu"],
        "relax": ["mẹo sống {topic}", "thư giãn cùng {topic}",
                  "{topic} cho tinh thần thoải mái", "góc thư giãn {topic}"],
    },
    "en": {
        "work": ["{topic} how to", "{topic} best practices", "latest {topic} news",
                 "{topic} tutorial for professionals", "{topic} tips and tricks",
                 "top {topic} tools", "{topic} case study"],
        "research": ["latest research on {topic}", "{topic} future trends",
                     "what is {topic} explained", "{topic} in-depth analysis",
                     "breakthroughs in {topic}"],
        "study": ["learn {topic} from scratch", "{topic} for beginners",
                  "{topic} complete guide", "free {topic} online course",
                  "how to master {topic}", "{topic} lecture notes"],
        "morningCheck": ["{topic} news today", "breaking {topic} updates",
                         "latest {topic} headlines", "what's new in {topic}",
                         "{topic} developments"],
        "entertainment": ["top {topic}", "{topic} highlights", "best {topic} videos",
                          "{topic} compilation"],
        "watchVideos": ["best {topic}", "{topic} video review", "{topic} documentary",
                        "{topic} explained"],
        "relax": ["{topic} lifestyle tips", "{topic} wellness guide",
                  "unwind with {topic}", "{topic} for relaxation"],
    },
    "zh": {
        "work": ["如何{topic}", "{topic}最佳实践", "{topic}最新消息",
                 "{topic}进阶教程", "{topic}常用工具", "{topic}实战经验"],
        "research": ["{topic}最新研究", "{topic}未来趋势", "什么是{topic}",
                     "{topic}深度分析", "{topic}突破进展"],
        "study": ["从零学{topic}", "{topic}入门教程", "{topic}完整指南",
                  "{topic}免费课程", "{topic}学习路线", "{topic}讲义"],
        "morningCheck": ["{topic}今日新闻", "{topic}最新消息", "{topic}最新动态",
                         "{topic}热点追踪", "{topic}进展"],
        "entertainment": ["最佳{topic}", "{topic}精彩集锦", "{topic}视频推荐",
                          "{topic}合集"],
        "watchVideos": ["最好的{topic}", "{topic}测评", "{topic}纪录片", "{topic}讲解"],
        "relax": ["{topic}生活小技巧", "{topic}养生指南", "和{topic}一起放松"],
    },
    "zh-TW": {
        "work": ["如何{topic}", "{topic}最佳實踐", "{topic}最新消息",
                 "{topic}進階教學", "{topic}常用工具", "{topic}實戰經驗"],
        "research": ["{topic}最新研究", "{topic}未來趨勢", "什麼是{topic}",
                     "{topic}深度分析", "{topic}突破進展"],
        "study": ["從零學{topic}", "{topic}入門教學", "{topic}完整指南",
                  "{topic}免費課程", "{topic}學習路線", "{topic}講義"],
        "morningCheck": ["{topic}今日新聞", "{topic}最新消息", "{topic}最新動態",
                         "{topic}熱點追蹤", "{topic}進展"],
        "entertainment": ["最佳{topic}", "{topic}精彩集錦", "{topic}影片推薦",
                          "{topic}合輯"],
        "watchVideos": ["最好的{topic}", "{topic}評測", "{topic}紀錄片", "{topic}講解"],
        "relax": ["{topic}生活小技巧", "{topic}養生指南", "和{topic}一起放鬆"],
    },
    "ja": {
        "work": ["{topic} やり方", "{topic} ベストプラクティス", "{topic} 最新ニュース",
                 "{topic} 実践ガイド", "{topic} おすすめツール", "{topic} 事例"],
        "research": ["{topic} 最新研究", "{topic} 今後のトレンド", "{topic} とは",
                     "{topic} 詳細分析", "{topic} 最新の進展"],
        "study": ["{topic} 初心者向け", "{topic} 入門", "{topic} 完全ガイド",
                  "{topic} 無料講座", "{topic} 勉強法", "{topic} 講義資料"],
        "morningCheck": ["{topic} ニュース 今日", "{topic} 最新ニュース",
                         "{topic} 最新情報", "{topic} 話題", "{topic} 動向"],
        "entertainment": ["{topic} おすすめ", "{topic} ハイライト", "{topic} 動画",
                          "{topic} まとめ"],
        "watchVideos": ["{topic} おすすめ動画", "{topic} レビュー",
                        "{topic} ドキュメンタリー", "{topic} 解説"],
        "relax": ["{topic} リラックス法", "{topic} 健康ガイド", "{topic} で癒される"],
    },
    "ko": {
        "work": ["{topic} 하는 법", "{topic} 모범 사례", "{topic} 최신 뉴스",
                 "{topic} 실전 가이드", "{topic} 추천 도구", "{topic} 사례"],
        "research": ["{topic} 최신 연구", "{topic} 향후 전망", "{topic} 란 무엇인가",
                     "{topic} 심층 분석", "{topic} 최신 성과"],
        "study": ["{topic} 기초부터", "{topic} 입문", "{topic} 완전 정복",
                  "{topic} 무료 강의", "{topic} 공부 방법", "{topic} 강의 자료"],
        "morningCheck": ["{topic} 오늘 뉴스", "{topic} 최신 소식", "{topic} 속보",
                         "{topic} 이슈", "{topic} 동향"],
        "entertainment": ["{topic} 추천", "{topic} 하이라이트", "{topic} 영상",
                          "{topic} 모음"],
        "watchVideos": ["{topic} 추천 영상", "{topic} 리뷰", "{topic} 다큐멘터리",
                        "{topic} 설명"],
        "relax": ["{topic} 생활 팁", "{topic} 건강 관리", "{topic} 로 휴식"],
    },
    "es": {
        "work": ["cómo {topic}", "mejores prácticas de {topic}",
                 "últimas noticias de {topic}", "guía práctica de {topic}",
                 "mejores herramientas de {topic}", "caso práctico de {topic}"],
        "research": ["últimas investigaciones sobre {topic}",
                     "tendencias futuras de {topic}", "qué es {topic}",
                     "análisis profundo de {topic}", "avances en {topic}"],
        "study": ["aprender {topic} desde cero", "{topic} para principiantes",
                  "guía completa de {topic}", "curso gratis de {topic}",
                  "cómo dominar {topic}", "apuntes de {topic}"],
        "morningCheck": ["noticias de {topic} hoy", "últimas noticias sobre {topic}",
                         "novedades de {topic}", "actualidad de {topic}",
                         "qué hay de nuevo en {topic}"],
        "entertainment": ["los mejores {topic}", "lo mejor de {topic}",
                          "vídeos de {topic}", "recopilación de {topic}"],
        "watchVideos": ["mejores vídeos de {topic}", "reseña de {topic}",
                        "documental sobre {topic}", "{topic} explicado"],
        "relax": ["consejos de bienestar sobre {topic}", "relajarse con {topic}",
                  "guía de {topic} para desconectar"],
    },
    "tr": {
        "work": ["{topic} nasıl yapılır", "{topic} en iyi uygulamalar",
                 "{topic} son haberler", "{topic} uygulamalı rehber",
                 "{topic} en iyi araçlar", "{topic} örnek çalışma"],
        "research": ["{topic} son araştırmalar", "{topic} gelecek trendleri",
                     "{topic} nedir", "{topic} derinlemesine analiz",
                     "{topic} yeni gelişmeler"],
        "study": ["sıfırdan {topic} öğren", "yeni başlayanlar için {topic}",
                  "{topic} tam rehber", "ücretsiz {topic} kursu",
                  "{topic} nasıl öğrenilir", "{topic} ders notları"],
        "morningCheck": ["{topic} bugünkü haberler", "{topic} son dakika",
                         "{topic} güncel haberler", "{topic} gelişmeler",
                         "{topic} hakkında yenilikler"],
        "entertainment": ["en iyi {topic}", "{topic} özetleri", "{topic} videoları",
                          "{topic} derlemesi"],
        "watchVideos": ["en iyi {topic} videoları", "{topic} inceleme",
                        "{topic} belgeseli", "{topic} anlatımı"],
        "relax": ["{topic} yaşam önerileri", "{topic} ile rahatla",
                  "{topic} sağlıklı yaşam rehberi"],
    },
    "ru": {
        "work": ["{topic} на практике", "{topic} лучшие практики", "{topic} последние новости",
                 "{topic} практическое руководство", "лучшие инструменты {topic}",
                 "разбор примера {topic}"],
        "research": ["последние исследования {topic}", "тренды {topic}",
                     "что такое {topic}", "глубокий анализ {topic}",
                     "прорывы в {topic}"],
        "study": ["{topic} с нуля", "{topic} для начинающих",
                  "полное руководство {topic}", "бесплатный курс {topic}",
                  "как освоить {topic}", "конспект {topic}"],
        "morningCheck": ["{topic} новости сегодня", "последние новости {topic}",
                         "что нового {topic}", "события {topic}", "сводка {topic}"],
        "entertainment": ["лучшее {topic}", "{topic} нарезка", "видео о {topic}",
                          "подборка {topic}"],
        "watchVideos": ["лучшие видео {topic}", "обзор {topic}",
                        "документальный фильм {topic}", "{topic} простыми словами"],
        "relax": ["{topic} советы для жизни", "расслабиться с {topic}",
                  "{topic} для отдыха"],
    },
}

# Dấu thời gian rắc ngẫu nhiên vào câu. Chuỗi rỗng chiếm đa số: câu nào cũng đính
# "mới nhất" thì lại thành một khuôn mẫu khác, dễ nhận ra chẳng kém.
TIME_HINTS: dict[str, list[str]] = {
    "vi": ["", "", "", "mới nhất", "gần đây", "năm nay", "mới", "đang hot"],
    "en": ["", "", "", "latest", "recently", "this year", "new", "trending"],
    "zh": ["", "", "", "最新", "近期", "今年", "热门"],
    "zh-TW": ["", "", "", "最新", "近期", "今年", "熱門"],
    "ja": ["", "", "", "最新", "最近", "今年", "話題の"],
    "ko": ["", "", "", "최신", "최근", "올해", "인기"],
    "es": ["", "", "", "últimas", "reciente", "este año", "tendencia"],
    "tr": ["", "", "", "en son", "yakın zamanda", "bu yıl", "gündemdeki"],
    "ru": ["", "", "", "последние", "недавно", "в этом году", "популярное"],
}

# Khi agent chưa khai chủ đề nào: câu chung, vẫn đúng ngôn ngữ của nó.
NO_TOPIC: dict[str, dict[str, list[str]]] = {
    "vi": {
        "morningCheck": ["tin nóng hôm nay", "tin thế giới"],
        "work": ["xu hướng công nghệ", "tin công nghệ mới"],
        "study": ["khoá học trực tuyến miễn phí", "kỹ năng nên học"],
        "research": ["nghiên cứu mới công bố", "phát hiện khoa học mới"],
    },
    "en": {
        "morningCheck": ["breaking news today", "world news"],
        "work": ["github trending", "technology news"],
        "study": ["free online courses", "skills worth learning"],
        "research": ["new research published", "recent scientific discoveries"],
    },
    "zh": {
        "morningCheck": ["今日热点新闻", "国际新闻"],
        "work": ["技术趋势", "科技新闻"],
        "study": ["免费在线课程", "值得学习的技能"],
        "research": ["最新科研成果", "科学新发现"],
    },
    "ja": {
        "morningCheck": ["今日のニュース", "世界のニュース"],
        "work": ["技術トレンド", "テクノロジーニュース"],
        "study": ["無料オンライン講座", "学ぶべきスキル"],
        "research": ["最新の研究成果", "科学の新発見"],
    },
    "ko": {
        "morningCheck": ["오늘의 주요 뉴스", "세계 뉴스"],
        "work": ["기술 트렌드", "테크 뉴스"],
        "study": ["무료 온라인 강의", "배울 만한 기술"],
        "research": ["최신 연구 결과", "새로운 과학 발견"],
    },
    "es": {
        "morningCheck": ["noticias de última hora", "noticias del mundo"],
        "work": ["tendencias tecnológicas", "noticias de tecnología"],
        "study": ["cursos gratis en línea", "habilidades que vale la pena aprender"],
        "research": ["nuevas investigaciones", "descubrimientos científicos recientes"],
    },
    "tr": {
        "morningCheck": ["son dakika haberler", "dünya haberleri"],
        "work": ["teknoloji trendleri", "teknoloji haberleri"],
        "study": ["ücretsiz çevrimiçi kurslar", "öğrenmeye değer beceriler"],
        "research": ["yeni araştırmalar", "son bilimsel keşifler"],
    },
    "ru": {
        "morningCheck": ["главные новости сегодня", "новости мира"],
        "work": ["технологические тренды", "новости технологий"],
        "study": ["бесплатные онлайн курсы", "навыки которые стоит освоить"],
        "research": ["новые исследования", "научные открытия"],
    },
}


def normalize_lang(lang: str) -> str:
    """'vi-VN' → 'vi', 'zh_TW' → 'zh-TW'. Không rõ thì tiếng Anh."""
    s = str(lang or "").strip().replace("_", "-")
    if not s:
        return "en"
    if s in TEMPLATES:
        return s
    low = s.lower()
    for key in TEMPLATES:
        if key.lower() == low:
            return key
    base = low.split("-")[0]
    for key in TEMPLATES:
        if key.lower() == base:
            return key
    return "en"


def _chain(lang: str) -> list[str]:
    """Thứ tự lùi: đúng ngôn ngữ → ngôn ngữ gốc → tiếng Anh."""
    lang = normalize_lang(lang)
    out = [lang]
    base = lang.split("-")[0]
    if base != lang:
        out.append(base)
    if "en" not in out:
        out.append("en")
    return out


def templates_for(behavior: str, lang: str) -> list[str]:
    """Mẫu câu cho một hành vi, theo ngôn ngữ agent. Luôn trả về ≥ 1 mẫu."""
    for code in _chain(lang):
        got = (TEMPLATES.get(code) or {}).get(behavior)
        if got:
            return list(got)
    # Hành vi lạ (chưa có bảng riêng): vẫn phải ra một câu dùng được, đúng ngôn ngữ.
    for code in _chain(lang):
        got = (TEMPLATES.get(code) or {}).get("work")
        if got:
            return list(got)
    return ["{topic}"]


def time_hints_for(lang: str) -> list[str]:
    for code in _chain(lang):
        got = TIME_HINTS.get(code)
        if got:
            return list(got)
    return TIME_HINTS["en"]


def no_topic_queries(behavior: str, lang: str) -> list[str]:
    """Agent chưa khai chủ đề nào — vẫn phải hỏi bằng tiếng của nó."""
    for code in _chain(lang):
        table = NO_TOPIC.get(code) or {}
        got = table.get(behavior) or table.get("work")
        if got:
            return list(got)
    return NO_TOPIC["en"]["work"]
