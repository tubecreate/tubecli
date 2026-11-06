"""Lồng lại giọng đọc: MỘT file đọc cả bài (Muse) → cắt thành file theo từng cảnh + mốc chữ cho phụ đề (21/10/2026).

User: «gọi 1 lần full luôn… làm capcut xong lồng lại bằng muse», rồi «chỗ logic lồng giọng bạn để ở phần tạo task». Muse
đọc cả bài trong MỘT chat (mỗi chat một giọng ⇒ không đọc theo từng cảnh được), nên phải tự cắt file dài theo cảnh:

1. Whisper (faster_whisper, nếu máy có) chép lời kèm mốc từng chữ → so TỪNG KÝ TỰ với kịch bản (SequenceMatcher) → giờ của
   mọi ký tự kịch bản (chỗ không khớp nội suy).
2. Mốc từ của Whisper lệch ±0,6 s (đo trên bản CapCut) ⇒ GHIM chữ-cuối-câu vào khoảng lặng thật bằng QUY HOẠCH ĐỘNG cả bài:
   khoảng lặng j tăng dần, chi phí = lệch giờ (sau trừ trễ chung) − thưởng khoảng lặng dài + 0,5 × |độ dài câu theo ghép −
   theo Whisper|. Chọn từng câu riêng lẻ từng nhầm khoảng nghỉ sau «四つ、» (giữa câu SAU) với khoảng nghỉ cuối đoạn.
3. Cắt giữa khoảng lặng giữa hai đoạn (đoạn = cảnh). Thử trên bản CapCut có ranh giới thật: 23 chỗ cắt lệch ≤ 0,1 s.
4. Mốc chữ ghi THEO KÝ TỰ (`<mp3>.words.json`): Studio `align_to_text` gộp mốc theo độ dài từ của nó ⇒ khớp mọi cách tách.

Máy không có faster_whisper: cắt theo khoảng lặng — lời xin Muse đòi 1,2–1,5 s lặng ở mỗi chỗ chuyển cảnh, chọn N−1 khoảng lặng
dài theo thứ tự cảnh gần vị trí ước theo số ký tự; không ghi mốc chữ (Studio tự ước lượng phụ đề như cũ).
"""
import difflib
import json
import logging
import os
import re
import subprocess
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MIN_SIL = 0.22           # khoảng lặng ngắn hơn là quãng ngắt trong chữ («よっつ» có っ ~0,2 s), không phải cuối câu
MIN_MATCH = 0.75         # Whisper nghe lại khớp kịch bản dưới mức này ⇒ Muse đọc sai / bỏ đoạn: không lồng
PARA_SIL = 0.5           # đường không Whisper: chỗ chuyển cảnh phải lặng ít nhất chừng này
_DROP = re.compile(r"[\s、。「」『』,.!?！？・…：:;；（）()\"'“”‘’ー〜~\-—]")
_SENT_END = re.compile(r"[。！？!?]|[.](?=\s|$)")


def _keep(ch: str) -> str:
    c = unicodedata.normalize("NFKC", ch)
    return c.lower() if c and not _DROP.fullmatch(c) else ""


def norm_with_map(text: str) -> Tuple[str, List[int]]:
    """(chuỗi chuẩn hoá — bỏ dấu câu/khoảng trắng, NFKC, chữ thường; [chỉ số ký tự GỐC của từng ký tự chuẩn hoá])."""
    out, idx = [], []
    for i, ch in enumerate(str(text or "")):
        for c in _keep(ch):
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def silences(path: str, ffmpeg: str, noise: str = "-35dB", min_dur: float = 0.2) -> List[Tuple[float, float]]:
    err = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", path, "-af", f"silencedetect=n={noise}:d={min_dur}",
                          "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    st = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", err)]
    en = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", err)]
    return list(zip(st, en))


