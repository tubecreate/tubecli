# -*- coding: utf-8 -*-
"""KHO NHÂN VẬT chung của mọi studio (10/10/2026) — cùng nếp với kho MẪU (tubecli.core.templates).

User: «tạo 1 kho để khi tôi làm về nhân vật này có thể lấy để đồng nhất» (Trần Bình An, Kiếm Lai) rồi chọn «kho ở lõi,
mẫu mang dàn»: kho ở lõi cho Content Studio / Pod Studio / Thumbnail Studio cùng đọc; một MẪU mang theo dàn nhân vật
(`cast` = các slug) — chọn mẫu là có đúng nhân vật + sheet; bán mẫu lên Chợ thì gói nhân vật đi kèm.

Mỗi nhân vật một thư mục `DATA_DIR/characters/<slug>/`:
    profile.json  {name, aliases[], series, kind, prompt_name, look (tiếng Anh, dáng CỐ ĐỊNH), personality, notes,
                   style, status ("draft" | "approved"), size, sheet, updated_at}
    sheet.<ext>   reference sheet (chính diện / nghiêng / sau lưng / toàn thân / nét mặt / tư thế / bối cảnh)

Khớp tên theo Unicode (casefold + NFC; chữ Latinh có ranh giới từ, chữ Hán/Nhật/Hàn khớp thẳng).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import threading
import unicodedata
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

PROFILE = "profile.json"
MAX_MATCH = 4
KINDS = ("person", "object", "place")
SHEET_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_LOCK = threading.RLock()
OLD_ROOT = ("content_studio", "character_library")      # kho cũ của Content Studio (10/10/2026, trước khi lên lõi)
_MIGRATED = False
_KEEP = ("name", "aliases", "series", "kind", "prompt_name", "look", "personality", "notes", "style", "status", "size")


def root() -> str:
    global _MIGRATED
    from tubecli import config
    d = os.path.join(str(config.DATA_DIR), "characters")
    os.makedirs(d, exist_ok=True)
    if not _MIGRATED:
        _MIGRATED = True
        old = os.path.join(str(config.DATA_DIR), *OLD_ROOT)
        if os.path.isdir(old):
            try:
                migrate_from(old, d)
            except Exception:      # noqa: BLE001 — kho cũ hỏng thì thôi, kho lõi vẫn chạy
                pass
    return d


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _norm(s: Any) -> str:
    return unicodedata.normalize("NFC", " ".join(str(s or "").split())).casefold()


def _fold(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in s if not unicodedata.combining(c))


def slug_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _fold(name).lower()).strip("_") or "character"


def ascii_name(name: str) -> str:
    """«Trần Bình An» → «Tran Binh An» (tên trong prompt tiếng Anh khi hồ sơ không khai prompt_name)."""
    return " ".join(_fold(name).split())


def _read(d: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(d, PROFILE), encoding="utf-8") as f:
            prof = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(prof, dict) or not prof.get("name"):
        return None
    prof["slug"] = os.path.basename(d)
    sheet = str(prof.get("sheet") or "")
    p = os.path.join(d, sheet) if sheet and not os.path.isabs(sheet) else sheet
    prof["sheet_path"] = p if p and os.path.isfile(p) else ""
    return prof


def load_all(base: Optional[str] = None) -> List[Dict[str, Any]]:
    base = base or root()
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    return [p for p in (_read(os.path.join(base, n)) for n in names) if p]


def get(key: str, base: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Theo slug, tên hay biệt danh."""
    k, ks = _norm(key), slug_of(key)
    for p in load_all(base):
        if p["slug"] == ks or k in names_of(p):
            return p
    return None


def names_of(prof: Dict[str, Any], aliases: bool = True) -> List[str]:
    vals = [prof.get("name"), prof.get("prompt_name")] + (list(prof.get("aliases") or []) if aliases else [])
    seen, out = set(), []
    for v in vals:
        n = _norm(v)
        if n and len(n) >= 2 and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _cjk(s: str) -> bool:
    return any("⺀" <= ch <= "鿿" or "가" <= ch <= "힯" or "぀" <= ch <= "ヿ" for ch in s)


def match(text: str, only: Optional[Iterable[str]] = None, base: Optional[str] = None,
          aliases: bool = True) -> List[Dict[str, Any]]:
    """Nhân vật kho mà `text` nhắc tên / biệt danh, theo thứ tự xuất hiện. only: chỉ xét các slug này (dàn của mẫu).

    aliases=False: chỉ TÊN ĐẦY ĐỦ — dùng khi mẫu không khai dàn: biệt danh hay là chữ thường («Bình An» = bình an),
    kịch bản Lão Tử nói «sống bình an» không được kéo Trần Bình An vào."""
    t = _norm(text)
    keep = {slug_of(x) for x in only} if only else None
    hits = []
    for prof in load_all(base):
        if keep is not None and prof["slug"] not in keep:
            continue
        pos = None
        for n in names_of(prof, aliases):
            m = re.search(re.escape(n) if _cjk(n) else r"(?<!\w)" + re.escape(n) + r"(?!\w)", t)
            if m and (pos is None or m.start() < pos):
                pos = m.start()
        if pos is not None:
            hits.append((pos, prof))
    hits.sort(key=lambda x: x[0])
    return [p for _, p in hits][:MAX_MATCH]


