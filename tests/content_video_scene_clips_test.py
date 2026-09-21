# -*- coding: utf-8 -*-
"""Video TỪNG CẢNH (bản thô) lên Google Drive — 21/9/2026.

VÌ SAO CÓ FILE NÀY
  User: «chỗ codex nếu tôi muốn upload shot (tức là shot đã ghép audio vào slide hoặc rối canvas) lên drive thì
  sao?» → bản THÔ: hình + giọng, chưa phủ bố cục. Trước nay thư mục project trên Drive có images/ và audio/ theo
  từng cảnh nhưng KHÔNG có video từng cảnh, mà khâu dựng thì đã tạo ra đúng những file ấy rồi xoá đi cùng thư mục
  tạm. Hai bộ dựng khác nhau nên hai đường lấy:
    · trình chiếu ảnh — giữ lại file đã dựng (không tốn thêm lượt mã hoá nào)
    · «Diễn giải» (canvas) — không có file theo cảnh, phải CẮT từ video cuối theo mốc giọng

  A. keep_scene_clips: chép ra thư mục bền, đánh số theo cảnh, lượt mới không lẫn cảnh cũ
  B. cut_scene_clips: cắt có mã hoá lại (không -c copy), bỏ cảnh 0 giây, báo số file
  C. route scene-clips: idempotent, mốc = cộng dồn giọng, shot câm = STILL_SECONDS
  D. _drive_plan: thêm scenes/scene_NNN.mp4 + cột «Scene video» trong Sheet; hỏng thì mọi thứ khác vẫn lên

Run:  python tests/content_video_scene_clips_test.py     (exit 0 = pass) — không mạng, không ffmpeg thật.
"""
import io
import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
CS = ROOT / "data" / "extensions_external" / "content_studio"
TMP = Path(tempfile.mkdtemp(prefix="cv_scene_clips_"))
PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:400])


eng_src = (CS / "engines" / "ffmpeg_video_engine.py").read_text(encoding="utf-8").replace("\r\n", "\n")
routes_src = (CS / "studio_routes.py").read_text(encoding="utf-8").replace("\r\n", "\n")
pipe_src = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8").replace("\r\n", "\n")


def seg(src, a, b):
    i = src.index(a)
    j = src.index(b, i + 1)
    return src[i:j]


# ── A. keep_scene_clips chạy THẬT (chỉ chép file, không cần ffmpeg) ──
print("── A. giữ file từng cảnh (đường trình chiếu) ───────────────")
mod = types.ModuleType("fe_probe")
mod.__dict__.update({"os": os, "logger": __import__("logging").getLogger("t"),
                     "OUT_DIR": str(TMP / "exports")})
exec(seg(eng_src, "STILL_SECONDS = 5.0", "async def cut_scene_clips"), mod.__dict__)
os.makedirs(TMP / "temp", exist_ok=True)
clips = []
for k in range(1, 4):
    p = TMP / "temp" / f"shot_{k}_main.mp4"
    p.write_bytes(b"MP4" + bytes([k]) * 100)
    clips.append(str(p))
clips.insert(2, None)           # shot hỏng giữa chừng: khâu dựng trả None
shots = [{"id": i} for i in range(4)]

rep = {}
n = mod.keep_scene_clips({"id": 77}, clips, shots, rep, raw=True)
out = mod.scenes_dir({"id": 77})
files = sorted(os.listdir(out))
ok(n == 3 and files == ["scene_001.mp4", "scene_002.mp4", "scene_004.mp4"],
   "chép đúng số cảnh; cảnh hỏng bị bỏ NHƯNG số thứ tự các cảnh sau giữ nguyên", (n, files))
ok((Path(out) / "scene_001.mp4").read_bytes().startswith(b"MP4\x01"), "nội dung đúng cảnh nào ra cảnh ấy")
ok(rep["scene_clips"] == {"dir": out, "count": 3, "raw": True}, "báo cáo nói thư mục + số file + là bản thô", rep)
ok("scenes" not in rep, "KHÔNG dùng khoá «scenes» — bộ dựng canvas đã dùng tên ấy cho số cảnh theo kiểu")

(Path(out) / "scene_009.mp4").write_bytes(b"old")
mod.keep_scene_clips({"id": 77}, clips[:1], shots[:1], {}, raw=True)
ok(sorted(os.listdir(out)) == ["scene_001.mp4"], "lượt dựng MỚI dọn sạch cảnh của lượt cũ", os.listdir(out))
ok(mod.keep_scene_clips({"id": 78}, [str(TMP / "khong-co.mp4")], [{}], {}, raw=False) == 0,
   "file không tồn tại → bỏ qua, không ném")

