"""Built-in node: Browser Action — uses TubeCLI browser profile system."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import asyncio


import os

class BrowserNode(BaseNode):
    node_type = "browser_action"
    display_name = "🌐 Browser Action"
    description = "Launch browser with a profile and perform actions (navigate, AI prompt, screenshot)."
    icon = "🌐"
    category = "Browser"

    def _setup_ports(self):
        self.add_input("url", PortType.TEXT, "URL to navigate to", required=False)
        self.add_input("prompt", PortType.TEXT, "AI prompt for browser agent", required=False)
        self.add_input("data", PortType.ANY, "Additional data", required=False)
        self.add_output("result", PortType.TEXT, "Action result / extracted data")
        self.add_output("screenshot_path", PortType.TEXT, "Screenshot file path")
        self.add_output("status", PortType.TEXT, "Execution status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        profile_name = self.config.get("profile_name", "")
        action = self.config.get("action", "navigate")
        url = inputs.get("url") or self.config.get("url", "")
        prompt = inputs.get("prompt") or self.config.get("prompt", "")
        headless = self.config.get("headless", False)
        ai_model = self.config.get("ai_model", "qwen:latest")
        wait_seconds = int(self.config.get("wait_seconds", 10))

        if not profile_name:
            return {"result": "", "screenshot_path": "", "status": "Error: No profile_name configured"}

        try:
            # Dynamically loaded by extension_manager so they are in sys.path
            from process_manager import browser_process_manager
            from profile_manager import get_profile

            # Verify profile exists
            profile = get_profile(profile_name)
            if not profile:
                return {"result": "", "screenshot_path": "", "status": f"Error: Profile '{profile_name}' not found"}

            if action == "navigate":
                # Launch browser, navigate to URL
                result = browser_process_manager.spawn(
                    profile=profile_name,
                    prompt=f'Go to "{url}"' if url else "",
                    headless=headless,
                    manual=not bool(url and prompt),
                    ai_model=ai_model,
                    url=url,
                )
                # Wait for process
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
                
                # Spawn browser
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
                    await asyncio.sleep(2)
                    waited += 2
                    status_info = browser_process_manager.get_status(instance_id) or {}
                    if status_info.get("status") in ["completed", "error", "terminated"]:
                        break
                
                # Extract summary from logs
                final_result = "Action completed, but no summary was found in browser logs."
                if log_file and os.path.exists(log_file):
                    try:
                        with open(log_file, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                            # Search from bottom for RESULT_SUMMARY
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
