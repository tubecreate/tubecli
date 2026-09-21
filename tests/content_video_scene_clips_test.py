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

  Rồi user: «nếu có thể thì bạn ghép bố cục thành 1 file mp4 riêng (lấy layout dài nhất làm gốc, các layout khác
  loop theo)» → build_layout_clip: bố cục MỘT MÌNH (khung + người dẫn), lỗ để trống, dài bằng clip người dẫn dài
  nhất. Chồng nó lên các file scene_NNN.mp4 ở trình dựng khác là ra đúng video đã xem.

  E. build_layout_clip: dài bằng clip dài nhất, clip ngắn lặp, ảnh lặp một khung, chrome trên cùng, hỏng trả {}
  F. route layout-clip + dòng «Layout overlay» trong Sheet

Run:  python tests/content_video_scene_clips_test.py     (exit 0 = pass) — không mạng, không ffmpeg thật.
"""
import asyncio
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

# ── E. build_layout_clip chạy THẬT (ffmpeg giả, chuỗi lọc thật) ──
print("── E. bố cục thành một mp4 riêng ───────────────────────────")
sys.path.insert(0, str(CS))
from vlayout import ffmpeg_chain as CHAIN          # noqa: E402 — chỉ dựng chuỗi lọc, không phụ thuộc gì


def mc(box, clip, **kw):
    d = {"box": box, "fit": "contain", "chroma": "chromakey=0x00b140:0.1:0.1", "clip": clip,
         "opacity": 1.0, "crop_y": 0.0, "trim": [0, 0, 0, 0]}
    d.update(kw)
    return d


DUR = {}
CALLS = []
RUN_OK = [True]
CHROME = [str(TMP / "chrome.png")]
MCS = [mc([1200, 600, 600, 400], str(TMP / "mc_long.mp4"), layer=0),
       mc([40, 620, 380, 400], str(TMP / "mc_short.mp4"), layer=1)]
DUR["mc_long.mp4"] = 62.5
DUR["mc_short.mp4"] = 11.0


async def fake_get_duration(p):
    return DUR.get(os.path.basename(str(p)), 0.0)


async def fake_run_ff(cmd, duration=0.0, on_frac=None):
    CALLS.append(list(cmd))
    if not RUN_OK[0]:
        return 1, b"boom"
    with open(cmd[-1], "wb") as f:
        f.write(b"M" * 5000)
    return 0, b""


mod.__dict__.update({
    "_ff": lambda n: n,
    "_tail": lambda e, lines=2: str(e),
    "_get_duration": fake_get_duration,
    "_run_ff": fake_run_ff,
    "_layout_load": lambda lid, frame, report=None, validate=False: (
        type("V", (), {"chain": CHAIN}), {"id": lid}, {"box": [480, 120, 960, 540]}),
    "_render_chrome_locked": lambda v, lay, var, out_dir, lang: CHROME[0],
    "_mc_ctxs": lambda v, lay, out_dir, seed="", report=None: list(MCS),
})

got = asyncio.run(mod.build_layout_clip({"id": 77}, layout_id="vl_1", frame=(1920, 1080),
                                        variables={"channel": "X"}))
cmd = CALLS[-1]
fc = cmd[cmd.index("-filter_complex") + 1]
ok(got.get("seconds") == 62.5 and cmd[cmd.index("-t") + 1] == "62.500",
   "độ dài = clip người dẫn DÀI NHẤT (không phải tổng, không phải ngắn nhất)", (got.get("seconds"), cmd))
ok(cmd.count("-stream_loop") == 2 and cmd[cmd.index("-stream_loop") + 1] == "-1",
   "MỌI clip lặp vô hạn rồi để -t cắt — clip ngắn không để lại khoảng trống cuối", cmd)
ok([l["looped"] for l in got["layers"]] == [False, True],
   "báo rõ lớp nào phải lặp (11 s trong 62,5 s) và lớp nào không", got["layers"])
ok(fc.index("[mc0]overlay=1200:600") < fc.index("[chrome]overlay=0:0"),
   "người dẫn nằm DƯỚI khung — đúng thứ tự của lượt phủ lớp trong video thật", fc)
ok("[mc1]overlay=40:620" in fc, "mỗi lớp dán đúng toạ độ hộp của nó")
ok(CHAIN.mc_filter(MCS[0], 30) in fc,
   "dùng ĐÚNG chuỗi tách phông của bản dựng thật (một bản duy nhất, không chép lại)")
ok("color=c=0x00b140:s=1920x1080:r=30" in " ".join(cmd),
   "nền = xanh phông, ghi 0xRRGGBB (lavfi đọc chắc chắn hơn #RRGGBB)", cmd)
ok("-an" in cmd and "+faststart" in cmd and "yuv420p" in cmd,
   "không tiếng (tiếng nằm ở file cảnh), tua được ngay")
ok(got["path"].endswith("layout.mp4") and os.path.dirname(got["path"]) == mod.scenes_dir({"id": 77}),
   "nằm cùng thư mục với video từng cảnh — Drive lấy cả cụm một lần", got.get("path"))

got = asyncio.run(mod.build_layout_clip({"id": 77}, layout_id="vl_1", frame=(1920, 1080), alpha=True))
cmd = CALLS[-1]
fc = cmd[cmd.index("-filter_complex") + 1]
ok(got["path"].endswith("layout.mov") and got["alpha"] is True and got["background"] == "",
   "alpha=True ra .mov — mp4 KHÔNG mang được kênh trong suốt, nên phải là vỏ khác", got.get("path"))
ok(cmd[cmd.index("-c:v") + 1] == "qtrle" and cmd[cmd.index("-pix_fmt") + 1] == "argb"
   and "yuv420p" not in fc,
   "qtrle/argb (RLE không mất dữ liệu, cái lỗ trong suốt nén còn gần như không gì)", cmd)
ok("color=c=black@0:" in " ".join(cmd) and fc.startswith("[0:v]format=rgba,"),
   "nền TRONG SUỐT thật, không phải xanh phông tô đè", fc[:60])
ok(fc.endswith("format=rgba[v]"), "giữ alpha đến tận khung ra")

MCS[:] = [mc([1200, 600, 600, 400], str(TMP / "sticker.png"), layer=0)]
got = asyncio.run(mod.build_layout_clip({"id": 77}, layout_id="vl_1", frame=(1920, 1080)))
cmd = CALLS[-1]
ok("-stream_loop" not in cmd and cmd[cmd.index("-loop") + 1] == "1",
   "nguồn là ẢNH thì lặp MỘT khung (-loop 1), không -stream_loop", cmd)
ok(got["seconds"] == 5.0 and cmd[cmd.index("-t") + 1] == "5.000",
   "không lớp nào là video → đoạn tĩnh STILL_SECONDS giây, không phải 0 giây", got)

CHROME[0], MCS[:] = "", []
ok(asyncio.run(mod.build_layout_clip({"id": 77}, layout_id="vl_1", frame=(1920, 1080))) == {},
   "bố cục rỗng (không khung, không người dẫn) → KHÔNG đẻ file")
CHROME[0] = str(TMP / "chrome.png")
RUN_OK[0] = False
ok(asyncio.run(mod.build_layout_clip({"id": 77}, layout_id="vl_1", frame=(1920, 1080))) == {},
   "ffmpeg hỏng thì trả {} — bước Drive chỉ thiếu file bố cục, không ném")
RUN_OK[0] = True

ok(mod.layout_variables({"id": 1, "title": "T", "episode_number": 3})["badge"] == "Tập 3"
   and "badge" not in mod.layout_variables({"id": 1, "title": "T"}),
   "khe chữ: có số tập mới có chip; MỘT bản dùng cho cả video lẫn file bố cục")
ok("lay_vars = layout_variables(episode, layout_vars)" in eng_src,
   "bản dựng video gọi CHÍNH hàm ấy (hai nơi tự bơm khe sẽ trôi khỏi nhau)")

# ── F. route + Drive ──
print("── F. route layout-clip + Drive ────────────────────────────")
lr = seg(routes_src, '@router.post("/api/v1/studio/episodes/{episode_id}/layout-clip")',
         '@router.get("/api/v1/studio/export-video/{filename}")')
ok('if os.path.isfile(out) and os.path.getsize(out) > 1000 and not body.get("rebuild")' in lr,
   "đã có thì trả luôn, ép dựng lại được")
ok("This project does not use a video layout." in lr, "dự án không dùng bố cục thì nói thẳng")
ok('(1080, 1920) if ar == "9:16"' in lr and '(1080, 1080) if ar == "1:1"' in lr,
   "khung dọc/vuông ra đúng cỡ — sai cỡ thì chồng lên video là lệch")
ok("FE.layout_variables(ep," in lr, "khe chữ lấy từ hàm chung, không bịa lại")
ok(routes_src.count('if f.startswith("scene_") and f.endswith(".mp4")') == 2,
   "route scene-clips chỉ đếm file CẢNH (cả lúc kiểm tra lẫn lúc trả danh sách) — layout.mp4 ở cùng thư mục")
ok('add("layout", lay["path"], f"{base} (layout)", "", "layout")' in pipe_src,
   "file bố cục lên Drive cạnh video, tên có «(layout)»")
ok('["Layout overlay", links.get("layout", "")]' in pipe_src, "Sheet có dòng «Layout overlay»")
ok("layout clip unavailable" in pipe_src, "không dựng được bố cục thì mọi thứ khác vẫn lên Drive")
ok("per scene, the layout overlay" in pipe_src,
   "dòng xin duyệt nói đúng những gì sắp lên Drive")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
