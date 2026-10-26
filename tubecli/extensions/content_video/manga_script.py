# -*- coding: utf-8 -*-
"""Kịch bản MANGA DRAMA (26/10/2026) — truyện tranh lồng tiếng tiếng Nhật (漫画動画 / 胸キュン漫画).

Mẫu khai `wizScriptFormat: manga` (Studio → metadata.script_format). Lõi viết theo HAI lượt (model nào cũng viết nổi):
1. Dàn ý JSON: tiêu đề kiểu kênh 【漫画】…, dàn nhân vật (giới tính / tuổi / ngoại hình tiếng Anh), bối cảnh, các phần.
2. Mỗi phần một lượt: các khung `[SHOW: bối cảnh | nhân vật trái→phải | góc máy]` + lời từng người nói.
Kết quả = một văn bản (Studio lưu ở tập, engines/manga_drama.parse_script tách khung không qua AI)."""
import json, re
from typing import Callable, Dict, List, Tuple

# Đo tập «ナギ» (23/10/2026): 3.259 chữ thoại → 13:25 (lời + khoảng nghỉ + mở / đóng khung) ⇒ ~243 chữ / phút; ~33 chữ / khung
CHARS_PER_MIN = 240
CHARS_PER_PANEL = 33
PANELS_PER_PART = 12

SYSTEM = (
    "You are the head writer of a hit Japanese YouTube channel of voiced manga videos (漫画動画 / 胸キュン漫画 / スカッと漫画). "
    "You write ORIGINAL stories with natural, emotional spoken Japanese dialogue — the kind that keeps viewers watching for "
    "15–20 minutes: a hook from the climax first, dramatic irony (the viewer learns the hidden truth early while the other "
    "characters misunderstand), small daily scenes that build tension, a satisfying reveal, and a sweet 胸キュン ending. "
    "Content is wholesome and suitable for all ages: no sexual content, no violence beyond a verbal argument, never "
    "describe the body or age of minors — high-school characters wear modest uniforms with knee-length skirts.")

PLAN_FMT = """Return ONLY one JSON object, no markdown, in this shape:
{{
 "title": "<a long YouTube title in Japanese in the genre's style, starting with 【漫画】, 60-110 characters, ending with 【胸キュン漫画】 or a similar tag>",
 "logline": "<one sentence in English>",
 "cast": [
  {{"id": "<short lowercase romaji id, e.g. minato>", "name": "<full Japanese name>", "reading": "<hiragana reading of the full name>",
    "call": "<the name others call them in dialogue, e.g. 湊>", "call_reading": "<hiragana>", "gender": "male|female",
    "age": "teen|adult|elder", "role": "<role in the story, English>",
    "look": "<English visual description for an illustrator: hair style and colour, eyes, face, outfit, accessories. No age numbers, no body measurements. Distinct silhouettes and hair colours so characters are easy to tell apart.>"}}
 ],
 "locations": [{{"id": "<short lowercase romaji id>", "name": "<Japanese name>", "look": "<English description of the empty background: place, furniture, light, time of day>"}}],
 "parts": [{{"title": "<part title>", "beats": "<what happens in this part, 2-4 sentences in English>", "panels": <number>}}]
}}
Rules: {n_cast} main characters (at least one male and one female; adults only if the story needs them, e.g. a teacher or a parent);
{n_locs} locations; exactly {n_parts} parts whose "panels" add up to about {n_panels}.
Part 1 opens with a flash-forward hook from the climax (2-4 panels) and then goes back in time with a narration panel."""

PANELS_FMT = """Write panels {a} to {b} (part {k} of {n}: «{title}» — {beats}).

Characters (id | name | how others call them | gender | age | role):
{cast}
Locations (id | name):
{locs}
{prev}
Format for EVERY panel, exactly:
[SHOW: <location id> | <ids of the characters visible in the panel, from LEFT to RIGHT, comma-separated> | <camera in English: shot size, who stands on the left / right, pose and expression; leave empty wall or sky beside the speakers' heads>]
<speaker>: <line in Japanese>

Speakers: use the character's call name (e.g. 湊). Narration lines start with 「ナレーション:」. Inner thoughts: 「湊（心）: …」.
Shouting: 「ひより！: …」. Every speaker except the narration must be visible in that panel.
Each panel holds ONE picture for 1-4 lines (several lines on the same picture is normal), each line at most 40 Japanese
characters, natural spoken Japanese with feeling (…, ！？ where it fits). Vary the camera (close-up, two-shot, wide).
Write about {chars} Japanese characters of dialogue in total for these panels. Output ONLY the panels, nothing else."""


def budget(minutes: float) -> Dict[str, int]:
    """Số khung / phần / nhân vật / bối cảnh cho một tập dài `minutes` phút."""
    chars = int(max(2.0, minutes) * CHARS_PER_MIN)
    panels = max(12, round(chars / CHARS_PER_PANEL))
    parts = max(3, round(panels / PANELS_PER_PART))
    return {"chars": chars, "panels": panels, "parts": parts, "cast": 4 if minutes >= 8 else 3,
            "locs": min(8, max(3, parts + 1))}


