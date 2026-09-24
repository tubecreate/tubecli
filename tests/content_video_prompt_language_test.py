# -*- coding: utf-8 -*-
"""Prompt vẽ ảnh KHÔNG được dính chữ ngoài tiếng Anh — 23/9/2026.

VÌ SAO CÓ FILE NÀY
  User: «cái lỗi tạo ảnh này bạn phải sửa prompt hoặc đổi provider tạo chứ để vậy à?»

  Đo trên hai video tiếng Nhật đã dựng: 600/600 prompt vẽ ảnh bị nối lời đọc tiếng Nhật vào đuôi, do
  `_fill_missing_prompts` và nhánh lấp vỏ shot lấy thẳng `narration_text` làm mô tả hình. Hai hậu quả:
    1. Model vẽ chỉ đọc tiếng Anh ⇒ đoạn ấy là nhiễu, và với schnell (đọc ~256 token đầu) nó còn đẩy phần
       có ích ra ngoài tầm đọc.
    2. Bộ lọc nội dung KHÔNG hiểu tiếng Nhật nên đoán bừa: «テレビを消すこと。歯を磨くこと。» (tắt tivi, đánh
       răng) bị trả `Input prompt contains NSFW content`, nhịp ấy MẤT HẲN ảnh. Xảy ra ở cả ba video.

  Hai lớp chặn, file này canh cả hai:
    A. LÕI không nhét chữ ngoài tiếng Anh vào prompt ngay từ đầu.
    B. Lỡ vẫn bị từ chối thì bộ vẽ GỘT prompt rồi thử lại, chứ không bỏ trắng cả nhịp.

Run:  python tests/content_video_prompt_language_test.py     (exit 0 = pass) — không mạng.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


print("\nA. LÕI: chữ ngoài tiếng Anh không vào prompt vẽ")
from tubecli.extensions.content_video.pipeline import _for_image   # noqa: E402

ok(_for_image("今夜、寝る前に、あなたが最後にすることは、何ですか。") == "",
   "lời đọc tiếng Nhật ⇒ BỎ HẲN, không nối vào prompt")
ok(_for_image("テレビを消すこと。 歯を磨くこと。") == "",
   "đúng câu đã làm bộ lọc trả NSFW cũng bị bỏ")
ok(_for_image("Bạn hãy ngồi yên một phút") == "",
   "tiếng Việt có dấu cũng bỏ — model vẽ không đọc được")
_en = "An elderly man sitting on the edge of a bed, both feet flat on the floor"
ok(_for_image(_en) == _en, "tiếng Anh giữ NGUYÊN VĂN")
ok(_for_image("Zhuangzi and Esteban walking") == "Zhuangzi and Esteban walking",
   "tên riêng có dấu KHÔNG bị nhầm là ngoại ngữ — ngưỡng 1/4 số chữ cái")
ok(len(_for_image("x" * 500)) == 300 and len(_for_image("x" * 500, 80)) == 80, "vẫn cắt theo trần độ dài")

src = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
ok("_for_image(show) or _for_image(narr)" in src,
   "nhánh lấp vỏ shot lọc TRƯỚC khi ghép prompt")
ok('+ _for_image(what)' in src and 'what[:300]' not in src,
   "_fill_missing_prompts lọc trước khi ghép — đây là chỗ sinh ra 600 prompt hỏng")

print("\nB. BỘ VẼ: bị từ chối thì GỘT rồi thử lại, không bỏ trắng nhịp")
STUDIO = ROOT / "data" / "extensions_external" / "content_studio"
sys.path[:0] = [str(STUDIO), str(STUDIO / "engines")]
from api_image_engine import _ascii_only                            # noqa: E402

_mixed = "White chalk on a blackboard. One isolated subject. テレビを消すこと。歯を磨くこと。"
ok(_ascii_only(_mixed) == "White chalk on a blackboard. One isolated subject.",
   "gột bỏ câu ngoài ASCII, GIỮ khoá phong cách bằng tiếng Anh")
ok(_ascii_only("A heart. An arrow.") == "A heart. An arrow.", "prompt toàn tiếng Anh không đổi")
ok(_ascii_only("今夜。歯を磨く。") == "", "toàn tiếng Nhật thì gột ra rỗng — người gọi phải tự bỏ qua")

eng = (STUDIO / "engines" / "api_image_engine.py").read_text(encoding="utf-8")
ok("clean = _ascii_only(prompt)" in eng and "if clean and clean != prompt:" in eng,
   "chỉ thử lại khi prompt THẬT SỰ đổi — gửi lại y nguyên là vô ích")
ok('res["cleaned_prompt"] = True' in eng,
   "đánh dấu nhịp nào phải gột mới vẽ được, để còn lần ra")
ok(eng.count("clean = _ascii_only(prompt)") == 1,
   "CHỈ thử lại MỘT lần — từ chối thật thì đừng đốt thêm lượt gọi")

print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
