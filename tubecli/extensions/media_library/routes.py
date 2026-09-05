"""API của Media Library — tiền tố /api/v1/media.

Câu lỗi trả về viết tiếng Anh: trang hiện nguyên phần thân lỗi ra dòng trạng
thái, mà trang thì đã dịch sang chín thứ tiếng — nhét một câu tiếng Việt vào
giữa giao diện tiếng Hàn là chỗ duy nhất còn lệch.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from . import library

logger = logging.getLogger("MediaLibrary.routes")

router = APIRouter(prefix="/api/v1/media", tags=["media_library"])
# Router thứ hai, không tiền tố: trang người dùng và file tĩnh của nó. TubeCLI
# không tự phục vụ thư mục static của extension, mỗi extension phải tự khai.
page_router = APIRouter(tags=["media_library_ui"])

EXT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(EXT_DIR, "static")
MAX_UPLOAD = 200 * 1024 * 1024      # video cũng vào đây, nên rộng tay hơn ảnh


@router.get("/collections")
def list_collections():
    return {"collections": library.list_all(), "stats": library.stats()}


@router.post("/collections")
def create_collection(body: Dict[str, Any] = Body(...)):
    name = str((body or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(400, "the collection needs a name")
    return {"ok": True, "collection": library.create(
        name, description=str((body or {}).get("description") or ""))}


@router.get("/collections/{cid}")
def get_collection(cid: str):
    c = library.get(cid)
    if not c:
        raise HTTPException(404, f"no collection '{cid}'")
    c["files"] = library.list_files(cid)
    c["cursor"] = library.peek_cycle(cid)
    return c


@router.put("/collections/{cid}")
def rename_collection(cid: str, body: Dict[str, Any] = Body(...)):
    c = library.rename(cid, name=str((body or {}).get("name") or ""),
                       description=(body or {}).get("description"))
    if not c:
        raise HTTPException(404, f"no collection '{cid}'")
    return {"ok": True, "collection": c}


@router.delete("/collections/{cid}")
def delete_collection(cid: str, keep_files: bool = Query(False)):
    if not library.delete(cid, with_files=not keep_files):
        raise HTTPException(404, f"no collection '{cid}'")
    return {"ok": True}


@router.post("/collections/{cid}/files")
async def upload_file(cid: str, file: UploadFile = File(...)):
    if not library.get(cid):
        raise HTTPException(404, f"no collection '{cid}'")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "the file is empty")
    if len(blob) > MAX_UPLOAD:
        raise HTTPException(413, f"the file is larger than {MAX_UPLOAD // (1024 * 1024)} MB")
    name = file.filename or "file"
    if not name.lower().endswith(library.ALL_EXT):
        raise HTTPException(400, "only images, GIFs or videos are accepted")
    saved = library.add_file(cid, name, blob)
    return {"ok": True, "name": saved, "kind": library.kind_of(saved)}


@router.post("/collections/{cid}/import")
def import_file(cid: str, body: Dict[str, Any] = Body(...)):
    """Chép một file đã nằm sẵn trên máy vào kho, khỏi tải lên lại."""
    if not library.get(cid):
        raise HTTPException(404, f"no collection '{cid}'")
    src = str((body or {}).get("path") or "")
    name = library.import_path(cid, src)
    if not name:
        raise HTTPException(400, f"could not read the file: {src}")
    return {"ok": True, "name": name}


@router.delete("/collections/{cid}/files/{filename}")
def remove_file(cid: str, filename: str):
    if not library.delete_file(cid, filename):
        raise HTTPException(404, "no such file in the collection")
    return {"ok": True}


@router.get("/collections/{cid}/files/{filename}")
def serve_file(cid: str, filename: str):
    p = library.file_path(cid, filename)
    if not p:
        raise HTTPException(404, "no such file")
    return FileResponse(p)


@router.post("/collections/{cid}/pick")
def pick_file(cid: str, body: Dict[str, Any] = Body(default={})):
    """Bốc một file theo luật. Mặc định KHÔNG dời con trỏ xoay vòng: xem trước
    mà làm kho nhảy một tấm mỗi lần thì chế độ xoay vòng thành vô nghĩa."""
    body = body or {}
    if not library.get(cid):
        raise HTTPException(404, f"no collection '{cid}'")
    path, why = library.pick(cid, str(body.get("mode") or "random"),
                             commit=bool(body.get("commit", False)),
                             chosen=str(body.get("file") or ""),
                             kind=str(body.get("kind") or ""))
    return {"file": os.path.basename(path) if path else "", "why": why,
            "path": path, "collection": cid}


@router.get("/health")
def health():
    return {"ok": True, **library.stats()}


# ── trang người dùng ───────────────────────────────────────────────────────

@page_router.get("/media-library", include_in_schema=False, response_class=HTMLResponse)
def media_page():
    p = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(p):
        return HTMLResponse("<h1>Media Library</h1><p>static/index.html is missing.</p>",
                            status_code=500)
    with open(p, encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(html.replace("__ASSET_VER__", _asset_version()),
                        headers={"Cache-Control": "no-store, must-revalidate"})


@page_router.get("/media-library-static/{filepath:path}", include_in_schema=False)
def media_static(filepath: str, v: str = Query("")):
    root = os.path.abspath(STATIC_DIR)
    full = os.path.abspath(os.path.join(root, filepath))
    if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
        raise HTTPException(404, f"no such static file: {filepath}")
    cache = "public, max-age=31536000, immutable" if v else "no-store"
    return FileResponse(full, headers={"Cache-Control": cache})


def _asset_version() -> str:
    """Đổi mỗi lần code đổi, để trình duyệt không giữ bản cũ. Đây là bài học đã
    trả giá ở Thumbnail Studio: HTML mới chạy với JS cũ thì chết ngay lúc khởi
    động và không nút nào bấm được."""
    try:
        return str(int(os.path.getmtime(os.path.join(STATIC_DIR, "app.js"))))
    except OSError:
        return "0"


__all__ = ["router", "page_router"]
