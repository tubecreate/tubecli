# Câu tìm kiếm của agent phải theo CHỦ ĐỀ của nó và ĐÚNG NGÔN NGỮ của nó.
#
# Chạy:  python tests/query_language_test.py       (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   Mẫu câu từng nằm cứng bằng tiếng Anh trong server.py, nên một agent tiếng Việt
#   vẫn gõ "learn X from scratch". Tệ hơn: danh sách dự phòng của hành vi "học" có
#   nguyên chuỗi "learning resources" — agent tìm đúng chuỗi đó rồi bấm vào
#   learningresources.com, một cửa hàng đồ chơi (người dùng chụp ảnh 9/9/2026).
#   Và hành vi "lướt tin" bỏ qua chủ đề hoàn toàn: mọi agent đọc trang chủ cùng
#   một tờ báo bất kể quan tâm cái gì.
import io
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} -> {detail}")


from tubecli.core import query_templates as qt  # noqa: E402

LANGS = ["vi", "en", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"]
TOPIC_BEHAVIORS = ["work", "research", "study", "morningCheck",
                   "entertainment", "watchVideos", "relax"]

# ── 1. Phủ đủ ngôn ngữ × hành vi ────────────────────────────────────────────
check("đủ 9 ngôn ngữ", sorted(qt.TEMPLATES) == sorted(LANGS), sorted(qt.TEMPLATES))
missing = [(lg, b) for lg in LANGS for b in TOPIC_BEHAVIORS if not qt.TEMPLATES[lg].get(b)]
check("mọi ngôn ngữ có mọi hành vi cần chủ đề", not missing, missing[:4])

thin = [(lg, b, len(qt.TEMPLATES[lg][b])) for lg in LANGS for b in TOPIC_BEHAVIORS
        if len(qt.TEMPLATES[lg][b]) < 3]
check("mỗi hành vi ≥ 3 mẫu (hai lượt liền nhau không trùng câu)", not thin, thin[:4])

no_slot = [(lg, b, t) for lg in LANGS for b in TOPIC_BEHAVIORS
           for t in qt.TEMPLATES[lg][b] if "{topic}" not in t]
check("mẫu nào cũng có chỗ cắm chủ đề", not no_slot, no_slot[:3])

# ── 2. Mỗi hành vi là một lớp vỏ KHÁC NHAU quanh cùng chủ đề ────────────────
# Đây chính là yêu cầu: học và lướt tin cùng bám chủ đề, chỉ khác tiền tố/hậu tố.
for lg in LANGS:
    shells = {b: set(qt.templates_for(b, lg)) for b in ("study", "morningCheck", "research")}
    check(f"{lg}: học ≠ lướt tin ≠ nghiên cứu",
          not (shells["study"] & shells["morningCheck"])
          and not (shells["study"] & shells["research"]),
          {k: list(v)[:1] for k, v in shells.items()})

# ── 3. Không rò tiếng Anh sang ngôn ngữ khác ────────────────────────────────
# Dấu hiệu rò: mẫu tiếng Việt/Nhật/Nga mà lại chứa nguyên văn cụm tiếng Anh.
LEAK = ("news today", "from scratch", "for beginners", "best practices",
        "latest research", "complete guide", "learning resources")
leaks = [(lg, b, t) for lg in LANGS if lg != "en"
         for b in TOPIC_BEHAVIORS for t in qt.TEMPLATES[lg][b]
         for k in LEAK if k in t.lower()]
check("không mẫu nào của ngôn ngữ khác dính nguyên cụm tiếng Anh", not leaks, leaks[:3])

check("chuỗi đưa agent vào cửa hàng đồ chơi đã biến mất",
      all("learning resources" not in " ".join(v.get("study", [])).lower()
          for v in qt.NO_TOPIC.values()))

# ── 4. Đường lùi ngôn ngữ ───────────────────────────────────────────────────
check("vi-VN → vi", qt.normalize_lang("vi-VN") == "vi")
check("zh_TW → zh-TW", qt.normalize_lang("zh_TW") == "zh-TW")
check("ngôn ngữ lạ → en", qt.normalize_lang("fr") == "en")
check("rỗng → en", qt.normalize_lang("") == "en" and qt.normalize_lang(None) == "en")
check("hành vi lạ vẫn ra mẫu dùng được, đúng ngôn ngữ",
      qt.templates_for("khong_co_that", "vi")[0] in qt.TEMPLATES["vi"]["work"])
check("dấu thời gian cũng theo ngôn ngữ",
      "mới nhất" in qt.time_hints_for("vi") and "latest" in qt.time_hints_for("en"))
check("dấu thời gian phần lớn để trống (đính hoài lại thành khuôn mẫu khác)",
      qt.time_hints_for("vi").count("") >= 3, qt.time_hints_for("vi"))

# ── 5. server.py thật sự dùng bảng này ──────────────────────────────────────
src = io.open(ROOT / "tubecli/api/server.py", encoding="utf-8").read()
check("server nạp module mẫu câu", "from tubecli.core import query_templates as _qt" in src)
check("mẫu tra theo ngôn ngữ agent", "_qt.templates_for(b, _agent_lang)" in src)
check("dấu thời gian tra theo ngôn ngữ agent", "_qt.time_hints_for(_agent_lang)" in src)
check("câu dự phòng tra theo ngôn ngữ agent", "_qt.no_topic_queries(behavior, _agent_lang)" in src)
check("KHÔNG còn bảng mẫu tiếng Anh cứng trong server",
      '"learn {topic} from scratch"' not in src and '"{topic} news today"' not in src)

# Từ khoá người dùng là CHỦ ĐỀ, phải được quấn theo hành vi trước khi đem tìm.
check("từ khoá được quấn theo hành vi, không gõ trần",
      'base_query = rng.choice(fmts).replace("{topic}", base_topic)' in src)
check("sổ sách vẫn ghi CHỦ ĐỀ thô (nếu không, vòng 'đã dùng' không khớp lại được)",
      "period_used.append(base_topic)" in src)

# Lướt tin: vào trang báo RỒI tìm chủ đề trong chính trang đó.
check("lướt tin có tìm chủ đề khi agent đã khai",
      "then search for '{base_query}', " in src and "Do NOT use Google." in src)
check("chưa khai chủ đề thì vẫn đọc trang chủ như cũ",
      "then click an internal link within the SAME site, " in src)
check("lướt tin nay cũng đốt một lượt từ khoá",
      'behavior not in ("checkEmails", "replyEmail", "sendReport")' in src)

print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{FAIL} FAIL / {PASS + FAIL}")
sys.exit(1 if FAIL else 0)
