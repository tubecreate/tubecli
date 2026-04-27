"""
Default Skills — Pre-built workflow templates that auto-register.
These are the starting skills available in every TubeCLI installation.
"""
from typing import List, Dict

def _base_url():
    try:
        from tubecli.config import get_api_port
        return f"http://localhost:{get_api_port()}"
    except Exception:
        return "http://localhost:5295"

DEFAULT_SKILLS: List[Dict] = [
    {
        "name": "📊 Google Sheets",
        "description": "Quản lý Google Sheets toàn diện: Tạo Sheet mới, Đọc dữ liệu, Ghi/Append dữ liệu, Đồng bộ metadata. Dùng: tubecli skill run \"Google Sheets\"",
        "skill_type": "API Integration",
        "commands": [
            "create sheet", "tạo sheet", "new spreadsheet",
            "read sheet", "đọc sheet", "read google sheet",
            "write sheet", "ghi sheet", "append sheet",
            "sync sheet", "đồng bộ sheet", "sync data to sheet",
        ],
        "workflow_data": {"nodes": [], "connections": []},
    },
    {
        "name": "🔍 Google Search",
        "description": "Tìm kiếm Google nhanh bằng HTTP + AI tóm tắt kết quả. Không cần mở browser. Dùng: tubecli skill run 'Google Search' --input 'từ khóa'",
        "skill_type": "Skill",
        "commands": [
            "google search", "tìm kiếm google", "search google", "tìm google",
        ],
        "workflow_data": {
            "name": "Google Search",
            "nodes": [
                {
                    "id": "search_query",
                    "type": "text_input",
                    "label": "🔍 Từ khóa tìm kiếm",
                    "config": {"text": ""},
                },
                {
                    "id": "web_search",
                    "type": "web_search",
                    "label": "🔍 Google Search (HTTP)",
                    "config": {},
                },
                {
                    "id": "ai_summarize",
                    "type": "model_agent",
                    "label": "🤖 AI Tóm tắt",
                    "config": {
                        "provider": "auto",
                        "system_prompt": "Bạn là trợ lý AI. Người dùng đã tìm kiếm Google, dưới đây là kết quả. Hãy tóm tắt ngắn gọn, rõ ràng bằng ngôn ngữ của người dùng. Nếu có thông tin thời tiết, tin tức, hoặc dữ liệu cụ thể, hãy trình bày rõ ràng. Trả lời tự nhiên, thân thiện.",
                        "max_tokens": 1024,
                        "temperature": 0.5,
                    },
                },
                {
                    "id": "result_output",
                    "type": "output",
                    "label": "📤 Kết quả",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "search_query",
                    "from_port_id": "content",
                    "to_node_id": "web_search",
                    "to_port_id": "query",
                },
                {
                    "from_node_id": "web_search",
                    "from_port_id": "results",
                    "to_node_id": "ai_summarize",
                    "to_port_id": "prompt",
                },
                {
                    "from_node_id": "ai_summarize",
                    "from_port_id": "response",
                    "to_node_id": "result_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "📧 Gmail Login",
        "description": "Mở trình duyệt và yêu cầu AI tự động truy cập Gmail để đăng nhập hoặc kiểm tra hòm thư.",
        "skill_type": "Skill",
        "commands": ["gmail login", "đăng nhập gmail", "check mail", "vào gmail", "login gmail",
                     "mở gmail", "vào mail", "check gmail", "đăng nhập mail"],
        "workflow_data": {
            "name": "Gmail Login",
            "nodes": [
                {
                    "id": "browser_login",
                    "type": "browser_action",
                    "label": "📧 Login Gmail",
                    "config": {
                        "action": "run_prompt",
                        "profile_name": "default",
                        "prompt": "Go to https://gmail.com and log in using saved credentials, or tell me there is no saved credential.",
                        "headless": False
                    },
                },
                {
                    "id": "result_output",
                    "type": "output",
                    "label": "📤 Output",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "browser_login",
                    "from_port_id": "result",
                    "to_node_id": "result_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "👥 Quick Team Creator",
        "description": "Tạo team AI tự động: mô tả team bằng ngôn ngữ tự nhiên → AI phân tích → tạo agents + cấu trúc team + sơ đồ tổ chức. VD: 'tạo team developer 4 người: 1 leader, 2 dev, 1 tester'",
        "skill_type": "Skill",
        "commands": [
            "tạo team", "create team", "tạo nhóm", "tạo đội",
            "build team", "new team", "thành lập team", "xây dựng team",
            "tạo team mới", "lập team"
        ],
        "workflow_data": {
            "name": "Quick Team Creator",
            "nodes": [
                {
                    "id": "team_desc",
                    "type": "text_input",
                    "label": "📝 Mô tả Team",
                    "config": {"text": ""},
                },
                {
                    "id": "build_body",
                    "type": "python_code",
                    "label": "🐍 Build API Body",
                    "config": {
                        "code": "import json\nresult = json.dumps({'description': text_input, 'provider': 'gemini', 'model': 'gemini-2.5-flash'})"
                    },
                },
                {
                    "id": "create_api",
                    "type": "api_request",
                    "label": "⚡ Gọi API tạo Team",
                    "config": {
                        "url": "http://localhost:5295/api/v1/studio3d/quick-team",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                },
                {
                    "id": "result_output",
                    "type": "output",
                    "label": "📤 Kết quả",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "team_desc",
                    "from_port_id": "content",
                    "to_node_id": "build_body",
                    "to_port_id": "text_input",
                },
                {
                    "from_node_id": "build_body",
                    "from_port_id": "result",
                    "to_node_id": "create_api",
                    "to_port_id": "body",
                },
                {
                    "from_node_id": "create_api",
                    "from_port_id": "response",
                    "to_node_id": "result_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "📥 Douyin/TikTok Downloader",
        "description": "Tải video chuyên biệt từ TikTok/Douyin không logo bằng Douyin Downloader API. AI tự tải và gửi file. Dùng: gửi link TikTok hoặc Douyin.",
        "skill_type": "Skill",
        "commands": [
            "tải video tiktok", "download tiktok", "tải tiktok", 
            "tải douyin", "download douyin", "tải video douyin",
        ],
        "workflow_data": {
            "name": "Douyin/TikTok Downloader",
            "nodes": [
                {
                    "id": "video_url",
                    "type": "text_input",
                    "label": "🔗 Video URL",
                    "config": {"text": ""},
                },
                {
                    "id": "parse_video",
                    "type": "api_request",
                    "label": "🔍 Parse Video Info",
                    "config": {
                        "url": "http://localhost:5295/api/v1/douyin_downloader/parse",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                },
                {
                    "id": "download_video",
                    "type": "api_request",
                    "label": "📥 Download Video",
                    "config": {
                        "url": "http://localhost:5295/api/v1/douyin_downloader/download",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                },
                {
                    "id": "result_output",
                    "type": "output",
                    "label": "📤 Kết quả",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "video_url",
                    "from_port_id": "content",
                    "to_node_id": "parse_video",
                    "to_port_id": "body",
                },
                {
                    "from_node_id": "parse_video",
                    "from_port_id": "response",
                    "to_node_id": "download_video",
                    "to_port_id": "body",
                },
                {
                    "from_node_id": "download_video",
                    "from_port_id": "response",
                    "to_node_id": "result_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "🌍 Universal Video Downloader",
        "description": "Tải video đa nền tảng (YouTube, Facebook, Twitter/X...) sử dụng yt-dlp. AI tự động tải và gửi file. Dùng: gửi link kèm dòng lệnh 'tải youtube' hoặc 'tải video'.",
        "skill_type": "Skill",
        "commands": [
            "tải youtube", "download youtube", "tải video", "download video",
            "tải facebook", "tải twitter", "tải đa nền tảng", "tải video youtube"
        ],
        "workflow_data": {
            "name": "Universal Video Downloader",
            "nodes": [
                {
                    "id": "video_url",
                    "type": "text_input",
                    "label": "🔗 Video URL",
                    "config": {"text": ""},
                },
                {
                    "id": "parse_video",
                    "type": "api_request",
                    "label": "🔍 Lấy thông tin video",
                    "config": {
                        "url": "http://localhost:5295/api/v1/ytdl/info",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                },
                {
                    "id": "download_video",
                    "type": "api_request",
                    "label": "📥 Tải xuống (yt-dlp)",
                    "config": {
                        "url": "http://localhost:5295/api/v1/ytdl/download",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                },
                {
                    "id": "result_output",
                    "type": "output",
                    "label": "📤 Kết quả",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "video_url",
                    "from_port_id": "content",
                    "to_node_id": "parse_video",
                    "to_port_id": "body",
                },
                {
                    "from_node_id": "parse_video",
                    "from_port_id": "response",
                    "to_node_id": "download_video",
                    "to_port_id": "body",
                },
                {
                    "from_node_id": "download_video",
                    "from_port_id": "response",
                    "to_node_id": "result_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "📅 Calendar Scheduler",
        "description": "Lập lịch sự kiện Google Calendar — hỗ trợ recurring events cho livestream hằng ngày, meeting, reminder. Dùng: tubecli skill run 'Calendar Scheduler' --input 'Meeting tomorrow 10am'",
        "skill_type": "Skill",
        "commands": [
            "lập lịch", "tạo lịch", "schedule", "create event",
            "thêm sự kiện", "đặt lịch", "lịch hẹn", "lên lịch livestream",
            "nhắc nhở", "reminder", "đặt hẹn", "lịch họp",
        ],
        "workflow_data": {
            "name": "Calendar Scheduler",
            "nodes": [
                {
                    "id": "event_input",
                    "type": "text_input",
                    "label": "📝 Event Description",
                    "config": {"text": ""},
                },
                {
                    "id": "google_auth",
                    "type": "google_auth",
                    "label": "🔐 Google Auth",
                    "config": {
                        "scopes": "https://www.googleapis.com/auth/calendar",
                    },
                },
                {
                    "id": "calendar_create",
                    "type": "google_calendar",
                    "label": "📅 Create Event",
                    "config": {"action": "quick_add"},
                },
                {
                    "id": "result_output",
                    "type": "output",
                    "label": "📤 Result",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "google_auth",
                    "from_port_id": "credentials",
                    "to_node_id": "calendar_create",
                    "to_port_id": "credentials",
                },
                {
                    "from_node_id": "event_input",
                    "from_port_id": "content",
                    "to_node_id": "calendar_create",
                    "to_port_id": "event_data",
                },
                {
                    "from_node_id": "calendar_create",
                    "from_port_id": "status",
                    "to_node_id": "result_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "🔴 Livestream Restreamer",
        "description": "Tạo phiên livestream (restream) từ link Douyin/TikTok lên YouTube. Dùng khi user yêu cầu: 'tạo phiên live', 'restream'. Cứ thấy douyin link kèm 'tạo live' thì dùng skill này KHÔNG dùng downloader.",
        "skill_type": "Skill",
        "commands": [
            "tạo phiên live", "tạo phiên livestream", "restream", "phát live", "phát trực tiếp"
        ],
        "workflow_data": {
            "name": "Livestream Restreamer",
            "nodes": [
                {
                    "id": "input_cmd",
                    "type": "text_input",
                    "label": "📝 Đầu vào",
                    "config": {"text": ""},
                },
                {
                    "id": "exec_live",
                    "type": "python_code",
                    "label": "🐍 Run Live API",
                    "config": {
                        "code": "import requests, re, json\n# text_input contains the whole user command\nlink_match = re.search(r'https?://[^\\s]+', text_input)\nlink = link_match.group(0) if link_match else ''\nemail_match = re.search(r'[\\w\\.-]+@[\\w\\.-]+\\.\\w+', text_input)\nemail = email_match.group(0) if email_match else ''\n\npayload = {'title': 'Live Restream', 'input_source': link}\nif email:\n    payload['token_id'] = email\nelse:\n    payload['token_id'] = ''\n\ntry:\n    resp = requests.post('http://localhost:5295/api/v1/livestream/auto-live', json=payload, timeout=30)\n    if resp.status_code == 200:\n        r_data = resp.json()\n        if r_data.get('status') == 'success':\n            result = f\"✅ Tạo phiên Live thành công!\\n🔗 Link phát: {link}\\n📺 Stream Key: {r_data.get('broadcast', {}).get('stream_key')}\\nID phiên: {r_data.get('ffmpeg_session_id')}\"\n        else:\n            result = f\"❌ Lỗi tạo live: {r_data.get('message', 'Không rõ lỗi')}\"\n    else:\n        result = f\"❌ Lỗi hệ thống ({resp.status_code}): {resp.text}\"\nexcept Exception as e:\n    result = f\"❌ Exception: {str(e)}\"\n"
                    },
                },
                {
                    "id": "result_output",
                    "type": "output",
                    "label": "📤 Kết quả",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "input_cmd",
                    "from_port_id": "content",
                    "to_node_id": "exec_live",
                    "to_port_id": "text_input",
                },
                {
                    "from_node_id": "exec_live",
                    "from_port_id": "result",
                    "to_node_id": "result_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "🕷️ Web Crawler & Watcher",
        "description": "Cào dữ liệu từ một trang web, lấy nội dung bài viết, tiêu đề, ảnh. Hoặc thiết lập theo dõi trang liên tục. Dùng: nhập URL cần cào.",
        "skill_type": "Extension",
        "commands": ["cào dữ liệu", "scrape", "đọc web", "crawl", "theo dõi trang", "watch page"],
        "workflow_data": {
            "name": "Web Crawler",
            "nodes": [
                {
                    "id": "input_cmd",
                    "type": "text_input",
                    "label": "📝 Lệnh (URL hoặc Yêu cầu)",
                    "config": {"text": ""}
                },
                {
                    "id": "web_scrape",
                    "type": "api_request",
                    "label": "🕸️ Scrape URL",
                    "config": {
                        "url": "http://localhost:5295/api/v1/web_crawler/scrape",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"}
                    }
                },
                {
                    "id": "result_output",
                    "type": "output",
                    "label": "📤 Kết quả",
                    "config": {"print": True}
                }
            ],
            "connections": [
                {
                    "from_node_id": "input_cmd",
                    "from_port_id": "content",
                    "to_node_id": "web_scrape",
                    "to_port_id": "body"
                },
                {
                    "from_node_id": "web_scrape",
                    "from_port_id": "response",
                    "to_node_id": "result_output",
                    "to_port_id": "data"
                }
            ]
        }
    }
]


def register_default_skills():
    """Register default skills if not already present."""
    try:
        from tubecli.core.skill import skill_manager

        existing = {s.name: s for s in skill_manager.get_all()}
        added = 0

        # Resolve current base URL to replace hardcoded localhost:5295
        base_url = _base_url()

        for skill_def in DEFAULT_SKILLS:
            name = skill_def["name"]
            if name not in existing:
                import copy, json
                wf = copy.deepcopy(skill_def["workflow_data"])
                # Replace hardcoded URLs in workflow nodes
                wf_json = json.dumps(wf)
                wf_json = wf_json.replace("http://localhost:5295", base_url)
                wf = json.loads(wf_json)

                skill_manager.create(
                    name=name,
                    workflow_data=wf,
                    skill_type=skill_def.get("skill_type", "Skill"),
                    description=skill_def.get("description", ""),
                    commands=skill_def.get("commands", []),
                )
                added += 1
                print(f"  ✅ Added skill: {name}")

        if added > 0:
            print(f"  📦 Registered {added} default skills")
        else:
            print(f"  ✓ All {len(DEFAULT_SKILLS)} default skills already installed")

    except Exception as e:
        print(f"  ❌ Error registering skills: {e}")
