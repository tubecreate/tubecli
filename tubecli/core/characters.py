# -*- coding: utf-8 -*-
"""KHO NHÂN VẬT chung của mọi studio (10/10/2026) — cùng nếp với kho MẪU (tubecli.core.templates).

User: «tạo 1 kho để khi tôi làm về nhân vật này có thể lấy để đồng nhất» (Trần Bình An, Kiếm Lai) rồi chọn «kho ở lõi,
mẫu mang dàn»: kho ở lõi cho Content Studio / Pod Studio / Thumbnail Studio cùng đọc; một MẪU mang theo dàn nhân vật
(`cast` = các slug) — chọn mẫu là có đúng nhân vật + sheet; bán mẫu lên Chợ thì gói nhân vật đi kèm.

MỖI KHO MỘT STYLE (user cùng ngày: «bỏ cái sheet cũ đi, mỗi kho đúng loại style, mắc công nhầm» — sheet 3D của Trần Bình
An đưa vào clip thuỷ mặc thì hình lệch style). Trần Bình An thuỷ mặc và Trần Bình An 3D là HAI hồ sơ ở hai kho; dự án
chỉ nhìn kho đúng style của nó:

    DATA_DIR/characters/<khoá style>/<slug>/
        profile.json  {name, aliases[], series, kind, prompt_name, look (tiếng Anh, dáng CỐ ĐỊNH), personality, notes,
                       role (tiếng Anh: vai với dàn — «Pei Qian's master, called sư phụ»), role_words[] («master»,
                       «sư phụ» — thực thể kịch bản tự tạo mang chữ này là CHÍNH nhân vật, bỏ), names {vi, en, zh,
                       zh-TW…: tên chuẩn theo ngôn ngữ — clone đổi ngôn ngữ dịch tên đúng, user 11/10/2026 «tag tên tiếng
                       anh và tiếng trung vào kho để AI biết nếu muốn chuyển ngữ»}, status ("draft" | "approved"), size,
                       sheet, updated_at}
        sheet.<ext>   reference sheet ĐÚNG style của kho

Khoá style = slug tên style («Ink Wash Film» → «ink_wash_film»). Khớp tên theo Unicode (casefold + NFC; chữ Latinh có
ranh giới từ, chữ Hán/Nhật/Hàn khớp thẳng).
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
_KEEP = ("name", "aliases", "series", "kind", "prompt_name", "look", "personality", "notes", "role", "role_words",
         "names", "status", "size")
# Ngôn ngữ viết bằng chữ Latinh: thiếu tên riêng thì dùng tên tiếng Anh (phiên âm) — «Chen Ping'an» trong bản tiếng Tây
# Ban Nha; ngôn ngữ khác (ru, ja, ko, th, ar…) thiếu tên thì để model tự phiên theo tên gốc chữ Hán + tiếng Anh.
LATIN_LANGS = ("en", "es", "fr", "de", "pt", "it", "id", "tr", "vi")


def root() -> str:
    from tubecli import config
    d = os.path.join(str(config.DATA_DIR), "characters")
    os.makedirs(d, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _norm(s: Any) -> str:
    return unicodedata.normalize("NFC", " ".join(str(s or "").split())).casefold()


def _fold(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in s if not unicodedata.combining(c))


def slug_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _fold(name).lower()).strip("_")[:60].strip("_") or "character"


def style_key(style: str) -> str:
    """«Ink Wash Film» → «ink_wash_film» — tên thư mục kho của style."""
    k = slug_of(style)
    if not str(style or "").strip() or k == "character":
        raise ValueError("style is required — every character store belongs to one visual style")
    return k


def ascii_name(name: str) -> str:
    """«Trần Bình An» → «Tran Binh An» (tên trong prompt tiếng Anh khi hồ sơ không khai prompt_name)."""
    return " ".join(_fold(name).split())


def store_dir(style: str, base: Optional[str] = None) -> str:
    return os.path.join(base or root(), style_key(style))


def stores(base: Optional[str] = None) -> List[Dict[str, Any]]:
    """[{key, count}] các kho đang có."""
    b = base or root()
    try:
        names = sorted(os.listdir(b))
    except OSError:
        return []
    out = []
    for n in names:
        d = os.path.join(b, n)
        if os.path.isdir(d) and not os.path.isfile(os.path.join(d, PROFILE)):
            out.append({"key": n, "count": len(_load_dir(d))})
    return out


def _read(d: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(d, PROFILE), encoding="utf-8") as f:
            prof = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(prof, dict) or not prof.get("name"):
        return None
    prof["slug"] = os.path.basename(d)
    prof["store"] = os.path.basename(os.path.dirname(d))
    sheet = str(prof.get("sheet") or "")
    p = os.path.join(d, sheet) if sheet and not os.path.isabs(sheet) else sheet
    prof["sheet_path"] = p if p and os.path.isfile(p) else ""
    return prof


def _load_dir(store: str) -> List[Dict[str, Any]]:
    try:
        names = sorted(os.listdir(store))
    except OSError:
        return []
    return [p for p in (_read(os.path.join(store, n)) for n in names) if p]


def load_all(style: Optional[str] = None, base: Optional[str] = None) -> List[Dict[str, Any]]:
    """Hồ sơ của kho `style`; style None = mọi kho."""
    if style:
        return _load_dir(store_dir(style, base))
    b = base or root()
    return [p for s in stores(b) for p in _load_dir(os.path.join(b, s["key"]))]


def names_of(prof: Dict[str, Any], aliases: bool = True) -> List[str]:
    nm = prof.get("names") if isinstance(prof.get("names"), dict) else {}
    vals = [prof.get("name"), prof.get("prompt_name")] + (list(prof.get("aliases") or []) + list(nm.values())
                                                           if aliases else [])
    seen, out = set(), []
    for v in vals:
        n = _norm(v)
        if n and len(n) >= 2 and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def get(key: str, style: Optional[str] = None, base: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Theo slug, tên hay biệt danh, trong kho `style` (None = kho đầu tiên có)."""
    k, ks = _norm(key), slug_of(key)
    for p in load_all(style, base):
        if p["slug"] == ks or k in names_of(p):
            return p
    return None


