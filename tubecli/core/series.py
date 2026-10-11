# -*- coding: utf-8 -*-
"""HỒ SƠ TRUYỆN (series bible) — quan hệ, nơi chốn, giai đoạn của một bộ truyện dài kỳ (11/10/2026).

User: «sau này đưa vào kịch bản thì làm sao AI biết để nó thiết kế cảnh cho đúng? template có xây dựng các mối quan hệ của
câu chuyện không?» → «tuỳ dạng chứ không phải cái nào cũng phải xây dựng nhân vật» → «trong studio có các dạng video».
Nên: hồ sơ truyện chỉ dùng cho dạng KỂ CHUYỆN (Film / Drama, Xianxia) và chỉ khi mẫu chọn một hồ sơ (wizSeries).

Không phụ thuộc style: ngoại hình + sheet nằm ở kho nhân vật của từng style (tubecli.core.characters); hồ sơ chỉ giữ
CÂU CHUYỆN — ai là ai với ai, gọi nhau thế nào, đứng với nhau ra sao, nơi chốn nào lặp lại, nhân vật đổi tuổi lúc nào.

DATA_DIR/series/<slug>.json:
    name, aliases[], names{vi, en, zh…}, summary (tiếng Anh: bối cảnh + vài mốc truyện có thật, để AI không bịa ngược)
    world        câu dặn thế giới hình (tiếng Anh) — thay wizWorldNote khi mẫu không khai
    members[]    slug thực thể trong kho nhân vật (người / nơi / vật) — tra trong kho đúng style của dự án
    relations[]  {a, b, rel, a_calls_b, b_calls_a, staging} — a/b là slug; staging = cách hai người xuất hiện cùng nhau
    phases{}     slug gốc → [{slug, when}] — mỗi giai đoạn tuổi là một hồ sơ riêng trong kho (ngoại hình + sheet riêng)
    updated_at
"""
from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

NARRATIVE_FORMATS = ("Drama / Narrative", "Xianxia Donghua")
_LOCK = threading.RLock()
_KEEP = ("name", "aliases", "names", "summary", "world", "members", "relations", "phases")
MAX_BRIEF = 2400


def root() -> str:
    from tubecli import config
    d = os.path.join(str(config.DATA_DIR), "series")
    os.makedirs(d, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slug_of(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60].strip("_") or "series"


def is_narrative(content_format: Any) -> bool:
    return str(content_format or "").strip() in NARRATIVE_FORMATS


def _path(slug: str, base: Optional[str] = None) -> str:
    return os.path.join(base or root(), slug_of(slug) + ".json")


def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: d[k] for k in _KEEP if k in d}
    out["members"] = [slug_of(m) for m in (out.get("members") or []) if str(m).strip()]
    rel = []
    for r in out.get("relations") or []:
        if isinstance(r, dict) and r.get("a") and r.get("b"):
            rel.append({k: " ".join(str(r.get(k) or "").split()) for k in ("a", "b", "rel", "a_calls_b", "b_calls_a",
                                                                            "staging") if r.get(k)})
            rel[-1]["a"], rel[-1]["b"] = slug_of(r["a"]), slug_of(r["b"])
    out["relations"] = rel
    ph = {}
    for k, v in (out.get("phases") or {}).items() if isinstance(out.get("phases"), dict) else []:
        items = [{"slug": slug_of(x.get("slug")), "when": " ".join(str(x.get("when") or "").split())}
                 for x in v or [] if isinstance(x, dict) and x.get("slug")]
        if items:
            ph[slug_of(k)] = items
    out["phases"] = ph
    return out


def list_all(base: Optional[str] = None) -> List[Dict[str, Any]]:
    b = base or root()
    out = []
    for n in sorted(os.listdir(b)) if os.path.isdir(b) else []:
        if n.endswith(".json"):
            s = get(n[:-5], base)
            if s:
                out.append(s)
    return out


