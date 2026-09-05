"""Lõi của Kho nguyên liệu: bộ sưu tập ảnh, video, GIF dùng chung.

Ý tưởng: mọi extension đều cần một túi nguyên liệu — Thumbnail Studio cần ảnh
cho lớp, Content Studio cần avatar, video editor cần chèn cảnh. Trước đây mỗi
extension tự đẻ một kho riêng, nên cùng một tấm ảnh phải tải lên năm lần và
sửa một chỗ thì bốn chỗ kia vẫn cũ.

Kho ở đây là **một cấp**: bộ sưu tập có tên, bên trong là file. Không có cây thư
mục lồng nhau — người dùng cần "kho avatar nam", "kho nền đỏ", chứ không cần
một hệ thống thư mục thứ hai bên cạnh File Manager.

Ba kiểu bốc, giống hệt cách Thumbnail Studio đã làm cho lớp:
  * `random` — bốc ngẫu nhiên mỗi lần dùng;
  * `cycle`  — đi hết kho rồi mới lặp, để hai lần dùng liên tiếp không trùng;
  * `ai`     — người gọi đưa sẵn tên file mà model đã chọn.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import threading
import time
import unicodedata
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("MediaLibrary")

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
GIF_EXT = (".gif",)
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv", ".m4v")
ALL_EXT = IMAGE_EXT + GIF_EXT + VIDEO_EXT

KIND_IMAGE, KIND_GIF, KIND_VIDEO = "image", "gif", "video"

_lock = threading.RLock()
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_ID_OK = re.compile(r"[^a-z0-9_]+")

MAX_NAME = 80


def data_dir() -> str:
    try:
        from tubecli.config import EXTENSIONS_DATA_DIR
        base = os.path.join(str(EXTENSIONS_DATA_DIR), "media_library")
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".tubecli", "media_library")
    os.makedirs(base, exist_ok=True)
    return base


def _meta_path() -> str:
    return os.path.join(data_dir(), "collections.json")


def safe_id(text: str, fallback: str = "collection") -> str:
    """Tên có dấu → định danh ASCII dùng làm tên thư mục.

    Thư mục đặt theo `id` chứ không theo tên hiển thị, và `id` không bao giờ
    đổi theo tên. T2Render dùng tên hiển thị làm khoá thư mục và phải trả giá:
    đổi tên là phải đổi cả thư mục, mà Windows thì khoá thư mục đang mở.
    """
    s = str(text or "").strip().lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = _ID_OK.sub("_", s).strip("_")
    return s[:60] or fallback


def kind_of(filename: str) -> str:
    ext = os.path.splitext(str(filename or ""))[1].lower()
    if ext in GIF_EXT:
        return KIND_GIF
    if ext in VIDEO_EXT:
        return KIND_VIDEO
    return KIND_IMAGE


def _load_meta() -> Dict[str, dict]:
    try:
        with open(_meta_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_meta(meta: Dict[str, dict]) -> None:
    tmp = _meta_path() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _meta_path())
    except OSError as ex:
        logger.warning("cannot save collections.json: %s", ex)


def collection_dir(cid: str) -> str:
    """Thư mục của một kho. Chặn thoát ra ngoài — đây là chỗ người dùng tải file
    lên, nên là ranh giới thật chứ không phải lễ nghi."""
    root = os.path.abspath(data_dir())
    cid = safe_id(cid, "")
    if not cid:
        raise ValueError("collection id is empty")
    full = os.path.abspath(os.path.join(root, cid))
    if not full.startswith(root + os.sep):
        raise ValueError(f"collection path escapes data dir: {cid!r}")
    return full


# ── bộ sưu tập ─────────────────────────────────────────────────────────────

def create(name: str, *, description: str = "", cid: str = "") -> dict:
    with _lock:
        meta = _load_meta()
        # Tên toàn chữ phi Latinh (Nhật, Hàn, Trung, Nga…) rụng hết sau khi lọc
        # về ASCII, nên phải có đường lui. Đường lui là TỪ TIẾNG ANH: mã kho là
        # định danh, người Nhật đặt tên kho tiếng Nhật mà nhận về "kho_2" thì đó
        # là tiếng Việt lọt vào chỗ không ai chờ.
        base = safe_id(cid or name, "collection")
        new_id, n = base, 2
        while new_id in meta:
            new_id, n = f"{base}_{n}", n + 1
        meta[new_id] = {
            "id": new_id,
            "name": (name or new_id).strip()[:MAX_NAME],
            "description": str(description or "").strip()[:400],
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        _save_meta(meta)
    os.makedirs(collection_dir(new_id), exist_ok=True)
    return dict(meta[new_id])


def rename(cid: str, *, name: str = "", description: Optional[str] = None) -> Optional[dict]:
    """Đổi tên hiển thị. KHÔNG đụng tới thư mục — `id` là bất biến."""
    with _lock:
        meta = _load_meta()
        c = meta.get(safe_id(cid, ""))
        if not c:
            return None
        if name:
            c["name"] = name.strip()[:MAX_NAME]
        if description is not None:
            c["description"] = str(description).strip()[:400]
        c["updated_at"] = time.time()
        _save_meta(meta)
        return dict(c)


def delete(cid: str, *, with_files: bool = True) -> bool:
    cid = safe_id(cid, "")
    with _lock:
        meta = _load_meta()
        if cid not in meta:
            return False
        meta.pop(cid)
        _save_meta(meta)
    if with_files:
        try:
            shutil.rmtree(collection_dir(cid), ignore_errors=True)
        except ValueError:
            pass
    return True


def get(cid: str) -> Optional[dict]:
    c = _load_meta().get(safe_id(cid, ""))
    if not c:
        return None
    out = dict(c)
    out.update(_stats(out["id"]))
    return out


def list_all() -> List[dict]:
    """Mọi kho, kèm số file và ảnh bìa. Kho mới sửa gần nhất lên đầu."""
    out = []
    for c in _load_meta().values():
        d = dict(c)
        d.update(_stats(d.get("id") or ""))
        out.append(d)
    out.sort(key=lambda x: -(x.get("updated_at") or 0))
    return out


def _stats(cid: str) -> dict:
    files = list_files(cid)
    kinds: Dict[str, int] = {}
    for f in files:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    return {"count": len(files), "kinds": kinds,
            "cover": files[0]["name"] if files else ""}


# ── file trong kho ─────────────────────────────────────────────────────────

def list_files(cid: str) -> List[dict]:
    """File trong kho, sắp xếp ổn định theo tên.

    Thứ tự phải ổn định vì `cycle` nhớ vị trí theo CHỈ SỐ: thứ tự nhảy là con
    trỏ trỏ sang tấm khác, tức chế độ xoay vòng hỏng một cách âm thầm.
    """
    try:
        d = collection_dir(cid)
    except ValueError:
        return []
    try:
        names = [n for n in os.listdir(d)
                 if not n.startswith(".") and n.lower().endswith(ALL_EXT)]
    except OSError:
        return []
    out = []
    for n in sorted(names, key=lambda s: s.lower()):
        p = os.path.join(d, n)
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        out.append({"name": n, "kind": kind_of(n), "bytes": size})
    return out


def add_file(cid: str, filename: str, blob: bytes) -> str:
    """Thêm file. Trùng tên thì thêm số — ghi đè im lặng là cách nhanh nhất để
    người dùng mất một tấm mà không biết."""
    d = collection_dir(cid)
    os.makedirs(d, exist_ok=True)
    base = os.path.basename(str(filename or "file"))
    stem, ext = os.path.splitext(base)
    ext = ext.lower() if ext.lower() in ALL_EXT else ".png"
    stem = _UNSAFE.sub("_", stem).strip("._") or "file"
    name, n = f"{stem}{ext}", 2
    while os.path.exists(os.path.join(d, name)):
        name, n = f"{stem}_{n}{ext}", n + 1
    with open(os.path.join(d, name), "wb") as f:
        f.write(blob)
    _touch(cid)
    return name


def import_path(cid: str, src: str) -> Optional[str]:
    """Chép một file đã có trên máy vào kho. Dùng khi người dùng kéo từ File
    Manager sang, khỏi phải tải lên lại thứ đã nằm sẵn trên đĩa."""
    if not os.path.isfile(src):
        return None
    try:
        with open(src, "rb") as f:
            return add_file(cid, os.path.basename(src), f.read())
    except OSError as ex:
        logger.warning("cannot import %s: %s", src, ex)
        return None


def delete_file(cid: str, filename: str) -> bool:
    try:
        d = collection_dir(cid)
    except ValueError:
        return False
    p = os.path.join(d, os.path.basename(str(filename or "")))
    if not os.path.isfile(p):
        return False
    try:
        os.remove(p)
    except OSError as ex:
        logger.warning("cannot delete %s: %s", p, ex)
        return False
    _touch(cid)
    return True


def file_path(cid: str, filename: str) -> Optional[str]:
    try:
        d = collection_dir(cid)
    except ValueError:
        return None
    p = os.path.join(d, os.path.basename(str(filename or "")))
    return p if os.path.isfile(p) else None


def _touch(cid: str) -> None:
    with _lock:
        meta = _load_meta()
        c = meta.get(safe_id(cid, ""))
        if c:
            c["updated_at"] = time.time()
            _save_meta(meta)


# ── bốc ────────────────────────────────────────────────────────────────────

def _cursor_path() -> str:
    return os.path.join(data_dir(), "cycle.json")


def _cursors() -> Dict[str, int]:
    try:
        with open(_cursor_path(), encoding="utf-8") as f:
            d = json.load(f)
        return {str(k): int(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def peek_cycle(cid: str) -> int:
    files = list_files(cid)
    if not files:
        return -1
    with _lock:
        return _cursors().get(safe_id(cid, ""), 0) % len(files)


def pick(cid: str, mode: str = "random", *, commit: bool = True,
         chosen: str = "", kind: str = "",
         rng: Optional[random.Random] = None) -> Tuple[str, str]:
    """Bốc một file. Trả (đường dẫn tuyệt đối, lý do).

    Kho rỗng trả ("", lý do) chứ không ném lỗi: người gọi phải còn ra được sản
    phẩm, cùng lắm là thiếu một lớp.
    """
    files = list_files(cid)
    if kind:
        files = [f for f in files if f["kind"] == kind]
    if not files:
        return "", ("collection is empty" if not kind
                    else f"collection has no {kind}")
    try:
        d = collection_dir(cid)
    except ValueError as ex:
        return "", str(ex)
    names = [f["name"] for f in files]

    if mode == "ai" and chosen:
        want = os.path.basename(str(chosen)).strip().lower()
        for n in names:
            if n.lower() == want:
                return os.path.join(d, n), f"AI picked {n}"
        return os.path.join(d, names[0]), \
            f"AI asked for {chosen!r}, not here; fell back to {names[0]}"

    if mode == "cycle":
        key = safe_id(cid, "") + ("/" + kind if kind else "")
        with _lock:
            cur = _cursors()
            i = cur.get(key, 0) % len(names)
            if commit:
                cur[key] = (i + 1) % len(names)
                tmp = _cursor_path() + ".tmp"
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(cur, f)
                    os.replace(tmp, _cursor_path())
                except OSError:
                    pass
        return os.path.join(d, names[i]), f"cycle {i + 1}/{len(names)}"

    r = rng or random
    return os.path.join(d, r.choice(names)), f"random 1/{len(names)}"


def stats() -> dict:
    cols = list_all()
    return {"collections": len(cols),
            "files": sum(c.get("count", 0) for c in cols),
            "dir": data_dir()}


__all__ = ["create", "rename", "delete", "get", "list_all", "list_files",
           "add_file", "import_path", "delete_file", "file_path", "pick",
           "peek_cycle", "collection_dir", "data_dir", "safe_id", "kind_of",
           "stats", "ALL_EXT", "IMAGE_EXT", "VIDEO_EXT", "GIF_EXT",
           "KIND_IMAGE", "KIND_GIF", "KIND_VIDEO"]
