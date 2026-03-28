"""Built-in node: Run Command — executes shell commands."""
import subprocess
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class RunCommandNode(BaseNode):
    node_type = "run_command"
    display_name = "💻 Run Command"
    description = "Execute a shell command. Use {text_input} or {input_data} as placeholders."
    category = "System"

    def _setup_ports(self):
        self.add_input("command", PortType.TEXT, "Command to execute", required=False)
        self.add_input("text_input", PortType.TEXT, "Text data (replaces {text_input} in command)", required=False)
        self.add_output("stdout", PortType.TEXT, "Standard output")
        self.add_output("exit_code", PortType.TEXT, "Exit code")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        command = inputs.get("command") or self.config.get("command", "")
        cwd = self.config.get("cwd", None)
        timeout = self.config.get("timeout", 60)

        if not command:
            return {"stdout": "No command provided", "exit_code": "1"}

        # Resolve template variables from inputs
        text_input = inputs.get("text_input", "")
        template_vars = {
            "text_input": str(text_input) if text_input else "",
            "input_data": str(text_input) if text_input else "",
            "command_input": str(inputs.get("command", "")) if inputs.get("command") else "",
        }
        for key, val in template_vars.items():
            command = command.replace("{" + key + "}", val)
            command = command.replace("{{" + key + "}}", val)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout,
            )
            return {
                "stdout": result.stdout + result.stderr,
                "exit_code": str(result.returncode),
            }
        except subprocess.TimeoutExpired:
            return {"stdout": f"Command timed out after {timeout}s", "exit_code": "124"}
        except Exception as e:
            return {"stdout": f"Error: {e}", "exit_code": "1"}

