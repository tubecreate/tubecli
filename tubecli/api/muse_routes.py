"""/api/v1/muse — Muse (muse.ai, agent AI của Meta) làm nhà cung cấp AI như 9Router.

Hai nhóm route:
  * quản lý: GET status · GET/PUT settings (hồ sơ trình duyệt giữ phiên Muse, số lượt mỗi chat phụ) · POST test
  * cổng chuẩn OpenAI ở /api/v1/muse/v1: GET models · POST chat/completions (cả stream) · POST images/generations
    — cho chỗ nào chỉ biết gọi kiểu OpenAI qua HTTP: Content Studio đọc PROVIDERS["muse"]["base_url"], storyboard
    của «Tạo video từ nội dung» stream qua brain.openai_compat_params. Brain và bộ vẽ ảnh của lõi gọi thẳng
    tubecli.core.muse, không qua HTTP.

Mọi lời gọi Muse chạy trong thread (asyncio.to_thread): mỗi lượt lái trình duyệt mất 5–60 s.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import JSONResponse, StreamingResponse

from tubecli.core import muse

router = APIRouter(prefix="/api/v1/muse", tags=["muse"])

# kind của MuseError → mã HTTP (client kiểu OpenAI đọc mã để biết nên thử lại hay báo cấu hình).
_STATUS = {"config": 400, "refused": 400, "auth": 401, "approval": 409, "busy": 429,
           "browser": 503, "timeout": 504, "error": 502}


def _error(e: "muse.MuseError") -> JSONResponse:
    return JSONResponse(status_code=_STATUS.get(e.kind, 502),
                        content={"error": {"message": f"Muse: {e}", "type": "muse_" + e.kind, "code": e.kind}})


def _profile_names() -> List[str]:
    """Tên hồ sơ trình duyệt để chọn (bỏ bản '<tên>_bas' — anh em của hồ sơ chính, không chọn riêng)."""
    try:
        root = muse._profiles_dir()
        return sorted(n for n in os.listdir(root)
                      if os.path.isdir(os.path.join(root, n)) and not n.endswith("_bas"))
    except Exception:      # noqa: BLE001
        return []


class MuseSettingsRequest(BaseModel):
    profile: Optional[str] = None          # None = giữ nguyên; "" = bỏ chọn
    turns_per_chat: Optional[int] = None
    extra_profiles: Optional[List[str]] = None   # tài khoản Muse PHỤ (mỗi hồ sơ một tài khoản) — vẽ song song
    lanes: Optional[int] = None                  # lượt cùng lúc MỖI tài khoản (1 = an toàn)
    remotes: Optional[List[dict]] = None         # nút Muse từ xa [{base_url, key, seats}] («giống 9Router», 9/10/2026)
    node_key: Optional[str] = None               # khoá để MÁY KHÁC gọi /api/v1/muse/v1/* của máy này


@router.get("/status")
async def api_status():
    return await asyncio.to_thread(muse.status)


def _public_settings() -> dict:
    """Cài đặt cho giao diện: khoá nút từ xa che bớt, khoá node chỉ báo có/không + 4 ký tự cuối."""
    st = muse.settings()
    st["remotes"] = [{**r, "key": (r["key"][:3] + "…" + r["key"][-3:]) if len(r.get("key") or "") > 8 else ("…" if r.get("key") else "")}
                     for r in st.get("remotes") or []]
    nk = st.pop("node_key", "")
    st["node_key_set"] = bool(nk)
    st["node_key_tail"] = nk[-4:] if nk else ""
    return st


@router.get("/settings")
async def api_get_settings():
    return {**_public_settings(), "profiles": _profile_names(),
            "default_turns_per_chat": muse.DEFAULT_TURNS_PER_CHAT, "max_turns_per_chat": muse.MAX_TURNS_PER_CHAT,
            "max_lanes": muse.MAX_LANES, "max_remote_seats": muse.MAX_REMOTE_SEATS}


@router.put("/settings")
async def api_put_settings(req: MuseSettingsRequest):
    try:
        remotes = req.remotes
        if remotes is not None:
            # khoá bị che («abc…xyz») gửi lại y nguyên = giữ khoá cũ của nút cùng base_url
            old = {r["base_url"]: r.get("key", "") for r in muse.settings().get("remotes") or []}
            fixed = []
            for r in remotes:
                if not isinstance(r, dict):
                    continue
                r = dict(r)
                url = str(r.get("base_url") or r.get("url") or "").strip().rstrip("/")
                if "…" in str(r.get("key") or "") and url in old:
                    r["key"] = old[url]
                fixed.append(r)
            remotes = fixed
        muse.set_settings(profile=req.profile, turns_per_chat=req.turns_per_chat,
                          extra_profiles=req.extra_profiles, lanes=req.lanes, remotes=remotes, node_key=req.node_key)
        return _public_settings()
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/node-key")
async def api_new_node_key():
    """Tạo khoá node mới (máy khác dùng để gọi Muse của máy này) — trả khoá MỘT lần."""
    import secrets
    key = secrets.token_urlsafe(24)
    muse.set_settings(node_key=key)
    return {"node_key": key}


@router.post("/test")
async def api_test():
    return await asyncio.to_thread(muse.test_chat)


# ── cổng chuẩn OpenAI ─────────────────────────────────────────────────────────

@router.get("/v1/models")
async def api_models():
    rows = [{"id": m, "object": "model", "created": 0, "owned_by": "muse", "type": "chat"} for m in muse.CHAT_MODELS]
    rows += [{"id": m, "object": "model", "created": 0, "owned_by": "muse", "type": "image"} for m in muse.IMAGE_MODELS]
    return {"object": "list", "data": rows}


class ChatRequest(BaseModel):
    model: str = muse.CHAT_MODEL
    messages: List[Any] = []
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    class Config:
        extra = "allow"


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@router.post("/v1/chat/completions")
async def api_chat_completions(req: ChatRequest):
    if not req.messages:
        return JSONResponse(status_code=400, content={"error": {"message": "messages is required",
                                                                 "type": "invalid_request_error"}})
    # Chờ trả lời XONG rồi mới mở luồng: hỏng thì còn trả đúng mã lỗi (401/429/504…) thay vì một luồng 200
    # chứa câu lỗi mà phía gọi đem đi parse như kịch bản. Client đọc tối đa 600 s, Muse ít khi quá 300 s.
    try:
        text = await asyncio.to_thread(muse.chat_completion, list(req.messages), req.model or muse.CHAT_MODEL)
    except muse.MuseError as e:
        return _error(e)
    cid = "chatcmpl-muse-" + uuid.uuid4().hex[:12]
    created = int(time.time())
    model = req.model or muse.CHAT_MODEL
    usage = {"prompt_tokens": 0, "completion_tokens": max(1, len(text) // 4), "total_tokens": max(1, len(text) // 4)}
    if not req.stream:
        return {"id": cid, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": usage}

    def chunk(delta: dict, finish=None) -> str:
        return _sse({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                     "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})

    async def gen():
        yield chunk({"role": "assistant", "content": ""})
        for i in range(0, len(text), 400):
            yield chunk({"content": text[i:i + 400]})
        yield chunk({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ImagesRequest(BaseModel):
    reference_images: Optional[List[str]] = None   # nút từ xa gửi ảnh tham chiếu (data URL / base64) — 9/10/2026
    thread_id: str = ""
    prompt: str
    model: str = muse.IMAGE_MODEL
    n: int = 1
    size: Optional[str] = None             # "1792x1024" kiểu OpenAI/9Router — chỉ lấy hướng khung
    aspect_ratio: Optional[str] = None     # "16:9" … thắng size khi có
    response_format: str = "b64_json"


def aspect_from(size: Optional[str], aspect: Optional[str]) -> str:
    if aspect and aspect in muse.ASPECTS:
        return aspect
    try:
        w, h = (int(x) for x in str(size or "").lower().split("x", 1))
    except ValueError:
        return "16:9"
    if w == h:
        return "1:1"
    r = w / h
    if r >= 1.5:
        return "16:9"
    if r > 1:
        return "4:3"
    return "9:16" if r <= 0.67 else "3:4"


def _decode_refs(items) -> list:
    """reference_images (data URL / base64) → file tạm; trả đường dẫn (bên gọi xoá)."""
    import tempfile
    paths = []
    for s in (items or [])[:3]:
        s = str(s or "")
        if "," in s and s.startswith("data:"):
            s = s.split(",", 1)[1]
        try:
            raw = base64.b64decode(s)
        except Exception:      # noqa: BLE001
            continue
        if len(raw) < 100:
            continue
        fd, p = tempfile.mkstemp(prefix="muse_ref_", suffix=".png" if raw[:4] == b"\x89PNG" else ".jpg")
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        paths.append(p)
    return paths


def _drop_files(paths) -> None:
    for p in paths or []:
        try:
            os.remove(p)
        except OSError:
            pass


@router.post("/v1/images/generations")
async def api_images(req: ImagesRequest):
    if not (req.prompt or "").strip():
        return JSONResponse(status_code=400, content={"error": {"message": "prompt is required",
                                                                 "type": "invalid_request_error"}})
    ar = aspect_from(req.size, req.aspect_ratio)
    refs = _decode_refs(req.reference_images)
    out = []
    try:
        for _ in range(max(1, min(4, int(req.n or 1)))):
            if refs or req.thread_id:
                data = await asyncio.to_thread(muse.generate_image_bytes, req.prompt, ar, refs or None,
                                               muse.IMAGE_TIMEOUT, req.thread_id or "")
            else:
                data = await asyncio.to_thread(muse.generate_image_bytes, req.prompt, ar)
            out.append({"b64_json": base64.b64encode(data).decode("ascii"), "revised_prompt": req.prompt})
    except muse.MuseError as e:
        if not out:
            _drop_files(refs)
            return _error(e)
    finally:
        _drop_files(refs)
    return {"created": int(time.time()), "data": out}


class VideosRequest(BaseModel):
    prompt: str = ""
    aspect_ratio: str = "16:9"
    reference_images: Optional[List[str]] = None       # data URL / base64
    thread_id: str = ""
    continue_from: bool = False
    timeout: Optional[int] = None

    class Config:
        extra = "allow"


@router.post("/v1/videos/generations")
async def api_videos(req: VideosRequest):
    """MỘT clip Muse cho máy khác (nút Muse từ xa, 9/10/2026): {data: [{b64_json (mp4), thread_id, width, height,
    duration}]}. Lỗi → {error: {code: kind}} để bên gọi dựng lại MuseError cùng kind."""
    if not (req.prompt or "").strip():
        return JSONResponse(status_code=400, content={"error": {"message": "prompt is required",
                                                                 "type": "invalid_request_error"}})
    refs = _decode_refs(req.reference_images)
    import tempfile
    tmp = tempfile.mkdtemp(prefix="muse_vid_")
    try:
        clip = await asyncio.to_thread(muse.generate_video_clip, req.prompt, tmp, refs, req.aspect_ratio or "16:9",
                                       bool(req.continue_from), req.thread_id or "",
                                       int(req.timeout or muse.VIDEO_TIMEOUT))
        with open(clip["path"], "rb") as f:
            data = f.read()
        return {"created": int(time.time()),
                "data": [{"b64_json": base64.b64encode(data).decode("ascii"), "thread_id": clip.get("thread_id", ""),
                          "width": clip.get("width"), "height": clip.get("height"), "duration": clip.get("duration")}]}
    except muse.MuseError as e:
        return _error(e)
    finally:
        _drop_files(refs)
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:      # noqa: BLE001
            pass