def whisper_chars(path: str, language: str = "", progress: Optional[Callable[[float], Any]] = None,
                  model_size: str = "", beam: int = 0) -> Optional[Tuple[str, List[float]]]:
    """(ký tự chuẩn hoá Whisper nghe được, giờ giữa của từng ký tự); None khi máy không có faster_whisper.
    progress(giây đã nghe) gọi sau mỗi đoạn Whisper trả về — bảng việc hiện «đã nghe m:ss / M:SS»."""
    try:
        from faster_whisper import WhisperModel
    except Exception:       # noqa: BLE001
        return None
    model = WhisperModel(model_size or WHISPER_MODEL, device="cpu", compute_type="int8")
    lang = str(language or "").split("-")[0].lower() or None
    segs, _ = model.transcribe(path, language=lang, word_timestamps=True, beam_size=beam or WHISPER_BEAM, vad_filter=False)
    chars, times = [], []
    for sg in segs:
        if progress is not None:
            try:
                progress(float(sg.end or 0))
            except Exception:      # noqa: BLE001 — báo tiến độ hỏng không được làm hỏng lượt nghe
                pass
        for w in sg.words or []:
            k = "".join(_keep(c) for c in w.word)
            for j, c in enumerate(k):
                chars.append(c)
                times.append(w.start + (w.end - w.start) * (j + 0.5) / len(k))
    return "".join(chars), times


def _char_times(script: str, heard: str, htimes: List[float]) -> Tuple[List[float], float]:
    """Giờ của từng ký tự kịch bản (khớp theo SequenceMatcher, chỗ không khớp nội suy) + tỉ lệ khớp."""
    sm = difflib.SequenceMatcher(None, script, heard, autojunk=False)
    t: List[Optional[float]] = [None] * len(script)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            t[a + k] = htimes[b + k]
    known = [i for i, v in enumerate(t) if v is not None]
    if not known:
        return [0.0] * len(script), 0.0
    for i in range(len(t)):
        if t[i] is None:
            lo = max((k for k in known if k < i), default=None)
            hi = min((k for k in known if k > i), default=None)
            if lo is not None and hi is not None:
                t[i] = t[lo] + (t[hi] - t[lo]) * (i - lo) / (hi - lo)
            else:
                t[i] = t[lo] if lo is not None else t[hi]
    return [float(v) for v in t], len(known) / max(1, len(script))