# ── B. cut_scene_clips: đọc mã, không chạy ffmpeg thật ──
print("── B. cắt cảnh từ video cuối (đường Diễn giải) ─────────────")
cut = seg(eng_src, "async def cut_scene_clips", "async def _get_duration")
ok('"-c", "copy"' not in cut and "-crf" in cut and "h264_nvenc" in cut,
   "MÃ HOÁ LẠI chứ không -c copy (mốc cảnh rơi giữa hai khung khoá → sao chép luồng là lệch)")
ok('"-ss", f"{a:.3f}"' in cut and '"-t", f"{b - a:.3f}"' in cut, "cắt theo giây, độ chính xác mili giây")
ok("if b - a <= 0.05:" in cut and "continue" in cut, "cảnh 0 giây thì bỏ, không đẻ file rỗng")
ok('os.path.getsize(out) > 1000' in cut, "chỉ tính là được khi file ra có nội dung thật")
ok('"-movflags", "+faststart"' in cut, "mp4 tua được ngay (moov lên đầu)")
ok("STILL_SECONDS = 5.0" in eng_src and re.search(r"SILENT_SECONDS = 5\.0",
   (CS / "engines" / "canvas_video_engine.py").read_text(encoding="utf-8")),
   "shot câm dài bằng nhau ở cả hai bộ dựng (5 giây) — mốc cắt mới không lệch dần")

# ── C. route ──
print("── C. route /scene-clips ───────────────────────────────────")
rt = seg(routes_src, '@router.post("/api/v1/studio/episodes/{episode_id}/scene-clips")',
         '@router.get("/api/v1/studio/export-video/{filename}")')
ok('if have and not body.get("rebuild")' in rt, "đã có file thì trả luôn (gọi lại không cắt lại)")
ok('body.get("rebuild")' in rt, "…nhưng ép dựng lại được")
ok("The episode has no rendered video yet" in rt, "chưa dựng video thì báo rõ, không cắt bừa")
ok("_shot_audio_path(s.get(\"tts_audio_url\"))" in rt and "FE.STILL_SECONDS" in rt,
   "mốc = cộng dồn thời lượng GIỌNG; shot không giọng dùng đúng hằng số ảnh tĩnh")
ok("abs(total - t) >" in rt and "logger.warning" in rt,
   "tuyến thời gian lệch xa video thật thì ghi log (đừng im lặng cắt sai)")
ok('encoder=str(meta.get("gpu_encoder")' in rt, "dùng đúng bộ mã hoá của dự án (GPU nếu có)")

# ── D. bước Drive của lõi ──
print("── D. đưa lên Drive ────────────────────────────────────────")
plan = seg(pipe_src, "def _drive_plan(state:", "def _drive_studio_context")
ok('add(f"clip:{i}", clips.get(i, ""), n, "scenes", "scene")' in plan, "mỗi cảnh một file trong scenes/")
ok('_post(f"/api/v1/studio/episodes/{state[\'episode_id\']}/scene-clips"' in plan, "gọi route của Studio để có file")
ok("except Exception as e:      # noqa: BLE001" in plan and "scene clips unavailable" in plan,
   "route hỏng chỉ mất thư mục scenes — video, ảnh, giọng vẫn lên Drive")
ok('for sub in ("images", "audio", "scenes"):' in pipe_src, "thư mục scenes/ được tạo trên Drive")
ok('"Scene video"' in pipe_src and 'links.get(f"clip:{i}", "")' in pipe_src,
   "Sheet có cột «Scene video» trỏ đúng cảnh")
ok('"Scenes": {1: 320, 2: 460, 3: 420, 5: 220, 6: 220, 7: 220}' in pipe_src, "cột mới đủ rộng để thấy link")
keep_call = seg(eng_src, "    # Video TỪNG CẢNH (bản thô)", "    if progress_callback:")
ok("raw=two_pass" in keep_call and "(m or {}).get(\"path\") for m in metas" in keep_call,
   "hai lượt lấy bản CHƯA phủ bố cục; một lượt lấy bản đã ghép")
ok("except Exception as e:" in keep_call, "giữ cảnh hỏng thì video vẫn xuất bình thường")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
