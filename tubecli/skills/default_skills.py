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
        "name": "🌐 Google Search",
        "description": "Tự động mở trình duyệt, tìm kiếm Google theo từ khóa và trích xuất kết quả bằng AI. Dùng: tubecli skill run 'Google Search' --input 'Tìm kiếm về AI'",
        "skill_type": "Skill",
        "commands": [
            "google search", "tìm kiếm google", "search google", "tìm video", "tìm google",
            "tìm", "tra cứu", "search", "tìm kiếm", "tra"
        ],
        "workflow_data": {
            "name": "Google Search",
            "nodes": [
                {
                    "id": "search_query",
                    "type": "text_input",
                    "label": "🔍 Từ khóa",
                    "config": {"text": "Tin tức AI mới nhất hôm nay"},
                },
                {
                    "id": "browser_search",
                    "type": "browser_action",
                    "label": "🌐 Browser Agent",
                    "config": {
                        "action": "run_prompt",
                        "profile_name": "default",
                        "prompt": "Go to Google, search for: {{input}}, and then summarize the top results you see.",
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
                    "from_node_id": "search_query",
                    "from_port_id": "content",
                    "to_node_id": "browser_search",
                    "to_port_id": "prompt",
                },
                {
                    "from_node_id": "browser_search",
                    "from_port_id": "result",
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
                )
                added += 1
                print(f"  ✅ Added skill: {name}")

        if added > 0:
            print(f"  📦 Registered {added} default skills")
        else:
            print(f"  ✓ All {len(DEFAULT_SKILLS)} default skills already installed")

    except Exception as e:
        print(f"  ❌ Error registering skills: {e}")
