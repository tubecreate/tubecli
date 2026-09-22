"""Agent Town telemetry — máy báo lên cloud mỗi khi một agent vào/ra một bước dây chuyền.

Trang chủ cloud.tubecreate.com vẽ các bước đó thành một thị trấn: mỗi gian hàng là một
extension, người đi bộ là agent đang chạy task. Nguồn phát là codex/manager.py report_step.

QUYỀN RIÊNG TƯ (user chốt 20/9/2026). Đây là việc THẬT của khách, không phải số liệu công
khai, mà /api/town/snapshot bên cloud thì ai cũng gọi được. Nên một dòng chỉ được mang:

    s  = mã extension (manifest.name — «browser», «capcut_tts», «con_st»…)
    st = trạng thái   (running | success | error | skipped | cancelled)
    a  = băm id agent (MỘT NGƯỜI TRÊN BẢN ĐỒ = MỘT AGENT CÓ THẬT, xem dưới)
    d  = số giây
    t  = mốc unix

KHÔNG gửi TÊN agent: đó là chữ người dùng tự gõ. Trang chủ tự đặt biệt danh suy ra từ
mã băm (pseudonym() ở lib/town.js). Ai muốn được xướng tên thì tự bật trong cài đặt
tài khoản, và cloud ghép tên lúc dựng snapshot — không bao giờ ghép vào dòng máy gửi.

MỘT NGƯỜI = MỘT AGENT CÓ THẬT (user chốt 20/9/2026): băm theo id AGENT chứ không phải
id task, nên cùng một agent chạy mười task vẫn là một người đi lại trong thị trấn.

KHÔNG tiêu đề, KHÔNG goal, KHÔNG username, KHÔNG đường dẫn, KHÔNG URL. Thêm trường mới vào
đây là mở rộng thứ lộ ra ngoài — cân nhắc đúng chỗ này, đừng cân nhắc ở chỗ khác.

BA NGUYÊN TẮC vì nó chạy chen vào dây chuyền thật:
  1. Không bao giờ chặn. report() chỉ bỏ vào hàng đợi trong bộ nhớ rồi trả về ngay.
  2. Không bao giờ làm hỏng lượt. Mọi lỗi mạng bị nuốt; hỏng telemetry không được phép
     làm hỏng một task video đang chạy.
  3. Không bao giờ phình. Hàng đợi có trần; đầy thì bỏ dòng CŨ NHẤT, vì cái đang diễn ra
     mới là cái trang chủ cần vẽ.

Tắt bằng biến môi trường TUBECLI_TOWN=off.
"""
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CLOUD_URL = os.environ.get("TUBECLI_CLOUD_URL", "https://cloud.tubecreate.com").rstrip("/")
INGEST_PATH = "/api/town/ingest"

# Mã extension: manifest.name — a-z 0-9 _ -. Kiểm hình dạng chứ KHÔNG kiểm theo danh
# sách cố định: máy cài extension mới từ Chợ thì nó phải lên được bản đồ ngay, không
# phải chờ cloud deploy lại. Cloud cũng kiểm hình dạng y hệt (EXT_RE ở lib/town.js).
_EXT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
STATUSES = frozenset({"running", "success", "error", "skipped", "cancelled"})

FLUSH_EVERY_SEC = 20.0      # gom 20 giây một chuyến: bước dây chuyền thưa, không cần realtime tới giây
MAX_QUEUE = 500
MAX_BATCH = 100
BACKOFF_MAX_SEC = 900.0     # cloud sập thì giãn dần tới 15 phút, không đập cửa


def _enabled() -> bool:
    return os.environ.get("TUBECLI_TOWN", "on").strip().lower() not in ("off", "0", "false", "no")


def agent_hash(agent_id: Any) -> str:
    """Mã ẩn danh ỔN ĐỊNH của một AGENT: cùng agent thì cùng mã qua mọi task và mọi lần
    khởi động lại, nên nó là một người cố định trên bản đồ. Không lần ngược ra agent."""
    return hashlib.sha256(f"town-agent:{agent_id}".encode("utf-8")).hexdigest()[:16]


