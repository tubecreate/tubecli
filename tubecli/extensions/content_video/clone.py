# -*- coding: utf-8 -*-
"""«Clone sang ngôn ngữ khác» — phần DỊCH (hàm thuần, không mạng; pipeline.py lo gọi model và Studio).

User 25/9/2026: «tôi làm xong một bài bằng tiếng việt, tôi muốn sử dụng lại hình ảnh và nội dung của nó nhưng dùng
ngôn ngữ khác, tôi muốn bấm clone và chọn ngôn ngữ». Mỗi nhịp dịch MỘT-MỘT (không gộp, không tách nhịp): ảnh, nhịp
và chỗ cắt giữ nguyên, chỉ đổi chữ — lời đọc, tiêu đề nhịp, chữ trên bảng (`metadata.scene`), nhãn sơ đồ.
"""
import copy
import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Chữ trên bảng theo loại cảnh (scene_kits/chalk_text.py build, chalk.py versus). Khoá lạ không dịch: `sprite`,
# `side`, `type` là tham chiếu/thiết đặt; `subject`/`painting` là prompt vẽ tiếng Anh (nhãn sơ đồ đi riêng).
SCENE_STR_KEYS = ("head", "body", "hot", "kick", "title", "sub", "question", "answer", "note", "stamp", "author",
                  "left", "right", "caption", "hot_label")
SCENE_LIST_KEYS = ("items", "lines", "y_labels", "x_labels", "l_items", "r_items")
BATCH = 12                       # nhịp mỗi lượt gọi model — đủ ngữ cảnh, trả lời không quá dài
_LABEL_RE = re.compile(r"'([^']{1,40})'")
_WORDY = re.compile(r"\w", re.UNICODE)


def _wordy(s: Any) -> bool:
    return isinstance(s, str) and bool(_WORDY.search(s))


def scene_texts(scene: Any) -> Dict[str, str]:
    """{đường dẫn: chữ} cần dịch của một cảnh: "head", "items.0", "items.2.1" (nhãn của [sprite, nhãn])."""
    out: Dict[str, str] = {}
    if not isinstance(scene, dict):
        return out
    for k in SCENE_STR_KEYS:
        if _wordy(scene.get(k)):
            out[k] = scene[k]
    for k in SCENE_LIST_KEYS:
        v = scene.get(k)
        if not isinstance(v, list):
            continue
        for i, it in enumerate(v):
            if _wordy(it):
                out[f"{k}.{i}"] = it
            elif isinstance(it, (list, tuple)) and len(it) >= 2 and _wordy(it[1]):
                out[f"{k}.{i}.1"] = it[1]      # [tham chiếu hình, nhãn] — chỉ dịch nhãn
    return out


def apply_scene_texts(scene: Dict, done: Dict[str, str]) -> Dict:
    """Cảnh mới với chữ đã dịch; khoá thiếu bản dịch giữ chữ cũ. `hot` phải nằm TRONG `head` (bộ cảnh chỉ tô chữ
    có thật) — lệch thì bỏ tô, còn hơn tô một cụm không xuất hiện."""
    sc = copy.deepcopy(scene)
    for path, text in (done or {}).items():
        if not isinstance(text, str) or not text.strip():
            continue
        parts = path.split(".")
        key = parts[0]
        if len(parts) == 1 and key in SCENE_STR_KEYS and key in sc:
            sc[key] = text.strip()
        elif len(parts) >= 2 and key in SCENE_LIST_KEYS and isinstance(sc.get(key), list):
            try:
                i = int(parts[1])
            except ValueError:
                continue
            if not 0 <= i < len(sc[key]):
                continue
            if len(parts) == 2 and isinstance(sc[key][i], str):
                sc[key][i] = text.strip()
            elif len(parts) == 3 and parts[2] == "1" and isinstance(sc[key][i], (list, tuple)) and len(sc[key][i]) >= 2:
                it = list(sc[key][i])
                it[1] = text.strip()
                sc[key][i] = it
    hot, head = str(sc.get("hot") or ""), str(sc.get("head") or "")
    if hot and head and hot not in head:
        low = head.lower().find(hot.lower())
        sc["hot"] = head[low:low + len(hot)] if low >= 0 else ""
    return sc


def diagram_labels(scene: Any) -> List[str]:
    if not isinstance(scene, dict) or str(scene.get("type") or "") != "diagram":
        return []
    return [m.strip() for m in _LABEL_RE.findall(str(scene.get("subject") or "")) if m.strip()]


def shot_meta(shot: Dict) -> Dict:
    raw = shot.get("metadata")
    if isinstance(raw, dict):
        return raw
    try:
        m = json.loads(raw or "{}")
    except (TypeError, ValueError):
        m = {}
    return m if isinstance(m, dict) else {}


