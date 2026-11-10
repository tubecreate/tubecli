"""Cấu hình NGÁCH của agent + bộ lọc ngách (niche gate) — 4/11/2026.

Sự cố thật: agent «Deep Biblical Echoes Niche Researcher» (kênh Kinh Thánh) làm task #149 «Big Tech's Selloff» — bước
gather đưa nguyên 5 bài báo tài chính trong kho vào bước script, không bước nào hỏi chủ đề có thuộc ngách không.

niche_gate(agent, text) → {pass, score, reason, deny}:
  (a) chứa từ cấm (deny_terms) → loại ngay, không gọi model — so không phân biệt hoa thường, có dấu / không dấu;
  (b) không thì hỏi một model RẺ chấm 0-10 mức liên quan tới must_relate_to (prompt ở tubecli/prompts/niche_gate.txt);
  (c) đạt khi score ≥ min_niche_score.
Model không trả lời được → KHÔNG đạt (cổng ĐÓNG, user chọn 4/11/2026): thà dừng ở review còn hơn làm video lạc ngách.
"""
import hashlib
import json
import logging
import re
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("Niche")

DEFAULTS: Dict[str, Any] = {
    "enabled": True,               # bộ lọc ngách BẬT mặc định cho mọi agent
    "language": "",
    "niche_description": "",
    "must_relate_to": [],
    "deny_terms": [],
    "min_niche_score": 7,
    "gate_model": "",              # rỗng = model AI mặc định của máy
    "browser_profile_ids": [],
    "explore_ratio": 0.2,
    "cooldown_days": 21,
}
MAX_TERMS = 60
MAX_TEXT = 6000                    # chữ đưa cho model chấm (đầu bài là đủ để biết chủ đề)
UNCONFIGURED = "NICHE_UNCONFIGURED"


# ── cấu hình ──────────────────────────────────────────────────────────────────
def _terms(v) -> List[str]:
    if isinstance(v, str):
        v = re.split(r"[,\n;]", v)
    if not isinstance(v, (list, tuple)):
        return []
    out: List[str] = []
    for x in v:
        s = " ".join(str(x or "").split())[:80]
        if s and s.lower() not in (o.lower() for o in out):
            out.append(s)
    return out[:MAX_TERMS]


def coerce(v: Any) -> Dict[str, Any]:
    """Cấu hình ngách sạch từ bất kỳ giá trị nào (không bao giờ ném; rác → mặc định)."""
    src = v if isinstance(v, dict) else {}
    out = dict(DEFAULTS)
    out["enabled"] = src.get("enabled") is not False and str(src.get("enabled")).lower() not in ("false", "0", "off")
    for key in ("language", "niche_description", "gate_model"):
        out[key] = " ".join(str(src.get(key) or "").split())[:600 if key == "niche_description" else 120]
    out["must_relate_to"] = _terms(src.get("must_relate_to"))
    out["deny_terms"] = _terms(src.get("deny_terms"))
    out["browser_profile_ids"] = [str(x) for x in _terms(src.get("browser_profile_ids"))][:20]
    try:
        out["min_niche_score"] = max(0, min(10, int(float(src.get("min_niche_score", DEFAULTS["min_niche_score"])))))
    except (TypeError, ValueError):
        pass
    try:
        out["explore_ratio"] = max(0.0, min(1.0, float(src.get("explore_ratio", DEFAULTS["explore_ratio"]))))
    except (TypeError, ValueError):
        pass
    try:
        out["cooldown_days"] = max(0, min(365, int(float(src.get("cooldown_days", DEFAULTS["cooldown_days"])))))
    except (TypeError, ValueError):
        pass
    return out


def configured(cfg: Dict[str, Any]) -> bool:
    return bool(cfg.get("must_relate_to") or cfg.get("niche_description"))


FROM_PROMPT = "NICHE_FROM_PROMPT"
_BLOCK_RE = re.compile(r"^\W*NICHE\s+CONFIG\b.*$", re.I | re.M)
_LINE_RE = re.compile(r"^\s*[-*•]?\s*([A-Za-z][A-Za-z /\-]{1,40}?)\s*(?:\([^)]*\))?\s*:\s*(.*\S)\s*$")
# Nhãn trong khối → trường của cấu hình (so chữ thường, bỏ khoảng trắng thừa)
_LABELS = {
    "niche": "niche_description", "niche description": "niche_description",
    "language": "language",
    "must relate to": "must_relate_to", "must-relate-to": "must_relate_to",
    "deny terms": "deny_terms", "deny": "deny_terms", "blocked terms": "deny_terms",
    "minimum niche score": "min_niche_score", "min niche score": "min_niche_score",
}


