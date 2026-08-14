"""CapCut TTS — HTTP routes.

Two layers:
  - Account management (/accounts…): add/list/remove the user's CapCut accounts,
    stored encrypted by account_store.
  - Proxy (/speakers, /languages, /synthesize, /preview): forward to the loopback
    Node server, attaching the chosen account's credentials as x-capcut-* headers.
    Audio comes back as audio/mpeg; synthesize results are also saved under the
    extension's data dir for the history tab.

The router holds decrypted CapCut passwords in flight, so it sits behind the
origin guard like cloud_api does.
"""
import logging
import os
import time
from pathlib import Path

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from tubecli.core.origin_guard import guard_origin
from tubecli.config import ext_data_path
from tubecli.extensions.capcut_tts.account_store import account_store
from tubecli.extensions.capcut_tts.process_manager import node_manager

logger = logging.getLogger("CapCutTTS.routes")

router = APIRouter(
    prefix="/api/v1/capcut-tts",
    tags=["capcut-tts"],
    dependencies=[Depends(guard_origin)],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _output_dir() -> Path:
    d = ext_data_path("capcut_tts", "output")
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── models ──────────────────────────────────────────────────────────────────
class AddAccountRequest(BaseModel):
    email: str
    password: str
    label: str = ""


class SynthesizeRequest(BaseModel):
    email: str            # which stored account to use
    text: str
    speaker: str = ""
    speed: int = 10
    volume: int = 10


# ── the Node server, ensured before any proxy call ──────────────────────────
def _ensure_node():
    """Start the Node server (seeded by the first enabled account) if needed.
    Returns its base URL or raises 400/503 with an actionable message."""
    bootstrap = account_store.bootstrap_account()
    if not bootstrap:
        raise HTTPException(400, "Chưa có tài khoản CapCut nào. Hãy thêm một tài khoản trước khi tổng hợp giọng.")
    res = node_manager.ensure_running(bootstrap)
    if res.get("status") != "success":
        raise HTTPException(503, res.get("message", "Không khởi động được server CapCut."))
    return node_manager.base_url()


def _account_headers(email: str) -> dict:
    """x-capcut-email/password headers for the chosen account, so the Node
    server uses THAT account rather than the bootstrap one."""
    creds = account_store.get_credentials(email)
    if not creds:
        raise HTTPException(400, f"Không tìm thấy hoặc không giải mã được tài khoản {email}.")
    return {"x-capcut-email": creds["email"], "x-capcut-password": creds["password"]}


# ── account management ──────────────────────────────────────────────────────
@router.get("/accounts")
async def list_accounts():
    """The user's CapCut accounts (no passwords)."""
    return {"accounts": account_store.list_masked(),
            "server_running": node_manager.is_running()}


@router.post("/accounts")
async def add_account(req: AddAccountRequest):
    res = account_store.add(req.email, req.password, req.label)
    if res["status"] == "error":
        raise HTTPException(400, res["message"])
    return res


@router.delete("/accounts/{email}")
async def remove_account(email: str):
    res = account_store.remove(email)
    if res["status"] == "error":
        raise HTTPException(404, res["message"])
    # If the removed account was the bootstrap, the running server is now on a
    # stale account — restart it on the next call.
    node_manager.stop()
    return res


@router.post("/accounts/{email}/toggle")
async def toggle_account(email: str, enabled: bool = True):
    res = account_store.set_enabled(email, enabled)
    if res["status"] == "error":
        raise HTTPException(404, res["message"])
    node_manager.stop()   # bootstrap set may have changed
    return res


@router.post("/accounts/{email}/test")
async def test_account(email: str):
    """Verify an account by synthesizing a one-word sample through it."""
    base = _ensure_node()
    headers = _account_headers(email)
    try:
        r = requests.post(f"{base}/v2/synthesize",
                          headers={**headers, "Content-Type": "application/json"},
                          json={"text": "xin chào", "speed": 10, "volume": 10}, timeout=60)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("audio"):
            account_store.record_use(email)
            return {"status": "success", "message": "Tài khoản hoạt động, tổng hợp thử thành công."}
        account_store.record_use(email, error=f"HTTP {r.status_code}")
        return {"status": "error", "message": f"CapCut trả lỗi {r.status_code}: {r.text[:160]}"}
    except Exception as e:
        account_store.record_use(email, error=str(e))
        raise HTTPException(502, f"Không gọi được CapCut: {e}")


# ── proxy: catalogue ────────────────────────────────────────────────────────
@router.get("/languages")
async def languages():
    """Available languages (served by the bootstrap account on the Node build)."""
    base = _ensure_node()
    try:
        r = requests.get(f"{base}/v2/languages", timeout=15)
        return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception as e:
        raise HTTPException(502, str(e))


@router.get("/speakers")
async def speakers(email: str, language: str = "", category: str = ""):
    """Voices available to a given account, optionally filtered."""
    base = _ensure_node()
    headers = _account_headers(email)
    params = {}
    if language:
        params["language"] = language
    if category:
        params["category"] = category
    try:
        r = requests.get(f"{base}/v2/speakers", headers=headers, params=params, timeout=20)
        return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception as e:
        raise HTTPException(502, str(e))


@router.get("/preview/{speaker_id}")
async def preview(speaker_id: str):
    """A short sample of a voice (bootstrap account on the Node build)."""
    base = _ensure_node()
    try:
        r = requests.get(f"{base}/v2/speakers/{speaker_id}/preview", timeout=60)
        if r.status_code != 200:
            raise HTTPException(r.status_code, r.text[:200])
        return Response(content=r.content, media_type=r.headers.get("content-type", "audio/mpeg"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


# ── proxy: synthesize (the main endpoint) ───────────────────────────────────
@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    """Turn text into speech using the chosen account, save the mp3, return it."""
    if not req.text.strip():
        raise HTTPException(400, "Chưa nhập nội dung cần đọc.")
    base = _ensure_node()
    headers = _account_headers(req.email)
    body = {"text": req.text, "speed": req.speed, "volume": req.volume, "method": "buffer"}
    if req.speaker:
        body["speaker"] = req.speaker
    try:
        r = requests.post(f"{base}/v2/synthesize",
                          headers={**headers, "Content-Type": "application/json"},
                          json=body, timeout=180)
    except Exception as e:
        account_store.record_use(req.email, error=str(e))
        raise HTTPException(502, f"Không gọi được CapCut: {e}")
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("audio"):
        account_store.record_use(req.email, error=f"HTTP {r.status_code}")
        detail = r.text[:200] if r.text else f"HTTP {r.status_code}"
        raise HTTPException(502, f"CapCut không trả về audio: {detail}")
    # Save to the history dir.
    fname = f"tts_{int(time.time())}.mp3"
    (_output_dir() / fname).write_bytes(r.content)
    account_store.record_use(req.email)
    return Response(
        content=r.content, media_type="audio/mpeg",
        headers={"Content-Disposition": f'inline; filename="{fname}"',
                 "X-CapCut-File": fname},
    )


# ── history ─────────────────────────────────────────────────────────────────
@router.get("/history")
async def history():
    """Recently synthesized files, newest first."""
    out = _output_dir()
    items = []
    for f in sorted(out.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
        st = f.stat()
        items.append({"file": f.name, "size": st.st_size, "created": int(st.st_mtime)})
    return {"items": items}


@router.get("/history/{filename}")
async def history_file(filename: str):
    """Serve one saved mp3, path-traversal guarded."""
    out = _output_dir().resolve()
    try:
        target = (out / filename).resolve()
        target.relative_to(out)
    except (ValueError, OSError):
        raise HTTPException(404, "Không tìm thấy file.")
    if not target.is_file():
        raise HTTPException(404, "Không tìm thấy file.")
    return FileResponse(str(target), media_type="audio/mpeg")


@router.delete("/history/{filename}")
async def delete_history(filename: str):
    out = _output_dir().resolve()
    try:
        target = (out / filename).resolve()
        target.relative_to(out)
    except (ValueError, OSError):
        raise HTTPException(404, "Không tìm thấy file.")
    if target.is_file():
        target.unlink()
        return {"status": "success"}
    raise HTTPException(404, "Không tìm thấy file.")


# ── server status / control ─────────────────────────────────────────────────
@router.get("/status")
async def status():
    return {
        "built": node_manager.is_built(),
        "running": node_manager.is_running(),
        "port": node_manager.port,
        "accounts": account_store.count_enabled(),
    }


@router.post("/server/restart")
async def restart_server():
    node_manager.stop()
    bootstrap = account_store.bootstrap_account()
    if not bootstrap:
        raise HTTPException(400, "Chưa có tài khoản CapCut nào.")
    res = node_manager.start(bootstrap)
    if res.get("status") != "success":
        raise HTTPException(503, res.get("message", "Không khởi động được."))
    return {"status": "success", "port": res.get("port")}


# ── UI page ─────────────────────────────────────────────────────────────────
@router.get("/page")
async def page():
    f = os.path.join(STATIC_DIR, "capcut.html")
    if os.path.exists(f):
        return FileResponse(f, media_type="text/html")
    raise HTTPException(404, "UI chưa sẵn sàng.")
