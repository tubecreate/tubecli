"""API Content DNA — tiền tố /api/v1/content-dna; trang người dùng /content-dna.

Câu lỗi trả về viết tiếng Anh (trang dịch sang chín thứ tiếng; câu lỗi hiện nguyên văn ở dòng trạng thái).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from . import apply, learn, store

router = APIRouter(prefix="/api/v1/content-dna", tags=["content_dna"])
page_router = APIRouter(tags=["content_dna_ui"])

EXT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(EXT_DIR, "static")
MAX_FILE = 20 * 1024 * 1024
MAX_FILES = 200


def _get_or_404(did: str) -> Dict[str, Any]:
    rec = store.get(did)
    if not rec:
        raise HTTPException(404, f"no content DNA '{did}'")
    return rec


@router.get("")
def list_dna():
    return {"items": store.list_all()}


@router.get("/agents")
def list_agents():
    """Agent nào học được (model của agent làm việc đúc ADN)."""
    from tubecli.core.agent import agent_manager
    rows = [{"id": a.id, "name": a.name, "model": str(getattr(a, "model", "") or "")}
            for a in getattr(agent_manager, "agents", {}).values()]
    return {"agents": sorted(rows, key=lambda r: (not r["model"], str(r["name"]).lower()))}


@router.post("/learn")
async def start_learn(name: str = Form(...), agent_id: str = Form(""), texts: str = Form(""),
                      links: str = Form(""), dna_id: str = Form(""),
                      files: Optional[List[UploadFile]] = File(None)):
    if dna_id and not store.get(dna_id):
        raise HTTPException(404, f"no content DNA '{dna_id}' to learn again")
    got = []
    for f in (files or [])[:MAX_FILES]:
        data = await f.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise HTTPException(413, f"{f.filename}: larger than {MAX_FILE // (1024 * 1024)} MB")
        got.append((f.filename or "file.txt", data))
    link_list = [l for l in str(links or "").replace(",", "\n").splitlines() if l.strip()]
    if not (texts.strip() or got or link_list):
        raise HTTPException(400, "add some samples: paste text, upload files or give YouTube links")
    jid = learn.start_job(name=name, agent_id=agent_id, texts=[texts] if texts.strip() else [], files=got,
                          links=link_list, dna_id=dna_id)
    return {"ok": True, "job": jid}


@router.get("/jobs/{jid}")
def job_status(jid: str):
    j = learn.get_job(jid)
    if not j:
        raise HTTPException(404, "no such learning job (the server may have restarted)")
    return j


@router.post("/jobs/{jid}/cancel")
def job_cancel(jid: str):
    return {"ok": learn.cancel_job(jid)}


@router.get("/{did}")
def get_dna(did: str):
    rec = _get_or_404(did)
    return dict(rec, versions=store.versions(did), usual_words=store.usual_words(rec))


@router.put("/{did}")
def update_dna(did: str, body: Dict[str, Any] = Body(...)):
    rec = dict(_get_or_404(did))
    if "name" in body:
        name = " ".join(str(body.get("name") or "").split())[:120]
        if not name:
            raise HTTPException(400, "the DNA needs a name")
        rec["name"] = name
    if "dna" in body:
        dna = store.normalize(body.get("dna"))
        if not dna["formats"]:
            raise HTTPException(400, "the structure needs at least one beat")
        rec["dna"] = dna
        rec["language"] = dna.get("language") or rec.get("language") or ""
    return store.save(rec)


@router.delete("/{did}")
def delete_dna(did: str):
    _get_or_404(did)
    return {"ok": store.delete(did)}


@router.get("/{did}/prompt")
def preview_prompt(did: str, words: int = Query(800, ge=60, le=20000), structure: bool = True):
    """Đúng khối chữ người viết kịch bản nhận — để xem ADN «nói» gì với AI trước khi dùng."""
    rec = _get_or_404(did)
    return {"words": words, "prompt": apply.prompt_block(rec, words, structure)}


# ── trang người dùng ───────────────────────────────────────────────────────

def _asset_version() -> str:
    try:
        return str(int(max(os.path.getmtime(os.path.join(STATIC_DIR, f)) for f in ("app.js", "app.css"))))
    except (OSError, ValueError):
        return "0"


@page_router.get("/content-dna", include_in_schema=False, response_class=HTMLResponse)
def dna_page():
    p = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(p):
        return HTMLResponse("<h1>Content DNA</h1><p>static/index.html is missing.</p>", status_code=500)
    with open(p, encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(html.replace("__ASSET_VER__", _asset_version()),
                        headers={"Cache-Control": "no-store, must-revalidate"})


@page_router.get("/content-dna-static/{filepath:path}", include_in_schema=False)
def dna_static(filepath: str, v: str = Query("")):
    root = os.path.abspath(STATIC_DIR)
    full = os.path.abspath(os.path.join(root, filepath))
    if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
        raise HTTPException(404, f"no such static file: {filepath}")
    return FileResponse(full, headers={"Cache-Control": "public, max-age=31536000, immutable" if v else "no-store"})


__all__ = ["router", "page_router"]