def from_system_prompt(text: str) -> Dict[str, Any]:
    """Đọc khối «NICHE CONFIG» mà chủ agent viết sẵn trong system prompt (10/11/2026 — «Deep Biblical Echoes» có đủ
    Must relate to / Deny terms / Minimum niche score trong prompt mà ô Niche của agent để trống ⇒ cổng chạy bằng
    research brief + cảnh báo NICHE_UNCONFIGURED). {} khi không có khối; chỉ trả các trường đọc được."""
    s = str(text or "")
    m = _BLOCK_RE.search(s)
    if not m:
        return {}
    out: Dict[str, Any] = {}
    started = False
    for line in s[m.end():].splitlines()[:40]:
        if not line.strip():
            if started:
                break           # khối kết thúc ở dòng trống đầu tiên sau các dòng «Nhãn: giá trị»
            continue
        lm = _LINE_RE.match(line)
        if not lm:
            if started:
                break
            continue
        key = _LABELS.get(" ".join(lm.group(1).lower().split()))
        if not key:
            started = True      # nhãn khác (Channel, Keyword bank…) vẫn thuộc khối
            continue
        started = True
        val = lm.group(2).strip()
        if key == "min_niche_score":
            n = re.search(r"\d+(?:\.\d+)?", val)
            if n:
                out[key] = n.group(0)
        elif key in ("must_relate_to", "deny_terms"):
            out[key] = [x for x in re.split(r"[,;]", val) if x.strip()]
        else:
            out[key] = val
    return out


def effective(agent) -> Tuple[Dict[str, Any], List[str]]:
    """(cấu hình dùng thật, cảnh báo). Trường nào của ô Niche còn trống thì lấy từ khối «NICHE CONFIG» trong system
    prompt (cảnh báo NICHE_FROM_PROMPT). Vẫn chưa có gì: mô tả lấy từ research_prompt / mô tả agent (an toàn — cổng vẫn
    chạy), kèm cảnh báo NICHE_UNCONFIGURED để task nói rõ."""
    raw = getattr(agent, "niche", None)
    cfg = coerce(raw)
    warns: List[str] = []
    block = from_system_prompt(getattr(agent, "system_prompt", "") or "")
    parsed = coerce(block)
    filled = False
    if block:
        was_configured = configured(cfg)
        for key in ("must_relate_to", "deny_terms", "niche_description", "language"):
            if not cfg.get(key) and parsed.get(key):
                cfg[key] = parsed[key]
                filled = True
        # Điểm tối thiểu: coerce luôn trả 7 khi trống nên không phân biệt được «chủ để 7» với «chưa khai» — chỉ lấy
        # của prompt khi ô Niche CHƯA khai gì (cả phải-liên-quan lẫn mô tả).
        src_min = (raw or {}).get("min_niche_score") if isinstance(raw, dict) else None
        if not was_configured and src_min in (None, "", DEFAULTS["min_niche_score"]) and "min_niche_score" in block:
            cfg["min_niche_score"] = parsed["min_niche_score"]
    if filled:
        warns.append(FROM_PROMPT)
    if configured(cfg):
        return cfg, warns
    desc = " ".join(str(getattr(agent, "research_prompt", "") or getattr(agent, "description", "") or "").split())
    cfg["niche_description"] = (desc or str(getattr(agent, "name", "") or ""))[:600]
    return cfg, warns + [UNCONFIGURED]


# ── từ cấm ────────────────────────────────────────────────────────────────────
def fold(text: str) -> str:
    from tubecli.core.scraped_store import fold as _fold
    return " ".join(_fold(str(text or "")).split())


def deny_hit(cfg: Dict[str, Any], text: str) -> str:
    """Từ cấm đầu tiên có trong `text` (so theo từ, không phân biệt hoa thường / dấu), hay ""."""
    hay = " " + re.sub(r"[^0-9a-z]+", " ", fold(text)) + " "
    for term in cfg.get("deny_terms") or []:
        needle = re.sub(r"[^0-9a-z]+", " ", fold(term)).strip()
        if needle and f" {needle} " in hay:
            return term
    return ""


