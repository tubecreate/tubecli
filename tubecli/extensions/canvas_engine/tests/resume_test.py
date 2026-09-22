# -*- coding: utf-8 -*-
"""Dựng TIẾP từ khung đã có sau khi bị giết / khởi động lại — 22/9/2026.

VÌ SAO CÓ FILE NÀY
  VPS 8 GB: hai lượt dựng (12 giờ và 40 phút) đều chết ở 48 %, bấm chạy lại thì dựng từ 0 — user: «sao render tới đó
  khi chạy lại thì nó render lại từ đầu?». Hai lý do: chunk mp4 bị giết giữa chừng không có mục lục cuối file (không
  đọc được), và thư mục tạm bị dọn khi lỗi. Nay: plan.json ghi bố cục chunk; chunk là MP4 PHÂN MẢNH (đọc được tới mảnh
  cuối đã ghi xong); lượt sau đếm khung đã có rồi dựng tiếp vào phần mới.

  1. plan.json: ghi/đọc, khác tổng số khung → bỏ (video đã đổi)
  2. MP4 phân mảnh bị CẮT giữa chừng (giả lập bị giết) vẫn đếm được khung; mp4 thường cắt giữa chừng → 0
  3. luật thử lại giữ bố cục chunk, chỉ giảm số chạy cùng lúc; danh sách ghép theo đúng thứ tự phần
  4. mã nguồn: không dọn temp_dir khi hỏng; --startFrame = start + khung đã có; Studio giữ out/ khi hỏng

Cần ffmpeg + ffprobe trên PATH cho mục 2 (không có thì bỏ qua mục đó, vẫn exit 0).
Run:  python tests/resume_test.py     (exit 0 = pass)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = Path(__file__).resolve().parent.parent / "renderer"
sys.path.insert(0, str(R))
os.chdir(str(R))
import engines.video_encoder as VE  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


print("── 1. plan.json ────────────────────────────────────────────")
tmp = tempfile.mkdtemp(prefix="ce-resume-")
plan = {"total_frames": 9000, "fps": 30, "ranges": [[0, 3000], [3000, 6000], [6000, 9000]], "parts": [["chunk_0.mp4"], [], []]}
VE._save_plan(tmp, plan)
ok(os.path.isfile(os.path.join(tmp, "plan.json")) and not os.path.exists(os.path.join(tmp, "plan.json.tmp")), "ghi qua file tạm rồi đổi tên")
back = VE._load_plan(tmp, 9000)
ok(back == dict(plan, clean=False), "đọc lại đúng bố cục + danh sách phần (plan cũ không có khoá clean = False)", back)
ok(VE._load_plan(tmp, 9001) is None, "tổng số khung khác → None (video đã đổi, dựng lại từ đầu)")
ok(VE._load_plan(tempfile.mkdtemp(prefix="ce-empty-"), 9000) is None, "không có plan.json → None")
with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as f:
    f.write("{hỏng")
ok(VE._load_plan(tmp, 9000) is None, "plan.json hỏng → None, không nổ")

print("── 1b. bản KHÔNG phụ đề (video từng cảnh lên Drive, 22/9/2026) ──")
ok(VE.clean_path_for("/x/edu_ep1_16_9.mp4") == "/x/edu_ep1_16_9_clean.mp4" and VE._clean_part("chunk_0.p1.mp4") == "chunk_0.p1.clean.mp4",
   "tên bản sạch: <video>_clean.mp4, phần chunk: chunk_w.pK.clean.mp4")
tmpc = tempfile.mkdtemp(prefix="ce-resume-clean-")
VE._save_plan(tmpc, {"total_frames": 900, "fps": 30, "clean": True, "ranges": [[0, 450], [450, 900]], "parts": [[], []]})
ok(VE._load_plan(tmpc, 900, clean=True) is not None and VE._load_plan(tmpc, 900, clean=False) is None,
   "plan ghi có/không bản sạch; đổi yêu cầu → dựng lại (phần cũ không có bản song song)")
VE._save_plan(tmpc, {"total_frames": 900, "fps": 30, "ranges": [[0, 900]], "parts": [[]]})
ok(VE._load_plan(tmpc, 900) is not None and VE._load_plan(tmpc, 900, clean=True) is None, "plan cũ (không có khoá clean) = không bản sạch")
js = open(os.path.join(str(R), "engines", "canvas_renderer.js"), "rb").read().decode("utf-8", "replace")
ok("if (SUB_ENGINE && !globalThis.T2_SKIP_SUB)" in js and "function paintSubtitleOnly(currentTime)" in js
   and "startFfmpeg(cleanFile, ' clean')" in js and "globalThis.T2_SKIP_SUB = true;" in js,
   "renderer: một lượt vẽ, khung không phụ đề → bản sạch, vẽ đè phụ đề → bản chính")
ok("(typeof args.cleanOutputFile === 'string' && SUB_ENGINE)" in js, "không có phụ đề thì KHÔNG mở ffmpeg thứ hai (bản chính đã sạch)")
enc_src = open(os.path.join(str(R), "engines", "video_encoder.py"), encoding="utf-8").read()
ok('cmd_w += ["--cleanOutputFile", os.path.join(temp_dir, _clean_part(part_name))]' in enc_src
   and '["--cleanOutputFile", clean_video] if clean else []' in enc_src, "cả đường chunk lẫn đường 1 tiến trình đều xin bản sạch")
ok("cap = min(nm, nc) - SALVAGE_DROP_TAIL" in enc_src and "_stitch_clean(temp_dir, plan, n_chunks" in enc_src,
   "dựng tiếp: bản chính và bản sạch của cùng một phần cắt về CÙNG số khung; ghép bản sạch sau bản chính")
ok("workers_override=fewer, clean=clean" in enc_src and "_pick_workers(aspect_ratio, _FFMPEG_MB if clean else 0)" in enc_src,
   "thử lại giữ yêu cầu bản sạch; ffmpeg thứ hai được tính vào RAM mỗi worker")

print("── 2. MP4 phân mảnh sống sót khi bị cắt ────────────────────")
ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
if ffmpeg and ffprobe:
    frag = os.path.join(tmp, "frag.mp4")
    plain = os.path.join(tmp, "plain.mp4")
    base = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30", "-frames:v", "300",
            "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-pix_fmt", "yuv420p"]
    subprocess.run(base + ["-movflags", VE.FRAG_MOVFLAGS, frag], check=True, timeout=120)
    subprocess.run(base + [plain], check=True, timeout=120)
    ok(VE._count_frames(frag) == 300 and VE._count_frames(plain) == 300, "file nguyên vẹn: đếm đủ 300 khung cả hai kiểu",
       (VE._count_frames(frag), VE._count_frames(plain)))
    for p in (frag, plain):
        data = open(p, "rb").read()
        with open(p, "wb") as f:
            f.write(data[: len(data) * 55 // 100])          # «bị giết» ở 55 % file
    nf, npl = VE._count_frames(frag), VE._count_frames(plain)
    ok(60 <= nf <= 200, "MP4 phân mảnh cắt ở 55 % → vẫn đếm được các khung đã ghi (gói cuối có thể dở)", nf)
    ok(npl == 0, "mp4 thường cắt giữa chừng → 0 khung (mất mục lục) — đây là lý do chạy lại từng phải dựng từ 0", npl)
    kept = VE._salvage_part(frag)
    ok(kept == nf - VE.SALVAGE_DROP_TAIL and VE._count_frames(frag) == kept, "làm sạch: remux copy, bỏ 2 gói cuối, số khung khớp file", (kept, nf))
    dec = subprocess.run([ffmpeg, "-v", "error", "-i", frag, "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    ok(dec.returncode == 0 and not dec.stderr.strip(), "file đã làm sạch giải mã trọn vẹn, không một lỗi", dec.stderr[:200])
    ok(VE._salvage_part(plain) == 0 and os.path.isfile(plain), "mp4 thường hỏng → 0, không thay file")
    ok(VE._count_frames(os.path.join(tmp, "khong_co.mp4")) == 0, "file không có → 0")
    tiny = os.path.join(tmp, "tiny.mp4")
    open(tiny, "wb").write(b"\0" * 100)
    ok(VE._count_frames(tiny) == 0, "file bé tí → 0, không gọi ffprobe")
else:
    print("  (không có ffmpeg/ffprobe trên PATH — bỏ qua mục 2)")

print("── 3. luật thử lại + thứ tự ghép ───────────────────────────")
src = open(os.path.join(str(R), "engines", "video_encoder.py"), encoding="utf-8").read()
body = src.split("# Multi-process parallel rendering")[1].split("raw_video = os.path.join(temp_dir")[0]
ok("plan = _load_plan(temp_dir, total_frames, clean)" in body and "_save_plan(temp_dir, plan)" in body, "lượt dựng đọc/ghi plan.json")
ok('"--startFrame", str(first)' in body and "first = start + done_before[w_idx]" in body, "chunk dựng tiếp từ start + khung đã có")
ok("asyncio.Semaphore(concurrency)" in body and "concurrency = max(1, min(workers_override if workers_override > 0 else num_workers, n_chunks))" in body,
   "số tiến trình cùng lúc tách khỏi bố cục chunk (thử lại ít worker hơn vẫn giữ nguyên chunk)")
ok('"-movflags", FRAG_MOVFLAGS' in body, "mọi chunk ghi MP4 phân mảnh")
ok("KHÔNG dọn temp_dir" in body and "shutil.rmtree(temp_dir, ignore_errors=True)" not in body.split("action, fewer = _after_parallel_failure")[0].split("except Exception as e:")[-1],
   "hỏng → KHÔNG dọn temp_dir (điểm lưu cho lượt sau)")
ok("for part in plan[\"parts\"][w]:" in body and "f_list.write(f\"file '{chunk_file}'\\n\")" in body, "danh sách ghép: mọi phần của mọi chunk theo thứ tự")
ok("workers_override=fewer" in body and "Resuming from" in body, "thử lại ngay sau khi worker chết đi đường dựng tiếp")
studio = Path(__file__).resolve().parents[4] / "data" / "extensions_external" / "content_studio" / "engines" / "canvas_video_engine.py"
if studio.is_file():
    st = studio.read_text("utf-8")
    ok("def reset_job_dir" in st and "def resume_state" in st and "if ok_done:" in st,
       "Content Studio: giữ out/temp_chunks_* khi hỏng, chỉ dọn thư mục việc khi dựng XONG")
    # chạy thật reset_job_dir trên thư mục giả
    sys.path.insert(0, str(studio.parent))
    sys.path.insert(0, str(studio.parent.parent))
    try:
        import canvas_video_engine as CE
        jd = Path(tempfile.mkdtemp(prefix="ce-job-"))
        (jd / "lesson").mkdir()
        (jd / "lesson" / "x.json").write_text("{}", "utf-8")
        (jd / "out" / "temp_chunks_edu.mp4").mkdir(parents=True)
        (jd / "out" / "temp_chunks_edu.mp4" / "plan.json").write_text("{}", "utf-8")
        (jd / "out" / "temp_chunks_edu.mp4" / "chunk_0.mp4").write_bytes(b"x" * 2000)
        (jd / "out" / "old.mp4").write_bytes(b"y")
        kept = CE.reset_job_dir(str(jd))
        ok(kept and (jd / "out" / "temp_chunks_edu.mp4" / "chunk_0.mp4").is_file() and not (jd / "lesson").exists()
           and not (jd / "out" / "old.mp4").exists(), "reset_job_dir: giữ đúng thư mục điểm lưu, dọn phần còn lại")
        jd2 = Path(tempfile.mkdtemp(prefix="ce-job2-"))
        (jd2 / "lesson").mkdir()
        ok(CE.reset_job_dir(str(jd2)) is False and jd2.is_dir() and not (jd2 / "lesson").exists(), "không có điểm lưu → dọn sạch như cũ")
    except Exception as e:      # noqa: BLE001
        ok(False, "reset_job_dir chạy được", e)
else:
    print("  (không có Content Studio cạnh repo — bỏ qua phần Studio)")

print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
