"""
Browser Process Manager
Manages browser process spawning, monitoring, and termination.
Ported from python-video-studio core/browser_process_manager.py.
"""
import os
import shutil
import subprocess
import threading
import uuid
import logging
from pathlib import Path
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
        context: Optional[Dict[str, Any]] = None,
        max_duration: Optional[int] = None,
        session_minutes: Optional[int] = None,
        run_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Spawn a new browser process.
        Returns dict with instance_id, pid, profile, status.

        run_id/agent_id are carried only so the monitor thread can close the run
        out in the run log when the process finally exits. A manual launch from
        the dashboard passes neither and is not recorded as an agent run.
        """
        instance_id = f"browser-{uuid.uuid4().hex[:8]}"
        debug_info = {}

        # Build command — expects browser-launcher in PATH or data dir
        args = self._build_args(profile, prompt, headless, manual, ai_model, url, instance_id, context, session_minutes)
        # Redacted at creation. _build_args puts --login-password on the argv for
        # a profile with a saved login, and cmd_str is display-only — it is never
        # what gets executed (args is). Before this, the account password went to
        # the server log via logger.info, into debug_info["command"] which spawn()
        # returns to the caller, and into the instance record that /instances and
        # /status hand to the dashboard in plaintext.
        from tubecli.core.run_log import redact
        cmd_str = redact(" ".join(args))
        logger.info(f"[Browser] Spawning: {cmd_str}")
        debug_info["command"] = cmd_str

        # For the standalone extension, the launcher logic is in the same directory as process_manager.py
        launcher_dir = str(Path(__file__).parent.absolute())
        
        # Still allow overriding via environment variable
        env_dir = os.environ.get("BROWSER_LAUNCHER_DIR")
        if env_dir and os.path.isdir(env_dir):
            launcher_dir = env_dir

        logger.info(f"[Browser] Using launcher dir: {launcher_dir}")
        debug_info["launcher_dir"] = launcher_dir

        # Check prerequisites
        # 1. Check if node is available
        try:
            # shell=False, and resolve node ourselves. With shell=True and a list,
            # POSIX runs only args[0] as the command and binds the rest to $0, $1...
            # so this was a bare `node` on Linux: --version went nowhere, stdout came
            # back empty, and node_available was set True regardless. Worse, a bare
            # `node` on a TTY opens the REPL and blocks until the 5s timeout.
            node_exe = shutil.which("node")
            if not node_exe:
                raise FileNotFoundError("`node` was not found on PATH")
            node_check = subprocess.run([node_exe, "--version"], capture_output=True,
                                        text=True, timeout=5)
            debug_info["node_version"] = node_check.stdout.strip()
            debug_info["node_available"] = True
        except Exception as e:
            debug_info["node_available"] = False
            debug_info["node_error"] = str(e)
            return {
                "instance_id": instance_id,
                "status": "error",
                "error": f"Node.js not found. Please install Node.js (https://nodejs.org). Error: {e}",
                "debug": debug_info,
            }

        # 2. Check if open.js exists
        open_js_path = os.path.join(launcher_dir, "open.js")
        debug_info["open_js_exists"] = os.path.exists(open_js_path)
        debug_info["open_js_path"] = open_js_path
        
        if not os.path.exists(open_js_path):
            # List what's actually in the directory
            try:
                dir_contents = os.listdir(launcher_dir)
                debug_info["launcher_dir_contents"] = dir_contents[:20]
            except Exception as e:
                debug_info["launcher_dir_error"] = str(e)
            
            return {
                "instance_id": instance_id,
                "status": "error",
                "error": f"open.js not found at {open_js_path}. Launcher directory may be incorrect.",
                "debug": debug_info,
            }

        # 3. Check if node_modules exists
        node_modules_path = os.path.join(launcher_dir, "node_modules")
        debug_info["node_modules_exists"] = os.path.exists(node_modules_path)

        try:
            if not os.path.isdir(launcher_dir):
                return {
                    "instance_id": instance_id,
                    "status": "error",
                    "error": f"Browser launcher directory not found: {launcher_dir}. "
                             f"Please place the browser-laucher folder next to the tubecli project.",
                    "debug": debug_info,
                }

            # Create log directory for browser output
            log_dir = Path(launcher_dir).parent / "logs" / "browser"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir / f"{instance_id}.log"
            log_file = open(log_file_path, "w", encoding="utf-8")
            logger.info(f"[Browser] Log file: {log_file_path}")
            debug_info["log_file"] = str(log_file_path)

            # NOTE: Do NOT use CREATE_NO_WINDOW — it hides the browser window!
            #
            # shell=False. This used to pass the arg LIST with shell=True, which
            # means two different things per platform: Windows joins the list via
            # list2cmdline (so it worked), but POSIX rewrites it to
            # ['/bin/sh', '-c'] + args — only "node" is the command, and open.js
            # plus every flag become $0, $1... which the command never references.
            # Linux therefore ran a bare `node`, which read EOF on stdin and exited
            # 0 instantly. No browser was ever launched by a scheduled agent run on
            # a server; the preview path (routes.py) already spawned node correctly,
            # which is why Remote worked on the same box.
            args[0] = node_exe
            process = subprocess.Popen(
                args,
                cwd=launcher_dir,
                stdout=log_file,
                stderr=log_file,
            )

            debug_info["pid"] = process.pid
            logger.info(f"[Browser] Process started with PID: {process.pid}")

            # Wait a moment and check if process immediately crashed
            import time
            time.sleep(1)
            poll_result = process.poll()
            if poll_result is not None:
                # Process already exited!
                log_file.close()
                try:
                    with open(log_file_path, "r", encoding="utf-8") as f:
                        log_content = f.read(2000)
                except:
                    log_content = "(could not read log)"
                
                debug_info["exit_code"] = poll_result
                debug_info["log_output"] = log_content
                logger.error(f"[Browser] Process exited immediately with code {poll_result}")
                
                return {
                    "instance_id": instance_id,
                    "status": "error",
                    "error": f"Browser process exited immediately (code {poll_result}). Check log for details.",
                    "log_output": log_content,
                    "debug": debug_info,
                }

            instance_info = {
                "instance_id": instance_id,
                "pid": process.pid,
                "profile": profile,
                "prompt": prompt[:100] if prompt else "",
                "status": "running",
                "started_at": datetime.now().isoformat(),
                "command": cmd_str,
                "log_file": str(log_file_path),
                "_process": process,
                "_log_file": log_file,
                # Underscore-prefixed so the existing filters in get_status/
                # list_all/list_running keep them out of API responses.
                "_run_id": run_id,
                "_agent_id": agent_id,
            }

            with self._instances_lock:
                self._instances[instance_id] = instance_info

            # Background monitor (with optional hard timeout)
            t = threading.Thread(target=self._monitor, args=(instance_id, max_duration), daemon=True)
            t.start()

            result = {k: v for k, v in instance_info.items() if not k.startswith("_")}
            result["debug"] = debug_info
            return result

        except (FileNotFoundError, NotADirectoryError) as e:
            logger.warning(f"[Browser] Launcher error: {e}")
            debug_info["exception"] = str(e)
            return {
                "instance_id": instance_id,
                "status": "error",
                "error": f"Browser launcher error at {launcher_dir}: {e}",
                "debug": debug_info,
            }
        except Exception as e:
            logger.error(f"[Browser] Spawn failed: {e}")
            debug_info["exception"] = str(e)
            raise

    def _build_args(self, profile, prompt, headless, manual, ai_model, url, instance_id, context=None, session_minutes=None):
        """Build command line arguments for browser launcher."""
        import os
        try:
            from tubecli.config import DATA_DIR, EXTENSIONS_DATA_DIR
            profiles_dir = os.path.join(EXTENSIONS_DATA_DIR, "browser", "browser_profiles")
        except ImportError:
            profiles_dir = os.path.join(os.path.dirname(__file__), "profiles")
        
        args = [
            "node", "open.js", 
            "--profile", profile, 
            "--instance-id", instance_id,
            "--profiles-dir", profiles_dir
        ]

        if context:
            try:
                import json as _json
                temp_dir = DATA_DIR / "temp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_file = temp_dir / f"context_{instance_id}.json"
                with open(temp_file, "w", encoding="utf-8") as f:
                    _json.dump(context, f, indent=2, ensure_ascii=False)
                args.extend(["--context-file", str(temp_file)])
                logger.info(f"[Browser] Injected context file: {temp_file}")
            except Exception as e:
                logger.warning(f"[Browser] Failed to write context file: {e}")
        if prompt:
            args.extend(["--prompt", prompt])
            # Use dynamic session_minutes, clamped between 2-10 minutes; default 5
            duration_min = max(2, min(10, int(session_minutes))) if session_minutes else 5
            args.extend(["--session", "--session-duration", str(duration_min)])
        elif manual:
            args.append("--manual")
        if url:
            args.extend(["--url", url])
        if headless:
            args.append("--headless")
        args.extend(["--ai-model", ai_model])
        
        # Auto-login: load google_account from profile config
        try:
            config_path = os.path.join(profiles_dir, profile, "config.json")
            if os.path.exists(config_path):
                import json as _json
                with open(config_path, "r", encoding="utf-8") as f:
                    config = _json.load(f)
                ga = config.get("google_account")
                if ga and isinstance(ga, dict) and ga.get("email"):
                    args.extend(["--login-email", ga["email"]])
                    args.extend(["--login-password", ga.get("password", "")])
                    if ga.get("recoveryEmail"):
                        args.extend(["--login-recovery", ga["recoveryEmail"]])
                    if ga.get("twoFactorCodes"):
                        args.extend(["--login-2fa", ga["twoFactorCodes"]])
                    logger.info(f"[Browser] Auto-login enabled for {ga['email']}")
        except Exception as e:
            logger.warning(f"[Browser] Failed to load google_account: {e}")
        
        return args

    def _monitor(self, instance_id: str, timeout_seconds: Optional[int] = None):
        """Monitor a browser process. Auto-kills it after timeout_seconds if still running."""
        with self._instances_lock:
            instance = self._instances.get(instance_id)
            if not instance:
                return
            process = instance.get("_process")
            run_id = instance.get("_run_id")
            agent_id = instance.get("_agent_id")
            started_at = instance.get("started_at")
            log_path = instance.get("log_file")

        if not process:
            return

        outcome = None
        return_code = None

        if timeout_seconds and timeout_seconds > 0:
            import time
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(5)
            else:
                # Deadline reached and process still running — force kill
                logger.warning(
                    f"[Browser] Instance {instance_id} exceeded max duration ({timeout_seconds}s). Force killing."
                )
                print(
                    f"[Browser] Instance {instance_id} exceeded max duration ({timeout_seconds}s). Force killing."
                )
                self._kill_tree(process)
                with self._instances_lock:
                    if instance_id in self._instances:
                        self._instances[instance_id]["status"] = "timeout_killed"
                        self._instances[instance_id]["ended_at"] = datetime.now().isoformat()
                outcome = "timeout_killed"

        if outcome is None:
            return_code = process.wait()
            outcome = "completed" if return_code == 0 else "error"
            with self._instances_lock:
                if instance_id in self._instances:
                    self._instances[instance_id]["status"] = outcome
                    self._instances[instance_id]["return_code"] = return_code
                    self._instances[instance_id]["ended_at"] = datetime.now().isoformat()

        # Outside the lock on purpose. This does file I/O, and the scheduler
        # takes _instances_lock on every tick through _count_running_agent_browsers
        # -> list_running; holding it across a write would put disk latency on the
        # scheduling path.
        self._record_run_end(run_id, agent_id, instance_id, outcome, return_code,
                             started_at, log_path)

    def _record_run_end(self, run_id, agent_id, instance_id, outcome, return_code,
                        started_at, log_path):
        """Close the run out in the durable log. Never raises into the monitor."""
        if not run_id:
            return   # a manual dashboard launch is not an agent run
        try:
            from tubecli.core import run_log

            duration = None
            try:
                duration = (datetime.now()
                            - datetime.fromisoformat(started_at)).total_seconds()
            except Exception:
                pass

            tail = None
            if outcome != "completed" and log_path:
                # Only on failure, and only the end of the file — this is what the
                # owner would otherwise have to SSH in to read. run_log redacts it.
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        tail = f.read()[-4000:]
                except Exception:
                    tail = None

            run_log.end(run_id, agent_id or "", outcome, return_code=return_code,
                        instance_id=instance_id, duration_sec=duration, log_tail=tail)
        except Exception as e:
            logger.warning(f"[Browser] Could not record run end: {e}")

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

    def _kill_tree(self, process):
        """Kill process and all its children (worker.exe, chrome.exe, etc.)"""
        try:
            pid = process.pid
            import subprocess as _sp
            # Windows: taskkill /T kills entire process tree
            _sp.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=10)
            logger.info(f"[Browser] Killed process tree for PID {pid}")
        except Exception as e:
            logger.warning(f"[Browser] taskkill failed, falling back to terminate: {e}")
            try:
                process.terminate()
            except Exception:
                pass

    def terminate(self, instance_id: str) -> bool:
        with self._instances_lock:
            instance = self._instances.get(instance_id)
            if not instance:
                return False
            process = instance.get("_process")
            if not process or process.poll() is not None:
                return False
            try:
                self._kill_tree(process)
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
                        self._kill_tree(process)
                        inst["status"] = "terminated"
                        inst["ended_at"] = datetime.now().isoformat()
                        return True
        return False


# Global singleton
browser_process_manager = BrowserProcessManager()
