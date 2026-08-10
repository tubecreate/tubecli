import os
import sys
import cv2
import torch
import logging
from typing import List, Tuple, Dict, Any, Optional

logger = logging.getLogger("video_editor.matting")

# ── RVM Setup ──────────────────────────────────────────────────────────
RVM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RobustVideoMatting")
if RVM_DIR not in sys.path and os.path.exists(RVM_DIR):
    sys.path.insert(0, RVM_DIR)

# ── AI Models ────────────────────────────────────────────────────────
_yolo_model = None
_rvm_model = None
_device = "cuda" if torch.cuda.is_available() else "cpu"

def get_yolo_model():
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        # Use YOLOv8n (nano) for speed, it's good enough for person detection
        _yolo_model = YOLO("yolov8n.pt")
    return _yolo_model

def get_rvm_model():
    global _rvm_model
    if _rvm_model is None:
        try:
            from model import MattingNetwork
            model = MattingNetwork('mobilenetv3').to(_device).eval()
            model_path = os.path.join(RVM_DIR, "rvm_mobilenetv3.pth")
            model.load_state_dict(torch.load(model_path, map_location=_device))
            _rvm_model = model
            logger.info("RVM Model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load RVM model: {e}")
            raise
    return _rvm_model


# ── AI Processing Functions ──────────────────────────────────────────

def detect_person_segments(video_path: str, fps_sample: float = 1.0) -> List[Tuple[float, float]]:
    """
    Scans the video and returns a list of (start_sec, end_sec) segments where a person is detected.
    fps_sample: Frames to sample per second (e.g., 1.0 = check 1 frame every second)
    """
    logger.info(f"Detecting person segments in {video_path}")
    model = get_yolo_model()
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video {video_path}")
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_interval = max(1, int(fps / fps_sample))
    
    segments = []
    current_start = None
    
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if frame_idx % frame_interval == 0:
            # Detect person (class 0 in COCO)
            results = model.predict(frame, classes=[0], verbose=False)
            has_person = len(results[0].boxes) > 0
            
            timestamp = frame_idx / fps
            
            if has_person and current_start is None:
                current_start = timestamp
            elif not has_person and current_start is not None:
                segments.append((current_start, timestamp))
                current_start = None
                
        frame_idx += 1
        
    if current_start is None and not segments:
        # If no person detected but we need to return something or maybe person spans whole video
        pass
    elif current_start is not None:
        segments.append((current_start, total_frames / fps))
        
    cap.release()
    
    # Merge segments that are close to each other (e.g., within 2 seconds)
    merged_segments = []
    if segments:
        merged_segments.append(segments[0])
        for s in segments[1:]:
            last_s = merged_segments[-1]
            if s[0] - last_s[1] <= 2.0:
                merged_segments[-1] = (last_s[0], s[1])
            else:
                merged_segments.append(s)
                
    logger.info(f"Person segments: {merged_segments}")
    return merged_segments

def remove_background(input_path: str, output_path: str) -> str:
    """
    Process video using RobustVideoMatting to extract alpha matte and composite onto green/blue screen or output RGBA.
    RVM inference interface.
    """
    logger.info(f"Removing background from {input_path}")
    from inference import convert_video
    
    model = get_rvm_model()
    
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    # RVM can output directly to video using PyAV or torchvision or cv2.
    # We will output as ProRes 4444 (with alpha) or PNG sequence.
    # To keep dependencies simple and file size manageable, let's output green screen first, then use FFmpeg to composite.
    # Wait, inference.py in RVM supports direct composition. Let's use RVM's interface.
    
    # Alternatively, use RVM's inference function to generate an RGBA or green screen.
    convert_video(
        model,                           # The loaded model, can be on any device (cpu or cuda).
        input_source=input_path,         # A video file or an image sequence directory.
        output_type='video',             # Choose "video" or "png_sequence"
        output_composition=output_path,  # File path for composition (green screen or solid color if background is provided)
        output_alpha=None,               # File path for alpha matte.
        output_foreground=None,          # File path for foreground object.
        output_video_mbps=8,             # Output video mbps. Not needed for png sequence.
        downsample_ratio=None,           # A hyperparameter to adjust or use None for auto.
        seq_chunk=1                      # Process n frames at once for better bipartite performance.
    )
    
    logger.info(f"Background removed. Output saved to {output_path}")
    return output_path

async def composite_background(
    foreground_file: str, 
    background_file: str, 
    output_file: str,
    chroma_key: str = "0x78FF9B"  # RVM default is [120, 255, 155] = #78FF9B
) -> Dict[str, Any]:
    """
    Uses FFmpeg to composite the green-screen foreground over the background.
    """
    try:
        from video_engine import _run_ffmpeg_async, detect_gpu_encoder, _ensure_output_dir
    except ImportError:
        import sys
        ve_dir = os.path.dirname(os.path.abspath(__file__))
        if ve_dir not in sys.path:
            sys.path.append(ve_dir)
        from video_engine import _run_ffmpeg_async, detect_gpu_encoder, _ensure_output_dir
    
    logger.info(f"Compositing {foreground_file} onto {background_file}")
    _ensure_output_dir(output_file)
    codec, _ = detect_gpu_encoder()
    
    # Use chromakey (better for green screens than colorkey) 
    # similarity=0.1 and blend=0.1 provide a soft edge.
    # We add despill=green to aggressively kill any remaining green pixels on the edges (the green halo).
    chroma_filter = f"chromakey={chroma_key}:0.12:0.05,despill=green"
    
    # Scale background to exactly match the foreground dimensions.
    # We must NOT use format=yuv420p on the foreground before overlay because it strips the Alpha channel!
    filter_complex = (
        f"[0:v]{chroma_filter}[fg];"
        f"[1:v][fg]scale2ref=w=rw:h=rh[bg_scaled][fg_ref];"
        f"[bg_scaled][fg_ref]overlay=shortest=1,format=yuv420p[outv]"
    )

    bg_ext = os.path.splitext(background_file)[1].lower()
    is_image = bg_ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]
    bg_input_args = ["-loop", "1", "-i", background_file] if is_image else ["-stream_loop", "-1", "-i", background_file]

    args = [
        "-y", 
        "-i", foreground_file,    # [0] Foreground
    ] + bg_input_args + [         # [1] Background
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",           # Map audio from foreground
        "-c:v", codec,
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",              # End when the shortest stream ends
        output_file
    ]
    
    result = await _run_ffmpeg_async(args, timeout=1200)
    if result.returncode != 0:
        raise RuntimeError(f"Composition failed: {result.stderr[-500:]}")
        
    return {"output": output_file, "status": "success", "file_size": os.path.getsize(output_file)}