def _anchor(t_of: List[float], ends: List[int], sil: List[Tuple[float, float]]) -> Tuple[List[float], int]:
    """Ghim chữ-cuối-câu vào khoảng lặng thật (quy hoạch động cả bài) rồi nội suy lại giữa các neo. Trả (giờ mới, số neo)."""
    diffs = []
    for i in ends:
        near = [s for s, e in sil if t_of[i] - 0.9 <= s <= t_of[i] + 0.4 and e - s >= MIN_SIL]
        if near:
            diffs.append(t_of[i] - min(near, key=lambda s: abs(s - t_of[i])))
    lag = sorted(diffs)[len(diffs) // 2] if diffs else 0.0
    wk = [t_of[i] - lag for i in ends]
    skip = 0.8
    cands = [[(j, abs(s - w) - 0.6 * min(e - s, 1.0)) for j, (s, e) in enumerate(sil)
              if w - 1.0 <= s <= w + 1.0 and e - s >= MIN_SIL] for w in wk]
    dp: List[Dict[int, Tuple[float, Optional[Tuple[int, int]]]]] = [dict() for _ in ends]
    for k in range(len(ends)):
        for j, lc in cands[k]:
            best: Tuple[float, Optional[Tuple[int, int]]] = (skip * k + lc, None)
            for kp in range(max(0, k - 4), k):
                for jp, (cp, _) in dp[kp].items():
                    if jp >= j:
                        continue
                    c = cp + skip * (k - kp - 1) + lc + 0.5 * abs((sil[j][0] - sil[jp][0]) - (wk[k] - wk[kp]))
                    if c < best[0]:
                        best = (c, (kp, jp))
            dp[k][j] = best
    end_best, state = None, None
    for k in range(len(ends)):
        for j, (c, _) in dp[k].items():
            c2 = c + skip * (len(ends) - 1 - k)
            if end_best is None or c2 < end_best:
                end_best, state = c2, (k, j)
    anchors: Dict[int, float] = {}
    while state:
        k, j = state
        anchors[ends[k]] = sil[j][0]
        if ends[k] + 1 < len(t_of):
            anchors[ends[k] + 1] = sil[j][1]
        state = dp[k][j][1]
    keys: List[int] = []
    for k in sorted(anchors):
        if not keys or anchors[k] > anchors[keys[-1]]:
            keys.append(k)
    if not keys:
        return t_of, 0
    t2 = list(t_of)
    for i in range(len(t_of)):
        if i <= keys[0]:
            t2[i] = t_of[i] + (anchors[keys[0]] - t_of[keys[0]])
        elif i >= keys[-1]:
            t2[i] = t_of[i] + (anchors[keys[-1]] - t_of[keys[-1]])
    for k0, k1 in zip(keys[:-1], keys[1:]):
        a0, a1, w0, w1 = anchors[k0], anchors[k1], t_of[k0], t_of[k1]
        for i in range(k0, k1 + 1):
            t2[i] = (a0 + (t_of[i] - w0) * (a1 - a0) / (w1 - w0)) if w1 > w0 else (a0 + (a1 - a0) * (i - k0) / max(1, k1 - k0))
    return t2, len(keys)


def _cut_between(a: float, b: float, sil: List[Tuple[float, float]]) -> float:
    """Chỗ cắt giữa đoạn trước (chữ cuối ở `a`) và đoạn sau (chữ đầu ở `b`): giữa khoảng lặng dài nằm trong khe; nằm ngoài
    khe bị phạt theo khoảng cách."""
    best = None
    for s, e in sil:
        if e < a - 0.8 or s > b + 0.8:
            continue
        dist = max(0.0, (a - 0.1) - e, s - (b + 0.1))
        score = (e - s) - 1.5 * dist
        if best is None or score > best[0]:
            best = (score, (s + e) / 2)
    return best[1] if best else (a + b) / 2


# Đường KHÔNG Whisper có giọng tạm (dò 6/11/2026 trên tập 888, chuẩn = chỗ cắt Whisper): −30 dB/0,15 s thấy 72/78 chỗ cắt
# thật; w_abs 0,1 · w_len 1,0 · lặng ≥ 0,12 s · cửa sổ ±5 s → lệch TB 0,50 s, 15/78 chỗ > 1 s (chia thẳng theo tỉ lệ: 1,75 s).
# Kém Whisper xa ⇒ chỉ là đường lùi khi máy không có faster_whisper.
GUIDE_WINDOW = 5.0
GUIDE_MIN_SIL = 0.12
GUIDE_NOISE, GUIDE_SIL_DUR = "-30dB", 0.15
# Whisper cho việc CẮT: base + beam 1 (36 s / 13′ trên máy dev, khớp 0,86, chỗ cắt lệch ≤ 0,21 s so với small/beam 5 — chữ
# cuối câu còn được ghim vào khoảng lặng thật bằng _anchor). small/beam 5 cũ: ~250 s, 23′ khi máy bận.
WHISPER_MODEL, WHISPER_BEAM = "base", 1


def _cuts_by_guide(guides: List[float], total: float, sil: List[Tuple[float, float]], w_abs: float = 0.1,
                   w_len: float = 1.0, min_sil: Optional[float] = None, window: Optional[float] = None) -> Optional[List[float]]:
    """Chỗ cắt theo THỜI LƯỢNG GIỌNG TẠM từng cảnh (CapCut / Edge đã đọc đúng lời ấy) — không cần Whisper (6/11/2026).

    Đo tập 888: tổng giọng tạm Edge 13,5′ vs file người dùng 12,3′, từng cảnh 0,71–1,05× ⇒ chia thẳng theo tỉ lệ lệch tới 5,2 s.
    Nên: co giãn cho tổng = độ dài file, rồi quy hoạch động chọn một khoảng lặng cho mỗi chỗ cắt (trong ±GUIDE_WINDOW): chi
    phí = lệch độ dài ĐOẠN so với giọng tạm (sai số không cộng dồn) + 0,3 × lệch vị trí tuyệt đối − thưởng khoảng lặng dài
    (cuối câu nghỉ lâu hơn dấu phẩy). Trả [0, c1, …, total] hoặc None khi không đủ khoảng lặng."""
    n = len(guides)
    if n <= 1:
        return [0.0, total]
    g = [max(0.05, float(x or 0)) for x in guides]
    scale = total / sum(g)
    g = [x * scale for x in g]
    expect, acc = [], 0.0
    for x in g[:-1]:
        acc += x
        expect.append(acc)
    min_sil = GUIDE_MIN_SIL if min_sil is None else min_sil
    window = GUIDE_WINDOW if window is None else window
    cand = sorted(((s + e) / 2, e - s) for s, e in sil if e - s >= min_sil and 0.2 < (s + e) / 2 < total - 0.2)
    if len(cand) < n - 1:
        return None
    INF = float("inf")
    win = [[j for j, (m, _) in enumerate(cand) if abs(m - expect[p]) <= window] for p in range(n - 1)]
    if any(not w for w in win):
        return None

    def local(p: int, j: int) -> float:
        m, L = cand[j]
        return w_abs * abs(m - expect[p]) - w_len * min(L, 1.2)

    dp: List[Dict[int, float]] = [dict() for _ in range(n - 1)]
    back: List[Dict[int, int]] = [dict() for _ in range(n - 1)]
    for j in win[0]:
        dp[0][j] = abs(cand[j][0] - g[0]) + local(0, j)
    for p in range(1, n - 1):
        for j in win[p]:
            best, arg = INF, -1
            for jp, v in dp[p - 1].items():
                if jp >= j or cand[j][0] - cand[jp][0] < 0.3:
                    continue
                c = v + abs((cand[j][0] - cand[jp][0]) - g[p])
                if c < best:
                    best, arg = c, jp
            if arg >= 0:
                dp[p][j], back[p][j] = best + local(p, j), arg
    last = {j: v + abs((total - cand[j][0]) - g[-1]) for j, v in dp[n - 2].items()}
    if not last:
        return None
    j = min(last, key=last.get)
    picks = []
    for p in range(n - 2, -1, -1):
        picks.append(j)
        j = back[p].get(j, -1)
    picks.reverse()
    if any(x < 0 for x in picks):
        return None
    return [0.0] + [cand[j][0] for j in picks] + [total]


def _cuts_by_silence(lengths: List[int], total: float, sil: List[Tuple[float, float]]) -> Optional[List[float]]:
    """Không có Whisper: N−1 chỗ cắt = khoảng lặng ≥ PARA_SIL theo thứ tự, gần vị trí ước theo số ký tự (quy hoạch động)."""
    n = len(lengths)
    if n <= 1:
        return [0.0, total]
    inner = [(s, e) for s, e in sil if e - s >= PARA_SIL and 0.3 < (s + e) / 2 < total - 0.3]
    if len(inner) < n - 1:
        return None
    # Muse nghỉ ở chỗ chuyển cảnh DÀI NHẤT bài (đo 21/10/2026: nam 1,34–1,43 s giữa các câu ≤ 1,1 s; nữ 2,0–2,6 s) ⇒ chỉ xét
    # khoảng lặng gần bằng N−1 khoảng dài nhất; thưởng độ dài mạnh hơn lệch vị trí ước theo số ký tự (ước lệch tới 8 s).
    durs = sorted((e - s for s, e in inner), reverse=True)
    floor = max(PARA_SIL, durs[n - 2] * 0.75)
    cand = [(s, e) for s, e in inner if e - s >= floor]
    tot = float(sum(lengths)) or 1.0
    expect, acc = [], 0
    for L in lengths[:-1]:
        acc += L
        expect.append(total * acc / tot)
    INF = float("inf")
    # dp[p][j] = chi phí tốt nhất khi chỗ cắt thứ p dùng khoảng lặng j
    dp = [[INF] * len(cand) for _ in range(n - 1)]
    back = [[-1] * len(cand) for _ in range(n - 1)]
    for p in range(n - 1):
        for j, (s, e) in enumerate(cand):
            local = abs((s + e) / 2 - expect[p]) - 6.0 * min(e - s, 3.0)
            if p == 0:
                dp[p][j] = local
                continue
            for jp in range(j):
                if dp[p - 1][jp] + local < dp[p][j]:
                    dp[p][j], back[p][j] = dp[p - 1][jp] + local, jp
    j = min(range(len(cand)), key=lambda x: dp[n - 2][x])
    if dp[n - 2][j] == INF:
        return None
    picks = []
    for p in range(n - 2, -1, -1):
        picks.append(j)
        j = back[p][j]
    picks.reverse()
    return [0.0] + [(cand[j][0] + cand[j][1]) / 2 for j in picks] + [total]


def split_by_paragraph(src: str, paragraphs: List[str], out_dir: str, ffmpeg: str = "", language: str = "",
                       names: Optional[List[str]] = None, transcribe: Optional[Callable] = None,
                       duration: Optional[Callable[[str], float]] = None, guides: Optional[List[float]] = None,
                       progress: Optional[Callable[[float, float], Any]] = None) -> Dict[str, Any]:
    """Cắt `src` (đọc cả bài) thành một file mp3 cho mỗi đoạn (= cảnh) trong `out_dir`, kèm `<mp3>.words.json` khi có
    Whisper. Trả {"files": [{"path", "start", "end", "seconds"}], "engine": "whisper"|"guide"|"silence", "match", "anchors"}.
    guides: thời lượng GIỌNG TẠM từng đoạn (CapCut / Edge) — máy không có Whisper thì cắt theo nó + khoảng lặng.
    progress(giây đã nghe, tổng giây) khi Whisper đang nghe.
    Ném ValueError khi bản đọc không khớp kịch bản / không tìm được chỗ chuyển cảnh."""
    if not ffmpeg:
        from tubecli.extensions.video_studio.ffmpeg_utils import find_ffmpeg
        ffmpeg = find_ffmpeg() or "ffmpeg"
    if duration is None:
        from tubecli.extensions.video_studio.ffmpeg_utils import media_duration as duration
    os.makedirs(out_dir, exist_ok=True)
    total = float(duration(src) or 0)
    if total <= 0:
        raise ValueError("cannot read the length of the voice-over file")
    paras = [str(p or "") for p in paragraphs]
    norms = [norm_with_map(p) for p in paras]
    sil = silences(src, ffmpeg)
    if transcribe is not None:
        heard = transcribe(src, language)
    else:
        heard = whisper_chars(src, language, progress=(lambda t: progress(t, total)) if progress else None)
    info: Dict[str, Any] = {"engine": "silence", "match": None, "anchors": 0}
    t_of: List[float] = []
    first: Dict[int, int] = {}
    last: Dict[int, int] = {}
    if heard and heard[0]:
        script, owner = "", []
        for p, (n, _) in enumerate(norms):
            script += n
            owner += [p] * len(n)
        t_of, ratio = _char_times(script, heard[0], heard[1])
        info.update(engine="whisper", match=round(ratio, 3))
        if ratio < MIN_MATCH:
            raise ValueError(f"the voice-over does not follow the script (only {ratio:.0%} of it was heard back)")
        ends, off = [], 0
        for p, (n, rawmap) in enumerate(norms):
            for m in _SENT_END.finditer(paras[p]):
                ks = [k for k, r in enumerate(rawmap) if r < m.start()]
                if ks:
                    ends.append(off + ks[-1])
            if n:
                ends.append(off + len(n) - 1)
            off += len(n)
        t_of, info["anchors"] = _anchor(t_of, sorted(set(ends)), sil)
        for i, p in enumerate(owner):
            first.setdefault(p, i)
            last[p] = i
        spoken = [p for p in range(len(paras)) if p in first]
        cuts = [0.0]
        for a_p, b_p in zip(spoken[:-1], spoken[1:]):
            cuts.append(max(_cut_between(t_of[last[a_p]], t_of[first[b_p]], sil), cuts[-1] + 0.3))
        cuts.append(total)
        bounds = {p: (cuts[k], cuts[k + 1]) for k, p in enumerate(spoken)}
    elif guides and len(guides) == len(paras) and all(float(g or 0) > 0 for p, g in enumerate(guides) if norms[p][0]):
        # không Whisper, có giọng tạm: độ dài từng đoạn theo giọng tạm + khoảng lặng −30 dB (xem GUIDE_*)
        spoken = [p for p in range(len(paras)) if norms[p][0]]
        cuts = _cuts_by_guide([float(guides[p]) for p in spoken], total,
                              silences(src, ffmpeg, noise=GUIDE_NOISE, min_dur=GUIDE_SIL_DUR))
        if not cuts:
            raise ValueError("no clear pause near the expected scene changes — cannot split the voice-over by scene")
        info["engine"] = "guide"
        bounds = {p: (cuts[k], cuts[k + 1]) for k, p in enumerate(spoken)}
    else:
        spoken = [p for p in range(len(paras)) if norms[p][0]]
        cuts = _cuts_by_silence([len(norms[p][0]) for p in spoken], total, sil)
        if not cuts:
            raise ValueError("no clear pause between the paragraphs of the voice-over — cannot split it by scene")
        bounds = {p: (cuts[k], cuts[k + 1]) for k, p in enumerate(spoken)}
    files: List[Dict[str, Any]] = []
    for p in range(len(paras)):
        if p not in bounds:
            files.append({"path": "", "start": 0.0, "end": 0.0, "seconds": 0.0})
            continue
        s0, s1 = bounds[p]
        name = (names[p] if names and p < len(names) else f"shot{p + 1:03d}") + ".mp3"
        out = os.path.join(out_dir, name)
        r = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{s0:.3f}", "-to", f"{s1:.3f}", "-i", src, "-ac", "1",
                            "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", out], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.isfile(out):
            raise ValueError(f"ffmpeg could not cut paragraph {p + 1}: {(r.stderr or '')[-200:]}")
        side = out + ".words.json"
        if t_of and p in first:
            marks = []
            for i in range(first[p], last[p] + 1):
                t0 = max(0.0, t_of[i] - s0 - 0.05)
                marks.append({"word": "", "start": round(t0, 3), "end": round(t0 + 0.12, 3)})
            # chữ của mốc = ký tự GỐC của kịch bản (Studio so theo chữ-và-số, gộp theo độ dài từ của nó)
            n, rawmap = norms[p]
            for k, m in enumerate(marks):
                m["word"] = paras[p][rawmap[k]]
            for k in range(1, len(marks)):
                marks[k]["start"] = max(marks[k]["start"], marks[k - 1]["start"] + 0.005)
                marks[k - 1]["end"] = max(marks[k - 1]["start"] + 0.005, min(marks[k - 1]["end"], marks[k]["start"]))
            with open(side, "w", encoding="utf-8") as f:
                json.dump({"engine": "dub+whisper-align", "words": marks}, f, ensure_ascii=False)
        elif os.path.isfile(side):
            os.remove(side)
        files.append({"path": out, "start": round(s0, 3), "end": round(s1, 3), "seconds": round(s1 - s0, 3)})
    info["files"] = files
    return info
