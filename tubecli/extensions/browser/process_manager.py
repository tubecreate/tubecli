"""
Browser Process Manager
Manages browser process spawning, monitoring, and termination.
Ported from python-video-studio core/browser_process_manager.py.
"""
import os
import re
import shutil
import subprocess
import threading
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

logger = logging.getLogger("BrowserProcessManager")


def _process_group_kwargs(windows: Optional[bool] = None) -> Dict[str, Any]:
    """Cờ Popen để tiến trình con mở một nhóm/session của RIÊNG nó.

    Vì sao cần: cả cây phải giết được bằng MỘT tín hiệu. Trên POSIX,
    start_new_session cho node một session mới nên pgid == pid — os.killpg dọn
    luôn chromium và mọi renderer con. Không có nó thì chỉ có node nhận SIGTERM,
    chromium (con của node) không nhận gì, thành mồ côi và tiếp tục giữ
    user-data-dir cùng SingletonLock của hồ sơ. Trên Windows, taskkill /T đi
    theo quan hệ cha-con nên cách giết không đổi; nhóm riêng chỉ để một Ctrl+C
    ở console máy chủ không giật mất trình duyệt giữa phiên.

    Tham số `windows` chỉ để test kiểm được cả hai nhánh trên một máy.
    """
    if windows is None:
        windows = os.name == "nt"
    if windows:
        # getattr: hằng số này chỉ tồn tại trên Windows.
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