def name_in(prof: Dict[str, Any], lang: str) -> str:
    """Tên chuẩn của nhân vật trong ngôn ngữ `lang` ("" khi không rõ): names[lang] → names[gốc ngôn ngữ] → zh-TW↔zh →
    tiếng Anh cho ngôn ngữ chữ Latinh."""
    nm = prof.get("names") if isinstance(prof.get("names"), dict) else {}
    lang = str(lang or "").strip()
    base = lang.split("-")[0].lower()
    for k in (lang, base, {"zh-TW": "zh", "zh": "zh-TW"}.get(lang, "")):
        if k and str(nm.get(k) or "").strip():
            return " ".join(str(nm[k]).split())
    if base in LATIN_LANGS:
        return " ".join(str(nm.get("en") or prof.get("prompt_name") or "").split())
    return ""


def glossary(text: str, lang: str, base: Optional[str] = None) -> List[Dict[str, str]]:
    """Nhân vật kho (mọi kho) mà `text` nhắc tới → [{source, target, zh, en}]: tên đang dùng trong text và tên chuẩn ở
    `lang` (target "" = model tự phiên theo zh/en). Cùng nhân vật ở nhiều kho style chỉ lấy một lần."""
    t = _norm(text)
    out, seen = [], set()
    # cùng nhân vật ở nhiều kho style (Trần Bình An thuỷ mặc + 3D): một mục, ưu tiên hồ sơ có khai `names`
    best: Dict[str, Dict[str, Any]] = {}
    for prof in load_all(None, base):
        k = _norm(prof.get("name"))
        if k not in best or (not best[k].get("names") and prof.get("names")):
            best[k] = prof
    for prof in best.values():
        hit = ""
        for n in names_of(prof, True):
            if re.search(re.escape(n) if _cjk(n) else r"(?<!\w)" + re.escape(n) + r"(?!\w)", t):
                hit = n
                break
        if not hit:
            continue
        nm = prof.get("names") if isinstance(prof.get("names"), dict) else {}
        src = next((v for v in [prof.get("name")] + list(prof.get("aliases") or []) + list(nm.values())
                    if _norm(v) == hit), prof.get("name"))
        tgt = name_in(prof, lang)
        key = (_norm(src), _norm(tgt), _norm(nm.get("zh")))
        if key in seen:
            continue
        seen.add(key)
        out.append({"source": str(src), "target": tgt, "zh": str(nm.get("zh") or ""),
                    "en": str(nm.get("en") or prof.get("prompt_name") or "")})
    return out


def _cjk(s: str) -> bool:
    return any("⺀" <= ch <= "鿿" or "가" <= ch <= "힯" or "぀" <= ch <= "ヿ" for ch in s)


def match(text: str, style: str, only: Optional[Iterable[str]] = None, aliases: bool = True,
          base: Optional[str] = None) -> List[Dict[str, Any]]:
    """Nhân vật kho `style` mà `text` nhắc tên / biệt danh, theo thứ tự xuất hiện. only: chỉ xét các slug này (dàn mẫu).

    aliases=False: chỉ TÊN ĐẦY ĐỦ — dùng khi mẫu không khai dàn: biệt danh hay là chữ thường («Bình An» = bình an),
    kịch bản Lão Tử nói «sống bình an» không được kéo Trần Bình An vào."""
    t = _norm(text)
    keep = {slug_of(x) for x in only} if only else None
    hits = []
    for prof in load_all(style, base):
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
    """Hồ sơ → thực thể canon (cùng dạng canon.build của Content Studio): tên = prompt_name, canon = look, sheet sẵn.
    Hồ sơ chưa có sheet: bên dựng vẽ theo style của dự án (= style của kho) rồi save(..., sheet_src=…) lại vào kho."""
    out = []
    for p in profiles or []:
        look = " ".join(str(p.get("look") or "").split())
        if len(look.split()) < 8:
            continue
        e = {"name": str(p.get("prompt_name") or ascii_name(p["name"])),
             "kind": p.get("kind") if p.get("kind") in KINDS else "person",
             "shot_ids": [], "paragraphs": [], "canon": look, "size": str(p.get("size") or ""),
             "from": "library", "library": p.get("slug", ""), "library_store": p.get("store", ""),
             "aliases": [p["name"]] + list(p.get("aliases") or [])}
        if str(p.get("role") or "").strip():
            e["role"] = " ".join(str(p["role"]).split())[:200]
        words = [" ".join(str(w).split()).lower() for w in (p.get("role_words") or []) if str(w).strip()]
        if words:
            e["role_words"] = words[:12]
        if p.get("sheet_path"):
            e["sheet"] = p["sheet_path"]
        out.append(e)
    return out


