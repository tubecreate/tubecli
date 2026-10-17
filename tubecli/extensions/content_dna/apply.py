"""DÙNG một ADN khi viết: khối chữ «CONTENT DNA» chèn vào system prompt của người viết kịch bản.

Gọi từ content_video/pipeline (_step_script) — một chỗ chèn, đi theo mọi đường viết (một lượt, theo dàn ý, rút
ngắn, sửa theo góp ý). Luật:
- structure=True: các nhịp (beats) theo thứ tự + số chữ mỗi nhịp tính từ độ dài mục tiêu; THAY lời khuyên cấu trúc
  chung của prompt nhưng GIỮ định dạng kỹ thuật (dòng TITLE, cảnh [SHOW]) — Studio cắt cảnh theo [SHOW].
- structure=False (chế độ «Tham khảo cấu trúc»): chỉ GIỌNG — cấu trúc là của video tham khảo.
- câu cửa miệng: tối đa MỘT trong cả bài (T2Content: lặp câu cửa miệng là thứ lộ «máy viết» nhất).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import store

OFF = ("none", "off", "-")


def choose(options: Optional[Dict[str, Any]], preset_meta: Optional[Dict[str, Any]]) -> str:
    """Mã ADN của lượt này: form/chat (options.content_dna) > mẫu (metadata.content_dna); "none" = tắt hẳn."""
    o = str((options or {}).get("content_dna") or "").strip()
    if o.lower() in OFF:
        return ""
    return o or str((preset_meta or {}).get("content_dna") or "").strip()


def load(did: str) -> Optional[Dict[str, Any]]:
    return store.get(did) if did and store.valid_id(did) else None


def _lines(title: str, items: List[str], limit: int) -> str:
    items = [i for i in items if i][:limit]
    return (f"{title}:\n" + "\n".join(f"- {i}" for i in items) + "\n") if items else ""


def prompt_block(rec: Dict[str, Any], words: int, structure: bool = True) -> str:
    dna = (rec or {}).get("dna") or {}
    fmt = (dna.get("formats") or [{}])[0]
    out = [f"\n\nCONTENT DNA \"{rec.get('name') or 'channel'}\" — write this piece the way this channel writes. "
           "Imitate its structure and voice; never copy its sentences.\n"]
    voice = [x for x in (("Genre", dna.get("genre")), ("Audience", dna.get("audience")),
                         ("Narrator", dna.get("persona")), ("Tone", dna.get("tone"))) if x[1]]
    if voice:
        out.append("\n".join(f"{k}: {v}" for k, v in voice) + "\n")
    if dna.get("style_summary"):
        out.append(f"Style: {dna['style_summary']}\n")
    beats = fmt.get("beats") or []
    if structure and beats:
        w = max(1, int(words or 0))
        out.append(
            f"\nSTRUCTURE — {fmt.get('name') or 'main format'}"
            + (f" ({fmt['description']})" if fmt.get("description") else "")
            + f". Go through these beats IN THIS ORDER with roughly these lengths (of {w} words in total). This "
            "replaces any generic structure advice in this prompt, but keep the TITLE line and the [SHOW] scene "
            "format exactly as asked; a beat may span several scenes or share one.\n")
        for i, b in enumerate(beats, 1):
            n = max(10, round(w * float(b.get("share") or 0) / 100))
            line = f"{i}. {b['name']} (~{n} words): {b.get('purpose') or ''}".rstrip(": ")
            if b.get("how"):
                line += f" — how: {b['how']}"
            out.append(line + "\n")
        if fmt.get("transitions"):
            out.append("Transitions: " + "; ".join(fmt["transitions"][:5]) + "\n")
        if fmt.get("pacing"):
            out.append(f"Pacing: {fmt['pacing']}\n")
    out.append(_lines("Openings this channel uses (pick ONE that fits)", dna.get("openings") or [], 5))
    out.append(_lines("Closings this channel uses (pick ONE that fits)", dna.get("closings") or [], 5))
    out.append(_lines("Rhetorical devices", dna.get("devices") or [], 8))
    if dna.get("signature_phrases"):
        out.append(_lines("Signature phrases (use AT MOST ONE in the whole piece, only where it fits naturally)",
                          dna["signature_phrases"], 8))
    out.append(_lines("Never", dna.get("avoid") or [], 8))
    return "".join(out).rstrip() + "\n"


def note_for(options: Optional[Dict[str, Any]], preset_meta: Optional[Dict[str, Any]], words: int,
             structure: bool = True) -> tuple:
    """(khối chữ, bản ghi) cho pipeline; ("", None) khi không có / không đọc được ADN."""
    rec = load(choose(options, preset_meta))
    return (prompt_block(rec, words, structure), rec) if rec else ("", None)


def usual_words(options: Optional[Dict[str, Any]], preset_meta: Optional[Dict[str, Any]]) -> int:
    """Độ dài «theo ADN» khi mẫu bật content_dna_length (= "dna"); 0 = không áp."""
    if str((preset_meta or {}).get("content_dna_length") or "").strip().lower() != "dna":
        return 0
    return store.usual_words(load(choose(options, preset_meta)))