def get(key: str, base: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Theo slug, tên hay biệt danh."""
    p = _path(key, base)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("name"):
                d["slug"] = os.path.basename(p)[:-5]
                return d
        except (OSError, ValueError):
            return None
    k = " ".join(str(key or "").split()).casefold()
    if not k:
        return None
    for n in sorted(os.listdir(base or root())):
        if not n.endswith(".json") or n[:-5] == slug_of(key):
            continue
        try:
            with open(os.path.join(base or root(), n), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        names = [d.get("name")] + list(d.get("aliases") or []) + list((d.get("names") or {}).values())
        if k in {" ".join(str(x or "").split()).casefold() for x in names}:
            d["slug"] = n[:-5]
            return d
    return None


def save(data: Dict[str, Any], base: Optional[str] = None) -> Dict[str, Any]:
    name = " ".join(str(data.get("name") or "").split())
    if not name:
        raise ValueError("name is required")
    slug = slug_of(data.get("slug") or name)
    with _LOCK:
        cur = get(slug, base) or {}
        cur.pop("slug", None)
        new = _clean({**cur, **{k: data[k] for k in _KEEP if k in data}, "name": name})
        new["updated_at"] = _now()
        p = _path(slug, base)
        with open(p + ".part", "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=1)
        os.replace(p + ".part", p)
    return get(slug, base) or new


def delete(key: str, base: Optional[str] = None) -> bool:
    s = get(key, base)
    if not s:
        return False
    with _LOCK:
        os.remove(_path(s["slug"], base))
    return True


def member_slugs(s: Optional[Dict[str, Any]]) -> List[str]:
    """Thành viên + mọi giai đoạn của họ (giữ thứ tự, không lặp)."""
    out: List[str] = []
    for m in (s or {}).get("members") or []:
        for x in [m] + [p["slug"] for p in ((s or {}).get("phases") or {}).get(m, [])]:
            if x not in out:
                out.append(x)
    return out


def brief(s: Optional[Dict[str, Any]], present: Optional[Iterable[str]] = None,
          names: Optional[Dict[str, str]] = None) -> str:
    """Đoạn STORY BIBLE (tiếng Anh) cho model chia cảnh / đạo diễn: bối cảnh + quan hệ giữa những người CÓ MẶT (`present`
    = slug; None = mọi thành viên) + quy tắc giai đoạn. names: slug → tên trong prompt (prompt_name của kho)."""
    if not s:
        return ""
    names = names or {}
    keep = set(present) if present is not None else set(member_slugs(s))
    nm = lambda x: names.get(x) or x.replace("_", " ").title()      # noqa: E731
    parts = []
    if str(s.get("summary") or "").strip():
        parts.append("STORY: " + " ".join(str(s["summary"]).split()))
    rels = []
    for r in s.get("relations") or []:
        if r["a"] in keep and r["b"] in keep:
            t = f"{nm(r['a'])} is {r.get('rel') or 'linked to'} {nm(r['b'])}"
            if r.get("a_calls_b"):
                t += f"; {nm(r['a'])} calls {nm(r['b'])} «{r['a_calls_b']}»"
            if r.get("b_calls_a"):
                t += f"; {nm(r['b'])} calls {nm(r['a'])} «{r['b_calls_a']}»"
            if r.get("staging"):
                t += f"; together on screen: {r['staging']}"
            rels.append(t)
    if rels:
        parts.append("RELATIONSHIPS: " + ". ".join(rels) + ".")
    ph = []
    for base_slug, items in (s.get("phases") or {}).items():
        if base_slug in keep or any(i["slug"] in keep for i in items):
            ph.append("; ".join(f"{nm(i['slug'])} = {i['when']}" for i in items if i.get("when")))
    if ph:
        parts.append("AGES: one person can appear at different ages - pick the version that fits each scene, never mix "
                     "two versions of the same person in one frame: " + " | ".join(x for x in ph if x) + ".")
    text = " ".join(parts)
    return text[:MAX_BRIEF]