class _Sender:
    def __init__(self) -> None:
        self._q: deque = deque()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._backoff = 0.0
        self._dropped = 0

    # ── Đầu vào ──────────────────────────────────────────────────
    def report(self, station: str, status: str, agent_id: Any, duration: float = 0.0) -> None:
        if not _enabled() or status not in STATUSES:
            return
        station = str(station or "").strip().lower()
        if not _EXT_RE.match(station):
            return
        row = {
            "s": station,
            "st": status,
            "a": agent_hash(agent_id),
            "d": max(0, int(duration or 0)),
            "t": int(time.time()),
        }
        with self._lock:
            if len(self._q) >= MAX_QUEUE:
                self._q.popleft()
                self._dropped += 1
            self._q.append(row)
        self._ensure_thread()

    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="town-telemetry", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ── Gửi ──────────────────────────────────────────────────────
    def _identity(self) -> Optional[Dict[str, str]]:
        """Chưa nối cloud thì chưa có gì để gửi: máy tự quản không có mã server lẫn khoá ký."""
        try:
            from tubecli.core import cloud_identity

            ident = cloud_identity.load()
        except Exception:
            return None
        code, key = ident.get("server_code"), ident.get("town_key")
        if not code or not key:
            return None
        return {"code": code, "key": key}

    def _loop(self) -> None:
        while not self._stop.wait(FLUSH_EVERY_SEC):
            try:
                self._flush_once()
            except Exception as e:                      # nguyên tắc 2: không bao giờ nổi lên trên
                logger.debug("[Town] flush failed: %s", e)

    def _flush_once(self) -> None:
        with self._lock:
            if not self._q:
                return
        if self._backoff and time.time() < self._backoff:
            return

        ident = self._identity()
        if not ident:
            # Chưa nối cloud: giữ hàng đợi (có trần) chứ không xoá — máy vừa được ghép nối
            # xong là chuyến kế tiếp đẩy được luôn những gì vừa chạy.
            return

        with self._lock:
            batch = [self._q.popleft() for _ in range(min(MAX_BATCH, len(self._q)))]
            dropped, self._dropped = self._dropped, 0
        if dropped:
            logger.debug("[Town] queue full, dropped %d oldest rows", dropped)

        body = json.dumps({"events": batch}, separators=(",", ":")).encode("utf-8")
        ts = str(int(time.time()))
        sig = hmac.new(
            ident["key"].encode("utf-8"), f"{ts}.".encode("utf-8") + body, hashlib.sha256
        ).hexdigest()

        req = urllib.request.Request(
            CLOUD_URL + INGEST_PATH,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Town-Server": ident["code"],
                "X-Town-Ts": ts,
                "X-Town-Sig": sig,
                # Tunnel Cloudflare chặn User-Agent mặc định của urllib — xem
                # core/ninerouter.py, cùng một cái bẫy.
                "User-Agent": "TubeCLI-Town/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                res.read()
            self._backoff = 0.0
        except urllib.error.HTTPError as e:
            # 4xx là lô này sai (khoá cũ, máy đã xoá) — gửi lại cũng thế, bỏ luôn.
            # 5xx là cloud đang hỏng — trả dòng về đầu hàng đợi và giãn nhịp.
            if e.code < 500:
                logger.debug("[Town] ingest rejected %s, dropping %d rows", e.code, len(batch))
                self._backoff = time.time() + min(BACKOFF_MAX_SEC, 300.0)
            else:
                self._requeue(batch)
                self._bump_backoff()
        except Exception:
            self._requeue(batch)
            self._bump_backoff()

    def _requeue(self, batch) -> None:
        with self._lock:
            for row in reversed(batch):
                if len(self._q) >= MAX_QUEUE:
                    break
                self._q.appendleft(row)

    def _bump_backoff(self) -> None:
        wait = 30.0 if not self._backoff else min(BACKOFF_MAX_SEC, (self._backoff - time.time()) * 2 or 60.0)
        self._backoff = time.time() + max(30.0, wait)


_sender = _Sender()


def report(station: str, status: str, agent_id: Any, duration: float = 0.0) -> None:
    """Điểm gọi duy nhất. An toàn ở mọi luồng, không bao giờ ném lỗi, không bao giờ chờ."""
    try:
        _sender.report(station, status, agent_id, duration)
    except Exception:
        pass


def stop() -> None:
    _sender.stop()