def plan_prompt(material: str, lang_note: str, b: Dict[str, int]) -> str:
    return (material + "\n\n" + lang_note + "\n\nPlan an ORIGINAL voiced manga episode inspired by the material above "
            f"(about {b['panels']} panels, ~{b['chars']} Japanese characters of dialogue).\n\n"
            + PLAN_FMT.format(n_cast=f"{b['cast']}-{b['cast'] + 2}", n_locs=f"{b['locs']}-{b['locs'] + 2}",
                              n_parts=b["parts"], n_panels=b["panels"]))


def parse_plan(text: str) -> Dict:
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        raise ValueError("the plan is not JSON")
    plan = json.loads(m.group(0))
    cast = [c for c in plan.get("cast") or [] if isinstance(c, dict) and c.get("id")]
    if not cast or not plan.get("parts"):
        raise ValueError("the plan has no cast or no parts")
    for c in cast:
        c["id"] = re.sub(r"[^0-9a-z_]+", "_", str(c["id"]).lower()).strip("_") or "c"
    for l in plan.get("locations") or []:
        l["id"] = re.sub(r"[^0-9a-z_]+", "_", str(l.get("id") or "").lower()).strip("_") or "place"
    plan["cast"] = cast
    return plan


def _clean(s) -> str:
    return " ".join(str(s or "").replace("|", "/").split())


def panels_prompt(plan: Dict, k: int, a: int, b: int, prev: str, chars: int) -> str:
    part = plan["parts"][k]
    cast = "\n".join(f"{c['id']} | {_clean(c.get('name'))} | {_clean(c.get('call'))} | {c.get('gender', '')} | "
                     f"{c.get('age', '')} | {_clean(c.get('role'))}" for c in plan["cast"])
    locs = "\n".join(f"{l['id']} | {_clean(l.get('name'))}" for l in plan.get("locations") or [])
    prev_s = f"\nThe previous panels ended with:\n{prev}\n" if prev else ""
    return PANELS_FMT.format(a=a, b=b, k=k + 1, n=len(plan["parts"]), title=_clean(part.get("title")),
                             beats=_clean(part.get("beats")), cast=cast, locs=locs, prev=prev_s, chars=chars)


_SHOW = re.compile(r"\[SHOW:", re.I)


def panels_only(text: str) -> str:
    """Từ khung [SHOW: đầu tiên trở đi (model hay mở bằng câu dẫn / ``` )."""
    t = str(text or "").replace("```", "")
    m = _SHOW.search(t)
    return t[m.start():].strip() if m else ""


def header(plan: Dict) -> str:
    def nm(base, rd):
        base, rd = _clean(base), _clean(rd)
        return f"{base}（{rd}）" if base and rd and rd != base else base
    cast = "\n".join(f"{c['id']} | {nm(c.get('name'), c.get('reading'))} | {nm(c.get('call'), c.get('call_reading'))} | "
                     f"{c.get('gender', '')} | {c.get('age', '')} | {_clean(c.get('look'))}" for c in plan["cast"])
    locs = "\n".join(f"{l['id']} | {_clean(l.get('name'))} | {_clean(l.get('look'))}" for l in plan.get("locations") or [])
    return f"CAST:\n{cast}\nLOCATIONS:\n{locs}\n"


def dialogue_chars(script: str) -> int:
    """Chữ thoại (bỏ dàn nhân vật, tiêu đề khung, nhãn người nói)."""
    n = 0
    for b in re.split(r"\[SHOW:[^\]]*\]", str(script or ""))[1:]:
        for line in b.splitlines():
            if ":" in line or "：" in line:
                n += len(re.split(r"[:：]", line, 1)[1].strip())
    return n


def minutes_of_script(script: str) -> float:
    return round(dialogue_chars(script) / CHARS_PER_MIN, 1)


def write(ask: Callable[[str, str, int], str], material: str, lang_note: str, minutes: float,
          say: Callable[[str], None] = lambda m: None, cancelled: Callable[[], bool] = lambda: False) -> Tuple[str, str]:
    """(title, script) — ask(system, user, budget_words) gọi model của agent."""
    b = budget(minutes)
    say(f"planning a voiced manga episode · ~{b['panels']} panels in {b['parts']} parts")
    plan = None
    for attempt in range(2):
        try:
            plan = parse_plan(ask(SYSTEM, plan_prompt(material, lang_note, b), 1500))
            break
        except (ValueError, json.JSONDecodeError) as e:
            if attempt:
                raise RuntimeError(f"The model did not return a usable manga plan: {e}")
    parts = plan["parts"]
    want = [max(2, int(p.get("panels") or 0) or b["panels"] // len(parts)) for p in parts]
    out, prev, n = [], "", 0
    for k, cnt in enumerate(want):
        if cancelled():
            raise RuntimeError("cancelled")
        say(f"writing part {k + 1}/{len(parts)} · panels {n + 1}–{n + cnt}")
        chunk = ""
        for attempt in range(2):
            chunk = panels_only(ask(SYSTEM, panels_prompt(plan, k, n + 1, n + cnt, prev, cnt * CHARS_PER_PANEL),
                                    max(500, cnt * 45)))
            if chunk:
                break
        if not chunk:
            raise RuntimeError(f"The model wrote no panels for part {k + 1}.")
        out.append(chunk)
        n += len(_SHOW.findall(chunk))
        prev = "\n".join(chunk.splitlines()[-6:])
    title = _clean(plan.get("title")) or "【漫画】"
    return title, header(plan) + "\n" + "\n\n".join(out).strip() + "\n"
