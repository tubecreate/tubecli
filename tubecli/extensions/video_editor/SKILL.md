---
name: Video Editor (FFmpeg)
description: AI-powered Video Editor with trimming, merging, effects, overlays, and export
---

# Video Editor Skill

This extension provides professional video editing capabilities via FFmpeg.
Supports GPU acceleration (NVENC, QSV, AMF) with automatic CPU fallback.

## Available API Endpoints

### Check Status
```
GET /api/v1/video/status
```
Returns FFmpeg version, GPU encoder info, and availability status.

### Create Project
```
POST /api/v1/video/projects
{"name": "My Video Project", "description": "optional"}
```
Creates a new editing project with timeline and media library.

### List Projects
```
GET /api/v1/video/projects
```

### Get Project Details
```
GET /api/v1/video/projects/{project_id}
```
Returns full project data including timeline tracks and media list.

### Update Project
```
PUT /api/v1/video/projects/{project_id}
{"name": "New Name", "timeline": {...}, "export_settings": {...}}
```

### Delete Project
```
DELETE /api/v1/video/projects/{project_id}
```

### Upload Media
```
POST /api/v1/video/upload
Content-Type: multipart/form-data
file: <video/audio/image file>
project_id: <optional project ID to attach to>
```

### Trim Video
```
POST /api/v1/video/trim
{
  "input_file": "/path/to/video.mp4",
  "start": "00:00:05",
  "end": "00:00:15"
}
```
Returns a `task_id` for status polling. Uses stream copy for speed.

### Merge Videos
```
POST /api/v1/video/merge
{
  "input_files": ["/path/to/clip1.mp4", "/path/to/clip2.mp4"],
  "transition": "none"
}
```
Supports transitions: `none`, `fade`, `dissolve`, `wipeleft`, `wiperight`.

### Add Overlay
```
POST /api/v1/video/overlay
{
  "input_file": "/path/to/video.mp4",
  "overlay_type": "text",
  "text": "Hello World",
  "x": "(w-text_w)/2",
  "y": "h-th-20",
  "fontsize": 36,
  "fontcolor": "white"
}
```
Supports `text` and `image` overlay types.

### Apply Effect
```
POST /api/v1/video/effect
{
  "input_file": "/path/to/video.mp4",
  "effect": "grayscale"
}
```
Available effects: `speed_2x`, `speed_0.5x`, `speed_1.5x`, `rotate_90`, `rotate_180`,
`rotate_270`, `flip_h`, `flip_v`, `mirror`, `grayscale`, `sepia`, `blur`, `blur_heavy`,
`sharpen`, `brightness_up`, `brightness_down`, `contrast_up`, `contrast_down`,
`saturate`, `desaturate`, `vignette`, `fade_in`, `fade_out`, `reverse`,
`vintage`, `negative`, `noise`, `stabilize`.

### Export Video
```
POST /api/v1/video/export
{
  "input_file": "/path/to/video.mp4",
  "format": "mp4",
  "quality": "high",
  "resolution": "1080p",
  "fps": 30
}
```
Quality levels: `low`, `medium`, `high`, `ultra`.
Resolutions: `360p`, `480p`, `720p`, `1080p`, `1440p`, `4k`.

### Custom FFmpeg Command
```
POST /api/v1/video/ffmpeg
{
  "command": "-y -i input.mp4 -vf scale=640:480 output.mp4"
}
```

### Check Task Status
```
GET /api/v1/video/task/{task_id}
```
Returns: `running`, `done`, or `error` with result/error details.

### Get Media Info
```
GET /api/v1/video/info?file=/path/to/video.mp4
```
Returns: duration, resolution, FPS, codecs, bitrate.

### Generate Thumbnail
```
GET /api/v1/video/thumbnail?file=/path/to/video.mp4&time=00:00:01
```
Returns JPEG thumbnail image.

### List Available Presets
```
GET /api/v1/video/presets
```
Returns available effects, export presets, and resolutions.

## Workflow Nodes

Use these nodes in the TubeCLI Workflow Builder:

