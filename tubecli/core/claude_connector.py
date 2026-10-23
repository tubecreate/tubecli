"""Trình kết nối claude.ai — phía MÁY (user 23/10/2026: «thêm trình kết nối vào claude để tự động điều chỉnh»).

Đường đi: claude.ai ──OAuth + MCP──▶ cloud.tubecreate.com/mcp ──ký HMAC town_key miền «mcp»──▶ POST /api/v1/public/mcp
(api/public_routes.py) ──▶ handle() ở đây ──▶ ĐÚNG bộ công cụ của Codex GPT (extensions/codex_gpt/tools.py): cùng khoá
cứng (BLOCK_ALL / BLOCK_WRITE / SECRET_SEGMENTS), cùng cách gọi API trong tiến trình kèm X-TubeCLI-Agent (route dựng node
coi đây là MODEL, không phải chủ).

Khác Codex ở chỗ DUYỆT (user chọn 23/10/2026):
  * Lệnh ĐỌC và lệnh ghi THƯỜNG (Retry, chạy ngay, tạo việc, sửa agent, điều khiển trình duyệt) chạy luôn.
  * Lệnh NGUY HIỂM (xoá/huỷ/dừng, cài extension, đưa agent lên Town — is_dangerous) KHÔNG chạy: trả «needs_approval»
    kèm tóm tắt; cloud tạo link duyệt cho chủ, chủ bấm Duyệt thì cloud gửi lại cùng lời gọi với approved=true.
    Không giữ request chờ người bấm: Cloudflare cắt request đi qua tunnel sau ~100 s.
  * Không dùng service.tool_approval của Codex: thẻ duyệt, «Allow for this chat», «Don't ask» của Codex không bao giờ phủ
    sang lời gọi từ claude.ai (và ngược lại).

Ba rào phía máy:
  1. Chữ ký town_key miền «mcp» + mốc giờ ±5 phút + nonce một lần (public_agents.verify_invoke) — chỉ cloud gọi được.
  2. Công tắc của chủ: global_settings.json «claude_connector» (mặc định TẮT). Cloud bật khi chủ cấp quyền máy này cho
     Claude trên trang đồng ý (bằng phiên của chủ); Claude không tự bật được — /api/v1/settings là chỉ-đọc với công cụ.
  3. Mức quyền cloud gửi kèm («read» | «write») được kiểm LẠI ở đây: kết nối chỉ-đọc không chạy được lệnh ghi nào.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Tuple

logger = logging.getLogger("ClaudeConnector")

SETTING = "claude_connector"          # global_settings.json — True = chủ cho Claude điều khiển máy này
AGENT = "claude_connector"            # X-TubeCLI-Agent + created_by của việc Claude tạo
LEVELS = ("read", "write")
MAX_BODY = 256 * 1024                 # board_create nhận goal tới 20 000 ký tự, browser_type 5 000

# Công cụ luôn nguy hiểm: đóng trình duyệt (cắt ngang phiên/việc đang chạy trên hồ sơ đó), cài mã mới, mở agent ra Town.
DANGER_TOOLS = {"browser_close", "market_install", "town_agent_offer"}
# Đoạn đường API (tách theo «-» «_») mang nghĩa phá/huỷ — DELETE thì luôn nguy hiểm, kể cả không có chữ nào ở đây.
DANGER_WORDS = {"delete", "remove", "purge", "cancel", "stop", "kill", "abort", "terminate", "reset", "wipe", "clear",
                "uninstall", "disable", "restart", "shutdown", "reboot", "destroy", "revoke", "unpublish", "drop"}


class ConnectorError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def enabled() -> bool:
    from tubecli import config

    return config.read_global_settings().get(SETTING) is True


def _segments(path: str):
    for seg in str(path or "").lower().split("/"):
        for part in re.split(r"[-_]", seg):
            if part:
                yield part


def is_dangerous(tool, args: Dict[str, Any]) -> bool:
    """Lệnh ghi cần chủ duyệt qua link. Chỉ xét SAU khi tool.prepare đã kiểm hợp lệ (đường đã chuẩn hoá)."""
    if tool.name in DANGER_TOOLS or tool.asks_always(args):
        return True
    if tool.name == "tubecli_api":
        from tubecli.extensions.codex_gpt import tools as T

        a = T._api_prepare(args)
        return a["method"] == "DELETE" or any(p in DANGER_WORDS for p in _segments(a["path"]))
    return False


def list_tools(level: str):
    """Công cụ cho claude.ai. Kết nối chỉ-đọc: bỏ công cụ CHỈ ghi (tubecli_api còn lại — GET vẫn chạy)."""
    from tubecli.extensions.codex_gpt import tools as T

    out = []
    for t in T.TOOLS.values():
        if level != "write" and t._write is True:
            continue
        pub = t.public()
        pub["annotations"] = dict(pub.get("annotations") or {}, destructiveHint=t.name in DANGER_TOOLS)
        out.append(pub)
    return out


async def _yes(*_a, **_k):
    return True, "", ""


async def call(name: str, args: Any, level: str, approved: bool, app) -> Dict[str, Any]:
    """{"result": <MCP tools/call result>} hoặc {"needs_approval": {tool, summary}}."""
    from tubecli.extensions.codex_gpt import tools as T

    tool = T.TOOLS.get(str(name or ""))
    if tool is None:
        return {"result": T.text_result(f"Unknown TubeCLI tool '{name}'", error=True)}
    args = args if isinstance(args, dict) else {}
    try:
        if tool.prepare:
            tool.prepare(args)                 # sai / bị khoá cứng → báo luôn, không bắt chủ duyệt thứ đằng nào cũng hỏng
        write = tool.is_write(args)
        if write and level != "write":
            return {"result": T.text_result(
                "This connection is read-only — the owner granted Claude read access to this server. Ask the owner to "
                "reconnect with read & write access if this change is needed.", error=True)}
        if write and not approved and is_dangerous(tool, args):
            ctx: Dict[str, Any] = {"app": app, "agent": AGENT}
            summary = (await tool.plan(args, ctx))["summary"] if tool.plan else tool.summary(args)
            return {"needs_approval": {"tool": tool.name, "summary": str(summary)[:2000]}}
    except T.ToolError as e:
        return {"result": T.text_result(str(e), error=True)}
    except ImportError as e:
        return {"result": T.text_result(f"This TubeCLI does not have that feature enabled ({e.name or e})", error=True)}
    return {"result": await T.call_tool(tool.name, args, app, _yes, agent=AGENT)}


async def handle(payload: Any, app) -> Tuple[int, Dict[str, Any]]:
    """Một lời gọi cloud đã ký: {"rpc": {method, params}, "level": "read"|"write", "approved": bool}."""
    if not enabled():
        return 403, {"ok": False, "code": "connector_off"}
    if not isinstance(payload, dict) or not isinstance(payload.get("rpc"), dict):
        return 400, {"ok": False, "code": "bad_request"}
    level = str(payload.get("level") or "read")
    if level not in LEVELS:
        return 400, {"ok": False, "code": "bad_level"}
    rpc = payload["rpc"]
    method = rpc.get("method")
    params = rpc.get("params") if isinstance(rpc.get("params"), dict) else {}
    if method == "tools/list":
        from tubecli import __version__

        return 200, {"ok": True, "result": {"tools": list_tools(level)}, "version": __version__}
    if method == "tools/call":
        out = await call(params.get("name"), params.get("arguments"), level, payload.get("approved") is True, app)
        return 200, {"ok": True, **out}
    return 400, {"ok": False, "code": "bad_method"}
