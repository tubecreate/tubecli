"""Built-in node: Browser Action — uses TubeCLI browser profile system.
Auto-reads browser profile and AI model from Global Settings."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import asyncio
import os
import json as _json


class BrowserNode(BaseNode):
    node_type = "browser_action"
    display_name = "🌐 Browser Action"
    description = "Launch browser with a profile and perform actions (navigate, AI prompt, screenshot). Auto-reads profile and AI model from Settings."
    icon = "🌐"
    category = "Browser"

    def _setup_ports(self):
        self.add_input("url", PortType.TEXT, "URL to navigate to", required=False)
        self.add_input("prompt", PortType.TEXT, "AI prompt for browser agent", required=False)
        self.add_input("data", PortType.ANY, "Additional data", required=False)
        self.add_output("result", PortType.TEXT, "Action result / extracted data")
        self.add_output("screenshot_path", PortType.TEXT, "Screenshot file path")
        self.add_output("status", PortType.TEXT, "Execution status")

    def _resolve_settings(self):
        """Read browser profile and AI model from Global Settings, with fallbacks."""
        from tubecli.config import get_setting, DATA_DIR

        # 1. Browser profile: node config → settings.json → fallback
        profile_name = self.config.get("profile_name", "")
        if not profile_name or profile_name == "default":
            profile_name = get_setting("default_browser_profile", "")

        # 2. AI model: node config → global_settings.json → default
        ai_model = self.config.get("ai_model", "")
        if not ai_model:
            global_settings_file = os.path.join(str(DATA_DIR), "global_settings.json")
            if os.path.exists(global_settings_file):
                try:
                    with open(global_settings_file, "r", encoding="utf-8") as f:
                        gs = _json.load(f)
                        ai_model = gs.get("default_model", "")
                except Exception:
                    pass
            if not ai_model:
                ai_model = "qwen:latest"

        return profile_name, ai_model

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        action = self.config.get("action", "navigate")
        url = inputs.get("url") or self.config.get("url", "")
        headless = self.config.get("headless", False)
        wait_seconds = int(self.config.get("wait_seconds", 10))

        # Merge user query with config prompt:
        # - If config has a detailed prompt (instructions), prepend user query as context
        # - If no config prompt, use input prompt directly
        user_query = inputs.get("prompt", "")
        config_prompt = self.config.get("prompt", "")
        
        if config_prompt and user_query and user_query != config_prompt:
            # Config has step-by-step instructions, prepend user's actual query
            if "{{input}}" in config_prompt:
                prompt = config_prompt.replace("{{input}}", user_query)
            else:
                prompt = f'Search query: "{user_query}"\n\n{config_prompt}'
        else:
            prompt = user_query or config_prompt

        # Auto-resolve profile + AI model from settings
        profile_name, ai_model = self._resolve_settings()

        try:
            from process_manager import browser_process_manager
            from profile_manager import get_profile, list_profiles

            # Verify profile, fallback to first available
            profile = get_profile(profile_name) if profile_name else None
            if not profile:
                all_profiles = list_profiles()
                if all_profiles:
                    profile_name = all_profiles[0]["name"]
                    profile = get_profile(profile_name)
                else:
                    return {
                        "result": "", "screenshot_path": "",
                        "status": "Error: No browser profiles available. Please create one in Settings.",
                    }

            if not profile:
                return {
                    "result": "", "screenshot_path": "",
                    "status": f"Error: Profile '{profile_name}' not found",
                }

            print(f"  [BrowserNode] profile={profile_name} model={ai_model} action={action} headless={headless}")

            if action == "navigate":
                result = browser_process_manager.spawn(
                    profile=profile_name,
                    prompt=f'Go to "{url}"' if url else "",
                    headless=headless,
                    manual=not bool(url and prompt),
                    ai_model=ai_model,
                    url=url,
                )
                await asyncio.sleep(wait_seconds)
                status_info = browser_process_manager.get_status(result.get("instance_id", ""))
                return {
                    "result": str(status_info),
                    "screenshot_path": "",
                    "status": f"✅ Navigated to {url}" if url else "✅ Browser launched",
                }

            elif action == "run_prompt":
                if not prompt:
                    return {"result": "", "screenshot_path": "", "status": "Error: No prompt for run_prompt action"}

                result = browser_process_manager.spawn(
                    profile=profile_name,
                    prompt=prompt,
                    headless=headless,
                    manual=False,
                    ai_model=ai_model,
                    url=url,
                )

                instance_id = result.get("instance_id", "")
                log_file = result.get("log_file", "")

                # Poll for completion (up to 3 minutes)
                max_wait = 180
                waited = 0
                status_info = result

                while waited < max_wait:
                    await asyncio.sleep(3)
                    waited += 3
                    status_info = browser_process_manager.get_status(instance_id) or {}
                    if status_info.get("status") in ["completed", "error", "terminated"]:
                        break

                # Extract summary from logs
                final_result = "Action completed, but no summary was found in browser logs."
                if log_file and os.path.exists(log_file):
                    try:
                        with open(log_file, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                            for line in reversed(lines):
                                if "RESULT_SUMMARY:" in line:
                                    final_result = line.split("RESULT_SUMMARY:")[1].strip()
                                    break
                    except Exception as e:
                        final_result = f"Error reading logs: {e}"

                return {
                    "result": final_result,
                    "screenshot_path": "",
                    "status": f"✅ AI Task: {status_info.get('status', 'unknown')}",
                }

            elif action == "manual":
                result = browser_process_manager.spawn(
                    profile=profile_name,
                    headless=headless,
                    manual=True,
                    ai_model=ai_model,
                )
                return {
                    "result": str(result),
                    "screenshot_path": "",
                    "status": "✅ Manual browser launched",
                }

            else:
                return {"result": "", "screenshot_path": "", "status": f"Error: Unknown action '{action}'"}

        except ImportError as e:
            return {"result": "", "screenshot_path": "", "status": f"Error: Browser extension not available: {e}"}
        except Exception as e:
            return {"result": "", "screenshot_path": "", "status": f"Error: {e}"}