def work_items(shots: List[Dict]) -> List[Dict]:
    """Mỗi nhịp một mục gửi model: {id, narration, title?, texts?, labels?} — bỏ khoá rỗng cho gọn."""
    out = []
    for sh in sorted(shots, key=lambda s: (s.get("storyboard_number") or 0, s.get("id") or 0)):
        scene = shot_meta(sh).get("scene")
        item: Dict[str, Any] = {"id": str(sh.get("id")),
                                "narration": " ".join(str(sh.get("narration_text") or "").split())}
        if _wordy(sh.get("title")):
            item["title"] = str(sh["title"])
        texts = scene_texts(scene)
        if texts:
            item["texts"] = texts
        labels = diagram_labels(scene)
        if labels:
            item["labels"] = labels
        # Nhịp không có chữ nào (lời rỗng, bảng trống) thì khỏi gửi — Studio chép nguyên. Lời rỗng mà bảng CÓ chữ vẫn
        # phải dịch: bỏ qua là chữ tiếng gốc nằm lại trên hình bản clone (nhịp lời rỗng có thật — lỗi chia lời .151).
        if item["narration"] or len(item) > 2:
            out.append(item)
    return out


def batches(items: List[Dict], size: int = BATCH) -> List[List[Dict]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def system_prompt(src_name: str, tgt_name: str) -> str:
    return (
        f"You are a professional translator for explainer videos. Translate from {src_name} into {tgt_name}.\n"
        "You receive a JSON object {\"shots\": [...]}. Each shot has an `id`, a `narration` (the voice-over, read "
        "aloud) and optionally `title`, `texts` (short on-screen chalkboard texts, keyed by path) and `labels` "
        "(short labels written inside a diagram picture).\n"
        "Rules:\n"
        f"- Translate EVERY shot one-to-one into natural, spoken {tgt_name}: same meaning, every sentence, nothing "
        "added, nothing summarised, nothing merged with another shot. Keep numbers, units and names.\n"
        "- On-screen `texts` stay short (a few words, like the original). The `hot` text is a highlighted phrase: it "
        "must be copied EXACTLY, letter for letter, from your translated `head`.\n"
        "- `labels`: same count and order, at most 3 words each, no apostrophes.\n"
        "- Reply with ONLY a JSON object {\"shots\": [...]} with the same ids and the same keys you received (same "
        "paths inside `texts`). No markdown, no comments.")


def user_prompt(batch: List[Dict]) -> str:
    return json.dumps({"shots": batch}, ensure_ascii=False)


def parse_reply(text: str) -> Dict[str, Dict]:
    """{id: mục đã dịch} từ trả lời của model; trả lời hỏng → {}."""
    s = str(text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        return {}
    try:
        obj = json.loads(s[a:b + 1])
    except ValueError:
        return {}
    shots = obj.get("shots") if isinstance(obj, dict) else None
    out: Dict[str, Dict] = {}
    for it in shots if isinstance(shots, list) else []:
        if isinstance(it, dict) and it.get("id") is not None and (
                _wordy(it.get("narration")) or isinstance(it.get("texts"), dict)
                or isinstance(it.get("labels"), list) or _wordy(it.get("title"))):
            out[str(it["id"])] = it
    return out


def missing(batch: List[Dict], got: Dict[str, Dict]) -> List[Dict]:
    """Mục chưa có bản dịch dùng được: bản gốc có lời mà bản dịch không có lời, hay bản gốc chỉ có chữ trên
    bảng / tiêu đề / nhãn mà không có mục trả về nào."""
    out = []
    for it in batch:
        tr = got.get(it["id"])
        if _wordy(it.get("narration")):
            if not (tr and _wordy(tr.get("narration"))):
                out.append(it)
        elif not tr:
            out.append(it)
    return out


def to_studio(items: List[Dict], got: Dict[str, Dict], scenes: Dict[str, Dict]) -> Dict[str, Dict]:
    """Bản dịch → body `texts` của route Studio clone-shots: {id: {narration_text, title, scene, labels}}."""
    out: Dict[str, Dict] = {}
    for it in items:
        tr = got.get(it["id"])
        if not tr:
            continue
        row: Dict[str, Any] = {}
        narration = " ".join(str(tr.get("narration") or "").split())
        if it.get("narration") and _wordy(narration):
            row["narration_text"] = narration
        if it.get("title") and _wordy(tr.get("title")):
            row["title"] = str(tr["title"]).strip()
        scene = scenes.get(it["id"])
        if isinstance(scene, dict) and isinstance(tr.get("texts"), dict):
            row["scene"] = apply_scene_texts(scene, {k: v for k, v in tr["texts"].items() if k in (it.get("texts") or {})})
        labels = tr.get("labels")
        if it.get("labels") and isinstance(labels, list):
            row["labels"] = [str(x) for x in labels][:len(it["labels"])]
        out[it["id"]] = row
    return out


def title_prompt(title: str, src_name: str, tgt_name: str) -> Tuple[str, str]:
    return (f"Translate this YouTube video title from {src_name} into {tgt_name}. Keep it natural and catchy for "
            f"{tgt_name} viewers, same meaning, similar length. Reply with the title only, no quotes.",
            str(title or ""))


def clean_title(text: str, fallback: str) -> str:
    t = " ".join(str(text or "").split()).strip().strip('"“”«»').strip()
    return t[:150] if t else fallback
