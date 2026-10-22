# -*- coding: utf-8 -*-
"""Kho ảnh template (22/10/2026): cờ agent «góp ảnh vào kho» + dòng cảnh báo ảnh lấy từ kho ở phần duyệt.

User: «chỗ góp ảnh vào kho nên cho vào setting của agent» — mặc định TẮT (ảnh sẽ được người khác dùng).

Kiểm:
  A. Agent: library_contribute mặc định False, ép bool, có trong to_dict (cloud dựa vào khoá này để biết server mới),
     cả hai model API (tạo / sửa) nhận trường
  B. pipeline gửi library_contribute của agent sang gen-images
  C. _library_image_warnings: có ảnh kho → một dòng nêu số, lý do, cảnh; Studio cũ / không có → []

Run:  python tests/library_contribute_test.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {detail}")


from tubecli.core.agent import Agent, PUBLISH_DEFAULTS, coerce_publish_value  # noqa: E402

print("── A. trường agent ──")
check("mặc định tắt", PUBLISH_DEFAULTS.get("library_contribute") is False
      and Agent(name="a").to_dict().get("library_contribute") is False)
check("ép bool", Agent(name="b", library_contribute="yes").library_contribute is True
      and coerce_publish_value("library_contribute", 0) is False)
check("to_dict phát khoá (cloud nhận ra server mới)", "library_contribute" in Agent(name="c").to_dict())
src = (ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8")
check("model tạo + sửa agent nhận trường", "library_contribute: Optional[bool] = False" in src
      and "library_contribute: Optional[bool] = None" in src)

print("── B. pipeline → gen-images ──")
from tubecli.extensions.content_video import pipeline as P  # noqa: E402
psrc = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
check("body gen-images mang library_contribute của agent",
      '"library_contribute": bool(getattr(state.get("agent"), "library_contribute", False))' in psrc)
check("cảnh báo ảnh kho nối sau cảnh báo đường lùi",
      "state[\"warnings\"].extend(_library_image_warnings(data))" in psrc)

print("── C. cảnh báo ở phần duyệt ──")
w = P._library_image_warnings({"library_images": {"count": 3, "total": 20, "why": {"refused": 1, "slow": 2},
                                                  "shots": [4, 9, 11]}})
check("một dòng: số / tổng, lý do xếp theo số lần, cảnh",
      len(w) == 1 and w[0].startswith("3/20 shot image(s) came from the template's image LIBRARY")
      and w[0].index("too slow") < w[0].index("refused by the model") and "shot 4, 9, 11" in w[0], w)
check("không có / Studio cũ / rác → []", P._library_image_warnings({}) == []
      and P._library_image_warnings({"library_images": {"count": 0}}) == []
      and P._library_image_warnings({"library_images": "x"}) == [] and P._library_image_warnings(None) == [])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
