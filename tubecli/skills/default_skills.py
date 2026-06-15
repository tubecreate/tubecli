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
            "create sheet", "new spreadsheet", "read sheet", "read google sheet", "write sheet", "append sheet", "sync sheet", "sync data to sheet",
        ],
        "workflow_data": {"nodes": [], "connections": []},
    },
    {
        "name": "🔍 Google Search",
        "description": "Quick Google Search via HTTP + AI summary of results. No browser required. Usage: tubecli skill run 'Google Search' --input 'keyword'",
        "skill_type": "Skill",
        "commands": [
            "google search", "search google",
        ],
        "workflow_data": {
            "name": "Google Search",
            "nodes": [
                {
                    "id": "search_query",
                    "type": "text_input",
                    "label": "🔍 Search Keyword",
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
                    "label": "🤖 AI Summarizer",
                    "config": {
                        "provider": "auto",
                        "system_prompt": "You are an AI assistant. The user has performed a Google search, and the results are below. Please summarize them briefly and clearly in the user's language. If there is weather information, news, or specific data, present it clearly. Answer naturally and in a friendly manner.",
                        "max_tokens": 1024,
                        "temperature": 0.5,
                    },
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
        "description": "Open browser and ask AI to automatically access Gmail to log in or check the inbox.",
        "skill_type": "Skill",
        "commands": ["gmail login", "check mail", "login gmail", "check gmail"],
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
        "description": "Create AI team automatically: describe team in natural language → AI analyzes → creates agents + team structure + org chart. Ex: 'create a developer team of 4: 1 leader, 2 devs, 1 tester'",
        "skill_type": "Skill",
        "commands": [
            "create team", "build team", "new team"
        ],
        "workflow_data": {
            "name": "Quick Team Creator",
            "nodes": [
                {
                    "id": "team_desc",
                    "type": "text_input",
                    "label": "📝 Team Description",
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
                    "label": "⚡ Call Create Team API",
                    "config": {
                        "url": "http://localhost:5295/api/v1/studio3d/quick-team",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
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
        "description": "Dedicated video downloader for TikTok/Douyin without watermark using Douyin Downloader API. AI auto-downloads and sends the file. Usage: send TikTok or Douyin link.",
        "skill_type": "Skill",
        "commands": [
            "download tiktok", "download douyin",
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
                    "label": "📤 Result",
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
        "description": "Multi-platform video downloader (YouTube, Facebook, Twitter/X...) using yt-dlp. AI auto-downloads and sends the file. Usage: send link with command 'download youtube' or 'download video'.",
        "skill_type": "Skill",
        "commands": [
            "download youtube", "download video", "download facebook", "download twitter", "cross-platform download"
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
                    "label": "🔍 Get Video Info",
                    "config": {
                        "url": "http://localhost:5295/api/v1/ytdl/info",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                },
                {
                    "id": "download_video",
                    "type": "api_request",
                    "label": "📥 Download (yt-dlp)",
                    "config": {
                        "url": "http://localhost:5295/api/v1/ytdl/download",
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
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
        "description": "Schedule Google Calendar events — supports recurring events for daily livestreams, meetings, reminders. Usage: tubecli skill run 'Calendar Scheduler' --input 'Meeting tomorrow 10am'",
        "skill_type": "Skill",
        "commands": [
            "schedule", "create event", "add event", "book appointment", "set reminder",
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
        "description": "Create a livestream session (restream) from a Douyin/TikTok link to YouTube. Use when user asks to 'restream' or 'start live'. If you see a douyin link with 'start live', use this skill, NOT the downloader.",
        "skill_type": "Skill",
        "commands": [
            "create live session", "start livestream", "restream", "broadcast live"
        ],
        "workflow_data": {
            "name": "Livestream Restreamer",
            "nodes": [
                {
                    "id": "input_cmd",
                    "type": "text_input",
                    "label": "📝 Input",
                    "config": {"text": ""},
                },
                {
                    "id": "exec_live",
                    "type": "python_code",
                    "label": "🐍 Run Live API",
                    "config": {
                        "code": "import requests, re, json\n# text_input contains the whole user command\nlink_match = re.search(r'https?://[^\\s]+', text_input)\nlink = link_match.group(0) if link_match else ''\nemail_match = re.search(r'[\\w\\.-]+@[\\w\\.-]+\\.\\w+', text_input)\nemail = email_match.group(0) if email_match else ''\n\npayload = {'title': 'Live Restream', 'input_source': link}\nif email:\n    payload['token_id'] = email\nelse:\n    payload['token_id'] = ''\n\ntry:\n    resp = requests.post('http://localhost:5295/api/v1/livestream/auto-live', json=payload, timeout=30)\n    if resp.status_code == 200:\n        r_data = resp.json()\n        if r_data.get('status') == 'success':\n            result = f\"✅ Live session created successfully!\\n🔗 Stream Link: {link}\\n📺 Stream Key: {r_data.get('broadcast', {}).get('stream_key')}\\nSession ID: {r_data.get('ffmpeg_session_id')}\"\n        else:\n            result = f\"❌ Error creating live: {r_data.get('message', 'Unknown error')}\"\n    else:\n        result = f\"❌ System error ({resp.status_code}): {resp.text}\"\nexcept Exception as e:\n    result = f\"❌ Exception: {str(e)}\"\n"
                    },
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
        "description": "Crawl data from a website, extract article content, titles, images. Or set up continuous page monitoring. Usage: enter the URL to crawl.",
        "skill_type": "Extension",
        "commands": ["scrape", "crawl", "watch page", "scrape website"],
        "workflow_data": {
            "name": "Web Crawler",
            "nodes": [
                {
                    "id": "input_cmd",
                    "type": "text_input",
                    "label": "📝 Command (URL or Request)",
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
                    "label": "📤 Result",
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
        from tubecli.config import get_language

        existing = {s.name: s for s in skill_manager.get_all()}
        added = 0

        # Resolve current base URL to replace hardcoded localhost:5295
        base_url = _base_url()
        lang = get_language()

        translations = {
            "vi": {
                "📊 Google Sheets": {
                    "description": "Quản lý Google Sheets toàn diện: Tạo Sheet mới, Đọc dữ liệu, Ghi/Append dữ liệu, Đồng bộ metadata. Dùng: tubecli skill run \"Google Sheets\"",
                    "commands": ["create sheet", "new spreadsheet", "read sheet", "read google sheet", "write sheet", "append sheet", "sync sheet", "sync data to sheet"],
                },
                "🔍 Google Search": {
                    "description": "Tìm kiếm Google nhanh bằng HTTP + AI tóm tắt kết quả. Không cần mở browser. Dùng: tubecli skill run 'Google Search' --input 'từ khóa'",
                    "commands": ["google search", "tìm kiếm google", "search google", "tìm google"],
                },
                "📧 Gmail Login": {
                    "description": "Mở trình duyệt và yêu cầu AI tự động truy cập Gmail để đăng nhập hoặc kiểm tra hộp thư.",
                    "commands": ["gmail login", "đăng nhập gmail", "vào mail", "login gmail", "mở gmail", "vào gmail", "check gmail", "đăng nhập mail"],
                },
                "👥 Quick Team Creator": {
                    "description": "Tạo team AI tự động: mô tả team bằng ngôn ngữ tự nhiên -> AI phân tích -> tạo agents + cấu trúc team + sơ đồ tổ chức. VD: 'tạo team developer 4 người: 1 leader, 2 dev, 1 tester'",
                    "commands": ["tạo team", "create team", "tạo nhóm", "tạo đội", "build team", "new team", "thành lập team", "xây dựng team", "tạo team mới", "lập team"],
                },
                "📥 Douyin/TikTok Downloader": {
                    "description": "Tải video chuyên biệt từ TikTok/Douyin không logo bằng Douyin Downloader API. AI tự tải và gửi file. Dùng: gửi link TikTok hoặc Douyin.",
                    "commands": ["tải video tiktok", "download tiktok", "tải tiktok", "tải douyin", "download douyin", "tải video douyin"],
                },
                "🌍 Universal Video Downloader": {
                    "description": "Tải video đa nền tảng (YouTube, Facebook, Twitter/X...) sử dụng yt-dlp. AI tự động tải và gửi file. Dùng: gửi link kèm dòng lệnh 'tải youtube' hoặc 'tải video'.",
                    "commands": ["tải youtube", "download youtube", "tải video", "download video", "tải facebook", "download facebook", "tải twitter", "tải đa nền tảng", "tải video youtube"],
                },
                "📅 Calendar Scheduler": {
                    "description": "Lập lịch sự kiện Google Calendar – hỗ trợ recurring events cho livestream hàng ngày, meeting, reminder. Dùng: tubecli skill run \"Calendar Scheduler\" --input \"Meeting tomorrow 10am\"",
                    "commands": ["lập lịch", "tạo lịch", "schedule", "create event", "thêm sự kiện", "đặt lịch", "lịch hẹn", "lên lịch livestream", "nhắc nhở", "reminder", "đặt hẹn", "lịch họp"],
                },
                "🔴 Livestream Restreamer": {
                    "description": "Tạo phiên livestream (restream) từ link Douyin/TikTok lên YouTube. Dùng khi user yêu cầu: 'tạo phiên live', 'restream'. Cứ thấy douyin link kèm 'tạo live' thì dùng skill này KHÔNG dùng downloader.",
                    "commands": ["tạo phiên live", "restream", "phát live", "phát trực tiếp"],
                },
                "🕷️ Web Crawler & Watcher": {
                    "description": "Cào dữ liệu từ một trang web, lấy nội dung bài viết, tiêu đề, ảnh. Hoặc thiết lập theo dõi trang liên tục. Dùng: nhập URL cần cào.",
                    "commands": ["cào dữ liệu", "scrape", "đọc web", "crawl", "theo dõi trang", "watch page"],
                }
            },
            "en": {
                "📊 Google Sheets": {
                    "description": "Comprehensive Google Sheets management: Create new Sheet, Read data, Write/Append data, Sync metadata. Usage: tubecli skill run \"Google Sheets\"",
                    "commands": ["create sheet", "new spreadsheet", "read sheet", "read google sheet", "write sheet", "append sheet", "sync sheet", "sync data to sheet"],
                },
                "🔍 Google Search": {
                    "description": "Quick Google Search via HTTP + AI summary of results. No browser required. Usage: tubecli skill run 'Google Search' --input 'keyword'",
                    "commands": ["google search", "search google"],
                },
                "📧 Gmail Login": {
                    "description": "Open browser and ask AI to automatically access Gmail to log in or check the inbox.",
                    "commands": ["gmail login", "check mail", "login gmail", "check gmail"],
                },
                "👥 Quick Team Creator": {
                    "description": "Create AI team automatically: describe team in natural language -> AI analyzes -> creates agents + team structure + org chart. Ex: 'create a developer team of 4: 1 leader, 2 devs, 1 tester'",
                    "commands": ["create team", "build team", "new team"],
                },
                "📥 Douyin/TikTok Downloader": {
                    "description": "Dedicated video downloader for TikTok/Douyin without watermark using Douyin Downloader API. AI auto-downloads and sends the file. Usage: send TikTok or Douyin link.",
                    "commands": ["download tiktok", "download douyin"],
                },
                "🌍 Universal Video Downloader": {
                    "description": "Multi-platform video downloader (YouTube, Facebook, Twitter/X...) using yt-dlp. AI auto-downloads and sends the file. Usage: send link with command 'download youtube' or 'download video'.",
                    "commands": ["download youtube", "download video", "download facebook", "download twitter", "cross-platform download"],
                },
                "📅 Calendar Scheduler": {
                    "description": "Schedule Google Calendar events — supports recurring events for daily livestreams, meetings, reminders. Usage: tubecli skill run 'Calendar Scheduler' --input 'Meeting tomorrow 10am'",
                    "commands": ["schedule", "create event", "add event", "book appointment", "set reminder"],
                },
                "🔴 Livestream Restreamer": {
                    "description": "Create a livestream session (restream) from a Douyin/TikTok link to YouTube. Use when user asks to 'restream' or 'start live'. If you see a douyin link with 'start live', use this skill, NOT the downloader.",
                    "commands": ["create live session", "start livestream", "restream", "broadcast live"],
                },
                "🕷️ Web Crawler & Watcher": {
                    "description": "Crawl data from a website, extract article content, titles, images. Or set up continuous page monitoring. Usage: enter the URL to crawl.",
                    "commands": ["scrape", "crawl", "watch page", "scrape website"],
                }
            }
        }

        for skill_def in DEFAULT_SKILLS:
            name = skill_def["name"]
            import copy, json
            wf = copy.deepcopy(skill_def["workflow_data"])
            # Replace hardcoded URLs in workflow nodes
            wf_json = json.dumps(wf)
            wf_json = wf_json.replace("http://localhost:5295", base_url)
            wf = json.loads(wf_json)

            # Fallback to defaults in code
            desc = skill_def.get("description", "")
            cmds = skill_def.get("commands", [])

            # Select translation if exists
            if lang in translations and name in translations[lang]:
                desc = translations[lang][name].get("description", desc)
                cmds = translations[lang][name].get("commands", cmds)

            if name not in existing:
                skill_manager.create(
                    name=name,
                    workflow_data=wf,
                    skill_type=skill_def.get("skill_type", "Skill"),
                    description=desc,
                    commands=cmds,
                )
                added += 1
                print(f"  ✅ Added skill: {name}")
            else:
                existing_skill = existing[name]
                skill_manager.update(
                    existing_skill.id,
                    description=desc,
                    commands=cmds,
                    workflow_data=wf,
                )
                # Check if it actually changed to log it
                if existing_skill.description != desc or existing_skill.commands != cmds:
                    logger_msg = f"Updated default skill '{name}' to lang '{lang}'"
                    # Try to log it or print it
                    print(f"  ⚡ Updated skill: {name} ({lang})")

        if added > 0:
            print(f"  📦 Registered {added} default skills")
        else:
            print(f"  ✓ All {len(DEFAULT_SKILLS)} default skills synced/installed")

    except Exception as e:
        print(f"  ❌ Error registering skills: {e}")
