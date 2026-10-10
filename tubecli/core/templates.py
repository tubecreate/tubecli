"""Kho MẪU dùng chung cho mọi studio (Content Studio, Pod Studio…) — một mẫu, mọi nơi dùng được (user 3/10/2026:
«mẫu này với mẫu của Content Studio có chung gốc được không? tức là cả 2 đều có thể dùng»).

Một mẫu = phần CHUNG + các PHẦN RIÊNG:
  shared   : khung hình, ngôn ngữ, kiểu hình (câu tả + khoá), thể loại, độ dài, phụ đề — mọi studio hiểu
  sections : "wizard"    → khoá wiz* của trình hướng dẫn (Content Studio VÀ Pod Studio dùng CÙNG bộ khoá này)
             "ref_video" → pipe «Video từ ảnh tham chiếu» của Pod Studio (format, clips, aspect, style…)
Mỗi phần riêng giữ NGUYÊN VĂN dữ liệu studio đã lưu (đọc lại y hệt — gói xuất/nhập, Chợ so dữ liệu), kèm ảnh chụp
phần chung lúc lưu. Đọc một phần riêng (section_view): khoá nào thuộc phần chung mà studio KHÁC đã đổi sau lần lưu ấy
thì được ghi đè theo phần chung — đổi khung hình ở Pod Studio thì Content Studio thấy ngay, còn khoá riêng (bộ cảnh,
kho sprite, giọng CapCut…) không ai đụng. Mẫu chỉ có phần riêng của studio này → studio kia nhận bản dựng từ phần chung.

Kho: DATA_DIR/templates/templates.json (đọc DATA_DIR lúc gọi — test đổi thư mục được). Content Studio giữ route
/api/v1/studio/presets cũ (đọc/ghi qua đây); lõi cũ chưa có file này thì nó lùi về presets.json như trước.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

SECTIONS = ("wizard", "ref_video")
SHARED_FIELDS = ("aspect", "language", "style", "style_preset", "genre", "length_sec", "subtitles")
ASPECTS = ("9:16", "16:9", "1:1", "4:3")
STYLE_PRESETS = ("3d", "anime", "photo", "painting")
# Tên hiển thị của khoá kiểu hình khi phải chép sang ô kiểu hình tự do của trình hướng dẫn.
STYLE_PRESET_TEXT = {"3d": "Semi-realistic 3D CG render", "anime": "2D anime illustration",
                     "photo": "Photorealistic, real photograph", "painting": "Painted illustration"}
# wizVideoLength ↔ giây ("standard" = video YouTube thường, không cố định → 0 = tự động)
_WIZ_LENGTHS = (("short_60s", 60), ("short_3m", 180), ("standard", 0), ("long_10m", 600))

# DÀN NHÂN VẬT của mẫu (10/10/2026, kho nhân vật tubecli.core.characters): t["cast"] = [slug…] ở cấp mẫu, mọi studio
# đọc được. Trình hướng dẫn (phần "wizard") chở nó qua khoá chuỗi `wizCast` = "slug1,slug2" — nhờ vậy gói xuất/nhập
# và Chợ (chỉ chở khoá wiz* giá trị đơn) mang dàn theo mà không phải đổi định dạng gói.
CAST_KEY = "wizCast"
MAX_CAST = 12

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _store_path() -> str:
    from tubecli import config
    d = os.path.join(str(config.DATA_DIR), "templates")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "templates.json")


def _load() -> List[dict]:
    try:
        with open(_store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return [t for t in data if isinstance(t, dict) and t.get("name")] if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        # File hỏng: giữ lại bản hỏng để cứu tay, đừng âm thầm ghi đè thành rỗng.
        p = _store_path()
        try:
            os.replace(p, p + f".broken-{int(time.time())}")
        except OSError:
            pass
        return []


def _save(items: List[dict]) -> None:
    p = _store_path()
    tmp = p + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# ── ánh xạ phần chung ↔ từng phần riêng ──────────────────────────────────────

def guess_style_preset(text: str) -> str:
    """Khoá kiểu hình từ câu tả tự do ("" khi không đoán được). Thứ tự quan trọng: «anime-styled 3D render» là 3d."""
    t = str(text or "")
    for key, pat in (("3d", r"\b3d\b|\bcg\b|cgi|render|pixar|unreal|octane|video game"),
                     ("anime", r"anime|manga|cel[- ]shad|\b2d\b|cartoon|chibi|donghua|ghibli"),
                     ("painting", r"paint|watercolou?r|ink wash|thuỷ mặc|thủy mặc|oil on|brush|chalk|phấn|marker|doodle|sketch"),
                     ("photo", r"photo|realis|real life|cinematic real|ảnh thật")):
        if re.search(pat, t, re.I):
            return key
    return ""


def _wiz_style_text(w: dict) -> str:
    s = str(w.get("wizStyle") or "").strip()
    if s == "__custom__":
        s = str(w.get("wizStyleCustom") or "").strip()
    return "" if s.lower() in ("", "default") else s


def _wiz_length(value: Any) -> Optional[int]:
    v = str(value or "").strip()
    for key, sec in _WIZ_LENGTHS:
        if v == key:
            return sec
    return None


def _nearest_wiz_length(sec: int) -> str:
    if not sec:
        return "standard"
    return min((k for k, s in _WIZ_LENGTHS if s), key=lambda k: abs(dict(_WIZ_LENGTHS)[k] - sec))


def _extract(section: str, d: dict) -> Dict[str, Any]:
    """Phần chung đọc ra từ dữ liệu của một phần riêng — chỉ những trường đọc được (không có thì không ghi)."""
    out: Dict[str, Any] = {}
    d = d if isinstance(d, dict) else {}
    if section == "wizard":
        if d.get("wizAspectRatio") in ASPECTS:
            out["aspect"] = d["wizAspectRatio"]
        if str(d.get("wizLanguage") or "").strip():
            out["language"] = str(d["wizLanguage"]).strip()
        if "wizStyle" in d:
            out["style"] = _wiz_style_text(d)
            out["style_preset"] = guess_style_preset(out["style"])
        if "wizPipelineTemplate" in d or "wizContentFormat" in d:
            drama = str(d.get("wizPipelineTemplate") or "").startswith("drama") or "drama" in str(d.get("wizContentFormat") or "").lower()
            out["genre"] = "drama" if drama else "explainer"
        if _wiz_length(d.get("wizVideoLength")) is not None:
            out["length_sec"] = _wiz_length(d["wizVideoLength"])
        if "wizSubtitleStyle" in d:
            out["subtitles"] = str(d.get("wizSubtitleStyle") or "")
    elif section == "ref_video":
        if d.get("aspect") in ASPECTS:
            out["aspect"] = d["aspect"]
        if str(d.get("language") or "").strip():
            out["language"] = str(d["language"]).strip()
        if "style" in d or "style_custom" in d:
            preset = str(d.get("style") or "").strip().lower()
            custom = str(d.get("style_custom") or "").strip()
            out["style_preset"] = preset if preset in STYLE_PRESETS else guess_style_preset(custom)
            out["style"] = custom or (STYLE_PRESET_TEXT.get(preset, "") if preset in STYLE_PRESETS else "")
        if d.get("format") in ("ad", "short", "drama"):
            out["genre"] = d["format"]
        try:
            clips = int(d.get("clips") or 0)
        except (TypeError, ValueError):
            clips = 0
        if clips > 0:
            out["length_sec"] = clips * 10
        if "subtitles" in d:
            out["subtitles"] = "on" if d.get("subtitles") in (True, 1, "1", "true", "on") else ""
    return out


def _apply(section: str, d: dict, field: str, value: Any) -> None:
    """Ghi một trường của phần chung vào dữ liệu phần riêng (chỉ gọi khi studio KHÁC đã đổi trường ấy)."""
    if section == "wizard":
        if field == "aspect" and value in ASPECTS:
            d["wizAspectRatio"] = value
        elif field == "language" and value:
            d["wizLanguage"] = value
        elif field == "style":
            d["wizStyle"], d["wizStyleCustom"] = (value or "Default"), ""
        elif field == "style_preset" and value in STYLE_PRESET_TEXT:
            if guess_style_preset(_wiz_style_text(d)) != value:      # câu tả hiện tại đã đúng khoá thì giữ nguyên chữ
                d["wizStyle"], d["wizStyleCustom"] = STYLE_PRESET_TEXT[value], ""
        elif field == "genre":
            drama = value == "drama"
            if "wizPipelineTemplate" not in d or drama != str(d.get("wizPipelineTemplate") or "").startswith("drama"):
                d["wizPipelineTemplate"] = "drama_scene" if drama else "explainer"
                d["wizContentFormat"] = "Drama / Narrative" if drama else "Educational / Learning"
        elif field == "length_sec" and isinstance(value, int):
            d["wizVideoLength"] = _nearest_wiz_length(value)
        elif field == "subtitles":
            d["wizSubtitleStyle"] = (str(d.get("wizSubtitleStyle") or "") or "capcut_bold") if value == "on" else str(value or "")
    elif section == "ref_video":
        if field == "aspect" and value in ("9:16", "16:9", "1:1"):
            d["aspect"] = value
        elif field == "language" and value:
            d["language"] = value
        elif field == "style_preset":
            d["style"] = value if value in STYLE_PRESETS else "auto"
        elif field == "style":
            if value and value not in STYLE_PRESET_TEXT.values():
                d["style_custom"] = value
            else:
                d.pop("style_custom", None)
        elif field == "genre":
            d["format"] = value if value in ("ad", "short", "drama") else ("short" if value else d.get("format", "ad"))
        elif field == "length_sec" and isinstance(value, int) and value > 0:
            d["clips"] = max(1, min(12, round(value / 10)))
        elif field == "subtitles":
            d["subtitles"] = bool(value)


def parse_cast(value: Any) -> List[str]:
    """«a, b» / ["a", "b"] → ["a", "b"] (slug kho nhân vật, bỏ trùng, giữ thứ tự)."""
    items = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
    out: List[str] = []
    for v in items:
        v = re.sub(r"[^a-z0-9_]+", "", str(v or "").strip().lower())
        if v and v not in out:
            out.append(v)
    return out[:MAX_CAST]


# ── bản ghi ──────────────────────────────────────────────────────────────────

def _find(items: List[dict], key: str) -> Optional[dict]:
    k = str(key or "").strip()
    if not k:
        return None
    for t in items:
        if t.get("id") == k:
            return t
    low = k.casefold()
    for t in items:
        if str(t.get("name") or "").strip().casefold() == low:
            return t
    return None


def list_templates() -> List[dict]:
    with _LOCK:
        return _load()


def get_template(key: str) -> Optional[dict]:
    """Theo id (tpl_…) hoặc tên (không phân biệt hoa thường)."""
    with _LOCK:
        return _find(_load(), key)


def save_section(name: str, section: str, data: dict, *, origin: str = "", replace: bool = False,
                 created_at: str = "", updated_at: str = "", legacy_id: Any = None) -> dict:
    """Lưu (tạo mới hoặc cập nhật theo tên) phần riêng `section` của mẫu `name`.

    Gộp theo khoá (replace=False): khoá studio này không gửi thì giữ — trình hướng dẫn Pod có khoá CS không có và
    ngược lại, cả hai cùng ghi phần "wizard". Phần chung cập nhật theo những trường đọc được từ dữ liệu mới."""
    name = str(name or "").strip()
    if not name:
        raise ValueError("Template name is required")
    if section not in SECTIONS:
        raise ValueError(f"Unknown template section: {section}")
    if not isinstance(data, dict):
        raise ValueError("Template data must be an object")
    with _LOCK:
        items = _load()
        t = _find(items, name)
        now = _now()
        if t is None:
            t = {"id": "tpl_" + uuid.uuid4().hex[:12], "name": name, "origin": origin or "",
                 "created_at": created_at or now, "updated_at": updated_at or now, "shared": {}, "sections": {}}
            if legacy_id is not None:
                t["legacy_id"] = legacy_id
            items.append(t)
        else:
            t["updated_at"] = updated_at or now
        sec = t.setdefault("sections", {}).get(section) or {}
        seen = section_view(t, section)          # bản studio này đang thấy trước khi lưu
        raw = dict(data) if replace else {**(sec.get("data") or {}), **data}
        if section == "wizard" and CAST_KEY in raw:
            if CAST_KEY in data or "cast" not in t:
                t["cast"] = parse_cast(raw[CAST_KEY])
            raw.pop(CAST_KEY)
        shared = t.setdefault("shared", {})
        # Chỉ trường người dùng THỰC SỰ đổi mới vào phần chung: trình hướng dẫn gửi lại cả bộ khoá, mà ánh xạ thô hơn
        # (thể loại explainer, độ dài theo nấc) — không lọc thì lưu lại không đổi gì cũng đè «ad / 30 s» của Pod Studio.
        before, after = _extract(section, seen), _extract(section, raw)
        for f, v in after.items():
            if f not in shared or before.get(f) != v:
                shared[f] = v
        t["sections"][section] = {"data": raw, "shared_at_write": dict(shared), "updated_at": t["updated_at"]}
        _save(items)
        return t


def delete_template(key: str) -> bool:
    with _LOCK:
        items = _load()
        t = _find(items, key)
        if not t:
            return False
        _save([x for x in items if x is not t])
        return True


def set_cast(key: str, cast: Any) -> Optional[dict]:
    """Đặt dàn nhân vật của mẫu (danh sách slug kho nhân vật; rỗng = bỏ dàn)."""
    with _LOCK:
        items = _load()
        t = _find(items, key)
        if not t:
            return None
        t["cast"], t["updated_at"] = parse_cast(cast), _now()
        _save(items)
        return t


def rename_template(key: str, new_name: str) -> Optional[dict]:
    new_name = str(new_name or "").strip()
    with _LOCK:
        items = _load()
        t = _find(items, key)
        if not t or not new_name:
            return None
        other = _find(items, new_name)
        if other is not None and other is not t:
            raise ValueError(f"A template named «{new_name}» already exists")
        t["name"], t["updated_at"] = new_name, _now()
        _save(items)
        return t


def section_view(t: dict, section: str) -> dict:
    """Dữ liệu phần riêng `section` để studio dùng: bản đã lưu + những trường chung studio khác đổi sau đó; chưa có
    phần riêng này thì dựng từ phần chung."""
    if not isinstance(t, dict):
        return {}
    shared = t.get("shared") or {}
    sec = (t.get("sections") or {}).get(section)
    if sec:
        out = dict(sec.get("data") or {})
        at = sec.get("shared_at_write") or {}
        changed = [f for f in SHARED_FIELDS if f in shared and shared.get(f) != at.get(f)]
    else:
        out = {}
        changed = [f for f in SHARED_FIELDS if f in shared and shared.get(f) not in (None, "")]
    # kiểu hình: câu tả trước, khoá sau (khoá thắng khi câu tả không nói rõ kiểu)
    for f in sorted(changed, key=lambda x: (x != "style", x)):
        _apply(section, out, f, shared[f])
    if section == "wizard" and t.get("cast"):
        out[CAST_KEY] = ",".join(t["cast"])
    return out


def summary(t: dict, section: str = "") -> dict:
    """Bản gọn cho API/giao diện: id, tên, nguồn, mốc, phần chung, studio nào đã lưu phần riêng (+ view nếu hỏi)."""
    out = {"id": t.get("id"), "name": t.get("name"), "origin": t.get("origin") or "",
           "created_at": t.get("created_at") or "", "updated_at": t.get("updated_at") or "",
           "shared": dict(t.get("shared") or {}), "sections": sorted((t.get("sections") or {}).keys()),
           "cast": list(t.get("cast") or [])}
    if section:
        out["view"] = section_view(t, section)
    return out


def import_legacy(rows: List[dict], section: str, origin: str, parse: Callable[[Any], dict]) -> Tuple[int, int]:
    """Chuyển một lần kho cũ (vd presets.json của Content Studio) vào đây: tên đã có thì bỏ qua. → (thêm, bỏ qua)."""
    added = skipped = 0
    with _LOCK:
        have = {str(t.get("name") or "").strip().casefold() for t in _load()}
    for r in rows or []:
        name = str((r or {}).get("name") or "").strip()
        if not name or name.casefold() in have:
            skipped += 1
            continue
        data = parse(r.get("data"))
        if not isinstance(data, dict):
            skipped += 1
            continue
        save_section(name, section, data, origin=origin, replace=True, created_at=str(r.get("created_at") or ""),
                     updated_at=str(r.get("updated_at") or ""), legacy_id=r.get("id"))
        have.add(name.casefold())
        added += 1
    return added, skipped