def _write_sheet(d: str, src: str = "", data_url: str = "") -> str:
    """Chép ảnh (đường dẫn hay data URL base64) thành sheet.<ext> trong thư mục nhân vật; trả tên file ("" nếu không có).
    Sheet cũ khác đuôi bị xoá — mỗi nhân vật đúng MỘT sheet."""
    if src:
        ext = os.path.splitext(src)[1].lower()
        if ext not in SHEET_EXTS:
            raise ValueError(f"sheet must be an image ({', '.join(SHEET_EXTS)})")
        if not os.path.isfile(src):
            raise ValueError(f"sheet not found: {src}")
        dst = os.path.join(d, "sheet" + ext)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst + ".part")
            os.replace(dst + ".part", dst)
    elif data_url:
        m = re.match(r"data:image/(png|jpe?g|webp);base64,(.+)$", str(data_url), re.S)
        if not m:
            raise ValueError("sheet_data must be a data:image/png|jpeg|webp;base64 URL")
        ext = ".jpg" if m.group(1).startswith("jp") else "." + m.group(1)
        with open(os.path.join(d, "sheet" + ext), "wb") as f:
            f.write(base64.b64decode(m.group(2)))
    else:
        return ""
    for other in SHEET_EXTS:
        if other != ext and os.path.isfile(os.path.join(d, "sheet" + other)):
            os.remove(os.path.join(d, "sheet" + other))
    return "sheet" + ext


def save(prof: Dict[str, Any], style: str, sheet_src: str = "", sheet_data: str = "",
         base: Optional[str] = None) -> Dict[str, Any]:
    """Thêm / sửa một nhân vật trong kho `style` (slug theo tên, hoặc `slug` có sẵn). Gộp trường với hồ sơ cũ."""
    name = " ".join(str(prof.get("name") or "").split())
    if not name:
        raise ValueError("name is required")
    slug = slug_of(prof.get("slug") or name)
    d = os.path.join(store_dir(style, base), slug)
    with _LOCK:
        os.makedirs(d, exist_ok=True)
        cur = _read(d) or {}
        for x in ("slug", "store", "sheet_path"):
            cur.pop(x, None)
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


def delete(key: str, style: str, base: Optional[str] = None) -> bool:
    p = get(key, style, base)
    if not p:
        return False
    with _LOCK:
        shutil.rmtree(os.path.join(store_dir(style, base), p["slug"]), ignore_errors=True)
    return True


def _data_url(path: str) -> str:
    if not path:
        return ""
    ext = os.path.splitext(path)[1].lower().lstrip(".").replace("jpg", "jpeg")
    with open(path, "rb") as f:
        return f"data:image/{ext};base64," + base64.b64encode(f.read()).decode("ascii")


def bundle(slugs: Iterable[str], style: str, base: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gói nhân vật đi kèm mẫu khi bán lên Chợ: [{store, profile, sheet_data}] — sheet nhúng base64."""
    out = []
    for s in slugs or []:
        p = get(s, style, base)
        if not p:
            continue
        prof = {k: p[k] for k in _KEEP if k in p}
        prof["slug"] = p["slug"]
        out.append({"store": p["store"], "profile": prof, "sheet_data": _data_url(p.get("sheet_path") or "")})
    return out


def install_bundle(items: List[Dict[str, Any]], style: Optional[str] = None, base: Optional[str] = None,
                   overwrite: bool = False) -> List[str]:
    """Cài gói nhân vật kèm mẫu từ Chợ vào kho của gói (hay `style`). Nhân vật đã có (cùng kho, cùng slug) thì GIỮ bản
    máy này trừ khi overwrite. Trả ["<kho>/<slug>"…]."""
    done = []
    for it in items or []:
        prof = dict((it or {}).get("profile") or {})
        st = str((it or {}).get("store") or style or "")
        if not prof.get("name") or not st.strip():
            continue
        slug = slug_of(prof.get("slug") or prof["name"])
        if not (get(slug, st, base) and not overwrite):
            save({**prof, "slug": slug}, st, sheet_data=str((it or {}).get("sheet_data") or ""), base=base)
        done.append(f"{style_key(st)}/{slug}")
    return done
