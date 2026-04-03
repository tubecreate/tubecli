"""
Default Skills — Pre-built workflow templates that auto-register.
These are the starting skills available in every TubeCLI installation.
"""
from typing import List, Dict

DEFAULT_SKILLS: List[Dict] = [
    {
        "name": "🧠 AI Summarizer",
        "description": "Input text → AI tóm tắt → output. Dùng: tubecli skill run 'AI Summarizer' --input 'text'",
        "skill_type": "Skill",
        "workflow_data": {
            "name": "AI Summarizer",
            "nodes": [
                {
                    "id": "input_text",
                    "type": "text_input",
                    "label": "📝 Input",
                    "config": {"text": ""},
                },
                {
                    "id": "ai_summarize",
                    "type": "ai_node",
                    "label": "🧠 AI Summarizer",
                    "config": {
                        "model": "qwen:latest",
                        "system_prompt": "Summarize the following text concisely.",
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
                    "from_node_id": "input_text",
                    "from_port_id": "content",
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
        "name": "📋 Data Collector",
        "description": "API request → parse JSON → save to file. Dùng: tubecli skill run 'Data Collector'",
        "skill_type": "Skill",
        "workflow_data": {
            "name": "Data Collector",
            "nodes": [
                {
                    "id": "api_fetch",
                    "type": "api_request",
                    "label": "🌐 Fetch API",
                    "config": {"url": "", "method": "GET"},
                },
                {
                    "id": "save_output",
                    "type": "output",
                    "label": "📤 Save",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "api_fetch",
                    "from_port_id": "response",
                    "to_node_id": "save_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "📊 Report Generator",
        "description": "Collect data → AI format → save report. Dùng: tubecli skill run 'Report Generator'",
        "skill_type": "Skill",
        "workflow_data": {
            "name": "Report Generator",
            "nodes": [
                {
                    "id": "data_input",
                    "type": "text_input",
                    "label": "📝 Data Input",
                    "config": {"text": ""},
                },
                {
                    "id": "ai_format",
                    "type": "ai_node",
                    "label": "🧠 AI Formatter",
                    "config": {
                        "system_prompt": "Format the following data into a structured report.",
                    },
                },
                {
                    "id": "report_output",
                    "type": "output",
                    "label": "📤 Report",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "data_input",
                    "from_port_id": "content",
                    "to_node_id": "ai_format",
                    "to_port_id": "prompt",
                },
                {
                    "from_node_id": "ai_format",
                    "from_port_id": "response",
                    "to_node_id": "report_output",
                    "to_port_id": "data",
                },
            ],
        },
    },
    {
        "name": "🔄 Batch Command Runner",
        "description": "Loop through commands → execute → log results. Dùng: tubecli skill run 'Batch Command Runner'",
        "skill_type": "Skill",
        "workflow_data": {
            "name": "Batch Command Runner",
            "nodes": [
                {
                    "id": "cmd_list",
                    "type": "text_input",
                    "label": "📝 Commands",
                    "config": {"text": "echo Hello\necho World"},
                },
                {
                    "id": "loop_cmds",
                    "type": "loop",
                    "label": "🔄 Loop",
                    "config": {},
                },
                {
                    "id": "exec_cmd",
                    "type": "run_command",
                    "label": "💻 Execute",
                    "config": {},
                },
                {
                    "id": "batch_output",
                    "type": "output",
                    "label": "📤 Results",
                    "config": {"print": True},
                },
            ],
            "connections": [
                {
                    "from_node_id": "cmd_list",
                    "from_port_id": "lines",
                    "to_node_id": "loop_cmds",
                    "to_port_id": "items",
                },
                {
                    "from_node_id": "loop_cmds",
                    "from_port_id": "current_item",
                    "to_node_id": "exec_cmd",
                    "to_port_id": "command",
                },
                {
                    "from_node_id": "exec_cmd",
                    "from_port_id": "stdout",
                    "to_node_id": "batch_output",
                    "to_port_id": "data",
                },
            ],
        },
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
        "commands": ["gmail login", "đăng nhập gmail", "check mail", "vào gmail", "login gmail"],
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
        "name": "📥 Video Downloader",
        "description": "Tải video từ TikTok/Douyin bằng cách gọi Downloader API. AI tự tải và gửi file. Dùng: gửi link TikTok hoặc Douyin.",
        "skill_type": "Skill",
        "commands": [
            "tải video", "download video", "tải về", "download",
            "tải tiktok", "tải douyin", "download tiktok", "download douyin",
            "lấy video", "get video", "tải file", "download file",
        ],
        "workflow_data": {
            "name": "Video Downloader",
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
                        "url": "http://localhost:5295/api/v1/downloader/parse",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                },
                {
                    "id": "download_video",
                    "type": "api_request",
                    "label": "📥 Download Video",
                    "config": {
                        "url": "http://localhost:5295/api/v1/downloader/download",
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
    }
]


def register_default_skills():
    """Register default skills if not already present."""
    try:
        from tubecli.core.skill import skill_manager

        existing = {s.name: s for s in skill_manager.get_all()}
        added = 0

        for skill_def in DEFAULT_SKILLS:
            name = skill_def["name"]
            if name not in existing:
                skill_manager.create(
                    name=name,
                    workflow_data=skill_def["workflow_data"],
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
