"""Kho ADN nội dung: DATA_DIR/content_dna/<id>.json, bản trước khi ghi đè giữ ở <id>.v<N>.json (MAX_VERSIONS bản).

Bản ghi:
    {id, name, version, created_at, updated_at, language, model, agent_id,
     stats: {docs, samples, words_median, words_avg}, titles: [...], sources: [{kind, ref, title}],
     dna: {language, genre, audience, persona, tone, style_summary, words,
           formats: [{name, description, beats: [{name, share, purpose, how, example}], transitions, pacing}],
           topics: {clusters: [{name, share, angles, anchors}], title_formulas, hook_types},
           openings, closings, devices, signature_phrases, avoid}}

id = slug ASCII của tên + 6 ký tự ngẫu nhiên: T2Content lấy slug trần nên tên toàn chữ Hán / Nhật ra slug rỗng → «mau»
→ các ADN đè nhau.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
MAX_VERSIONS = 5
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,70}$")
_LIST_FIELDS = ("openings", "closings", "devices", "signature_phrases", "avoid")


def data_dir() -> str:
    from tubecli.config import DATA_DIR
    return os.path.join(str(DATA_DIR), "content_dna")


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-")
    return s or "dna"


def new_id(name: str) -> str:
    return f"{_slug(name)}-{secrets.token_hex(3)}"


def valid_id(did: str) -> bool:
    return bool(_ID_RE.match(str(did or "")))


def _path(did: str) -> str:
    if not valid_id(did):
        raise ValueError(f"bad DNA id: {did!r}")
    return os.path.join(data_dir(), f"{did}.json")


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def get(did: str) -> Optional[Dict[str, Any]]:
    if not valid_id(did):
        return None
    return _read(_path(did))


def _clip(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _str_list(v: Any, n_items: int, n_chars: int) -> List[str]:
    if isinstance(v, str):
        v = [x for x in re.split(r"\n+", v)]
    out: List[str] = []
    for x in v if isinstance(v, list) else []:
        s = _clip(x if not isinstance(x, dict) else (x.get("text") or x.get("name") or ""), n_chars)
        if s and s not in out:
            out.append(s)
        if len(out) >= n_items:
            break
    return out


def _share(v: Any) -> float:
    try:
        return max(0.0, float(str(v).strip().rstrip("%")))
    except (TypeError, ValueError):
        return 0.0


def _rescale(items: List[Dict[str, Any]]) -> None:
    """Tỷ lệ % cộng đúng 100 (làm tròn số nguyên, phần dư dồn vào mục lớn nhất). Không có tỷ lệ nào ⇒ chia đều."""
    if not items:
        return
    raw = [_share(it.get("share")) for it in items]
    total = sum(raw)
    if total <= 0:
        raw, total = [1.0] * len(items), float(len(items))
    vals = [max(1, round(r * 100 / total)) for r in raw]
    vals[vals.index(max(vals))] += 100 - sum(vals)
    for it, v in zip(items, vals):
        it["share"] = int(v)


def normalize(dna: Any) -> Dict[str, Any]:
    """ADN từ model / người sửa tay → đúng khuôn: chuỗi cắt gọn, danh sách đúng kiểu, tỷ lệ cộng 100.
    Không bao giờ ném — ADN hỏng thành ADN rỗng có khuôn."""
    d = dna if isinstance(dna, dict) else {}
    out: Dict[str, Any] = {
        "language": _clip(d.get("language"), 40),
        "genre": _clip(d.get("genre"), 200),
        "audience": _clip(d.get("audience"), 400),
        "persona": _clip(d.get("persona"), 600),
        "tone": _clip(d.get("tone"), 400),
        "style_summary": _clip(d.get("style_summary"), 1500),
    }
    try:
        out["words"] = max(0, min(20000, int(float(d.get("words") or 0))))
    except (TypeError, ValueError):
        out["words"] = 0
    formats = []
    for f in (d.get("formats") or [])[:3] if isinstance(d.get("formats"), list) else []:
        if not isinstance(f, dict):
            continue
        beats = []
        for b in (f.get("beats") or [])[:12] if isinstance(f.get("beats"), list) else []:
            if isinstance(b, dict) and _clip(b.get("name"), 120):
                beats.append({"name": _clip(b.get("name"), 120), "share": _share(b.get("share")),
                              "purpose": _clip(b.get("purpose"), 400), "how": _clip(b.get("how"), 600),
                              "example": _clip(b.get("example"), 300)})
        if not beats:
            continue
        _rescale(beats)
        formats.append({"name": _clip(f.get("name"), 120) or "Main format",
                        "description": _clip(f.get("description"), 600),
                        "beats": beats, "transitions": _str_list(f.get("transitions"), 8, 200),
                        "pacing": _clip(f.get("pacing"), 400)})
    out["formats"] = formats
    t = d.get("topics") if isinstance(d.get("topics"), dict) else {}
    clusters = []
    for c in (t.get("clusters") or [])[:8] if isinstance(t.get("clusters"), list) else []:
        if isinstance(c, dict) and _clip(c.get("name"), 120):
            clusters.append({"name": _clip(c.get("name"), 120), "share": _share(c.get("share")),
                             "angles": _str_list(c.get("angles"), 6, 200),
                             "anchors": _str_list(c.get("anchors"), 8, 120)})
    _rescale(clusters)
    out["topics"] = {"clusters": clusters, "title_formulas": _str_list(t.get("title_formulas"), 10, 200),
                     "hook_types": _str_list(t.get("hook_types"), 8, 200)}
    for k, n in zip(_LIST_FIELDS, (8, 8, 12, 12, 12)):
        out[k] = _str_list(d.get(k), n, 300)
    return out


def summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    dna = rec.get("dna") or {}
    fmt = (dna.get("formats") or [{}])[0]
    return {"id": rec.get("id"), "name": rec.get("name"), "language": rec.get("language") or dna.get("language") or "",
            "genre": dna.get("genre") or "", "format": fmt.get("name") or "", "beats": len(fmt.get("beats") or []),
            "words": usual_words(rec), "samples": (rec.get("stats") or {}).get("samples") or 0,
            "docs": (rec.get("stats") or {}).get("docs") or 0, "version": rec.get("version") or 1,
            "updated_at": rec.get("updated_at") or rec.get("created_at") or 0}


def usual_words(rec: Optional[Dict[str, Any]]) -> int:
    """Độ dài thường gặp của bài mẫu (chữ): ADN ghi `words` (sửa tay được), không có thì trung vị lúc học."""
    if not rec:
        return 0
    try:
        w = int((rec.get("dna") or {}).get("words") or 0)
    except (TypeError, ValueError):
        w = 0
    return w or int((rec.get("stats") or {}).get("words_median") or 0)


def list_all() -> List[Dict[str, Any]]:
    d = data_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        if fn.endswith(".json") and not re.search(r"\.v\d+\.json$", fn):
            rec = _read(os.path.join(d, fn))
            if rec and rec.get("id"):
                out.append(summary(rec))
    return sorted(out, key=lambda r: (str(r.get("name") or "").lower(), r.get("id") or ""))


def save(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Ghi (nguyên tử). Bản đang có cất thành <id>.v<version>.json, chỉ giữ MAX_VERSIONS bản gần nhất."""
    rec = dict(rec)
    if not valid_id(rec.get("id")):
        rec["id"] = new_id(rec.get("name") or "")
    rec["name"] = _clip(rec.get("name"), 120) or "Untitled DNA"
    rec["dna"] = normalize(rec.get("dna"))
    now = time.time()
    with _LOCK:
        os.makedirs(data_dir(), exist_ok=True)
        path = _path(rec["id"])
        old = _read(path)
        if old:
            v = int(old.get("version") or 1)
            os.replace(path, os.path.join(data_dir(), f"{rec['id']}.v{v}.json"))
            rec["version"] = v + 1
            rec["created_at"] = old.get("created_at") or now
            vers = sorted((int(m.group(1)), fn) for fn in os.listdir(data_dir())
                          for m in [re.match(re.escape(rec["id"]) + r"\.v(\d+)\.json$", fn)] if m)
            for _, fn in vers[:-MAX_VERSIONS]:
                try:
                    os.remove(os.path.join(data_dir(), fn))
                except OSError:
                    pass
        else:
            rec["version"] = int(rec.get("version") or 1)
            rec.setdefault("created_at", now)
        rec["updated_at"] = now
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    return rec


def versions(did: str) -> List[int]:
    if not valid_id(did) or not os.path.isdir(data_dir()):
        return []
    return sorted(int(m.group(1)) for fn in os.listdir(data_dir())
                  for m in [re.match(re.escape(did) + r"\.v(\d+)\.json$", fn)] if m)


def delete(did: str) -> bool:
    if not valid_id(did):
        return False
    gone = False
    with _LOCK:
        for v in versions(did):
            try:
                os.remove(os.path.join(data_dir(), f"{did}.v{v}.json"))
            except OSError:
                pass
        try:
            os.remove(_path(did))
            gone = True
        except OSError:
            pass
    return gone
