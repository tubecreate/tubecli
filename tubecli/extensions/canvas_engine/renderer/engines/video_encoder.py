"""
EduVideo Studio — Video Encoder v2.
Supports two modes: 'pipe' (fast, single step) and 'frames' (stable, PNG + FFmpeg).
"""
import os
import json
import asyncio
import shutil
import logging
from typing import Optional, Callable, List
from pathlib import Path

logger = logging.getLogger("EduVideoStudio.VideoEncoder")

# Thư mục gốc app: khi đóng gói PyInstaller, __file__ nằm trong _internal/ còn
# engines/ + node_modules/ đặt cạnh .exe → phải lấy BASE_DIR từ config.
# Fallback __file__ để module vẫn chạy độc lập ngoài app.
try:
    from config import BASE_DIR as _APP_DIR
    _APP_DIR = Path(_APP_DIR)
except Exception:
    _APP_DIR = Path(__file__).resolve().parent.parent

CANVAS_RENDERER_JS = _APP_DIR / "engines" / "canvas_renderer.js"

# Bản đóng gói là GUI KHÔNG có console. Mỗi tiến trình console (node/ffmpeg)
# sinh ra sẽ tự bung một CỬA SỔ ĐEN đè lên app — render 8 worker = 8 cửa sổ.
# Chạy từ python.exe lúc dev thì con kế thừa console sẵn nên không lộ lỗi.
# CREATE_NO_WINDOW chặn hẳn; tiến trình cháu (ffmpeg do node gọi) cũng kế thừa.
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


async def _exec(*args, **kwargs):
    """asyncio.create_subprocess_exec + ẩn cửa sổ console trên Windows."""
    if os.name == "nt":
        kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
    return await asyncio.create_subprocess_exec(*args, **kwargs)


# ── Chọn số worker render theo SỨC MÁY ────────────────────────────────────
# Mỗi worker = 1 tiến trình node giữ một canvas full-res trong RAM + 1 ffmpeg.
# Trước đây cứ lấy cpu_count-1 (tối đa 8) → máy nhiều lõi ít RAM bị swap và
# TREO. Giờ lấy min(theo lõi, theo RAM trống) và cho phép người dùng ép cứng.
_RAM_PER_WORKER_MB = {          # ước lượng RAM một worker cần theo khung hình
    "9:16": 1500,               # 1080x1920
    "16:9": 1500,
    "1:1": 1000,
}
# ĐO THẬT 21/9/2026, VPS 4 vCPU / 7.751 MB, video Diễn giải 321 nhịp tranh phủ khung 16:9: ước lượng cũ (700 MB +
# tranh ≤256 MB) cho 3 worker → RAM lên 98 % (7.579 MB) ngay 15 phút đầu, máy không trả lời được 30 phút liền, 48 %
# sau 12 giờ rồi bị khởi động lại. Tức mỗi chuỗi node + ffmpeg thật sự ăn ~2 GB, không phải ~1 GB: node giữ canvas +
# heap V8 + tranh đã giải mã ngoài LRU, ffmpeg libx264 1080p thêm vài trăm MB mà chưa hề được tính. Nay tính cả ffmpeg
# và chừa 2 GB cho TubeCLI + Studio (PIL) + hệ điều hành: máy 8 GB → 2 worker, 4 GB → 1, máy 32 GB không đổi đáng kể.
_FFMPEG_MB = 300
_OS_RESERVE_MB = 2048


def _free_ram_mb() -> int:
    """RAM khả dụng (MB). Trả 0 nếu không đo được → bỏ qua ràng buộc RAM."""
    try:
        import psutil
        return int(psutil.virtual_memory().available / 1048576)
    except Exception:
        pass
    if os.name == "nt":         # không cần psutil: hỏi thẳng Windows
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return int(ms.ullAvailPhys / 1048576)
        except Exception:
            pass
    return 0


_SPRITE_BUDGET_MB = 256         # = T2_SPRITE_BUDGET_MB mặc định của canvas_renderer.js (LRU tranh sprite)