def as_canon(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Hồ sơ → thực thể canon (cùng dạng canon.build của Content Studio): tên = prompt_name, canon = look, sheet sẵn."""
    out = []
    for p in profiles or []:
        look = " ".join(str(p.get("look") or "").split())
        if len(look.split()) < 8:
            continue
        e = {"name": str(p.get("prompt_name") or ascii_name(p["name"])),
             "kind": p.get("kind") if p.get("kind") in KINDS else "person",
             "shot_ids": [], "paragraphs": [], "canon": look, "size": str(p.get("size") or ""),
             "from": "library", "library": p.get("slug", ""), "aliases": [p["name"]] + list(p.get("aliases") or [])}
        if p.get("sheet_path"):
            e["sheet"] = p["sheet_path"]
        out.append(e)
    return out


def _write_sheet(d: str, src: str = "", data_url: str = "") -> str:
    """Chép ảnh (đường dẫn hay data URL base64) thành sheet.<ext> trong thư mục nhân vật; trả tên file ("" nếu không có)."""
    if src:
        ext = os.path.splitext(src)[1].lower()
        if ext not in SHEET_EXTS:
            raise ValueError(f"sheet must be an image ({', '.join(SHEET_EXTS)})")
        if not os.path.isfile(src):
            raise ValueError(f"sheet not found: {src}")
        dst = os.path.join(d, "sheet" + ext)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
        return "sheet" + ext
    if data_url:
        m = re.match(r"data:image/(png|jpe?g|webp);base64,(.+)$", str(data_url), re.S)
        if not m:
            raise ValueError("sheet_data must be a data:image/png|jpeg|webp;base64 URL")
        ext = ".jpg" if m.group(1).startswith("jp") else "." + m.group(1)
        with open(os.path.join(d, "sheet" + ext), "wb") as f:
            f.write(base64.b64decode(m.group(2)))
        return "sheet" + ext
    return ""


def save(prof: Dict[str, Any], sheet_src: str = "", sheet_data: str = "", base: Optional[str] = None) -> Dict[str, Any]:
    """Thêm / sửa một nhân vật (slug theo tên, hoặc `slug` có sẵn). Gộp trường với hồ sơ cũ."""
    base = base or root()
    name = " ".join(str(prof.get("name") or "").split())
    if not name:
        raise ValueError("name is required")
    slug = slug_of(prof.get("slug") or name)
    d = os.path.join(base, slug)
    with _LOCK:
        os.makedirs(d, exist_ok=True)
        cur = _read(d) or {}
        cur.pop("slug", None)
        cur.pop("sheet_path", None)
        new = {**cur, **{k: prof[k] for k in _KEEP if k in prof}}
        new["name"] = name
        new["aliases"] = [" ".join(str(a).split()) for a in (new.get("aliases") or []) if str(a).strip()]
        new.setdefault("prompt_name", ascii_name(name))
        new.setdefault("status", "draft")
        if new.get("kind") not in KINDS:
            new["kind"] = "person"
        sheet = _write_sheet(d, sheet_src, sheet_data)
        if sheet:
            new["sheet"] = sheet
        new["updated_at"] = _now()
        tmp = os.path.join(d, PROFILE + ".part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(d, PROFILE))
    return _read(d) or new


def delete(key: str, base: Optional[str] = None) -> bool:
    p = get(key, base)
    if not p:
        return False
    with _LOCK:
        shutil.rmtree(os.path.join(base or root(), p["slug"]), ignore_errors=True)
    return True


def bundle(slugs: Iterable[str], base: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gói nhân vật đi kèm mẫu khi bán lên Chợ: [{profile, sheet_data}] — sheet nhúng base64."""
    out = []
    for s in slugs or []:
        p = get(s, base)
        if not p:
            continue
        prof = {k: p[k] for k in _KEEP if k in p}
        prof["slug"] = p["slug"]
        item = {"profile": prof, "sheet_data": ""}
        if p.get("sheet_path"):
            ext = os.path.splitext(p["sheet_path"])[1].lower().lstrip(".").replace("jpg", "jpeg")
            with open(p["sheet_path"], "rb") as f:
                item["sheet_data"] = f"data:image/{ext};base64," + base64.b64encode(f.read()).decode("ascii")
        out.append(item)
    return out


def install_bundle(items: List[Dict[str, Any]], base: Optional[str] = None, overwrite: bool = False) -> List[str]:
    """Cài gói nhân vật kèm mẫu từ Chợ. Nhân vật đã có (cùng slug) thì GIỮ bản máy này trừ khi overwrite."""
    done = []
    for it in items or []:
        prof = dict((it or {}).get("profile") or {})
        if not prof.get("name"):
            continue
        slug = slug_of(prof.get("slug") or prof["name"])
        if get(slug, base) and not overwrite:
            done.append(slug)
            continue
        save({**prof, "slug": slug}, sheet_data=str((it or {}).get("sheet_data") or ""), base=base)
        done.append(slug)
    return done


def migrate_from(old_root: str, base: Optional[str] = None) -> int:
    """Chuyển kho cũ (Content Studio `content_studio/character_library`) sang kho lõi MỘT lần; slug đã có thì bỏ qua."""
    n = 0
    for p in load_all(old_root):
        if get(p["slug"], base):
            continue
        prof = {k: p[k] for k in _KEEP if k in p}
        save({**prof, "slug": p["slug"]}, sheet_src=p.get("sheet_path") or "", base=base)
        n += 1
    return n
