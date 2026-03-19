"""
Browser Process Manager
Manages browser process spawning, monitoring, and termination.
Ported from python-video-studio core/browser_process_manager.py.
"""
import os
import subprocess
import threading
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger("BrowserProcessManager")


class BrowserProcessManager:
    """Singleton to manage all browser processes."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._instances: Dict[str, Dict[str, Any]] = {}
        self._instances_lock = threading.Lock()

    def spawn(
        self,
        profile: str,
        prompt: str = "",
        headless: bool = False,
        manual: bool = True,
        ai_model: str = "qwen:latest",
        url: str = "",
    ) -> Dict[str, Any]:
        """
        Spawn a new browser process.
        Returns dict with instance_id, pid, profile, status.
        """
        instance_id = f"browser-{uuid.uuid4().hex[:8]}"

        # Build command — expects browser-launcher in PATH or data dir
        args = self._build_args(profile, prompt, headless, manual, ai_model, url, instance_id)
        cmd_str = " ".join(args)
        logger.info(f"[Browser] Spawning: {cmd_str}")

        # Define launcher directory dynamically relative to project root
        # tubecli project root = BASE_DIR (config.py), browser-laucher is a sibling
        from tubecli.config import BASE_DIR as _base
        project_root = str(_base.parent)  # parent of tubecli/ = workspace root

        env_dir = os.environ.get("BROWSER_LAUNCHER_DIR")
        if env_dir and os.path.isdir(env_dir):
            launcher_dir = env_dir
        elif os.path.isdir(os.path.join(project_root, "browser-laucher")):
            launcher_dir = os.path.join(project_root, "browser-laucher")
        elif os.path.isdir(os.path.join(project_root, "python-video-studio", "browser-laucher")):
            launcher_dir = os.path.join(project_root, "python-video-studio", "browser-laucher")
        else:
            launcher_dir = os.path.join(project_root, "browser-laucher")
            logger.warning(f"[Browser] browser-laucher not found at {launcher_dir}")

        logger.info(f"[Browser] Using launcher dir: {launcher_dir}")

        try:
            if not os.path.isdir(launcher_dir):
                return {
                    "instance_id": instance_id,
                    "status": "error",
                    "error": f"Browser launcher directory not found: {launcher_dir}. "
                             f"Please place the browser-laucher folder next to the tubecli project.",
                }

            creation_flags = 0
            if os.name == "nt":
                creation_flags = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(
                args,
                cwd=launcher_dir,
                creationflags=creation_flags,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            instance_info = {
                "instance_id": instance_id,
                "pid": process.pid,
                "profile": profile,
                "prompt": prompt[:100] if prompt else "",
                "status": "running",
                "started_at": datetime.now().isoformat(),
                "command": cmd_str,
                "_process": process,
            }

            with self._instances_lock:
                self._instances[instance_id] = instance_info

            # Background monitor
            t = threading.Thread(target=self._monitor, args=(instance_id,), daemon=True)
            t.start()

            return {k: v for k, v in instance_info.items() if not k.startswith("_")}

        except (FileNotFoundError, NotADirectoryError) as e:
            logger.warning(f"[Browser] Launcher error: {e}")
            return {
                "instance_id": instance_id,
                "status": "error",
                "error": f"Browser launcher error at {launcher_dir}: {e}",
            }
        except Exception as e:
            logger.error(f"[Browser] Spawn failed: {e}")
            raise

    def _build_args(self, profile, prompt, headless, manual, ai_model, url, instance_id):
        """Build command line arguments for browser launcher."""
        from tubecli.extensions.browser.profile_manager import PROFILES_DIR
        
        args = [
            "node", "open.js", 
            "--profile", profile, 
            "--instance-id", instance_id,
            "--profiles-dir", PROFILES_DIR
        ]
        if prompt:
            args.extend(["--prompt", prompt])
            args.extend(["--session", "--session-duration", "10"])
        elif url:
            args.extend(["--prompt", f'Go to "{url}"'])
        elif manual:
            args.append("--manual")
        if headless:
            args.append("--headless")
        args.extend(["--ai-model", ai_model])
        return args

    def _monitor(self, instance_id: str):
        with self._instances_lock:
            instance = self._instances.get(instance_id)
            if not instance:
                return
            process = instance.get("_process")

        if process:
            return_code = process.wait()
            with self._instances_lock:
                if instance_id in self._instances:
                    self._instances[instance_id]["status"] = "completed" if return_code == 0 else "error"
                    self._instances[instance_id]["return_code"] = return_code
                    self._instances[instance_id]["ended_at"] = datetime.now().isoformat()

    def get_status(self, instance_id: str) -> Optional[Dict[str, Any]]:
        with self._instances_lock:
            instance = self._instances.get(instance_id)
            if not instance:
                return None
            process = instance.get("_process")
            if process and process.poll() is not None:
                instance["status"] = "completed" if process.returncode == 0 else "error"
                instance["return_code"] = process.returncode
            return {k: v for k, v in instance.items() if not k.startswith("_")}

    def list_running(self) -> List[Dict[str, Any]]:
        result = []
        with self._instances_lock:
            for inst_id, inst in self._instances.items():
                process = inst.get("_process")
                if process and process.poll() is not None:
                    inst["status"] = "completed" if process.returncode == 0 else "error"
                if inst["status"] == "running":
                    result.append({k: v for k, v in inst.items() if not k.startswith("_")})
        return result

    def list_all(self) -> List[Dict[str, Any]]:
        result = []
        with self._instances_lock:
            for inst in self._instances.values():
                result.append({k: v for k, v in inst.items() if not k.startswith("_")})
        return result

    def terminate(self, instance_id: str) -> bool:
        with self._instances_lock:
            instance = self._instances.get(instance_id)
            if not instance:
                return False
            process = instance.get("_process")
            if not process or process.poll() is not None:
                return False
            try:
                process.terminate()
                instance["status"] = "terminated"
                instance["ended_at"] = datetime.now().isoformat()
                return True
            except Exception as e:
                logger.error(f"Error terminating {instance_id}: {e}")
                return False

    def stop_by_profile(self, profile: str) -> bool:
        with self._instances_lock:
            for inst_id, inst in self._instances.items():
                if inst["profile"] == profile and inst["status"] == "running":
                    process = inst.get("_process")
                    if process:
                        process.terminate()
                        inst["status"] = "terminated"
                        inst["ended_at"] = datetime.now().isoformat()
                        return True
        return False


# Global singleton
browser_process_manager = BrowserProcessManager()