# ── chấm bằng model ───────────────────────────────────────────────────────────
_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_CACHE_MAX = 2000
_CACHE_LOCK = threading.Lock()
_FAILOVER_RE = re.compile(r"^\s*⚠️?\s*\*?\[Auto-Failover[^\]]*\]\*?\s*", re.I)


def gate_model(cfg: Dict[str, Any]) -> str:
    m = str(cfg.get("gate_model") or "").strip()
    if m:
        return m
    try:
        from tubecli import config
        return str(config.read_global_settings().get(config.GLOBAL_DEFAULT_MODEL_SETTING) or "").strip()
    except Exception:       # noqa: BLE001
        return ""


def _key(cfg: Dict[str, Any], kind: str, text: str) -> str:
    raw = json.dumps([cfg.get("niche_description"), cfg.get("must_relate_to"), kind, text], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parse_score(reply: str) -> Tuple[int, str]:
    """(điểm 0-10, lý do) từ câu trả lời của model; không đọc được → (-1, câu gốc)."""
    s = _FAILOVER_RE.sub("", str(reply or "")).strip()
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            score = int(round(float(obj.get("score"))))
            return max(0, min(10, score)), " ".join(str(obj.get("reason") or "").split())[:200]
        except (ValueError, TypeError, AttributeError):
            pass
    m = re.search(r"\bscore\W{0,5}(\d{1,2})\b", s, re.I)
    if m:
        return max(0, min(10, int(m.group(1)))), ""
    return -1, s[:200]


def _ask(agent, model: str, prompt: str) -> str:
    from tubecli.core.brain import AgentBrain
    base = agent.to_dict() if hasattr(agent, "to_dict") else dict(agent or {})
    ag = dict(base, model=model, provider="")
    with AgentBrain.output_budget(300):
        return str(AgentBrain._call_llm(ag, [{"role": "user", "content": prompt}], temperature=0.0) or "")


def niche_gate(agent, text: str, kind: str = "item", cfg: Dict[str, Any] = None) -> Dict[str, Any]:
    """{pass, score, reason, deny, cached}. Cổng tắt (enabled=False) → luôn đạt, score None."""
    if cfg is None:
        cfg, _warn = effective(agent)
    if not cfg.get("enabled", True):
        return {"pass": True, "score": None, "reason": "niche gate is off for this agent", "deny": "", "cached": False}
    text = str(text or "").strip()
    hit = deny_hit(cfg, text)
    if hit:
        return {"pass": False, "score": 0, "reason": f"contains the blocked term «{hit}»", "deny": hit, "cached": False}
    if not text:
        return {"pass": False, "score": 0, "reason": "no text to judge", "deny": "", "cached": False}
    body = text[:MAX_TEXT]
    key = _key(cfg, kind, body)
    with _CACHE_LOCK:
        hit_c = _CACHE.get(key)
        if hit_c is not None:
            _CACHE.move_to_end(key)
            out = dict(hit_c)
            out["pass"] = out["score"] is not None and out["score"] >= int(cfg["min_niche_score"])
            out["cached"] = True
            return out
    model = gate_model(cfg)
    if not model:
        return {"pass": False, "score": None, "reason": "no AI model is set for the niche gate (niche.gate_model or the "
                "server default) — the gate stays closed", "deny": "", "cached": False}
    from tubecli.core import prompt_templates
    prompt = prompt_templates.render(
        "niche_gate", niche=cfg.get("niche_description") or "(not described)",
        must_relate_to=", ".join(cfg.get("must_relate_to") or []) or "(see the niche)",
        language=cfg.get("language") or "any", kind=kind, text=body)
    try:
        reply = _ask(agent, model, prompt)
    except Exception as e:      # noqa: BLE001
        reply = f"[Error] {e}"
    score, reason = parse_score(reply)
    if score < 0:
        # Model lỗi / trả lời lạc: cổng ĐÓNG, và KHÔNG ghi vào cache (lần sau hỏi lại).
        return {"pass": False, "score": None, "reason": "the niche gate model did not answer: " + " ".join(
            str(reply or "").split())[:160], "deny": "", "cached": False, "unavailable": True}
    result = {"score": score, "reason": reason, "deny": "", "model": model}
    with _CACHE_LOCK:
        _CACHE[key] = result
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    out = dict(result, cached=False)
    out["pass"] = score >= int(cfg["min_niche_score"])
    return out


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