| Node | Inputs | Outputs |
|------|--------|---------|
| ✂️ **Video Trim** | `input_file`, `start_time`, `end_time` | `output_file`, `status` |
| 🔗 **Video Merge** | `input_files`, `transition` | `output_file`, `status` |
| 📝 **Video Overlay** | `input_file`, `overlay_type`, `text`/`overlay_file`, `position` | `output_file`, `status` |
| ✨ **Video Effect** | `input_file`, `effect` | `output_file`, `status` |
| 📤 **Video Export** | `input_file`, `format`, `quality`, `resolution` | `output_file`, `file_size`, `status` |
| 🎬 **FFmpeg Command** | `command`, `input_file` | `output_file`, `stdout`, `status` |

## Example Pipeline

Chain nodes in a workflow:
1. **Video Trim** (cut intro) → 
2. **Video Effect** (apply grayscale) →
3. **Video Overlay** (add watermark) →
4. **Video Export** (1080p high quality MP4)

## AI Background Removal (Tách nền video)

Tính năng AI tự động tách nhân vật ra khỏi nền video và thay nền mới.
Sử dụng RobustVideoMatting (deep learning) để xử lý.

### Tạo Job tách nền
```
POST /api/v1/video/jobs
{
  "source_url": "https://v.douyin.com/...",
  "bg_path": "c:/path/to/background.jpg",
  "trim_no_person": true
}
```
- `source_url`: URL video gốc (Douyin, TikTok, YouTube...)
- `bg_path`: Đường dẫn ảnh/video nền thay thế. Dùng `#00FF00` cho màn xanh (greenscreen)
- `trim_no_person`: Tự động cắt bỏ đoạn không có người (mặc định: true)

### Xem danh sách Job
```
GET /api/v1/video/jobs
```

### Xem chi tiết Job
```
GET /api/v1/video/jobs/{job_id}
```

### Xóa Job
```
DELETE /api/v1/video/jobs/{job_id}
```

## Telegram Chatbot Actions

Khi người dùng yêu cầu tách nền / remove background / thay nền video qua chat, trả về JSON:

```json
{
  "action": "remove_background",
  "source_url": "https://v.douyin.com/... hoặc /path/to/local/file.mp4",
  "bg_type": "green",
  "file_path": "/path/to/local/file.mp4"
}
```

### Quy tắc chọn source:
- **ƯU TIÊN `file_path`**: Nếu video đã được tải về trước đó (hệ thống báo "File path: xxx"), PHẢI dùng `file_path` đó làm `source_url`. KHÔNG tải lại lần 2.
- **Dùng `source_url` + URL**: Chỉ khi chưa có file local và người dùng cung cấp URL.
- **Hỏi lại người dùng**: Nếu không có cả URL lẫn file_path, HỎI LẠI: "Bạn muốn tách nền video nào? Hãy gửi link video."
- `source_url` hỗ trợ cả URL lẫn đường dẫn file local (ví dụ: `data\downloads\video.mp4`)

### Các giá trị `bg_type`:
- `"green"` hoặc `"greenscreen"`: Xuất video với nền xanh (chromakey) để chỉnh sửa thêm
- `"transparent"`: Giống green, xuất nền xanh
- `"image"`: Thay nền bằng ảnh (cần thêm trường `bg_path`)
- Nếu người dùng không chỉ rõ nền → mặc định dùng `"green"`

Từ khóa nhận biết: tách nền, tách nhân vật, remove background, xóa nền, thay nền, chromakey, greenscreen, chroma key, background removal

## Chỉnh sửa Video (Edit, Effect, Rotate)

Khi người dùng yêu cầu chỉnh sửa video, lật video, xoay gương, làm mờ, trắng đen, hãy trả về action `edit_video`:

```json
{
  "action": "edit_video",
  "effect": "flip_h",
  "input_file": "/path/to/local/file.mp4"
}
```

### Các giá trị `effect` hỗ trợ:
- `flip_h`: Xoay gương, lật ngang (mirror). Dùng khi user yêu cầu "xoay gương", "lật video".
- `flip_v`: Lật dọc
- `rotate_90`: Xoay 90 độ
- `rotate_180`: Xoay 180 độ
- `grayscale`: Làm trắng đen
- `blur`: Làm mờ (có thể truyền `"params": {"sigma": 5}` để mờ nhiều hơn)
- `speed_2x`: Tăng tốc độ gấp đôi
- `speed_0.5x`: Giảm tốc độ một nửa

Từ khóa nhận biết: xoay video, lật video, chỉnh tốc độ, hiệu ứng, lật ngang, xoay gương, mirror, grayscale, chỉnh màu.