def _sprite_pack_mb() -> int:
    """RAM MỖI worker cần thêm cho tranh sprite (MB): tổng ảnh của gói sau giải mã, nhưng không quá ngân sách LRU
    của renderer. Trước 19/9/2026 renderer nạp CẢ gói lúc khởi động và _pick_workers không biết gói to bao nhiêu:
    194 tranh phủ khung ≈ 1,3 GB × 12 worker → tràn RAM 32 GB."""
    import struct
    roots = []
    try:
        from config import TEMPLATE_CACHE_DIR
        roots.append(Path(TEMPLATE_CACHE_DIR))
    except Exception:
        pass
    if os.environ.get("T2_TEMPLATE_CACHE"):
        roots.append(Path(os.environ["T2_TEMPLATE_CACHE"]))
    total = 0
    for root in roots:
        try:
            for png in root.glob("*/sprites/*.png"):
                with open(png, "rb") as f:
                    head = f.read(24)
                if len(head) >= 24 and head[12:16] == b"IHDR":
                    w, h = struct.unpack(">II", head[16:24])
                    total += w * h * 4
        except Exception:
            continue
    return min(_SPRITE_BUDGET_MB, total // 1048576)


def _pick_workers(aspect_ratio: str = "9:16") -> int:
    """Số tiến trình render song song an toàn cho máy này.

    settings['render_workers']: 0 = tự động (mặc định), >0 = ép cứng.
    """
    try:
        from config import load_settings
        forced = int(load_settings().get("render_workers", 0) or 0)
    except Exception:
        forced = 0
    if forced > 0:
        return max(1, min(forced, 16))

    cpu = os.cpu_count() or 4
    # Trần THEO SỐ LÕI, không phải số cứng.
    #   Trần 8 vốn là điểm ngọt ĐO THỰC TẾ trên máy 12 lõi (nâng 11 worker ở đó
    #   còn CHẬM hơn vì tranh chấp CPU) — nhưng áp cùng số 8 cho máy 20 lõi thì
    #   bỏ phí quá nửa CPU (đo 27/07 trên i5-14600KF 20 luồng: 8 worker → CPU
    #   chỉ 44%, GPU 15%, đĩa 1% ⇒ nghẽn ở SỐ WORKER chứ không phải encode).
    #   max(8, cpu//2 + 2) giữ NGUYÊN HỆT hành vi cũ cho máy ≤12 lõi (4→3, 6→5,
    #   8→7, 12→8) và chỉ nới cho máy lớn (16→10, 20→12, 32→18).
    #   Ràng buộc RAM bên dưới vẫn hạ tiếp nếu máy nhiều lõi mà ít RAM.
    by_cpu = max(1, min(cpu - 1, max(8, cpu // 2 + 2)))   # chừa lõi cho UI + HĐH

    free = _free_ram_mb()
    if free <= 0:
        return by_cpu                          # không đo được RAM → theo lõi
    need = _RAM_PER_WORKER_MB.get(aspect_ratio, 1500) + _sprite_pack_mb() + _FFMPEG_MB
    # Chừa chỗ cho app + hệ điều hành, phần còn lại chia cho worker
    by_ram = max(1, int((free - _OS_RESERVE_MB) / need))

    n = max(1, min(by_cpu, by_ram))
    if n < by_cpu:
        logger.info(f"[Pipe] Giảm còn {n} worker (RAM trống {free} MB, "
                    f"mỗi worker ~{need} MB) thay vì {by_cpu} theo số lõi.")
    return n

# Encoder presets for ffmpeg
ENCODER_MAP = {
    "cpu":   {"codec": "libx264",    "preset": "fast",     "extra": ["-crf", "22", "-threads", "0"]},
    "nvenc": {"codec": "h264_nvenc", "preset": "p4",       "extra": ["-rc", "vbr", "-cq", "23", "-b:v", "8M", "-maxrate", "12M", "-bufsize", "16M"]},
    "qsv":   {"codec": "h264_qsv",  "preset": "veryfast", "extra": ["-global_quality", "23", "-look_ahead", "0"]},
    "amf":   {"codec": "h264_amf",  "preset": "speed",    "extra": ["-rc", "cqp", "-qp_i", "22", "-qp_p", "22", "-usage", "transcoding"]},
}


def _find_executable(name: str) -> str:
    """Tìm ffmpeg/ffprobe chạy được, tránh bản miniconda hỏng.

    Thứ tự: bản đóng gói cạnh .exe (BASE_DIR/tools|ffmpeg) → PATH (winget cài lúc
    setup) → tên trần. KHÔNG hard-code đường dẫn theo máy dev (C:\\Users\\ADMIN…)
    vì máy người dùng khác username, ffmpeg sẽ không tìm thấy → render hỏng."""
    import os, shutil
    # 1. ffmpeg đóng gói cạnh app (nếu có) — ổn định nhất, không phụ thuộc máy
    for d in (_APP_DIR / "tools", _APP_DIR / "ffmpeg" / "bin", _APP_DIR):
        exe_path = d / f"{name}.exe"
        try:
            if exe_path.is_file():
                return str(exe_path)
        except Exception:
            pass
    # 2. env override tường minh
    env_dir = os.environ.get("T2STUDIO_FFMPEG_DIR")
    if env_dir:
        p = os.path.join(env_dir, f"{name}.exe")
        if os.path.exists(p):
            return p
    # 3. PATH (Node/ffmpeg cài qua winget lúc setup nằm ở đây)
    found = shutil.which(name)
    if found:
        if "miniconda3" in found.lower():        # bản miniconda hay hỏng codec
            for path_dir in os.environ.get("PATH", "").split(os.pathsep):
                if not path_dir or "miniconda3" in path_dir.lower():
                    continue
                exe_path = os.path.join(path_dir, f"{name}.exe")
                if os.path.exists(exe_path):
                    return exe_path
        return found
    return name


async def _concat_videos_ffmpeg(segments: List[str], output_path: str, aspect_ratio: str, gpu_encoder: str = "nvenc"):
    """
    Concatenate video segments cleanly using FFmpeg complex filter.
    Ensures all segments are standardized to matching resolutions, 30 FPS, and resampled audio.
    """
    import shutil
    import asyncio
    
    ffmpeg_exe = _find_executable("ffmpeg")
    
    # Target resolution based on aspect ratio
    if aspect_ratio == "16:9":
        tw, th = 1920, 1080
    else:
        tw, th = 1080, 1920
        
    enc = ENCODER_MAP.get(gpu_encoder, ENCODER_MAP["nvenc"])
    
    # Build filter complex inputs
    filter_complex = ""
    inputs = []
    
    for i, seg in enumerate(segments):
        inputs.extend(["-i", seg])
        # scale each segment to exact target, pad to avoid skew, format yuv420p at 30 fps
        filter_complex += f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p[v{i}];"
        # Audio resample to standard 44100Hz stereo
        filter_complex += f"[{i}:a]aresample=44100,pan=stereo[a{i}];"
        
    # Now concatenate audio and video elements
    for i in range(len(segments)):
        filter_complex += f"[v{i}][a{i}]"
    filter_complex += f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
    
    cmd = [
        ffmpeg_exe, "-y", "-threads", "0"
    ] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", enc["codec"], "-preset", enc["preset"]
    ]
    
    if enc.get("extra"):
        cmd.extend(enc["extra"])
        
    cmd.extend([
        "-c:a", "aac", "-b:a", "128k",
        output_path
    ])
    
    logger.info(f"[Concat] Stitching {len(segments)} segments using {gpu_encoder}...")
    
    proc = await _exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        # Fallback to CPU libx264 if GPU encoder fails during stitching
        if gpu_encoder != "cpu":
            logger.warning(f"[Concat] GPU encoding failed, falling back to CPU...")
            cpu_enc = ENCODER_MAP["cpu"]
            cpu_cmd = [
                ffmpeg_exe, "-y", "-threads", "0"
            ] + inputs + [
                "-filter_complex", filter_complex,
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", cpu_enc["codec"], "-preset", cpu_enc["preset"]
            ] + cpu_enc.get("extra", []) + [
                "-c:a", "aac", "-b:a", "128k",
                output_path
            ]
            proc_fb = await _exec(
                *cpu_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr_fb = await proc_fb.communicate()
            if proc_fb.returncode != 0:
                raise RuntimeError(f"FFmpeg concat fallback failed: {stderr_fb.decode()[:300]}")
        else:
            raise RuntimeError(f"FFmpeg concat failed: {stderr.decode()[:300]}")


def _find_node():
    """Tìm node.exe: bản bundle cạnh app (tools/node/node.exe hoặc tools/node.exe)
    → PATH. Trả None nếu không có — KHÁC ffmpeg, không fallback "tên trần":
    spawn tên trần khi thiếu chỉ ném FileNotFoundError WinError 2 cụt lủn,
    user máy mới không thể đoán "file specified" chính là node.exe."""
    for p in (_APP_DIR / "tools" / "node" / "node.exe",
              _APP_DIR / "tools" / "node.exe"):
        try:
            if p.is_file():
                return str(p)
        except Exception:
            pass
    return shutil.which("node")


def _find_node_modules():
    """Find node_modules with canvas package. Tolerant với nhiều layout."""
    here = Path(__file__).resolve()
    candidates = [
        _APP_DIR / "node_modules",             # cạnh .exe (bản đóng gói) / gốc project (dev)
        _APP_DIR / "engines" / "node_modules",
        here.parent / "node_modules",          # engines/node_modules
        here.parent.parent / "node_modules",   # t2studio/node_modules
    ]
    # dò thêm vài cấp cha (an toàn nếu đóng gói khác cấu trúc)
    for up in range(2, min(6, len(here.parents))):
        candidates.append(here.parents[up] / "node_modules")
    # env override + node_modules chia sẻ của TubeCLI (nếu đã cài canvas ở đó)
    import os as _os
    if _os.environ.get("T2STUDIO_NODE_MODULES"):
        candidates.insert(0, Path(_os.environ["T2STUDIO_NODE_MODULES"]))
    candidates.append(Path(r"C:\tubecreate-vue\tubecli\node_modules"))
    for p in candidates:
        try:
            if (p / "canvas").is_dir():
                return p
        except Exception:
            continue
    return None


async def _ensure_canvas():
    """Ensure node-canvas is installed, install if needed.

    Trước đây hàm này KHÔNG kiểm tra returncode của npm install: fail là im
    lặng trả về đường dẫn node_modules không tồn tại → renderer chết sau đó
    với "Render failed:" rỗng. Giờ fail ở đâu báo rõ ở đó, kèm cách khắc phục.
    """
    nm = _find_node_modules()
    if nm:
        return nm
    ext_dir = _APP_DIR
    npm_exe = shutil.which("npm")
    if not npm_exe:
        # Thiếu npm = thiếu Node.js (npm đi kèm Node) → nói thẳng, không spawn
        # để rồi nhận WinError 2 mù mờ.
        raise RuntimeError(
            "Chưa có package 'canvas' và không tìm thấy npm để tự cài. "
            "Cài Node.js LTS (kèm npm) tại https://nodejs.org rồi mở lại app, "
            "hoặc vào Cài đặt → Công cụ render → Cài tự động.")
    logger.info("Installing node-canvas...")
    proc = await _exec(
        npm_exe, "install", "canvas", "--save",
        cwd=str(ext_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    nm = _find_node_modules()          # tìm lại: cài xong phải THẤY canvas thật
    if proc.returncode != 0 or nm is None:
        err = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "Không tự cài được package 'canvas'"
            + (f" (npm install lỗi: {err[-200:]})" if err else " (npm install lỗi)")
            + " — cần Node.js + mạng tới registry.npmjs.org/GitHub. "
              "Vào Cài đặt → Công cụ render, hoặc chạy tay 'npm install canvas' "
              "trong thư mục app.")
    return nm


async def render_and_encode(
    script_path: str,
    timing_path: str,
    output_dir: str,
    project_id: str,
    theme: str = "dark",
    bg_color: str = "",
    bg: str = "",                       # id preset nền (core/backgrounds.py); "" = theo phong cách
    aspect_ratio: str = "9:16",
    art_style: str = "default",
    title_color: str = "",
    text_color: str = "",
    font_family: str = "",
    subtitle: Optional[dict] = None,    # core.subtitles.subtitle_config(project); None = không phụ đề
    render_mode: str = "pipe",
    gpu_encoder: str = "nvenc",
    intro_video_path: Optional[str] = None,
    outro_video_path: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    proc_registry: Optional[list] = None,   # caller truyền list rỗng để HUỶ giữa chừng
) -> str:
    """Render + encode video. Supports 'pipe' and 'frames' modes.

    proc_registry: list do NGƯỜI GỌI tạo sẵn (rỗng) — mọi tiến trình node/ffmpeg
    spawn ra trong lúc render đều tự thêm vào đây. Người gọi (render_service.py)
    giữ tham chiếu này để HUỶ render giữa chừng: kill từng proc trong danh sách
    (kèm cây con — ffmpeg node tự spawn bên trong không lộ ra Python) thay vì
    chỉ đổi cờ trạng thái, kẻo bấm Huỷ xong CPU/GPU vẫn bị worker mồ côi chiếm.
    """
    os.makedirs(output_dir, exist_ok=True)

    if progress_callback:
        progress_callback(5, "Preparing renderer...")

    node_modules = await _ensure_canvas()
    node_exe = _find_node()
    if not node_exe:
        # Chặn TRƯỚC khi spawn: để _exec tự ném thì user chỉ thấy
        # "FileNotFoundError [WinError 2]" — không có chữ "Node" nào trong đó.
        raise RuntimeError(
            "Không tìm thấy Node.js — render video cần Node.js. "
            "Cài bản LTS tại https://nodejs.org rồi mở lại app, "
            "hoặc vào Cài đặt → Công cụ render → Cài tự động.")
    ext_dir = _APP_DIR

    audio_path = os.path.join(os.path.dirname(script_path), "audio", "full_audio.mp3")
    aspect_suffix = aspect_ratio.replace(":", "_")
    final_video = os.path.join(output_dir, f"edu_{project_id}_{aspect_suffix}.mp4")

    env = os.environ.copy()
    env["NODE_PATH"] = str(node_modules)
    # Kho sprite của template (ui.sprite trong renderer)
    try:
        from config import TEMPLATE_CACHE_DIR
        env["T2_TEMPLATE_CACHE"] = str(TEMPLATE_CACHE_DIR)
    except Exception:
        pass
    # Override màu/font do người dùng chọn — renderer đọc từ env (fallback của args)
    if title_color:
        env["T2_TITLE_COLOR"] = title_color
    if text_color:
        env["T2_TEXT_COLOR"] = text_color
    if font_family:
        env["T2_FONT"] = font_family
    # Nền tuỳ biến (độc lập phong cách). Truyền qua env để MỌI worker chunk
    # song song đều nhận, không phải sửa 4 chỗ dựng lệnh.
    if bg:
        try:
            from core.backgrounds import get as _bg_get
            cfg = _bg_get(bg)
            if cfg:
                env["T2_BG_GRAD"] = ",".join(cfg["grad"])
                env["T2_BG_FX"] = cfg["fx"]
        except Exception as e:
            logger.warning(f"Nền '{bg}' không áp được: {e}")

    # ── Phụ đề cháy chữ ──────────────────────────────────────────────────
    # 'subtitle' là dict ĐÃ GIẢI QUYẾT (core.subtitles.subtitle_config): preset
    # đã chọn xong, không còn "" = auto. Truyền qua CẢ HAI kênh:
    #   • --subtitle <json>  : cờ CLI, thêm vào CẢ 4 chỗ dựng lệnh (pipe/frames
    #     × đơn/chunk) — thiếu 1 chỗ là chunk đó mất phụ đề, video nhấp nháy.
    #   • T2_SUBTITLE (env)  : lưới an toàn, mọi tiến trình con thừa kế.
    # subtitle=None hoặc enabled=False → sub_args=[] → renderer không thấy cờ
    # → vẽ y hệt bản chưa có phụ đề (tương thích ngược).
    sub_args: List[str] = []
    if isinstance(subtitle, dict) and subtitle.get("enabled"):
        try:
            from core.subtitles import to_json as _sub_json
            payload = _sub_json(subtitle)
        except Exception:
            payload = json.dumps(subtitle, ensure_ascii=False, separators=(",", ":"))
        sub_args = ["--subtitle", payload]
        env["T2_SUBTITLE"] = payload
        logger.info(f"[Subtitle] preset={subtitle.get('preset')} "
                    f"scale={subtitle.get('fontScale')}")

    # Prepend working ffmpeg directory to PATH so subprocesses spawned by node find the correct ffmpeg
    ffmpeg_exe = _find_executable("ffmpeg")
    ffmpeg_dir = os.path.dirname(ffmpeg_exe)
    if ffmpeg_dir:
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")

    # 1. Render primary slide content video
    if render_mode == "pipe":
        await _render_pipe(
            node_exe, ext_dir, script_path, timing_path, output_dir,
            theme, bg_color, aspect_ratio, art_style, audio_path, final_video, env, progress_callback, gpu_encoder,
            sub_args=sub_args, proc_registry=proc_registry,
        )
    else:
        await _render_frames(
            node_exe, ext_dir, script_path, timing_path, output_dir,
            theme, bg_color, aspect_ratio, art_style, audio_path, final_video, env, progress_callback, gpu_encoder,
            sub_args=sub_args, proc_registry=proc_registry,
        )

    # 2. Perform FFmpeg stitching if custom video Intro or Outro template is selected
    if intro_video_path or outro_video_path:
        if progress_callback:
            progress_callback(97, "🎬 Nối ghép Intro/Outro video...")
            
        segments = []
        if intro_video_path:
            segments.append(intro_video_path)
        segments.append(final_video)
        if outro_video_path:
            segments.append(outro_video_path)
            
        stitched_temp = final_video + ".stitched.mp4"
        try:
            await _concat_videos_ffmpeg(segments, stitched_temp, aspect_ratio, gpu_encoder)
            if os.path.exists(stitched_temp):
                os.replace(stitched_temp, final_video)
                logger.info(f"Stitching success! Combined video: {final_video}")
        except Exception as e:
            logger.error(f"FFmpeg concatenation failed: {e}")
            if os.path.exists(stitched_temp):
                try:
                    os.remove(stitched_temp)
                except Exception:
                    pass
            # We degrade gracefully: return the unstitched final_video instead of crashing
            if progress_callback:
                progress_callback(99, "⚠️ Lỗi ghép video, giữ lại video gốc...")

    if progress_callback:
        progress_callback(100, "Video export complete!")

    file_size = os.path.getsize(final_video)
    logger.info(f"Final: {final_video} ({file_size / 1024 / 1024:.1f} MB)")
    return final_video


# ── stderr của worker: đọc theo KHỐI, không theo DÒNG ─────────────────────
# Node chuyển tiếp nguyên văn stderr của ffmpeg, mà dòng thống kê của ffmpeg kết
# bằng ký tự CR (carriage return) chứ không phải LF. readline() của asyncio đợi LF
# và ném ValueError khi gom quá 64 KiB không thấy — `except: pass` nuốt lỗi, luồng
# đọc CHẾT, ống stderr đầy, process.stderr.write của Node trên Windows là ĐỒNG BỘ
# nên worker đứng, ffmpeg đói khung. Mọi worker cùng in một nhịp nên cùng đứng một
# lúc — đo 19/9/2026: hai lượt dựng 188 shot đều chết đúng ~14-16 phút, «No progress
# for 1800s» ở 75-81 %. Video ngắn hơn 10 phút dựng không bao giờ chạm 64 KiB.
_STDERR_KEEP = 200_000          # giữ đuôi ngần này byte cho câu báo lỗi


async def _drain_stderr(proc, sink: list) -> None:
    """Hút stderr của một tiến trình con tới khi đóng; `sink` giữ tối đa _STDERR_KEEP byte cuối."""
    kept = 0
    try:
        while True:
            chunk = await proc.stderr.read(65536)
            if not chunk:
                break
            sink.append(chunk)
            kept += len(chunk)
            while kept > _STDERR_KEEP and len(sink) > 1:
                kept -= len(sink.pop(0))
    except Exception:       # noqa: BLE001 — luồng đọc không được chết trước tiến trình
        pass


async def _run_node_renderer(node_exe, ext_dir, cmd, env, progress_callback, pct_range=(8, 96), proc_registry=None):
    """Run canvas_renderer.js and stream progress."""
    proc = await _exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ext_dir),
        env=env,
    )
    if proc_registry is not None:
        proc_registry.append(proc)   # đăng ký NGAY sau spawn — huỷ giữa chừng cần thấy proc này

    stderr_lines = []
    async def read_stderr():
        await _drain_stderr(proc, stderr_lines)

    stderr_task = asyncio.create_task(read_stderr())

    pct_start, pct_end = pct_range
    # Renderer báo lỗi ra STDOUT ({status:'error',message:...} — vd 'canvas not
    # installed') chứ KHÔNG phải stderr. Trước đây chỉ đọc stderr nên user nhận
    # "Render failed: " RỖNG. Giữ lại message stdout để dùng khi stderr trống.
    stdout_error = ""
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        line_str = line.decode("utf-8", errors="replace").strip()
        if line_str.startswith("{"):
            try:
                msg = json.loads(line_str)
                if msg.get("type") == "progress" and progress_callback:
                    pct = int(pct_start + msg.get("percent", 0) / 100 * (pct_end - pct_start))
                    progress_callback(pct, msg.get("message", "Rendering..."))
                elif msg.get("type") == "done":
                    logger.info(f"Renderer done: {msg.get('totalFrames')} frames")
                elif msg.get("status") == "error" or msg.get("type") == "error":
                    stdout_error = str(msg.get("message") or msg.get("error")
                                       or line_str)
            except json.JSONDecodeError:
                pass

    await proc.wait()
    await stderr_task

    stderr_content = b"".join(stderr_lines).decode("utf-8", errors="replace")
    if proc.returncode != 0:
        # Filter out info lines to find actual error
        error_lines = [l for l in stderr_content.split('\n') if l.strip() and not l.strip().startswith('[Renderer]')]
        error_msg = '\n'.join(error_lines[-20:]) if error_lines else stderr_content[-2000:]
        if not error_msg.strip():
            error_msg = stdout_error or "(renderer không in lỗi nào ra stderr)"
        if "canvas" in error_msg.lower() and "not installed" in error_msg.lower():
            # Dịch lỗi kỹ thuật thành hành động user làm được
            error_msg += (" — package 'canvas' chưa cài được. "
                          "Vào Cài đặt → Công cụ render → Cài tự động.")
        logger.error(f"Renderer error: {error_msg[:2000]}")
        raise RuntimeError(f"Render failed: {error_msg[:2000]}")
    return proc


async def _render_pipe(node_exe, ext_dir, script_path, timing_path, output_dir,
                       theme, bg_color, aspect_ratio, art_style, audio_path, final_video, env, progress_callback, gpu_encoder="nvenc",
                       sub_args=None, proc_registry=None):
    """PIPE MODE: render + encode in single step (fast). Uses multi-process chunk rendering."""
    import math
    sub_args = list(sub_args or [])      # ['--subtitle', '<json>'] hoặc []
    enc = ENCODER_MAP.get(gpu_encoder, ENCODER_MAP["nvenc"])
    encoder_label = {"cpu": "CPU", "nvenc": "NVIDIA GPU", "qsv": "Intel QSV", "amf": "AMD AMF"}.get(gpu_encoder, gpu_encoder)

    # 1. Determine total duration and total frames
    total_duration = 30.0
    try:
        with open(timing_path, "r", encoding="utf-8-sig") as f:
            timing_data = json.load(f)
            total_duration = timing_data.get("total_duration", 30.0)
    except Exception as e:
        logger.warning(f"[Pipe] Could not read timing map to determine duration: {e}")

    total_frames = math.ceil(total_duration * 30)

    # 2. Số worker theo SỨC MÁY THẬT (không chỉ số lõi)
    num_workers = _pick_workers(aspect_ratio)

    # Fallback to single worker if total duration is extremely short (under 5 seconds)
    if total_frames < 150:
        num_workers = 1

    logger.info(f"[Pipe] Rendering → {final_video} (encoder: {encoder_label}, workers: {num_workers}, frames: {total_frames})")

    if num_workers == 1:
        # Single process fallback
        cmd = [
            node_exe, str(CANVAS_RENDERER_JS),
            "--script", script_path,
            "--timing", timing_path,
            "--output", output_dir,
            "--theme", theme, "--bg-color", bg_color, "--aspect", aspect_ratio,
            "--style", art_style,
            "--fps", "30",
            "--mode", "pipe",
            "--outputFile", final_video,
            "--codec", enc["codec"],
            "--preset", enc["preset"],
        ] + sub_args
        if enc.get("extra"):
            cmd.extend(["--ffmpegExtra", " ".join(enc["extra"])])
        if os.path.isfile(audio_path):
            cmd.extend(["--audio", audio_path])

        if progress_callback:
            progress_callback(8, f"⚡ Pipe + {encoder_label}: rendering...")

        try:
            await _run_node_renderer(node_exe, ext_dir, cmd, env, progress_callback, (8, 96), proc_registry=proc_registry)
        except RuntimeError as e:
            logger.warning(f"[Pipe] Failed ({e}), falling back to frames + CPU encoder...")
            if progress_callback:
                progress_callback(10, "⚠️ Pipe failed, switching to CPU frames mode...")
            return await _render_frames(
                node_exe, ext_dir, script_path, timing_path, output_dir,
                theme, bg_color, aspect_ratio, art_style, audio_path, final_video, env, progress_callback, "cpu",
                sub_args=sub_args,
            )
    else:
        # Multi-process parallel rendering
        temp_dir = os.path.join(output_dir, f"temp_chunks_{os.path.basename(final_video)}")
        os.makedirs(temp_dir, exist_ok=True)

        chunk_size = total_frames // num_workers
        workers_ranges = []
        for w in range(num_workers):
            start = w * chunk_size
            end = total_frames if w == num_workers - 1 else (w + 1) * chunk_size
            workers_ranges.append((start, end))

        # ── HYBRID GPU+CPU encode (mỗi worker = 1 tiến trình node vẽ khung hình
        # BẰNG CPU (cairo — không có bản GPU) rồi TỰ PIPE thẳng vào 1 ffmpeg con
        # riêng, không qua đĩa). TRƯỚC ĐÂY mọi chunk đều ép cứng libx264 CPU dù
        # người dùng đã chọn GPU (nhãn tiến trình "NVIDIA GPU" khi đó SAI — đo
        # thực tế 27/07: GPU 15%, CPU 44%) ⇒ card hình cắm ngồi không, còn CPU
        # phải cõng CẢ vẽ khung hình LẪN encode libx264 của tất cả worker.
        # Giờ: vài chunk ĐẦU giao thẳng cho GPU (encoder đã chọn ở Cài đặt) —
        # gần như KHÔNG tốn CPU nữa vì chip encode riêng xử lý — số còn lại vẫn
        # CPU libx264 ultrafast (đã là preset nhanh nhất) chạy SONG SONG. Encode
        # dời bớt sang GPU ⇒ CPU rảnh hơn cho phần vẽ khung hình (nút thắt thật).
        # Trần vài chunk GPU thay vì TẤT CẢ: card tiêu dùng thường chỉ có 1-2
        # khối NVENC vật lý — giao 12 tiến trình cùng lúc không tăng thêm thông
        # lượng, có khi driver cũ còn lỗi "hết phiên". 3 là mức an toàn đo được
        # trên phần lớn GPU NVIDIA phổ thông; ép tay qua settings.json khi cần
        # (khoá "gpu_chunks", 0 = trần mặc định).
        _GPU_CHUNK_CAP = {"nvenc": 3, "qsv": 2, "amf": 2}
        gpu_chunks = 0
        if gpu_encoder in _GPU_CHUNK_CAP:
            try:
                from config import load_settings
                forced_gc = int(load_settings().get("gpu_chunks", 0) or 0)
            except Exception:
                forced_gc = 0
            gpu_chunks = (max(0, min(forced_gc, num_workers)) if forced_gc > 0
                         else min(_GPU_CHUNK_CAP[gpu_encoder], num_workers))
        if gpu_chunks > 0:
            logger.info(f"[Pipe] Encode: {gpu_chunks} chunk qua {encoder_label} "
                       f"(GPU) + {num_workers - gpu_chunks} chunk qua CPU — chạy song song.")

        procs = []
        for w, (start, end) in enumerate(workers_ranges):
            chunk_path = os.path.join(temp_dir, f"chunk_{w}.mp4")
            if w < gpu_chunks:
                # Chunk này encode BẰNG GPU — dùng đúng codec/preset người dùng
                # đã chọn (nvenc/qsv/amf), y hệt đường 1-worker ở trên.
                chunk_codec, chunk_preset = enc["codec"], enc["preset"]
                # -profile:v high ép CẢ hai nhánh GPU/CPU ra CÙNG profile H.264
                # — thiếu dòng này, nvenc mặc định "main" còn x264 mặc định
                # "high" → nối 2 kiểu khác profile bằng concat -c copy có thể
                # giật 1 khung ở đúng chỗ nối 2 chunk (hiếm nhưng có thật).
                chunk_extra = list(enc.get("extra") or []) + ["-profile:v", "high"]
            else:
                chunk_codec, chunk_preset = "libx264", "ultrafast"
                chunk_extra = ["-crf", "22", "-threads", "2", "-profile:v", "high"]
            cmd_w = [
                node_exe, str(CANVAS_RENDERER_JS),
                "--script", script_path,
                "--timing", timing_path,
                "--output", output_dir,
                "--theme", theme, "--bg-color", bg_color, "--aspect", aspect_ratio,
                "--style", art_style,
                "--fps", "30",
                "--mode", "pipe",
                "--outputFile", chunk_path,
                "--codec", chunk_codec,
                "--preset", chunk_preset,
                "--startFrame", str(start),
                "--endFrame", str(end)
            ] + sub_args      # MỌI chunk phải có cùng cờ phụ đề, không thì
                              # phân đoạn nào thiếu là phụ đề biến mất giữa video
            cmd_w.extend(["--ffmpegExtra", " ".join(chunk_extra)])
            # Note: We do NOT pass --audio to workers to avoid audio sync issues in chunked videos

            proc = await _exec(
                *cmd_w,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ext_dir),
                env=env,
            )
            procs.append(proc)
            if proc_registry is not None:
                proc_registry.append(proc)

        worker_progress = [0] * num_workers

        async def monitor_worker(w_idx, proc):
            stderr_lines = []
            async def read_stderr():
                await _drain_stderr(proc, stderr_lines)

            stderr_task = asyncio.create_task(read_stderr())

            # Lỗi renderer nằm trên STDOUT (json status:'error') — giữ lại để
            # không báo "failed: " rỗng khi stderr trống (xem _run_node_renderer)
            stdout_error = ""
            try:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if line_str.startswith("{"):
                        try:
                            msg = json.loads(line_str)
                            if msg.get("type") == "progress":
                                f = msg.get("frame", 0)
                                start = msg.get("startFrame", 0)
                                worker_progress[w_idx] = max(0, f - start)

                                # Aggregate progress
                                total_done = sum(worker_progress)
                                pct = int((total_done / total_frames) * 100)
                                mapped_pct = int(8 + (pct / 100.0) * (96 - 8))
                                if progress_callback:
                                    progress_callback(mapped_pct, f"⚡ Pipe + {encoder_label}: rendering... {pct}% ({total_done}/{total_frames} frames)")
                            elif msg.get("status") == "error" or msg.get("type") == "error":
                                stdout_error = str(msg.get("message") or msg.get("error") or line_str)
                        except json.JSONDecodeError:
                            pass
            finally:
                await proc.wait()
                await stderr_task
                stderr_content = b"".join(stderr_lines).decode("utf-8", errors="replace")
                if proc.returncode != 0:
                    error_lines = [l for l in stderr_content.split('\n') if l.strip() and not l.strip().startswith('[Renderer]')]
                    error_msg = '\n'.join(error_lines[-10:]) if error_lines else stderr_content[-1000:]
                    if not error_msg.strip():
                        error_msg = stdout_error or "(renderer không in lỗi nào ra stderr)"
                    raise RuntimeError(f"Worker {w_idx} failed (exit code {proc.returncode}): {error_msg}")

        tasks = [monitor_worker(i, procs[i]) for i in range(num_workers)]
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"[Pipe] Parallel rendering error: {e}")
            for p in procs:
                try:
                    p.terminate()
                except Exception:
                    pass
            # Cleanup temp directory on error
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            # Fallback to frames CPU mode
            logger.warning("[Pipe] Parallel render failed, falling back to frames + CPU...")
            if progress_callback:
                progress_callback(10, "⚠️ Parallel render failed, switching to CPU frames mode...")
            return await _render_frames(
                node_exe, ext_dir, script_path, timing_path, output_dir,
                theme, bg_color, aspect_ratio, art_style, audio_path, final_video, env, progress_callback, "cpu",
                sub_args=sub_args,
            )

        # 3. Concatenate video chunks using FFmpeg demuxer
        if progress_callback:
            progress_callback(96, "🎬 Ghép các phân đoạn video...")

        concat_list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f_list:
            for w in range(num_workers):
                chunk_file = os.path.join(temp_dir, f"chunk_{w}.mp4").replace("\\", "/")
                f_list.write(f"file '{chunk_file}'\n")

        raw_video = os.path.join(temp_dir, "raw_video.mp4")
        ffmpeg_exe = _find_executable("ffmpeg")
        concat_cmd = [
            ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list_path, "-c", "copy", raw_video
        ]

        logger.info(f"[Pipe] Stitching chunks: {' '.join(concat_cmd)}")
        proc_concat = await _exec(
            *concat_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr_concat = await proc_concat.communicate()
        if proc_concat.returncode != 0:
            logger.error(f"[Pipe] FFmpeg concat failed: {stderr_concat.decode()[:500]}")
            # Try to copy first chunk or fallback
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            raise RuntimeError(f"FFmpeg chunk concat failed: {stderr_concat.decode()[:300]}")

        # 4. Mux audio bằng STREAM COPY — chunks đã là h264 (libx264 crf22),
        # encode lại lần 2 tốn ~10-15% tổng thời gian và còn GIẢM chất lượng.
        # Copy giữ nguyên video, chỉ ghép audio (gần như tức thì).
        if progress_callback:
            progress_callback(98, "🔊 Ghép âm thanh...")

        if os.path.isfile(audio_path):
            cmd_mux = [
                ffmpeg_exe, "-y",
                "-i", raw_video, "-i", audio_path,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", final_video,
            ]
            logger.info(f"[Pipe] Mux (stream copy): {' '.join(cmd_mux)}")
            proc_mux = await _exec(
                *cmd_mux, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr_mux = await proc_mux.communicate()
            if proc_mux.returncode != 0:
                # Hiếm: copy lỗi → transcode như đường cũ
                logger.warning(f"[Pipe] Copy-mux failed: {stderr_mux.decode()[:200]}"
                               ", falling back to transcode")
                cmd_fb = [ffmpeg_exe, "-y", "-i", raw_video, "-i", audio_path,
                          "-c:v", enc["codec"], "-preset", enc["preset"]]
                if enc.get("extra"):
                    cmd_fb.extend(enc["extra"])
                cmd_fb.extend(["-c:a", "aac", "-b:a", "128k", "-shortest",
                               final_video])
                proc_fb = await _exec(
                    *cmd_fb, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc_fb.communicate()
        else:
            shutil.copy2(raw_video, final_video)

        # 5. Cleanup temp chunk files
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"[Pipe] Cleanup chunks error: {e}")

    if not os.path.isfile(final_video):
        logger.warning("[Pipe] No output file produced, falling back to frames + CPU...")
        if progress_callback:
            progress_callback(10, "⚠️ Không tìm thấy file kết quả, chuyển sang CPU frames mode...")
        return await _render_frames(
            node_exe, ext_dir, script_path, timing_path, output_dir,
            theme, bg_color, aspect_ratio, art_style, audio_path, final_video, env, progress_callback, "cpu",
            sub_args=sub_args,
        )

    if progress_callback:
        progress_callback(100, "Video export complete!")

    file_size = os.path.getsize(final_video)
    logger.info(f"Final: {final_video} ({file_size / 1024 / 1024:.1f} MB)")
    return final_video


async def _render_frames(node_exe, ext_dir, script_path, timing_path, output_dir,
                          theme, bg_color, aspect_ratio, art_style, audio_path, final_video, env, progress_callback, gpu_encoder="nvenc",
                          sub_args=None, proc_registry=None):
    """FRAMES MODE: render JPEGs then FFmpeg encode (stable). Uses multi-process parallel rendering."""
    import math
    sub_args = list(sub_args or [])      # ['--subtitle', '<json>'] hoặc []
    frames_dir = os.path.join(os.path.dirname(script_path), "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # Clean old frames
    for f in os.listdir(frames_dir):
        if f.endswith(".png") or f.endswith(".jpg"):
            try:
                os.remove(os.path.join(frames_dir, f))
            except Exception:
                pass

    # 1. Determine total duration and total frames
    total_duration = 30.0
    try:
        with open(timing_path, "r", encoding="utf-8-sig") as f:
            timing_data = json.load(f)
            total_duration = timing_data.get("total_duration", 30.0)
    except Exception as e:
        logger.warning(f"[Frames] Could not read timing map: {e}")

    total_frames = math.ceil(total_duration * 30)

    # 2. Determine worker count based on CPU cores
    cpu_count = os.cpu_count() or 4
    num_workers = max(1, min(cpu_count - 1, 4))

    # Fallback to single worker if extremely short
    if total_frames < 150:
        num_workers = 1

    logger.info(f"[Frames] Rendering PNG/JPEGs (workers: {num_workers}, total frames: {total_frames})")

    # Step 1: Render frames (Single or Parallel)
    if num_workers == 1:
        cmd = [
            node_exe, str(CANVAS_RENDERER_JS),
            "--script", script_path,
            "--timing", timing_path,
            "--output", frames_dir,
            "--theme", theme, "--bg-color", bg_color, "--aspect", aspect_ratio,
            "--style", art_style,
            "--fps", "30",
            "--mode", "frames",
        ] + sub_args
        if progress_callback:
            progress_callback(5, "🖼️ Rendering frames...")
        await _run_node_renderer(node_exe, ext_dir, cmd, env, progress_callback, (5, 65), proc_registry=proc_registry)
    else:
        chunk_size = total_frames // num_workers
        workers_ranges = []
        for w in range(num_workers):
            start = w * chunk_size
            end = total_frames if w == num_workers - 1 else (w + 1) * chunk_size
            workers_ranges.append((start, end))

        procs = []
        for w, (start, end) in enumerate(workers_ranges):
            cmd_w = [
                node_exe, str(CANVAS_RENDERER_JS),
                "--script", script_path,
                "--timing", timing_path,
                "--output", frames_dir,
                "--theme", theme, "--bg-color", bg_color, "--aspect", aspect_ratio,
                "--style", art_style,
                "--fps", "30",
                "--mode", "frames",
                "--startFrame", str(start),
                "--endFrame", str(end)
            ] + sub_args      # chunk nào thiếu cờ là chunk đó mất phụ đề
            proc = await _exec(
                *cmd_w,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ext_dir),
                env=env,
            )
            procs.append(proc)
            if proc_registry is not None:
                proc_registry.append(proc)

        worker_progress = [0] * num_workers

        async def monitor_worker(w_idx, proc):
            stderr_lines = []
            async def read_stderr():
                await _drain_stderr(proc, stderr_lines)

            stderr_task = asyncio.create_task(read_stderr())

            # Lỗi renderer nằm trên STDOUT — như monitor_worker của pipe mode
            stdout_error = ""
            try:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if line_str.startswith("{"):
                        try:
                            msg = json.loads(line_str)
                            if msg.get("type") == "progress":
                                f = msg.get("frame", 0)
                                start = msg.get("startFrame", 0)
                                worker_progress[w_idx] = max(0, f - start)

                                # Aggregate progress
                                total_done = sum(worker_progress)
                                pct = int((total_done / total_frames) * 100)
                                mapped_pct = int(5 + (pct / 100.0) * (65 - 5))
                                if progress_callback:
                                    progress_callback(mapped_pct, f"🖼️ Rendering frames... {pct}% ({total_done}/{total_frames})")
                            elif msg.get("status") == "error" or msg.get("type") == "error":
                                stdout_error = str(msg.get("message") or msg.get("error") or line_str)
                        except json.JSONDecodeError:
                            pass
            finally:
                await proc.wait()
                await stderr_task
                stderr_content = b"".join(stderr_lines).decode("utf-8", errors="replace")
                if proc.returncode != 0:
                    error_lines = [l for l in stderr_content.split('\n') if l.strip() and not l.strip().startswith('[Renderer]')]
                    error_msg = '\n'.join(error_lines[-10:]) if error_lines else stderr_content[-1000:]
                    if not error_msg.strip():
                        error_msg = stdout_error or "(renderer không in lỗi nào ra stderr)"
                    raise RuntimeError(f"Worker {w_idx} failed (exit code {proc.returncode}): {error_msg}")

        tasks = [monitor_worker(i, procs[i]) for i in range(num_workers)]
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"[Frames] Parallel rendering error: {e}")
            for p in procs:
                try:
                    p.terminate()
                except Exception:
                    pass
            raise e

    frame_count = len([f for f in os.listdir(frames_dir) if f.endswith(".jpg")])
    if frame_count == 0:
        raise RuntimeError("No frames rendered!")
    logger.info(f"Rendered {frame_count} frames")

    # Step 2: FFmpeg encode with selected encoder
    enc = ENCODER_MAP.get(gpu_encoder, ENCODER_MAP["nvenc"])
    encoder_label = {"cpu": "CPU", "nvenc": "NVIDIA GPU", "qsv": "Intel QSV", "amf": "AMD AMF"}.get(gpu_encoder, gpu_encoder)
    if progress_callback:
        progress_callback(68, f"🎬 Encoding ({encoder_label})...")

    ffmpeg_exe = _find_executable("ffmpeg")
    raw_video = os.path.join(output_dir, f"raw_{os.path.basename(final_video)}")
    frame_pattern = os.path.join(frames_dir, "frame_%06d.jpg")

    cmd_encode = [
        ffmpeg_exe, "-y",
        "-threads", "0",               # use all CPU threads for decode
        "-framerate", "30",
        "-i", frame_pattern,
        "-c:v", enc["codec"], "-preset", enc["preset"],
    ] + enc.get("extra", []) + [
        "-pix_fmt", "yuv420p",
        raw_video,
    ]
    proc2 = await _exec(
        *cmd_encode, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr2 = await proc2.communicate()
    if proc2.returncode != 0:
        # Fallback to CPU if GPU encoder fails
        if gpu_encoder != "cpu":
            logger.warning(f"{encoder_label} failed, falling back to CPU: {stderr2.decode()[:200]}")
            if progress_callback:
                progress_callback(70, "⚠️ GPU failed, falling back to CPU...")
            cpu_enc = ENCODER_MAP["cpu"]
            cmd_fallback = [
                ffmpeg_exe, "-y",
                "-threads", "0",
                "-framerate", "30",
                "-i", frame_pattern,
                "-c:v", cpu_enc["codec"], "-preset", cpu_enc["preset"],
            ] + cpu_enc.get("extra", []) + [
                "-pix_fmt", "yuv420p",
                raw_video,
            ]
            proc_fb = await _exec(
                *cmd_fallback, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_fb = await proc_fb.communicate()
            if proc_fb.returncode != 0:
                raise RuntimeError(f"FFmpeg encode failed (CPU fallback): {stderr_fb.decode()[:300]}")
        else:
            raise RuntimeError(f"FFmpeg encode failed: {stderr2.decode()[:300]}")
    # Step 3: Mux audio
    if os.path.isfile(audio_path):
        if progress_callback:
            progress_callback(85, "🔊 Muxing audio...")
        cmd_mux = [
            ffmpeg_exe, "-y",
            "-i", raw_video,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            final_video,
        ]
        proc3 = await _exec(
            *cmd_mux, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr3 = await proc3.communicate()
        if proc3.returncode != 0:
            logger.warning(f"Mux failed, using raw: {stderr3.decode()[:200]}")
            shutil.copy2(raw_video, final_video)
    else:
        shutil.copy2(raw_video, final_video)

    # Cleanup
    try:
        os.remove(raw_video)
    except Exception:
        pass

    # Clean up intermediate JPEG/PNG frames to save disk space
    try:
        for f in os.listdir(frames_dir):
            if f.endswith(".png") or f.endswith(".jpg"):
                os.remove(os.path.join(frames_dir, f))
    except Exception as e:
        logger.warning(f"[Frames] Failed to clean up frames directory: {e}")

    if progress_callback:
        progress_callback(100, "Video export complete!")

    file_size = os.path.getsize(final_video)
    logger.info(f"Final: {final_video} ({file_size / 1024 / 1024:.1f} MB)")
    return final_video