class KillResult:
    """Câu trả lời của một lần giết: nó có chết THẬT không, và nếu không thì ai còn sống.

    Là object chứ không phải bool vì người gọi cần cả hai thứ: quyết định (đóng
    sổ lượt chạy thế nào) và bằng chứng (PID nào còn sống, để ghi thẳng vào
    nhật ký nhóm cho chủ máy đọc). bool() vẫn dùng được nên `if killed:` đọc
    tự nhiên như cũ.
    """

    __slots__ = ("confirmed", "alive", "detail")

    def __init__(self, confirmed: bool, alive: Optional[List[int]] = None, detail: str = ""):
        self.confirmed = bool(confirmed)
        self.alive = list(alive or [])
        self.detail = detail

    def __bool__(self):
        return self.confirmed

    def __repr__(self):
        return f"KillResult(confirmed={self.confirmed}, alive={self.alive}, detail={self.detail!r})"


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
        ai_model: str = "",
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

        # Every launcher in the codebase funnels through spawn(), so the chain is
        # applied once here: whatever the caller passed (an agent's own model, or
        # nothing at all) becomes a model that is actually configured. Callers
        # that already resolved get the same answer — step 1 wins unchanged.
        from tubecli.config import resolve_browser_ai_model
        ai_model = resolve_browser_ai_model(ai_model)

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
            # Nhóm/session riêng cho cả cây — xem _process_group_kwargs().
            # Đã kiểm mọi chỗ đọc tiến trình này trước khi đổi: không nơi nào
            # dựa vào việc con thừa hưởng tín hiệu hay chung console với máy chủ.
            # stdout/stderr đã đổ vào file log (ngay trên), shutdown_event
            # (api/server.py:1086) không đụng tới trình duyệt, `tubecli stop`
            # (main.py) và force_kill_profile (cuối file này) đều tìm nạn nhân
            # bằng psutil theo dòng lệnh, không theo nhóm.
            process = subprocess.Popen(
                args,
                cwd=launcher_dir,
                stdout=log_file,
                stderr=log_file,
                **_process_group_kwargs(),
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
            profile = instance.get("profile") or""

        if not process:
            return

        outcome = None
        return_code = None
        kill_report = None

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
                # KHÔNG đóng sổ theo niềm tin. Bản cũ gọi _kill_tree rồi ghi
                # ngay "timeout_killed" và return — không một lần process.wait().
                # Nên một lượt được ghi là ĐÃ DỪNG trong khi chrome của nó vẫn
                # sống, và lượt hẹn giờ kế tiếp bị chặn vì hồ sơ "đang bị điều
                # khiển bởi <agent>". _kill_tree bây giờ trả lời có chết thật
                # không, và chính câu trả lời đó mới được ghi.
                kill_report = self._kill_tree(process)
                if kill_report.confirmed:
                    outcome = "timeout_killed"
                else:
                    # Chuỗi MỚI, đặt CẠNH chứ không thay: "timeout_killed" vẫn
                    # là kết cục của một lượt dừng thành công và mọi nơi đọc nó
                    # (run_log, tools/check_browsing.py, bảng Hoạt động) không
                    # đổi. Bảng Hoạt động chưa biết chuỗi này thì hiện nguyên
                    # văn (app.js:4499 có nhánh dự phòng) — xấu còn hơn nói dối.
                    outcome = "timeout_kill_failed"
                return_code = process.poll()
                with self._instances_lock:
                    inst = self._instances.get(instance_id)
                    if inst is not None:
                        inst["status"] = outcome
                        inst["ended_at"] = datetime.now().isoformat()
                        inst["kill_confirmed"] = kill_report.confirmed
                        if return_code is not None:
                            inst["return_code"] = return_code
                        if not kill_report.confirmed:
                            inst["still_alive"] = kill_report.detail

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
        #
        # Đọc log MỘT lần ở đây, trước khi đóng sổ: đây là chỗ DUY NHẤT luôn thấy
        # cả tiến trình kết thúc lẫn toàn bộ log của nó. Hai chỗ gọi cũ đều hụt —
        # /log/{profile} chỉ chạy khi có người bấm xem, còn nhánh crash trong
        # spawn() chỉ nhìn được cửa sổ 1 giây, mà lỗi khoá BAS nổ ở giây thứ ~10.
        warnings = self._note_launch_evidence(log_path)
        work = self._read_run_work(log_path)
        note = ""
        if kill_report is not None and not kill_report.confirmed:
            # Dấu này đi vào run_log để "đã dừng nhưng chưa chắc chết" có thể
            # đếm được về sau, còn `note` là câu người đọc thấy trên bảng nhóm.
            warnings.append(self._MARK_KILL_UNCONFIRMED)
            note = f"KHÔNG dừng được tiến trình: {kill_report.detail}"
        # Chấm lại theo việc phiên THỰC SỰ làm, không chỉ theo exit code.
        outcome, refine_note = self._refine_outcome(outcome, work)
        if refine_note:
            note = (note + " · " + refine_note) if note else refine_note
        self._record_run_end(run_id, agent_id, instance_id, outcome, return_code,
                             started_at, log_path, profile, warnings, note, work)

    # Dấu mốc do browser_manager.js in ra. ĐỔI CHUỖI Ở ĐÂY LÀ PHẢI ĐỔI CẢ BÊN IN.
    _MARK_BAS_OK = "BAS_LAUNCH_OK"
    _MARK_ANTIDETECT_OFF = "ANTIDETECT_OFF"

    # Không đến từ log của trình duyệt như hai dấu trên: dấu này do CHÍNH máy chủ
    # ghi ra khi nó đã bắn tín hiệu mà tiến trình vẫn không chết.
    _MARK_KILL_UNCONFIRMED = "KILL_UNCONFIRMED"

    # open.js in cho MỖI bước: "[Session] 3/10 min | Step: search (7) | Page: ..."
    # Số trong ngoặc là thứ tự hành động, nên max của nó = số hành động đã thử.
    _STEP_RE = re.compile(
        r"\[Session\]\s*([\d.]+)\s*/\s*([\d.]+)\s*min\s*\|\s*Step:\s*([A-Za-z_]+)"
        r"(?:\s*\((\d+)\))?")
    # session.end() in ở cuối một phiên chạy trọn: con số CHÍNH XÁC nhất (đếm
    # actionHistory), nên khi có thì nó thắng số suy ra từ các dòng Step.
    _ACTIONS_RE = re.compile(r"^Actions:\s*(\d+)\s*$", re.M)

    # ── "Đang làm gì" trực tiếp (read_live_action) ─────────────────────────
    # Cùng dòng Step nhưng lấy CẢ Page: sau nó — "[Session] 3/22 min | Step:
    # read_gmail (14) | Page: gmail". [^\n]*? để dấu ngoặc/pipe ở giữa không cản.
    _STEP_LIVE_RE = re.compile(
        r"\[Session\][^\n]*?Step:\s*([A-Za-z_]+)(?:\s*\((\d+)\))?"
        r"(?:[^\n]*?Page:\s*([A-Za-z0-9_\-]+))?")
    # open.js ghi URL hiện tại: "[TabManager] Now on: https://…" và
    # "[Manual] Navigated in-page. Now on: https://…".
    _NOW_ON_RE = re.compile(r"Now on:\s*(https?://\S+)")
    # 14 verb của ACTION_REGISTRY gộp về 5 nhóm mà client biết dịch. Không khớp
    # -> 'browsing' (an toàn: "đang lướt" đúng với gần hết hành động web).
    _ACTION_BUCKET = {
        "read_gmail": "reading", "extract_content": "reading",
        "search_extract": "reading", "visual_scan": "reading",
        "search": "searching",
        "watch": "watching",
        "type": "writing", "comment": "writing",
        "navigate": "browsing", "browse": "browsing", "click": "browsing",
        "login": "browsing", "save_image": "browsing", "wait": "browsing",
    }
    # host -> tên thân thiện. Danh từ riêng nên KHÔNG cần dịch — đây là lý do
    # `where` được server tính chứ không để client đoán từ URL thô.
    _FRIENDLY_HOST = {
        "mail.google.com": "Gmail", "gmail.com": "Gmail",
        "youtube.com": "YouTube", "m.youtube.com": "YouTube",
        "google.com": "Google", "news.google.com": "Google News",
        "facebook.com": "Facebook", "tiktok.com": "TikTok",
        "twitter.com": "X", "x.com": "X", "instagram.com": "Instagram",
        "docs.google.com": "Google Docs", "drive.google.com": "Google Drive",
        "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT",
    }

    def _read_run_work(self, log_path):
        """Lượt chạy này THỰC SỰ làm được gì, đọc từ log của chính nó.

        Vì sao cần: bản ghi lượt chạy chỉ có outcome, nên một lượt gõ + tìm + bấm
        + đọc 39 lần rồi hỏng ở bước cuối trông y hệt một lượt chết ngay giây đầu.
        Người dùng nhìn cột toàn "Lỗi" rồi kết luận sai rằng nó chưa từng chạy.

        Trả None khi log không nói gì — KHÔNG trả 0% cho một lượt không rõ.
        """
        if not log_path:
            return None
        try:
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception:
            return None

        steps = []
        elapsed = target = None
        highest = 0
        for m in self._STEP_RE.finditer(text):
            try:
                elapsed = float(m.group(1))
                target = float(m.group(2))
            except Exception:
                pass
            steps.append(m.group(3).lower())
            if m.group(4):
                try:
                    highest = max(highest, int(m.group(4)))
                except Exception:
                    pass

        done = None
        tail = self._ACTIONS_RE.findall(text)
        if tail:
            try:
                done = int(tail[-1])
            except Exception:
                done = None
        if done is None:
            done = highest or (len(steps) or None)
        if done is None and not steps:
            return None

        # Gộp theo tên nhưng GIỮ THỨ TỰ xuất hiện: người đọc cần biết nó đã làm
        # những việc gì, không cần 113 dòng lặp lại.
        order, tally = [], {}
        for name in steps:
            if name not in tally:
                order.append(name)
                tally[name] = 0
            tally[name] += 1

        work = {"actions": done, "kinds": [{"name": n, "n": tally[n]} for n in order]}
        if elapsed is not None and target and target > 0:
            work["elapsed_min"] = round(elapsed, 1)
            work["target_min"] = round(target, 1)
            # Chặn 100: chạy quá giờ vẫn là "đi hết phiên", không phải 130%.
            work["progress_pct"] = min(100, int(round(100.0 * elapsed / target)))
        # Chuỗi hành động CHÍNH đã chạy trọn? open.js in đúng hai dấu này ngay
        # trước khi xổ kết quả. Có nó nghĩa là việc đã xong — mọi thứ chết sau
        # đó (watchdog cắt lúc session mode, browser đóng lúc dọn, exit != 0)
        # là chuyện của phần ĐUÔI, không phủ nhận việc phiên đã làm được.
        if "__RESULTS_START__" in text or "All actions completed successfully" in text:
            work["completed_chain"] = True
        # Phần LỖI, tách riêng: một dòng gọn để bảng/bản tin nói "vấp ở đâu"
        # mà không cần mở cả log. Ưu tiên lỗi rõ ràng nhất ở gần cuối.
        err = self._first_error_line(text)
        if err:
            work["error"] = err
        return work

    _ERR_RE = re.compile(
        r"(?:!!!\s*CRITICAL ERROR\s*!!!|Process finished with FAILURE"
        r"|Propagating error|Unhandled|Error:|TimeoutError|net::ERR_)[^\n]*", re.I)

    def _first_error_line(self, text):
        """Một dòng lỗi tiêu biểu của phiên (để 'error ghi phần error riêng').

        Quét từ CUỐI lên: lỗi làm phiên dừng nằm ở đuôi, không phải một cảnh
        báo thoáng qua lúc đầu. Trả None khi phiên không có lỗi nào — một lượt
        chạy trọn không được gắn dòng lỗi vu vơ."""
        hits = self._ERR_RE.findall(text or "")
        if not hits:
            return None
        line = " ".join(str(hits[-1]).split())
        return line[:180]

    def _friendly_where(self, url, page_type):
        """Nơi agent đang đứng, thân thiện: 'Gmail'/'YouTube'/'abc.com'. None nếu mù."""
        host = ""
        if url:
            try:
                host = (urlparse(url).hostname or "").lower()
                host = re.sub(r"^www\.", "", host)
            except Exception:
                host = ""
        if host:
            return self._FRIENDLY_HOST.get(host, host)
        # Không có URL trong đuôi log — dùng Page: (gmail / youtube_home / news).
        if page_type:
            pt = page_type.lower()
            for needle, nice in (("gmail", "Gmail"), ("youtube", "YouTube"),
                                 ("github", "GitHub")):
                if needle in pt:
                    return nice
            return page_type.replace("_", " ")
        return None

    def read_live_action(self, log_path):
        """Việc agent ĐANG làm lúc này, rút từ ĐUÔI log của chính lượt chạy.

        Khác _read_run_work (tổng kết cả lượt khi xong): hàm này chỉ cần một sự
        thật đang-diễn-ra — hành động mới nhất + đang ở trang nào — để mặt node và
        bảng Hoạt động thay chữ trơ "Đang chạy" bằng "Đang đọc · Gmail". Đọc 32KB
        cuối thôi (dòng mới nằm ở cuối file) nên rẻ, gọi được mỗi vài giây.

        Trả None khi chưa có gì để khoe. Ngược lại:
          {bucket, action, where, url, step}
        bucket là nhóm hành động (client dịch: reading/searching/watching/writing/
        browsing); where là nơi thân thiện; action giữ verb gốc cho ai cần chi tiết.
        """
        if not log_path:
            return None
        try:
            with open(log_path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                # LUÔN quay về đầu cửa sổ đuôi. Quên bước này (chỉ seek khi file to
                # hơn 32KB) thì với log nhỏ con trỏ nằm ở EOF và read() ra rỗng.
                fh.seek(max(0, size - 32768))
                text = fh.read().decode("utf-8", errors="replace")
        except Exception:
            return None

        action = page_type = step_n = None
        for m in self._STEP_LIVE_RE.finditer(text):   # lần lặp CUỐI = mới nhất
            action, step_n, page_type = m.group(1), m.group(2), m.group(3)
        url = None
        for m in self._NOW_ON_RE.finditer(text):
            url = m.group(1)
        if not action and not url:
            return None

        return {
            "bucket": self._ACTION_BUCKET.get((action or "").lower(), "browsing"),
            "action": action,
            "where": self._friendly_where(url, page_type),
            "url": url,
            "step": int(step_n) if (step_n and step_n.isdigit()) else None,
        }

    def _note_launch_evidence(self, log_path):
        """Đọc log một lượt vừa xong và rút ra hai sự thật nó biết mà không ai hỏi.

        1. Khoá BAS còn sống hay đã chết. `shardx_runtime` không thăm dò qua mạng
           được (key.php trả khoá về ngon lành rồi engine vẫn chết lúc mở), nên
           phán quyết chỉ đến từ một lượt mở THẬT. Trước đây chỉ chiều "hỏng" có
           người ghi; chiều "tốt" thì không, nên máy chỉ cài BAS chạy khoá dùng
           chung mãi mãi bị coi là không dùng được và mọi profile mới ở đó bị ghim
           sang một nhân chưa tải về.
        2. Lượt này có bật chống phát hiện không. ANTIDETECT_OFF nghĩa là trình
           duyệt đã mở mà KHÔNG áp dấu vân tay nào: mã thoát vẫn 0, History vẫn
           đầy, không có dòng này thì nó không khác gì một lượt sạch.

        Trả về danh sách cảnh báo để đính vào bản ghi run_log. Không bao giờ ném.
        """
        warnings = []
        if not log_path:
            return warnings
        try:
            if not os.path.exists(log_path):
                return warnings
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()[-20000:]
        except Exception:
            return warnings
        if not text:
            return warnings

        try:
            from .routes import note_launch_output
            verdict = note_launch_output(text)
        except Exception as e:
            verdict = None
            logger.debug(f"[Browser] Could not read BAS key verdict: {e}")
        if verdict != "bad" and self._MARK_BAS_OK in text:
            # Chỉ ghi "tốt" khi log KHÔNG hề nói khoá hỏng: một phiên có thể mở
            # được lúc đầu rồi khoá hết hạn giữa chừng, và bằng chứng xấu thắng.
            try:
                from . import shardx_runtime as sx
                sx.mark_bas_key_ok()
            except Exception as e:
                logger.debug(f"[Browser] Could not record BAS key success: {e}")

        if self._MARK_ANTIDETECT_OFF in text:
            warnings.append(self._MARK_ANTIDETECT_OFF)
            logger.warning(
                "[Browser] Phiên vừa xong mở KHÔNG có dấu vân tay (ANTIDETECT_OFF) — "
                f"log: {log_path}")
        return warnings

    _PROGRESS_MIN_ACTIONS = 2      # dưới mức này coi như "chưa kịp làm gì"

    def _refine_outcome(self, outcome, work):
        """Trả (outcome đã chỉnh, note thêm). Không bao giờ ném lỗi."""
        try:
            if not isinstance(work, dict):
                return outcome, ""
            done = work.get("actions") or 0
            if work.get("completed_chain"):
                # Việc chính đã chạy trọn. Chỉ nâng các kết cục "hỏng/hết giờ";
                # refused/skipped là quyết định có chủ đích, không đụng.
                if outcome in ("error", "timeout_killed", "timeout_kill_failed"):
                    return "completed", ""
                return outcome, ""
            if outcome == "error" and done >= self._PROGRESS_MIN_ACTIONS:
                return "partial", ""
        except Exception:
            pass
        return outcome, ""

    def _record_run_end(self, run_id, agent_id, instance_id, outcome, return_code,
                        started_at, log_path, profile="", warnings=None, note="",
                        work=None):
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
            if (outcome != "completed" or warnings) and log_path:
                # Only on failure, and only the end of the file — this is what the
                # owner would otherwise have to SSH in to read. run_log redacts it.
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        tail = f.read()[-4000:]
                except Exception:
                    tail = None

            run_log.end(run_id, agent_id or "", outcome, return_code=return_code,
                        instance_id=instance_id, duration_sec=duration, log_tail=tail,
                        warnings=warnings)
            # Bản tin một dòng vào chat (+ Telegram nếu agent có nối). Sau
            # run_log.end để dòng launch đã đầy đủ; tự nuốt mọi lỗi.
            try:
                from tubecli.core import run_bulletin
                run_bulletin.post_end(agent_id or "", run_id, outcome,
                                      duration_sec=duration, warnings=warnings, work=work)
            except Exception:
                pass
            # Bảng cạnh nhóm mới là chỗ chủ máy thật sự nhìn. Trước đây nó chỉ có
            # "browser running" (spawn được) và im lặng mãi mãi sau đó — nên một phiên
            # chết sau 5 giây trông y hệt một phiên chạy trọn 8 phút. Ghi cả cái kết.
            if outcome != "completed":
                self._log_group_failure(agent_id, profile, outcome, return_code, tail, note)
            elif warnings:
                # Chạy xong nhưng KHÔNG sạch. Bảng nhóm là chỗ chủ máy thật sự nhìn,
                # nên một phiên mở trần phải hiện ở đó, không chỉ nằm trong log.
                self._log_antidetect_warning(agent_id, profile, warnings)
        except Exception as e:
            logger.warning(f"[Browser] Could not record run end: {e}")

    def _log_group_failure(self, agent_id, profile, outcome, return_code, tail, note=""):
        """Một dòng trên bảng của mọi nhóm agent này thuộc về, nói phiên hỏng thế nào.
        Best effort tuyệt đối: nhật ký không bao giờ được làm hỏng vòng theo dõi."""
        try:
            if not agent_id:
                return
            from tubecli.core import group_context, group_log
            groups = group_context.groups_for_agent(agent_id) or []
            if not groups:
                return
            # Câu cuối cùng đáng đọc trong log của tiến trình: dòng lỗi thật, không
            # phải đuôi 4000 ký tự. Ưu tiên dòng có dấu hiệu lỗi, không thì dòng cuối.
            reason = ""
            for line in reversed((tail or "").splitlines()):
                line = line.strip()
                if not line:
                    continue
                if not reason:
                    reason = line
                low = line.lower()
                if "!!!" in line or "error" in low or "failed" in low or "cannot" in low:
                    reason = line
                    break
            name = ""
            try:
                from tubecli.core.agent import agent_manager
                a = agent_manager.get(agent_id)
                name = getattr(a, "name", "") or ""
            except Exception:
                pass
            what = {"timeout_killed": "hết giờ, bị dừng",
                    "timeout_kill_failed": "hết giờ NHƯNG KHÔNG dừng được",
                    "partial": "làm được một phần rồi vấp"}.get(outcome, outcome)
            title = (f"schedule {profile} — phiên dừng: {what}" if profile
                     else f"schedule — phiên dừng: {what}")
            if return_code is not None:
                title += f" (mã {return_code})"
            for g in groups:
                gid = (g or {}).get("group_id") if isinstance(g, dict) else ""
                if gid:
                    group_log.append(gid, agent_id, name, kind="schedule",
                                     title=title,
                                     detail=((note + " | ") if note else "") + reason[:400],
                                     ok=False)
        except Exception as e:
            logger.warning(f"[Browser] Could not log session failure to group: {e}")

    def _log_antidetect_warning(self, agent_id, profile, warnings):
        """Phiên chạy TRỌN nhưng mở trần — vẫn phải hiện trên bảng nhóm.

        Đây là ca nguy hiểm nhất vì nó không giống lỗi: mã thoát 0, History đầy,
        báo cáo "thành công". Không nói ở đây thì chống phát hiện tắt hàng tuần
        cũng không ai biết. Best effort tuyệt đối, như _log_group_failure.
        """
        try:
            if not agent_id or self._MARK_ANTIDETECT_OFF not in (warnings or []):
                return
            from tubecli.core import group_context, group_log
            groups = group_context.groups_for_agent(agent_id) or []
            if not groups:
                return
            name = ""
            try:
                from tubecli.core.agent import agent_manager
                a = agent_manager.get(agent_id)
                name = getattr(a, "name", "") or ""
            except Exception:
                pass
            title = (f"schedule {profile} — mở KHÔNG có dấu vân tay" if profile
                     else "schedule — mở KHÔNG có dấu vân tay")
            detail = ("Phiên chạy xong nhưng trình duyệt mở mà không áp dấu vân tay nào, "
                      "nên lượt này KHÔNG ẩn danh: mọi hồ sơ trên máy trông giống hệt nhau. "
                      "Xem dòng ANTIDETECT_OFF trong log của phiên.")
            for g in groups:
                gid = (g or {}).get("group_id") if isinstance(g, dict) else ""
                if gid:
                    group_log.append(gid, agent_id, name, kind="schedule",
                                     title=title, detail=detail, ok=False)
        except Exception as e:
            logger.warning(f"[Browser] Could not log antidetect warning to group: {e}")

    @staticmethod
    def _refresh_exit_status(inst: Dict[str, Any]) -> None:
        """Bản ghi còn ghi "running" mà tiến trình đã thoát thì cập nhật cho đúng.

        CHỈ khi còn "running". Trước đây mỗi lượt đọc đều ghi đè, nên một kết cục
        đã được ghi đàng hoàng ("timeout_killed", "terminated", và bây giờ là
        "timeout_kill_failed") chỉ sống tới lần /status kế tiếp rồi biến thành
        "error" — chính chỗ hiển thị xoá mất sự thật mà vòng theo dõi vừa ghi.
        """
        process = inst.get("_process")
        if not process or process.poll() is None:
            return
        if inst.get("status") != "running":
            return
        inst["status"] = "completed" if process.returncode == 0 else "error"
        inst["return_code"] = process.returncode

    def get_status(self, instance_id: str) -> Optional[Dict[str, Any]]:
        with self._instances_lock:
            instance = self._instances.get(instance_id)
            if not instance:
                return None
            self._refresh_exit_status(instance)
            return {k: v for k, v in instance.items() if not k.startswith("_")}

    def list_running(self) -> List[Dict[str, Any]]:
        result = []
        with self._instances_lock:
            for inst_id, inst in self._instances.items():
                self._refresh_exit_status(inst)
                if inst["status"] == "running":
                    result.append({k: v for k, v in inst.items() if not k.startswith("_")})
        return result

    def list_all(self) -> List[Dict[str, Any]]:
        result = []
        with self._instances_lock:
            for inst in self._instances.values():
                result.append({k: v for k, v in inst.items() if not k.startswith("_")})
        return result

    # ── Giết cả cây, rồi CHỨNG MINH nó đã chết ───────────────────────────────
    # Hai trần thời gian, cả hai đều bắt buộc: vòng theo dõi không được phép treo,
    # nhưng cũng không được phép kết luận khi chưa hỏi lại.
    _KILL_GRACE_SEC = 5.0        # cho tự đóng sau tín hiệu lịch sự
    _KILL_CONFIRM_SEC = 6.0      # chờ tối đa bấy nhiêu rồi mới dám nói "chết rồi"

    def _kill_tree(self, process, grace: Optional[float] = None) -> KillResult:
        """Giết tiến trình cùng toàn bộ con cháu, rồi TRẢ LỜI nó có chết thật không.

        Vì sao phải hỏi lại: bản cũ chỉ chạy `taskkill`, một lệnh CHỈ CÓ trên
        Windows. Trên Linux nó ném FileNotFoundError, rơi xuống nhánh dự phòng
        process.terminate() — tức một SIGTERM gửi cho MỖI tiến trình node.
        Chromium là con của node nên không nhận được gì: nó thành mồ côi, tiếp
        tục giữ user-data-dir và SingletonLock của hồ sơ, và lượt hẹn giờ kế
        tiếp bị từ chối với "Hồ sơ đang bị điều khiển bởi <agent>". Giết mà
        không kiểm chứng thì không khác gì không giết.

        Không bao giờ ném: người gọi cần một câu trả lời để ghi sổ, không phải
        một ngoại lệ.
        """
        pid = getattr(process, "pid", None)
        if pid is None:
            return KillResult(True, detail="không có tiến trình để giết")
        grace = self._KILL_GRACE_SEC if grace is None else grace

        if process.poll() is not None:
            # Đã chết sẵn. Vẫn thu xác (wait) để trên POSIX nó không nằm lại
            # dạng zombie — zombie vẫn nhận tín hiệu 0 và làm mọi phép kiểm
            # "còn sống không" sau đây trả lời sai.
            self._wait_dead(process, 1.0)
            return KillResult(True, detail="tiến trình đã kết thúc từ trước")

        # Chụp ảnh cây TRƯỚC khi bắn: cha chết rồi thì không còn cách nào hỏi nó
        # đã từng có những đứa con nào, mà chính đứa cháu chromium mới là cái giữ
        # khoá hồ sơ. Chụp sau khi biết cha còn sống nên không sợ PID đã bị hệ
        # điều hành cấp lại cho ai khác.
        snapshot = self._snapshot_tree(pid)

        if os.name == "nt":
            self._kill_tree_windows(process, pid)
        else:
            self._kill_group_posix(pid, grace,
                                   lambda t: self._wait_dead(process, t))

        # Bắn kiểu gì cũng kết thúc bằng một câu hỏi: nó chết chưa?
        died = self._wait_dead(process, self._KILL_CONFIRM_SEC)
        alive, checked = self._still_alive(snapshot)

        if died and not alive:
            note = "" if checked else " (không có psutil: chỉ kiểm được tiến trình cha)"
            logger.info(f"[Browser] Đã giết và xác nhận cây tiến trình PID {pid}{note}")
            return KillResult(True)

        parts = []
        if not died:
            parts.append(f"PID {pid} vẫn sống sau khi đã bắn tín hiệu")
        if alive:
            parts.append("còn sống: " + ", ".join(str(p) for p in alive))
        detail = "; ".join(parts) or f"PID {pid} không xác nhận được là đã chết"
        logger.error(f"[Browser] GIẾT KHÔNG THÀNH — {detail}. "
                     "Hồ sơ vẫn đang bị chiếm; dùng /stop với force=true để dọn.")
        return KillResult(False, alive=alive, detail=detail)

    def _kill_tree_windows(self, process, pid):
        """Windows: taskkill /T /F vẫn là cách đúng — nó đi theo quan hệ cha-con
        nên dọn được cả chrome.exe lẫn đám renderer. Chỉ khác một điều: bây giờ
        nó không còn là câu trả lời cuối cùng, _kill_tree vẫn hỏi lại."""
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        except Exception as e:
            logger.warning(f"[Browser] taskkill hỏng ({e}) — thử kill trực tiếp")
            try:
                process.kill()
            except Exception:
                pass

    def _kill_group_posix(self, pid, grace, wait_dead, _ops=None):
        """POSIX: bắn cả NHÓM — SIGTERM trước, rồi SIGKILL cho cái còn lại.

        Trả về danh sách tín hiệu đã thực sự gửi (test đọc chính nó).

        spawn() mở tiến trình với start_new_session=True nên pgid == pid: node,
        chromium và mọi renderer nằm chung MỘT nhóm và chết cùng nhau. Nếu nhóm
        không phải của riêng ta (tiến trình mở từ trước bản vá này) thì chỉ bắn
        đúng pid — thà sót một cây còn hơn bắn nhầm cả nhóm của máy chủ.

        _ops chỉ để test tiêm hàm giả: logic leo thang phải kiểm được cả trên máy
        không phải POSIX. Cùng lý do mà hằng số tín hiệu lấy bằng getattr —
        Windows không có SIGKILL.
        """
        import signal as _signal
        SIGTERM = getattr(_signal, "SIGTERM", 15)
        SIGKILL = getattr(_signal, "SIGKILL", 9)
        ops = _ops or {}
        getpgid = ops.get("getpgid") or getattr(os, "getpgid", None)
        killpg = ops.get("killpg") or getattr(os, "killpg", None)
        kill = ops.get("kill") or os.kill

        pgid = None
        if getpgid:
            try:
                pgid = getpgid(pid)
            except Exception as e:
                logger.warning(f"[Browser] Không đọc được pgid của {pid}: {e}")
        own_group = bool(killpg) and pgid is not None and pgid == pid
        if not own_group:
            logger.warning(
                f"[Browser] PID {pid} không có nhóm riêng (pgid={pgid}) — chỉ giết "
                "được đúng tiến trình đó, con cháu có thể ở lại mồ côi")

        sent = []

        def _send(sig):
            try:
                if own_group:
                    killpg(pgid, sig)
                else:
                    kill(pid, sig)
                sent.append(sig)
                return True
            except ProcessLookupError:
                return False                    # đã chết sẵn: hết việc
            except Exception as e:
                logger.warning(f"[Browser] Không gửi được tín hiệu {sig} tới {pid}: {e}")
                return False

        if not _send(SIGTERM):
            return sent
        wait_dead(grace)
        # KHÔNG tin SIGTERM. node có thể đã thoát trong khi chromium con vẫn sống
        # — mà chromium mới là cái giữ SingletonLock. Còn thở là SIGKILL.
        if self._target_alive(pgid if own_group else pid, own_group, ops):
            _send(SIGKILL)
        return sent

    def _target_alive(self, target, own_group, ops=None) -> bool:
        """Tín hiệu 0: nhóm (hoặc tiến trình) đó còn ai không.

        Không chắc thì trả True. Nghi ngờ thì tốn thêm một phát SIGKILL vào chỗ
        trống, còn đoán bừa là "sạch rồi" thì đúng bằng con bug đang sửa.
        """
        ops = ops or {}
        killpg = ops.get("killpg") or getattr(os, "killpg", None)
        kill = ops.get("kill") or os.kill
        try:
            if own_group and killpg:
                killpg(target, 0)
            else:
                kill(target, 0)
            return True
        except ProcessLookupError:
            return False
        except Exception:
            return True

    def _wait_dead(self, process, timeout: float) -> bool:
        """Chờ có trần và THU XÁC — True nếu tiến trình đã thật sự kết thúc.

        Phải là process.wait() chứ không phải poll(): trên POSIX một đứa con
        chưa được thu vẫn là zombie, vẫn tồn tại dưới mắt tín hiệu 0.
        """
        try:
            process.wait(timeout=max(0.0, timeout))
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return process.poll() is not None

    def _snapshot_tree(self, pid):
        """(pid, thời điểm tạo) của tiến trình và mọi con cháu, chụp TRƯỚC khi giết."""
        snap = []
        try:
            import psutil                       # đã là phụ thuộc của repo (pyproject.toml)
            root = psutil.Process(pid)
            procs = [root]
            try:
                procs += root.children(recursive=True)
            except Exception:
                pass
            for pr in procs:
                try:
                    snap.append((pr.pid, pr.create_time()))
                except Exception:
                    snap.append((pr.pid, None))
        except Exception as e:
            logger.debug(f"[Browser] Không chụp được cây tiến trình {pid}: {e}")
        return snap

    def _still_alive(self, snapshot, deadline: float = 2.0):
        """Ai trong ảnh chụp còn sống THẬT, sau khi cho hệ điều hành một nhịp dọn.

        Đối chiếu cả thời điểm tạo để không nhận nhầm một tiến trình mới vừa
        được cấp đúng số PID đó.

        Trả về (danh sách còn sống, có kiểm chứng được không). Không có psutil
        thì nói thẳng là KHÔNG BIẾT, chứ danh sách rỗng ở đây sẽ bị đọc thành
        "sạch rồi" — đúng kiểu báo cáo hão mà cả bản vá này chống lại.
        """
        if not snapshot:
            return [], True
        try:
            import psutil
        except Exception:
            return [], False
        import time as _t
        end = _t.time() + max(0.0, deadline)
        while True:
            alive = []
            for pid, ctime in snapshot:
                try:
                    pr = psutil.Process(pid)
                    if pr.status() == psutil.STATUS_ZOMBIE:
                        continue                # đã chết, chỉ chưa ai thu
                    if ctime is not None and abs(pr.create_time() - ctime) > 1.0:
                        continue                # PID đã được cấp lại cho tiến trình khác
                    alive.append(pid)
                except psutil.NoSuchProcess:
                    continue
                except psutil.AccessDenied:
                    alive.append(pid)           # còn tồn tại, chỉ là không đọc được
                except Exception:
                    continue
            if not alive or _t.time() >= end:
                return alive, True
            _t.sleep(0.2)

    def _mark_stopped(self, instance_id: str, report: KillResult):
        """Ghi kết cục của một lần dừng tay. "terminated" giữ nguyên nghĩa cũ —
        đã dừng THẬT; ca không dừng được có tên riêng để không ai đọc nhầm."""
        with self._instances_lock:
            inst = self._instances.get(instance_id)
            if inst is None:
                return
            inst["status"] = "terminated" if report.confirmed else "terminate_failed"
            inst["ended_at"] = datetime.now().isoformat()
            inst["kill_confirmed"] = report.confirmed
            if not report.confirmed:
                inst["still_alive"] = report.detail

    def terminate(self, instance_id: str) -> bool:
        """Dừng một phiên. True CHỈ KHI tiến trình đã thật sự chết.

        False bây giờ có hai nghĩa — không có gì để dừng, HOẶC dừng không được.
        Cả hai đều là "chưa dừng", và đó mới là câu người gọi hỏi. Trả True khi
        chrome vẫn đang giữ hồ sơ là cách cũ để một lượt hẹn giờ kế tiếp đâm vào
        "Hồ sơ đang bị điều khiển" mà không ai hiểu vì sao.
        """
        with self._instances_lock:
            instance = self._instances.get(instance_id)
            if not instance:
                return False
            process = instance.get("_process")
            if not process or process.poll() is not None:
                return False

        # Giết NGOÀI khoá: _kill_tree chờ tới vài giây, mà bộ lập lịch chạm
        # _instances_lock mỗi nhịp (_count_running_agent_browsers -> list_running).
        # Giữ khoá qua một lần chờ là đặt độ trễ hệ điều hành lên đường lập lịch.
        try:
            report = self._kill_tree(process)
        except Exception as e:
            logger.error(f"Error terminating {instance_id}: {e}")
            return False

        self._mark_stopped(instance_id, report)
        if not report.confirmed:
            logger.error(f"[Browser] Không dừng được {instance_id}: {report.detail}")
        return report.confirmed

    def stop_by_profile(self, profile: str) -> bool:
        """Dừng phiên đang chạy của một hồ sơ. True CHỈ KHI nó đã thật sự chết."""
        target_id = None
        process = None
        with self._instances_lock:
            for inst_id, inst in self._instances.items():
                if inst["profile"] == profile and inst["status"] == "running":
                    process = inst.get("_process")
                    target_id = inst_id
                    break
        if not target_id or not process:
            return False

        report = self._kill_tree(process)       # ngoài khoá — xem terminate()
        self._mark_stopped(target_id, report)
        if not report.confirmed:
            logger.error(
                f"[Browser] Hồ sơ '{profile}' KHÔNG dừng được: {report.detail} — "
                "còn tiến trình giữ user-data-dir, gọi /stop với force=true để dọn")
        return report.confirmed


# Global singleton
browser_process_manager = BrowserProcessManager()


# ── Dọn sạch một profile ─────────────────────────────────────────────────────
# Vì sao cần: /stop cũ chỉ giết những tiến trình còn nằm trong dict RAM của tiến
# trình TubeCLI hiện tại. Mỗi lần restart TubeCLI (cập nhật, sập, deploy) dict đó
# rỗng lại, trong khi chrome cũ vẫn sống và vẫn giữ khoá user-data-dir. Lần mở sau
# chrome mới thấy profile đang bị chiếm, thoát ngay -> WebSocket đóng trước khi có
# khung hình nào, và người dùng chỉ thấy "phiên live view đã đóng, thử lại".
# Ở đây tìm theo THƯ MỤC PROFILE trong dòng lệnh, nên bắt được cả tiến trình mồ côi.

_CHROME_LOCKS = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")

# Dấu vết CỔNG CDP của phiên đã chết. Không phải khoá của Chrome, nhưng cùng một
# kiểu rác và nguy hiểm hơn: cổng ephemeral được hệ điều hành cấp lại, nên một
# preview_cdp.json mồ côi trỏ script attach vào browser của profile KHÁC (đúng
# tài khoản khác). Đã dọn profile thì dọn cả nó.
_STALE_CDP_FILES = ("preview_cdp.json", "DevToolsActivePort")


def _profile_dir(profile_name: str) -> str:
    from .profile_manager import PROFILES_DIR
    return os.path.abspath(os.path.join(PROFILES_DIR, profile_name))


def _owns_profile(cmdline, prof_dir: str) -> bool:
    """Dòng lệnh này có đang mở đúng profile đó không.

    So theo biên thư mục: "…/browser_profiles/tuan5" không được khớp với
    "…/browser_profiles/tuan50" — nếu không, dọn một profile sẽ giết nhầm profile khác.
    """
    if not cmdline:
        return False
    target = os.path.normcase(prof_dir)
    for arg in cmdline:
        a = os.path.normcase(str(arg))
        idx = a.find(target)
        if idx == -1:
            continue
        tail = a[idx + len(target):idx + len(target) + 1]
        if tail in ("", "/", "\\", '"', "'"):
            return True
    return False


def force_kill_profile(profile_name: str, wait: float = 3.0) -> dict:
    """Giết mọi tiến trình đang giữ `profile_name` rồi gỡ khoá Chrome còn sót.

    Trả báo cáo thay vì ném lỗi: "không có gì để dọn" là kết quả hợp lệ của một
    thao tác dọn dẹp, không phải sự cố.
    """
    report = {"killed": [], "locks_removed": [], "errors": []}
    prof_dir = _profile_dir(profile_name)

    try:
        import psutil
    except Exception as e:                       # không có psutil: chịu, nhưng nói ra
        report["errors"].append(f"psutil không dùng được: {e}")
        psutil = None

    if psutil:
        me = os.getpid()
        # Không tự sát: TubeCLI (và cha của nó) phải sống sót qua thao tác này.
        protected = {me}
        try:
            protected |= {p.pid for p in psutil.Process(me).parents()}
        except Exception:
            pass

        victims = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.pid in protected:
                    continue
                if _owns_profile(proc.info.get("cmdline"), prof_dir):
                    victims.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Con trước, cha sau: giết cha trước thì chrome con thành mồ côi và vẫn giữ khoá.
        expanded = []
        for v in victims:
            try:
                expanded.extend(v.children(recursive=True))
            except Exception:
                pass
            expanded.append(v)

        seen = set()
        ordered = []
        for pr in expanded:
            if pr.pid not in seen and pr.pid not in protected:
                seen.add(pr.pid)
                ordered.append(pr)

        for pr in ordered:
            try:
                report["killed"].append({"pid": pr.pid, "name": pr.name()})
                pr.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            except Exception as e:
                report["errors"].append(str(e))

        gone, alive = psutil.wait_procs(ordered, timeout=wait)
        for pr in alive:                          # xin không được thì lấy bằng vũ lực
            try:
                pr.kill()
            except Exception:
                pass
        if alive:
            psutil.wait_procs(alive, timeout=1.5)

    # Chrome bị giết cứng để lại khoá; lần mở sau nó thấy khoá là từ chối chạy.
    for lock in _CHROME_LOCKS + _STALE_CDP_FILES:
        for path in (os.path.join(prof_dir, lock), os.path.join(prof_dir, "Default", lock)):
            try:
                if os.path.lexists(path):
                    os.remove(path)
                    report["locks_removed"].append(path)
            except OSError as e:
                report["errors"].append(f"{path}: {e}")

    return report
