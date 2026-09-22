'use strict';

/**
 * subtitle_engine.js — Phụ đề "karaoke" cho canvas_renderer.js
 *
 *   const { makeSubtitle, loadPresets, getPreset } = require('./subtitle_engine.js');
 *   const sub = makeSubtitle(preset, opts);
 *   sub.draw(ctx, W, H, step, tSec, fps);     // gọi mỗi frame, SAU cùng
 *
 * `step` = một phần tử timing_map.json steps + voice_text của script:
 *   { id, start, end, duration, words: [{word, norm, start, end}], voice_text }
 *
 * NGUYÊN TẮC BẤT DI BẤT DỊCH (render song song chia chunk):
 *   draw() là HÀM THUẦN của tSec. Không tích luỹ trạng thái giữa các frame,
 *   không Math.random(), không đọc frame trước. Worker 3 khởi động lạnh ở
 *   frame 900 phải vẽ y hệt worker 1 nếu nó chạy tới frame 900 → nếu không,
 *   sẽ thấy phụ đề "nhảy" đúng chỗ nối chunk.
 *
 * Bố cục (phrase + vị trí từng từ) được TÍNH MỘT LẦN cho mỗi step rồi cache;
 * mỗi frame chỉ còn nội suy thời gian + vẽ.
 */

const fs = require('fs');
const path = require('path');

// ────────────────────────────────────────────────────────────────────
// Hằng số điều chỉnh cách gom cụm từ (phrase)
// ────────────────────────────────────────────────────────────────────
const GAP_BREAK = 0.42;      // im lặng > 0.42s giữa 2 từ → tách cụm (khi cụm đã HIỆN đủ lâu)
const GAP_HARD = 1.20;       // im lặng dài cỡ này → LUÔN tách (nghỉ lấy hơi thật sự)
const MIN_PHRASE_DUR = 1.10; // cụm HIỆN ngắn hơn 1.1s → gộp/mượn từ cụm bên cạnh (chống "đọc gấp")
const TARGET_PHRASE_DUR = 1.60; // chưa hiện đủ 1.6s thì đừng cắt ở ranh giới ngữ nghĩa
const MIN_SOLO_DUR = 0.40;   // cụm 1 từ (không tránh được) phải nán ít nhất 12 frame
const MIN_PHRASE_CHARS = 8;  // đừng tách cụm quá cụt vì một dấu chấm sớm
const LEAD_IN = 0.03;        // hiện xong in-anim trước khi từ đầu tiên vang lên
const TAIL_HOLD = 0.90;      // cụm cuối của step nán lại sau khi hết tiếng (đọc nốt cho xong)
const IN_ANIM_MAX_FRAC = 0.20; // in-anim không được ăn quá 20% cửa sổ hiện của cụm
const TYPE_MAX_FRAC = 0.30;  // typewriter: gõ XONG trong ≤30% cửa sổ hiện của cụm…
const TYPE_MAX_SEC = 0.70;   // …và không quá 0.7s — phần còn lại là để ĐỌC, không phải để xem gõ
const MIN_WORD_DUR = 0.05;   // từ có start==end (TTS lỗi) → ép tối thiểu 50ms
const SH_OFF = 8000;         // độ lệch "vẽ nguồn ra ngoài khung" khi dựng lớp bóng
const BOTTOM_LIMIT = 0.90;   // mép dưới phụ đề không được vượt quá 0.90*H
                             // (né hairline tiến trình của mathnoir ở y≈H-56
                             //  và thanh UI của TikTok/Shorts ở 9:16)

// Emoji: y hệt regex mà canvas_renderer dùng cho bộ chặn fillText.
const EMOJI_RE = /([\uD800-\uDBFF][\uDC00-\uDFFF]|[☀-➿]|[⌀-⏿])/;
const EMOJI_RE_G = /([\uD800-\uDBFF][\uDC00-\uDFFF]|[☀-➿]|[⌀-⏿])/g;

// Dấu câu kết thúc / ngắt vế
const SENT_END = /[.!?…]["'”’)\]]?$/;
const CLAUSE_END = /[,;:—–]["'”’)\]]?$/;

const GENERIC_FAMILIES = new Set(['sans-serif', 'serif', 'monospace', 'cursive', 'fantasy', 'system-ui']);
const BOGUS_FAMILY = '"__t2_no_such_family_zz__"';

// "Từ này không biến hình" — một object DUY NHẤT để so sánh bằng === (không cấp
// phát object mới mỗi từ mỗi frame).
const FX_NONE = { s: 1, dy: 0 };

// ────────────────────────────────────────────────────────────────────
// Easing — mọi hoạt ảnh chạy trên thời gian LIÊN TỤC, không theo frame
// ────────────────────────────────────────────────────────────────────
function clamp01(x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }
function easeOutCubic(p) { p = clamp01(p); const q = 1 - p; return 1 - q * q * q; }
function easeInCubic(p) { p = clamp01(p); return p * p * p; }
function easeInOutCubic(p) {
    p = clamp01(p);
    return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
}
function easeOutBack(p) {
    p = clamp01(p);
    const c1 = 1.70158, c3 = c1 + 1, q = p - 1;
    return 1 + c3 * q * q * q + c1 * q * q;   // vọt lố nhẹ → cảm giác "pop"
}

// ────────────────────────────────────────────────────────────────────
// Màu: parse + trộn (dùng để nội suy màu từ thường → từ đang đọc)
// ────────────────────────────────────────────────────────────────────
function parseColor(c) {
    if (!c) return [255, 255, 255, 1];
    if (Array.isArray(c)) return c;
    const s = String(c).trim();
    let m = /^#([0-9a-f]{3,8})$/i.exec(s);
    if (m) {
        let h = m[1];
        if (h.length === 3 || h.length === 4) h = h.split('').map(function (ch) { return ch + ch; }).join('');
        const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
        const a = h.length >= 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
        return [r, g, b, a];
    }
    m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/i.exec(s);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
    return [255, 255, 255, 1];
}
function cssColor(rgba) {
    return 'rgba(' + Math.round(rgba[0]) + ',' + Math.round(rgba[1]) + ',' + Math.round(rgba[2]) + ',' +
        (Math.round(rgba[3] * 1000) / 1000) + ')';
}
function mixColor(a, b, t) {
    t = clamp01(t);
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t, a[3] + (b[3] - a[3]) * t];
}
function withAlpha(rgba, a) { return [rgba[0], rgba[1], rgba[2], rgba[3] * a]; }
function luminance(rgba) {
    return (0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]) / 255;
}
/** Màu chữ tương phản khi nằm trên ô màu (box_wipe): nền sáng → chữ đen. */
function contrastOn(rgba) {
    return luminance(rgba) > 0.55 ? [12, 12, 16, 1] : [255, 255, 255, 1];
}

// ────────────────────────────────────────────────────────────────────
// Preset: nạp + chuẩn hoá (mọi field đều có mặc định → preset thiếu key
// vẫn chạy, không ném lỗi giữa lúc render 3000 frame)
// ────────────────────────────────────────────────────────────────────
function defaultPresetsPath() {
    return path.join(__dirname, 'subtitle_presets.json');
}

function loadPresets(file) {
    const p = file || defaultPresetsPath();
    const raw = JSON.parse(fs.readFileSync(p, 'utf-8'));
    const list = Array.isArray(raw) ? raw : (raw.presets || []);
    return list.filter(function (x) { return x && x.id; });
}

function getPreset(presets, id) {
    const list = Array.isArray(presets) ? presets : [];
    if (!list.length) return null;
    if (id) {
        for (let i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    }
    return list[0];   // id lạ → dùng preset đầu tiên thay vì tắt phụ đề
}

function num(v, d) { const n = Number(v); return isFinite(n) ? n : d; }

function normalizePreset(p) {
    p = p || {};
    const f = p.font || {}, c = p.color || {}, l = p.layout || {};
    const sh = c.shadow || {}, bx = c.box || {};
    const i = p.in || {}, o = p.out || {}, w = p.word || {};
    return {
        id: p.id || 'custom',
        name: p.name || p.id || 'custom',
        font: {
            family: f.family || 'sans-serif',
            size: Math.max(10, num(f.size, 52)),
            weight: f.weight || 700,
            uppercase: !!f.uppercase,
            letterSpacing: num(f.letterSpacing, 0),
            lineHeight: Math.max(0.9, num(f.lineHeight, 1.2)),
            maxLines: Math.max(1, Math.round(num(f.maxLines, 2))),
            maxCharsPerLine: Math.max(6, Math.round(num(f.maxCharsPerLine, 26)))
        },
        color: {
            fill: c.fill || '#ffffff',
            active: c.active || c.fill || '#facc15',
            stroke: c.stroke || '#000000',
            strokeWidth: Math.max(0, num(c.strokeWidth, 0)),
            shadow: {
                color: sh.color || 'rgba(0,0,0,0)',
                blur: Math.max(0, num(sh.blur, 0)),
                dx: num(sh.dx, 0),
                dy: num(sh.dy, 0)
            },
            box: {
                enabled: !!bx.enabled,
                fill: bx.fill || 'rgba(0,0,0,0.45)',
                radius: Math.max(0, num(bx.radius, 14)),
                padX: Math.max(0, num(bx.padX, 24)),
                padY: Math.max(0, num(bx.padY, 14))
            }
        },
        layout: {
            anchor: l.anchor || 'bottom',
            yPct: num(l.yPct, 0.82),
            // Kiểu chữ của video giải thích Nhật (user gửi ảnh mẫu 21/9/2026): câu TÁCH ĐÔI quanh hình — dòng đầu
            // nằm ở ĐỈNH khung, (các) dòng còn lại ở ĐÁY, hình ở giữa. Cụm chỉ có một dòng thì vẫn nằm ở đáy.
            split: l.split === true,
            splitTopPct: num(l.splitTopPct, 0.055),
            safePct: Math.max(0, num(l.safePct, 0.06)),
            align: l.align || 'center'
        },
        in: { kind: i.kind || 'fade', durMs: Math.max(0, num(i.durMs, 180)) },
        out: { kind: o.kind || 'fade', durMs: Math.max(0, num(o.durMs, 140)) },
        word: { kind: w.kind || 'highlight', amount: num(w.amount, 0.12), leadMs: num(w.leadMs, 40) }
    };
}

// ────────────────────────────────────────────────────────────────────
// Font: chọn family THỰC SỰ có trong máy
// ────────────────────────────────────────────────────────────────────
// Mẹo dò: đo cùng một chuỗi bằng family cần thử và bằng một family CHẮC CHẮN
// không tồn tại. Bằng nhau → fontconfig đã rơi về Sans mặc định (chính là
// Be Vietnam Pro do alias sans-serif) → coi như family đó KHÔNG có.
// Thực đo trên máy dev: Montserrat/Outfit/Orbitron/Impact/Arial Black/Fredoka
// đều KHÔNG có → mọi preset gọi chúng sẽ tự rơi về stack hệ thống.
function familyAvailable(ctx, fam, px) {
    const probe = 'Hamburgefonstiv 0123 Việt';
    const save = ctx.font;
    let ok = false;
    try {
        ctx.font = 'bold ' + px + 'px "' + fam + '"';
        const a = ctx.measureText(probe).width;
        ctx.font = 'bold ' + px + 'px ' + BOGUS_FAMILY;
        const b = ctx.measureText(probe).width;
        ok = Math.abs(a - b) > 0.5;
    } catch (e) { ok = false; }
    ctx.font = save;
    return ok;
}

function splitFamilies(familyStr) {
    return String(familyStr || '').split(',')
        .map(function (s) { return s.trim().replace(/^["']|["']$/g, ''); })
        .filter(Boolean);
}

// ────────────────────────────────────────────────────────────────────
// Chuẩn hoá word timings
// ────────────────────────────────────────────────────────────────────
/**
 * timing_map.json ghi thời điểm từ theo giờ TUYỆT ĐỐI (audio_engine dịch theo
 * current_offset). Nhưng contract lại mô tả là tương đối — nên ta TỰ DÒ, để
 * đúng cả hai kiểu dữ liệu:
 *   - từ đầu tiên nằm trong [step.start, step.end] và từ cuối không vượt quá
 *     step.end nhiều  → TUYỆT ĐỐI
 *   - ngược lại (thời gian bắt đầu từ ~0 trong khi step.start > 0) → TƯƠNG ĐỐI
 */
function wordsAreAbsolute(step, words) {
    const s = num(step.start, 0), e = num(step.end, s + num(step.duration, 0));
    if (s <= 0.001) return true;             // step đầu: hai cách hiểu trùng nhau
    const w0 = num(words[0].start, 0);
    const wN = num(words[words.length - 1].end, 0);
    const absFit = (w0 >= s - 0.25) && (wN <= e + 0.75);
    const relFit = (w0 >= -0.25) && (wN <= (e - s) + 0.75);
    if (absFit && !relFit) return true;
    if (relFit && !absFit) return false;
    return absFit;                           // nhập nhằng → tin absFit (dữ liệu thật)
}

/** Trả [{text, start, end}] đã sắp xếp, đơn điệu, không đè nhau, kẹp trong step. */
const CJK_RE = /[぀-ヿ㐀-䶿一-鿿]/;
// Dấu không được đứng ĐẦU dòng (kinsoku): dính vào chữ đứng trước để bộ xếp dòng không bao giờ tách chúng ra.
const CJK_TAIL_RE = /^[、。，．！？）」』】〕〉》…‥ー]+$/;

function isCjkRun(words) {
    if (!words || !words.length) return false;
    let n = 0;
    for (const w of words) if (CJK_RE.test(w.text)) n++;
    return n > words.length * 0.5;
}

// «Từ» là cả một CÂU tiếng Nhật/Trung (người gọi ước lượng mốc từ bằng cách tách theo khoảng trắng — Content Studio
// trước 21/9/2026): chia nó thành các VẾ, thời gian chia theo số chữ. Không chia thì chunkLongWord phải chặt theo bề
// ngang và dòng gãy giữa chữ («…地面に置きま / した。»).
function splitCjkClauses(words) {
    const out = [];
    for (const w of words) {
        const parts = CJK_RE.test(w.text) ? (w.text.match(/[^、。，．！？…]+[、。，．！？…」』）]*|[、。，．！？…」』）]+/g) || []) : [];
        if (parts.length < 2) { out.push(w); continue; }
        const total = Array.from(w.text).length || 1;
        let acc = 0;
        for (const p of parts) {
            const n = Array.from(p).length;
            out.push({ text: p, start: w.start + (w.end - w.start) * (acc / total),
                end: w.start + (w.end - w.start) * ((acc + n) / total) });
            acc += n;
        }
    }
    return out;
}

function glueCjkPunct(words) {
    if (!isCjkRun(words)) return words;
    const out = [];
    for (const w of words) {
        if (out.length && CJK_TAIL_RE.test(w.text)) {
            const p = out[out.length - 1];
            p.text += w.text;
            p.end = Math.max(p.end, w.end);
        } else out.push(w);
    }
    return out;
}

function normalizeWords(step) {
    const s = num(step.start, 0);
    const e = Math.max(s + 0.05, num(step.end, s + num(step.duration, 2)));
    const raw = Array.isArray(step.words) ? step.words : [];
    const src = raw.filter(function (w) {
        return w && typeof w.word === 'string' && w.word.trim().length > 0;
    });
    if (!src.length) return synthWords(step, s, e);

    const abs = wordsAreAbsolute(step, src);
    const off = abs ? 0 : s;
    let out = src.map(function (w) {
        let a = num(w.start, 0) + off, b = num(w.end, 0) + off;
        if (!(b > a)) b = a + MIN_WORD_DUR;     // start==end hoặc end<start (TTS lỗi)
        return { text: String(w.word).trim(), start: a, end: b };
    });
    out.sort(function (a, b) { return a.start - b.start; });
    out = glueCjkPunct(splitCjkClauses(out));

    // Ép đơn điệu: bỏ đè nhau, kẹp trong [s, e], đảm bảo mỗi từ có bề dày.
    let prevEnd = s;
    for (let i = 0; i < out.length; i++) {
        const w = out[i];
        w.start = Math.min(Math.max(w.start, prevEnd), e - MIN_WORD_DUR);
        w.end = Math.max(w.end, w.start + MIN_WORD_DUR);
        w.end = Math.min(w.end, e);
        if (w.end <= w.start) w.end = w.start + MIN_WORD_DUR;   // sát mép cuối
        prevEnd = w.end;
    }
    return out;
}

/**
 * Step không có words (voice_text rỗng, EverAI, Deepgram STT hỏng, preview
 * chưa chạy TTS): rải chữ của voice_text đều theo ĐỘ DÀI ký tự trong step.
 * Vẫn cho ra timing liên tục → mọi hoạt ảnh vẫn mượt như có word timing.
 */
function synthWords(step, s, e) {
    const text = String(step.voice_text || '').trim();
    if (!text) return [];
    let toks = text.split(/\s+/).filter(Boolean);
    if (!toks.length) return [];
    if (CJK_RE.test(text)) {
        // Tiếng Nhật/Trung không có dấu cách: cả câu là MỘT «từ» dài hơn cả dòng, chunkLongWord phải chặt nó ở chỗ
        // bất kỳ và cả câu sáng lên cùng lúc. Tách theo VẾ (tới hết dấu 、。…): dòng ngắt ở dấu câu, chữ sáng theo vế.
        const parts = [];
        for (const t of toks) {
            const m = t.match(/[^、。，．！？…]+[、。，．！？…」』）]*|[、。，．！？…」』）]+/g);
            if (m) for (const x of m) parts.push(x); else parts.push(t);
        }
        toks = parts;
    }
    const pad = Math.min(0.15, (e - s) * 0.05);
    const t0 = s + pad, t1 = Math.max(t0 + 0.1, e - pad);
    let total = 0;
    const wts = toks.map(function (t) { const w = t.length + 1; total += w; return w; });
    const out = [];
    let acc = 0;
    for (let i = 0; i < toks.length; i++) {
        const a = t0 + (t1 - t0) * (acc / total);
        acc += wts[i];
        const b = t0 + (t1 - t0) * (acc / total);
        out.push({ text: toks[i], start: a, end: Math.max(a + MIN_WORD_DUR, b) });
    }
    return out;
}

// ────────────────────────────────────────────────────────────────────
// Gom từ thành cụm (phrase)
// ────────────────────────────────────────────────────────────────────
function charLen(words, from, to) {
    let n = 0;
    for (let i = from; i < to; i++) n += words[i].text.length + (i > from ? 1 : 0);
    return n;
}

/**
 * Gom từ thành cụm.
 *
 * `fits(from, to)` = "khoảng từ [from,to) nhét TRỌN vào maxLines dòng" — ĐO THẬT
 * bằng chính packLines (bề ngang pixel + maxCharsPerLine), KHÔNG ước bằng
 * maxCharsPerLine × maxLines nữa.
 *
 * Vì sao: sức chứa tính theo KÝ TỰ luôn lệch với xếp dòng theo PIXEL ("mmm" rộng
 * gấp 3 "iii"). Cụm lọt qua cửa ký tự nhưng tràn dòng khi xếp thật → packLines
 * đẩy phần dư sang cụm MỚI, và cụm mới đó (thường 1 từ) sinh ra ĐÚNG LÚC ĐÓ,
 * tức là SAU khi gộp cụm cụt đã chạy xong → không ai gộp nó nữa → chớp 1 từ
 * ("chứng" tách khỏi "chứng minh"). Đo thật ngay từ đây thì phần dư không còn.
 */
function groupPhrases(words, F, fits) {
    const capacity = F.maxCharsPerLine * F.maxLines;   // chỉ còn dùng cho ngưỡng "gần đầy"
    const groups = [];
    let start = 0;
    for (let i = 0; i < words.length; i++) {
        const w = words[i];
        const nxt = words[i + 1];
        if (!nxt) { groups.push([start, i + 1]); break; }
        const curChars = charLen(words, start, i + 1);
        const gap = nxt.start - w.end;
        // Cửa sổ HIỆN thực tế nếu cắt tại đây: cụm nán trên màn hình suốt khoảng
        // lặng, tới lúc cụm sau xuất hiện → tính CẢ gap. Người xem than "đọc hơi
        // gấp" chính vì trước đây cứ hết câu/ngắt hơi là cắt, bất kể cụm mới hiện
        // được 0.8–1.4s — giờ CHƯA HIỆN ĐỦ TARGET_PHRASE_DUR thì không cắt ở ranh
        // giới ngữ nghĩa nữa, gom tiếp cho cụm đầy đặn (chữ chỉ được hiện đúng
        // bằng thời gian lời nói của nó, nên muốn cụm sống lâu hơn CHỈ CÓ CÁCH
        // gom nhiều từ hơn).
        const dispDur = (w.end - words[start].start) + Math.max(0, gap);
        const longEnough = dispDur >= TARGET_PHRASE_DUR;
        let cut = false;
        if (!fits(start, i + 2)) cut = true;                                    // hết chỗ (ĐO THẬT)
        else if (gap > GAP_HARD && curChars >= MIN_PHRASE_CHARS) cut = true;    // nghỉ dài — luôn tách
        else if (longEnough && SENT_END.test(w.text) && curChars >= MIN_PHRASE_CHARS) cut = true;   // hết câu
        else if (longEnough && gap > GAP_BREAK && curChars >= MIN_PHRASE_CHARS) cut = true;   // ngắt hơi
        else if (longEnough && CLAUSE_END.test(w.text) && curChars >= capacity * 0.62) cut = true;  // hết vế + gần đầy
        if (cut) { groups.push([start, i + 1]); start = i + 1; }
    }
    return groups;
}

/**
 * Cửa sổ HIỆN xấp xỉ của cụm: chữ nán trên màn hình tới khi cụm SAU xuất hiện
 * (cụm cuối: thêm TAIL_HOLD). Đây mới là thời gian người xem được đọc — cụm nói
 * nhanh nhưng có khoảng lặng dài phía sau thì KHÔNG hề "chớp".
 */
function phraseWindow(words, g, next) {
    const end = next ? words[next[0]].start : (words[g[1] - 1].end + TAIL_HOLD);
    return end - words[g[0]].start;
}

/** Cụm "cụt": 1 từ, hoặc HIỆN chưa tới MIN_PHRASE_DUR → chớp lên rồi tắt. */
function isTinyPhrase(words, g, next) {
    const n = g[1] - g[0];
    if (n <= 1) return true;
    return phraseWindow(words, g, next) < MIN_PHRASE_DUR;
}

/**
 * Hàng xóm được phép teo lại tới cỡ nào khi cho mượn từ?
 * ≥ 2 từ thì luôn được. Còn đúng 1 từ thì từ đó phải DÀI (≥ 8 ký tự) và không
 * chớp (≥ 0.4s) — tức là một cụm 1 từ KHÔNG THỂ TRÁNH (kiểu "EFFORTLESSLY" ở
 * preset cỡ đại 1 dòng), chứ không phải ta vừa đá quả bóng mồ côi sang cụm bên.
 * Cụm 1 từ NGẮN thì cấm tiệt → mượn không bao giờ đẻ ra mồ côi mới.
 */
function canShrinkTo(words, from, to) {
    const n = to - from;
    if (n >= 2) return true;
    if (n <= 0) return false;
    return words[from].text.length >= MIN_PHRASE_CHARS &&
        (words[to - 1].end - words[from].start) >= MIN_SOLO_DUR;
}

/**
 * Chữa cụm cụt — CHẠY SAU khi đã xếp dòng/cắt phần dư, nên không cụm nào sinh
 * sau lưng nó nữa.
 *
 *   a. Còn chỗ → gộp hẳn vào hàng xóm (ưu tiên cụm TRƯỚC: đuôi câu cụt dính lên).
 *   b. Hết chỗ → MƯỢN từ của hàng xóm (canShrinkTo canh để hàng xóm không tự
 *      biến thành mồ côi — nếu không thì hai cụm chỉ đá quả bóng cho nhau).
 *      Hàng xóm thiếu từ thì tới lượt NÓ đi mượn ở vòng sau: cái thiếu cứ thế lan
 *      sang trái cho tới cụm nào còn dư từ.
 *   c. Vẫn tắc → nới TRẦN KÝ TỰ (chỉ là gợi ý dễ đọc), giữ nguyên TRẦN PIXEL.
 *
 * Chỉ còn đúng một trường hợp cụm 1 từ sống sót: cả câu vốn chỉ có 1 từ, hoặc từ
 * DÀI tới mức 2 từ không thể chung một cụm dù đã nới trần ký tự ("EFFORTLESSLY"
 * ở preset cỡ đại 1 dòng). Cụm 1 từ NGẮN thì không bao giờ còn.
 */
function reflowPhrases(words, groups, fits, fitsSoft) {
    const out = groups.map(function (g) { return [g[0], g[1]]; });
    for (let pass = 0; pass < 3 && out.length > 1; pass++) {
        let changed = false;
        for (let i = 0; i < out.length && out.length > 1; i++) {
            const g = out[i];
            if (!isTinyPhrase(words, g, out[i + 1])) continue;
            const prev = out[i - 1], next = out[i + 1];
            if (prev && fits(prev[0], g[1])) {          // a. gộp vào cụm trước
                prev[1] = g[1];
                out.splice(i, 1); i--; changed = true; continue;
            }
            if (next && fits(g[0], next[1])) {          // a. gộp vào cụm sau
                next[0] = g[0];
                out.splice(i, 1); i--; changed = true; continue;
            }
            let moved = false;                          // b. mượn từ
            if (prev) {
                for (let p = g[0] - 1; p > prev[0]; p--) {
                    if (!canShrinkTo(words, prev[0], p) || !fits(p, g[1])) break;
                    prev[1] = p; g[0] = p; moved = true;
                    if (!isTinyPhrase(words, g, next)) break;
                }
            }
            if (!moved && next) {
                for (let p = g[1] + 1; p < next[1]; p++) {
                    if (!canShrinkTo(words, p, next[1]) || !fits(g[0], p)) break;
                    g[1] = p; next[0] = p; moved = true;
                    if (!isTinyPhrase(words, g, next)) break;
                }
            }
            if (moved) { changed = true; continue; }

            // c. Đường cùng: gộp bằng cách NỚI TRẦN KÝ TỰ (maxCharsPerLine chỉ là
            //    gợi ý dễ đọc), TRẦN PIXEL của khung thì vẫn giữ nguyên. Nhờ vậy
            //    "THAT EXECUTES ITSELF" (20 ký tự > trần 18 của big_impact, nhưng
            //    chỉ rộng 840/934 px) được ở chung một cụm thay vì bỏ rơi "ITSELF".
            if (prev && fitsSoft(prev[0], g[1])) {
                prev[1] = g[1]; prev.soft = true;
                out.splice(i, 1); i--; changed = true; continue;
            }
            if (next && fitsSoft(g[0], next[1])) {
                next[0] = g[0]; next.soft = true;
                out.splice(i, 1); i--; changed = true; continue;
            }
            // Hết cách: cả khung không chứa nổi → cụm 1 từ là chuyện có thật.
        }
        if (!changed) break;
    }
    return out;
}

// ────────────────────────────────────────────────────────────────────
// Đo chữ (có mô phỏng letterSpacing — node-canvas 3.x nhận thuộc tính
// ctx.letterSpacing nhưng KHÔNG áp dụng, đã kiểm chứng: delta = 0)
// ────────────────────────────────────────────────────────────────────
function measureW(ctx, text, ls) {
    if (!ls) return ctx.measureText(text).width;
    const cps = Array.from(text);
    let w = 0;
    for (let i = 0; i < cps.length; i++) w += ctx.measureText(cps[i]).width + ls;
    return Math.max(0, w - ls);
}

/** Cắt từ dài quá một dòng (URL, từ ghép dính) thành các mẩu vừa bề ngang. */
function chunkLongWord(ctx, text, ls, maxW) {
    const cps = Array.from(text);
    const out = [];
    let cur = '';
    for (let i = 0; i < cps.length; i++) {
        const t = cur + cps[i];
        if (cur && measureW(ctx, t, ls) > maxW) { out.push(cur); cur = cps[i]; }
        else cur = t;
    }
    if (cur) out.push(cur);
    return out.length ? out : [text];
}

// ────────────────────────────────────────────────────────────────────
// makeSubtitle
// ────────────────────────────────────────────────────────────────────
/**
 * @param {object} preset  một phần tử của subtitle_presets.json
 * @param {object} opts    { fontScale, yPct, maxLines, fontFamily, fallbackFamily, warn }
 *                         yPct/maxLines = null → dùng giá trị của preset
 *                         fontFamily → font người dùng chọn; nếu có VÀ available
 *                         thì thắng preset.font.family, vắng → giữ font preset
 * @returns {{draw: function, preset: object, layoutFor: function}}
 */
function makeSubtitle(preset, opts) {
    const P = normalizePreset(preset);
    const O = opts || {};
    const fontScale = num(O.fontScale, 1) > 0 ? num(O.fontScale, 1) : 1;
    const yPctOv = (O.yPct === null || O.yPct === undefined) ? null : num(O.yPct, null);
    const maxLinesOv = (O.maxLines === null || O.maxLines === undefined) ? null : Math.max(1, Math.round(num(O.maxLines, 2)));
    // num(null,·)=0 (Number(null)===0, finite) → KHÔNG dùng num trực tiếp: renderer
    // truyền THẲNG null khi SUB_CFG.bottomLimitPct vắng (88ea6ff), num sẽ trả 0 →
    // maxBottom=−outset → mọi phụ đề bị kẹp lên MÉP TRÊN. Guard null/undefined như yPct.
    const bottomLimit = (O.bottomLimitPct === null || O.bottomLimitPct === undefined)
        ? BOTTOM_LIMIT : num(O.bottomLimitPct, BOTTOM_LIMIT);
    const fallbackFamily = O.fallbackFamily || 'sans-serif';
    const warn = typeof O.warn === 'function' ? O.warn : function () { };

    /**
     * RS — HỆ SỐ PHÓNG ĐỘ PHÂN GIẢI của canvas đích (canvas_renderer.js/RSCALE).
     *
     * KHÔNG dùng cho bố cục. draw(ctx, W, H, …) vẫn nhận W/H LOGIC (1080×1920)
     * nên `min(W,H)/1080 = 1` → cỡ chữ, lề, xuống dòng tính y hệt như cũ; việc
     * phóng do transform của ctx lo. Đó là thiết kế đúng: engine không cần biết
     * mình đang vẽ ở 1080p hay 4K.
     *
     * RS CHỈ dùng cho CANVAS PHỤ (lớp bóng, ảnh chữ đúc sẵn) — chúng là ẢNH
     * BITMAP thật, nên phải đúc ở RS× rồi blit bằng drawImage CÓ dw/dh (toạ độ
     * logic). Nếu đúc ở cỡ logic, ctx đã scale sẽ PHÓNG TO chúng lên → chữ vẽ
     * sống thì nét mà chữ blit + bóng thì MỜ. Đúng loại nói dối phải diệt.
     *
     * Vắng khoá = 1 → bên gọi cũ không đổi hành vi.
     */
    const RS = (function () {
        const v = num(O.renderScale, 1);
        return (isFinite(v) && v > 0) ? v : 1;
    })();

    /**
     * Tạo canvas phụ — PHẢI xin từ HOST, KHÔNG được đoán lớp Canvas từ
     * `ctx.canvas.constructor`.
     *
     * Cái bẫy đã cắn thật: trên trình duyệt `ctx.canvas.constructor` là
     * HTMLCanvasElement, mà `new HTMLCanvasElement()` NÉM "Illegal constructor".
     * Mọi chỗ dựng canvas phụ đều nằm trong try/catch nuốt lỗi → nó âm thầm tụt
     * xuống đường dự phòng, và xem trước web MẤT SẠCH bóng/quầng sáng của phụ đề
     * (16/16 preset đều có shadow.blur > 0 → không preset nào thoát), trong khi
     * video render ra thì CÓ. Đúng loại nói dối mà cả đợt này sinh ra để diệt.
     */
    const mkCanvas = (typeof O.createCanvas === 'function')
        ? O.createCanvas
        : function (w, h) {
            // Không có host → thử lối cũ, nhưng KÊU LÊN thay vì chết im lặng.
            warn('createCanvas không được truyền vào makeSubtitle — bóng/quầng '
                 + 'sáng của phụ đề có thể biến mất. Xem subtitle_engine.js.');
            throw new Error('makeSubtitle: thiếu opts.createCanvas');
        };

    const C = {
        fill: parseColor(P.color.fill),
        active: parseColor(P.color.active),
        stroke: parseColor(P.color.stroke),
        shadow: parseColor(P.color.shadow.color),
        box: parseColor(P.color.box.fill)
    };

    let familyResolved = null;   // dò một lần, cần ctx nên phải hoãn tới draw đầu
    const cache = new Map();     // step.id → layout

    function resolveFamily(ctx) {
        if (familyResolved) return familyResolved;
        // Font người dùng CHỦ ĐỘNG chọn (O.fontFamily, từ SUB_CFG.fontFamily do
        // app bơm) ĐƯỢC ƯU TIÊN, chen LÊN TRƯỚC preset.font.family. Vắng khoá →
        // wanted = đúng preset như cũ (không đổi hành vi). Chỉ những family THỰC
        // SỰ có trong máy (familyAvailable) mới được chọn — Kalam/font lạ không
        // register sẽ bị loại → rơi về preset/stack hệ thống, KHÔNG ra ô vuông.
        const userFams = splitFamilies(O.fontFamily);
        const wanted = userFams.concat(splitFamilies(P.font.family));
        let picked = null;
        for (const fam of wanted) {
            if (GENERIC_FAMILIES.has(fam.toLowerCase())) continue;
            if (familyAvailable(ctx, fam, 40)) { picked = fam; break; }
        }
        if (picked) {
            // Vẫn nối stack hệ thống phía sau: pango fallback theo GLYPH, nên
            // dấu tiếng Việt / emoji mà font chính thiếu sẽ được mượn từ
            // Be Vietnam Pro thay vì ra ô vuông.
            familyResolved = '"' + picked + '", ' + fallbackFamily;
        } else {
            familyResolved = fallbackFamily;
            const first = wanted.find(function (f) { return !GENERIC_FAMILIES.has(f.toLowerCase()); });
            if (first) warn('font "' + first + '" không có trong máy → dùng stack hệ thống (' +
                fallbackFamily.split(',')[0] + ')');
        }
        return familyResolved;
    }

    function fontString(px) {
        return P.font.weight + ' ' + Math.round(px) + 'px ' + familyResolved;
    }

    /** Ascent/descent CÓ dấu tiếng Việt (Ẫ, Ộ, Ự) + đuôi chữ (g, j, y). */
    function fontMetrics(ctx, font) {
        const save = ctx.font;
        ctx.font = font;
        const m = ctx.measureText('ẪỘỰỖĐHQgjyp');
        const asc = Math.max(num(m.actualBoundingBoxAscent, 0), num(m.emHeightAscent, 0));
        const desc = Math.max(num(m.actualBoundingBoxDescent, 0), num(m.emHeightDescent, 0));
        ctx.font = save;
        return { asc: asc, desc: desc };
    }

    // ── Dựng bố cục cho MỘT step (cache theo step.id) ────────────────
    function layoutFor(ctx, W, H, step) {
        const key = String(step.id) + '|' + W + 'x' + H + '|' + fontScale + '|' +
            (step.subtitle_y_pct != null ? step.subtitle_y_pct : (step.subtitle_pos || '')) + '|' +
            (maxLinesOv || '');
        const hit = cache.get(key);
        if (hit) return hit;
        const L = buildLayout(ctx, W, H, step);
        cache.set(key, L);
        // Mỗi cụm giữ 1–2 canvas (lớp bóng + ảnh mờ) → giữ cache của MỌI step sẽ
        // ngốn hàng chục MB, mà video_encoder chạy tới 8 worker song song. Render
        // đi tới theo thời gian nên chỉ cần step hiện tại (+1 để phòng lùi lại).
        while (cache.size > 2) cache.delete(cache.keys().next().value);
        return L;
    }

    function buildLayout(ctx, W, H, step) {
        resolveFamily(ctx);

        // ── Thích ứng theo TỈ LỆ KHUNG ───────────────────────────────
        // Preset viết cho 9:16 (1080x1920): 58px = 3% chiều cao khung — cỡ phụ
        // đề dọc chuẩn. Đem NGUYÊN cỡ đó sang 16:9 (1920x1080) thì nó chiếm
        // 5.4% chiều cao → chữ to lộ, khối 2 dòng nuốt mất vùng hình. Ngược
        // lại khung ngang RỘNG gấp đôi nên thừa sức chứa gấp đôi ký tự trên
        // MỘT dòng, giữ trần 26 ký tự chỉ tổ bẻ câu vô cớ.
        // Ba tham số dưới đây kéo phụ đề về đúng tỉ lệ của từng khung.
        const ar = W / Math.max(1, H);
        let arFont = 1, arChars = 1, arLines = 0, arY = null;
        if (ar >= 1.2) {            // NGANG (16:9) — chuẩn YouTube
            arFont = 0.78;          //  58 → 45px ≈ 4.2% chiều cao
            arChars = 1.9;          //  26 → 49 ký tự/dòng: câu thường lọt 1 hàng
            arLines = 1;            //  ép MỘT hàng — bề ngang dư sức
            arY = 0.90;             //  hạ sát đáy (không có UI Reels che như khung dọc)
        } else if (ar > 1.05) {     // VUÔNG (1:1)
            arFont = 0.9;
            arChars = 1.3;
            arY = 0.86;
        }

        // Mẫu TÁCH TRÊN + DƯỚI (layout.split) sống nhờ có ≥ 2 dòng: luật «khung ngang ép MỘT hàng, mỗi hàng dài gấp 1,9»
        // ở trên sẽ khiến nó không bao giờ có dòng để đưa lên đỉnh khung. Cỡ chữ (arFont) thì vẫn theo khung như mọi mẫu.
        if (P.layout.split === true) { arLines = 0; arChars = 1; }

        const F = {
            // maxLinesOv = người dùng chỉ định rõ → luôn thắng thích ứng tự động
            maxLines: maxLinesOv || arLines || P.font.maxLines,
            maxCharsPerLine: Math.max(6, Math.round(P.font.maxCharsPerLine * arChars))
        };
        // Cỡ chữ theo CẠNH NGẮN (min(W,H)/1080 = 1.0 ở cả 9:16, 16:9, 1:1 độ phân
        // giải chuẩn), rồi nhân hệ số tỉ lệ khung ở trên để ra đúng % chiều cao.
        const px = Math.max(12, Math.round(
            P.font.size * fontScale * (Math.min(W, H) / 1080) * arFont));
        const ls = P.font.letterSpacing * (px / P.font.size);
        const font = fontString(px);
        const met = fontMetrics(ctx, font);
        const lineH = px * P.font.lineHeight;
        const strokeOut = P.color.strokeWidth;   // nửa nét vẽ tràn ra ngoài chữ
        const safeX = W * P.layout.safePct;
        const boxPadX = P.color.box.enabled ? P.color.box.padX : 0;
        const maxW = Math.max(80, W - 2 * safeX - 2 * boxPadX - 2 * strokeOut);

        let words = normalizeWords(step);
        const empty = { phrases: [], px: px, font: font };
        if (!words.length) return empty;

        if (P.font.uppercase) {
            for (const w of words) w.text = w.text.toUpperCase();   // toUpperCase giữ đúng dấu tiếng Việt
        }

        ctx.save();
        ctx.font = font;
        // Tiếng Nhật/Trung viết LIỀN: mốc từ của TTS là từng chữ hay cụm 1–3 chữ, chèn dấu cách giữa chúng thì
        // phụ đề ra "送る 前 に 、" — đọc như bị vỡ chữ. Quá nửa số «từ» là chữ Hán/kana ⇒ xếp sát nhau.
        const spaceW = isCjkRun(words) ? 0 : measureW(ctx, ' ', ls);

        // Từ dài hơn CẢ DÒNG (URL, chuỗi dính) → cắt thành các mẩu vừa bề ngang
        // NGAY TỪ ĐÂY, mỗi mẩu là một "từ" độc lập với lát thời gian riêng (chia
        // theo số ký tự). Nhờ vậy maxLines vẫn được tôn trọng: mẩu thừa bị đẩy
        // sang cụm sau đúng theo cơ chế thường, thay vì phình dòng vô hạn.
        const flat = [];
        for (const w of words) {
            if (measureW(ctx, w.text, ls) <= maxW) { flat.push(w); continue; }
            const chunks = chunkLongWord(ctx, w.text, ls, maxW);
            const totalCh = chunks.reduce(function (a, c) { return a + Array.from(c).length; }, 0) || 1;
            let acc = 0;
            for (const ch of chunks) {
                const n = Array.from(ch).length;
                const a = w.start + (w.end - w.start) * (acc / totalCh);
                acc += n;
                const b = w.start + (w.end - w.start) * (acc / totalCh);
                flat.push({ text: ch, start: a, end: Math.max(a + 0.001, b) });
            }
        }
        words = flat;

        // Đo bề ngang MỖI TỪ đúng MỘT LẦN. packLines/fits được gọi O(n²) lần lúc
        // gom cụm — đo lại trong đó (letterSpacing = measureText từng ký tự) thì
        // dựng bố cục một step sẽ tốn hàng trăm ms.
        const wW = words.map(function (w) { return measureW(ctx, w.text, ls); });
        const fits = function (from, to) {
            return packLines(words, wW, from, to, spaceW, maxW, F).leftover >= to;
        };
        // Như fits nhưng BỎ trần ký tự (giữ trần pixel) — chỉ dùng làm đường cùng
        // để cứu một cụm mồ côi, xem reflowPhrases.
        const fitsSoft = function (from, to) {
            return packLines(words, wW, from, to, spaceW, maxW, F, true).leftover >= to;
        };

        // 1. Gom cụm với sức chứa = XẾP DÒNG THẬT (không còn phần dư bất ngờ)
        let groups = groupPhrases(words, F, fits);

        // 2. Lưới an toàn: nếu vẫn còn cụm tràn (không nên xảy ra nữa) thì cắt
        //    phần dư ra cụm mới — GIỮ lại vòng lặp cũ nhưng nó chạy TRƯỚC bước 3.
        const ranges = [];
        const queue = groups.slice();
        let guard = 0;
        while (queue.length && guard++ < 4 * words.length + 8) {
            const g = queue.shift();
            const leftover = packLines(words, wW, g[0], g[1], spaceW, maxW, F).leftover;
            if (leftover > g[0] && leftover < g[1]) {
                queue.unshift([leftover, g[1]]);            // phần dư → cụm kế tiếp
                g[1] = leftover;
            }
            if (g[1] > g[0]) ranges.push(g);
        }

        // 3. Chữa cụm cụt — CHẠY SAU bước 2 nên mọi cụm (kể cả cụm sinh từ phần
        //    dư) đều được gộp/mượn. Đây là chỗ cụm "chứng" bị bỏ sót trước đây.
        groups = reflowPhrases(words, ranges, fits, fitsSoft);

        const phrases = [];
        for (const g of groups) {
            // g.soft = cụm được cứu bằng cách nới trần ký tự → xếp dòng cũng phải
            // nới đúng như vậy, nếu không nó lại tách ra y như cũ.
            const packed = packLines(words, wW, g[0], g[1], spaceW, maxW, F, g.soft);
            if (!packed.lines.length) continue;
            balanceLines(packed.lines, spaceW, maxW,
                g.soft ? Infinity : F.maxCharsPerLine);
            phrases.push({ range: g, lines: packed.lines });
        }
        // CHÚ Ý: ctx.font vẫn phải là `font` cho tới hết hàm — đoạn dưới còn đo
        // bề rộng từng ký tự. ctx.restore() nằm ở CUỐI buildLayout.

        if (!phrases.length) { ctx.restore(); return empty; }

        // ── Hình học khối chữ ────────────────────────────────────────
        const sStart = num(step.start, 0);
        const sEnd = Math.max(sStart + 0.05, num(step.end, sStart + num(step.duration, 2)));

        for (const ph of phrases) {
            let blockW = 0;
            for (const ln of ph.lines) blockW = Math.max(blockW, ln.w);
            const blockH = ph.lines.length * lineH;

            // Neo dọc. Với anchor 'bottom', yPct = MÉP DƯỚI của khối chữ.
            // Thứ tự thắng: step → project/settings (yPctOv) → tỉ lệ khung (arY)
            // → preset. arY chỉ khác null ở 16:9 và 1:1 (xem buildLayout).
            let yPct = yPctOv !== null ? yPctOv
                : (arY !== null ? arY : P.layout.yPct);
            if (typeof step.subtitle_y_pct === 'number') yPct = step.subtitle_y_pct;
            else if (H > W && typeof step.subtitle_y_pct_9_16 === 'number') yPct = step.subtitle_y_pct_9_16;
            else if (step.subtitle_pos === 'top') yPct = Math.max(P.layout.safePct + 0.02, 0.16);
            else if (step.subtitle_pos === 'center') yPct = 0.5;

            const anchor = (step.subtitle_pos === 'top') ? 'top'
                : (step.subtitle_pos === 'center') ? 'center' : P.layout.anchor;
            const padY = P.color.box.enabled ? P.color.box.padY : 0;
            let top;
            if (anchor === 'top') top = H * yPct;
            else if (anchor === 'center') top = H * yPct - blockH / 2;
            else top = H * yPct - blockH;

            // Vùng an toàn: mép dưới (kể cả hộp + viền chữ) không quá bottomLimit,
            // mép trên không thụt lên quá safePct.
            const outset = padY + strokeOut + 2;
            const maxBottom = H * bottomLimit - outset;
            const minTop = H * P.layout.safePct + outset;
            if (top + blockH > maxBottom) top = maxBottom - blockH;
            if (top < minTop) top = minTop;

            // Tách TRÊN + DƯỚI: dòng 0 lên đỉnh khung, các dòng sau giữ nguyên chỗ neo ở đáy. Chỉ áp cho neo 'bottom'
            // (step tự đặt top/center thì người dùng đã chọn chỗ — không tách nữa).
            const split = P.layout.split === true && ph.lines.length >= 2 && anchor === 'bottom';
            let lineTop = null;
            if (split) {
                const restH = (ph.lines.length - 1) * lineH;
                let restTop = H * yPct - restH;
                if (restTop + restH > maxBottom) restTop = maxBottom - restH;
                const top0 = Math.max(minTop, H * P.layout.splitTopPct);
                lineTop = [top0];
                for (let li = 1; li < ph.lines.length; li++) lineTop.push(restTop + (li - 1) * lineH);
                top = top0;
            }
            ph.split = split;
            ph.blockW = blockW;
            ph.blockH = split ? Math.round(lineTop[lineTop.length - 1] + lineH - top) : blockH;
            ph.top = Math.round(top);

            // yPct HIỆU LỰC sau kẹp vùng an toàn, theo đúng neo. App sửa bố cục
            // (T2_EDIT) dùng làm mốc kéo: subtitle_y_pct mới = yPctEff + dY/H
            // → khối chữ nằm đúng chỗ thả, kể cả lần kéo đầu khi chưa có khoá.
            ph.yPctEff = (anchor === 'top') ? top / H
                : (anchor === 'center') ? (top + blockH / 2) / H
                    : (top + ph.blockH) / H;

            // Toạ độ tuyệt đối từng từ (làm tròn ở BƯỚC DỰNG — lúc chạy chỉ cộng
            // thêm offset thực, không bao giờ làm tròn scale/alpha/dịch chuyển).
            for (let li = 0; li < ph.lines.length; li++) {
                const ln = ph.lines[li];
                let lx;
                if (P.layout.align === 'left') lx = safeX + boxPadX + strokeOut;
                else if (P.layout.align === 'right') lx = W - safeX - boxPadX - strokeOut - ln.w;
                else lx = (W - ln.w) / 2;
                lx = Math.round(lx);
                ln.x = lx;
                const lt = split ? lineTop[li] : ph.top + li * lineH;
                ln.baseY = Math.round(lt + (lineH - (met.asc + met.desc)) / 2 + met.asc);
                for (const it of ln.items) {
                    it.absX = lx + it.x;
                    it.baseY = ln.baseY;
                }
            }

            const bx = Math.round((P.layout.align === 'center' ? (W - blockW) / 2 : ph.lines[0].x) - boxPadX - strokeOut);
            ph.boxX = bx;
            ph.boxY = Math.round(ph.top - padY - strokeOut * 0.5);
            ph.boxW = Math.round(blockW + 2 * boxPadX + 2 * strokeOut);
            // Tách trên/dưới: «hộp» là cả dải từ dòng trên tới dòng dưới — chỉ để lớp bóng biết vùng cần đúc; hộp NỀN
            // thì không vẽ (một tấm nền trùm từ đỉnh tới đáy là che cả hình — xem drawPhrase).
            ph.boxH = Math.round(ph.blockH + 2 * padY + strokeOut);

            // Thời gian nói của cụm
            ph.tStart = words[ph.range[0]].start;
            ph.tEnd = words[ph.range[1] - 1].end;
        }

        // ── Cửa sổ hiển thị ──────────────────────────────────────────
        // Cụm i tắt hẳn đúng lúc cụm i+1 bắt đầu hiện (chỉ MỘT cụm trên màn hình
        // → không bao giờ chồng hai câu lên nhau). Hệ quả: giữa hai cụm có một
        // "nhịp trống" dài = outDur + inDur. Nếu hai cụm nói LIỀN nhau (không có
        // khoảng lặng), nhịp trống đó rơi vào giữa lời → thấy phụ đề chớp tắt.
        // Vì vậy: ÉP thời lượng in/out vào đúng khoảng lặng thật giữa hai cụm
        // (tối thiểu 0.09s ≈ 3 frame @30fps) — có nghỉ thì hiệu ứng chạy đủ, nói
        // liền thì đổi câu gọn gàng.
        const inDur0 = P.in.durMs / 1000, outDur0 = P.out.durMs / 1000;
        const tot0 = inDur0 + outDur0;
        for (let i = 0; i < phrases.length; i++) {
            const ph = phrases[i];
            const prev = phrases[i - 1];
            let inD = inDur0, lead = LEAD_IN;
            if (prev) {
                const gap = Math.max(0, ph.tStart - prev.tEnd);
                const budget = Math.max(0.09, Math.min(tot0, gap + 0.10));
                inD = tot0 > 0 ? budget * (inDur0 / tot0) : 0;
                prev.outDur = budget - inD;
                lead = Math.min(LEAD_IN, gap * 0.25);
            }
            ph.inDur = inD;
            let ds = ph.tStart - inD - lead;
            if (prev) ds = Math.max(ds, prev.dispStart + 0.10);   // cụm trước phải kịp thấy
            ph.dispStart = Math.max(sStart, ds);
        }
        phrases[phrases.length - 1].outDur = outDur0;

        for (let i = 0; i < phrases.length; i++) {
            const ph = phrases[i];
            const nxt = phrases[i + 1];
            let de = nxt ? nxt.dispStart : Math.min(sEnd, ph.tEnd + TAIL_HOLD);
            if (!nxt) de = Math.max(de, Math.min(sEnd, ph.dispStart + TARGET_PHRASE_DUR));
            ph.dispEnd = Math.max(ph.dispStart + 0.08, de);
            const win = ph.dispEnd - ph.dispStart;
            ph.outDur = Math.min(ph.outDur, win / 3);   // cụm ngắn → tắt nhanh hơn
            // In-anim vốn đã bị ép vào khoảng lặng giữa hai cụm; kẹp THÊM theo độ
            // dài cụm để hoạt ảnh vào không bao giờ ăn quá 20% thời gian đọc.
            ph.inDur = Math.min(ph.inDur, win * IN_ANIM_MAX_FRAC);

            // Typewriter: gõ phải XONG SỚM rồi để nguyên câu nằm yên cho người
            // xem đọc — trước đây gõ bám theo giọng đọc nên vừa gõ xong ký tự
            // cuối là cụm sau đã đè lên, không kịp đọc gì. Tốc độ giờ tính theo
            // KÝ TỰ: hoàn tất trong ≤30% cửa sổ hiện và không quá 0.7s.
            if (P.in.kind === 'typewriter') {
                ph.typeDur = Math.max(0.06, Math.min(TYPE_MAX_SEC, win * TYPE_MAX_FRAC));
            }

            // Chỉ số ký tự luỹ kế (cho typewriter) + BỀ RỘNG TỪNG KÝ TỰ.
            // Đo trước ở đây, KHÔNG đo lúc chạy: measureText từng code point tốn
            // ~2.4ms/dòng (đo thật) — mỗi frame làm lại là mất trắng 30% ngân sách.
            let cAcc = 0;
            for (const ln of ph.lines) {
                for (const it of ln.items) {
                    it.cStart = cAcc;
                    const cps = Array.from(it.text);
                    it.nChars = cps.length;
                    cAcc += it.nChars;
                    it.cEnd = cAcc;
                    if (ls || P.in.kind === 'typewriter') {
                        it.cps = cps;
                        it.cpEmoji = cps.map(function (cp) { return EMOJI_RE.test(cp); });
                        it.adv = new Array(cps.length + 1);
                        let a = 0;
                        for (let k = 0; k < cps.length; k++) {
                            it.adv[k] = a;
                            a += ctx.measureText(cps[k]).width + ls;
                        }
                        it.adv[cps.length] = a;
                    }
                    if (!ls && EMOJI_RE.test(it.text)) {
                        // Chỉ cần cho pha VIỀN (bỏ qua đoạn emoji) → tính sẵn offset.
                        const parts = it.text.split(EMOJI_RE_G).filter(Boolean);
                        let dx = 0;
                        it.segs = parts.map(function (p) {
                            const seg = { text: p, dx: dx, emoji: EMOJI_RE.test(p) };
                            dx += ctx.measureText(p).width;
                            return seg;
                        });
                    }
                }
            }
            ph.nChars = cAcc;
        }

        ctx.restore();
        return {
            phrases: phrases, px: px, ls: ls, font: font,
            asc: met.asc, desc: met.desc, lineH: lineH, strokeOut: strokeOut
        };
    }

    /**
     * Nhét từ [from,to) vào tối đa maxLines dòng. `wW` = bề ngang ĐÃ ĐO của từng
     * từ (đo một lần ở buildLayout — hàm này bị gọi rất nhiều lần lúc gom cụm).
     * Trả { lines, leftover }: leftover = chỉ số từ ĐẦU TIÊN không nhét vừa
     * (= to nếu vừa hết) → caller đẩy phần dư sang một cụm mới.
     */
    function packLines(words, wW, from, to, spaceW, maxW, F, softChars) {
        const lines = [];
        const charCap = softChars ? Infinity : F.maxCharsPerLine;
        let cur = { items: [], w: 0, chars: 0 };

        function pushLine() {
            if (cur.items.length) lines.push(cur);
            cur = { items: [], w: 0, chars: 0 };
        }

        for (let i = from; i < to; i++) {
            const w = words[i];   // đã được cắt nhỏ ở buildLayout → luôn vừa một dòng
            const pw = wW[i];
            const add = cur.items.length ? spaceW + pw : pw;
            const addChars = cur.items.length ? 1 + w.text.length : w.text.length;
            const overflow = cur.items.length > 0 &&
                (cur.w + add > maxW || cur.chars + addChars > charCap);
            if (overflow) {
                if (lines.length + 1 >= F.maxLines) {
                    // Đã kín maxLines dòng → từ này và phần còn lại sang cụm sau.
                    pushLine();
                    return { lines: lines, leftover: Math.max(i, from + 1) };
                }
                pushLine();
            }
            const x = cur.items.length ? cur.w + spaceW : 0;
            cur.items.push({
                text: w.text, x: x, w: pw, wi: i,
                wStart: w.start, wEnd: w.end
            });
            cur.w = x + pw;
            cur.chars += addChars;
        }
        pushLine();
        return { lines: lines, leftover: to };
    }

    /** Tính lại x/w/chars của một dòng sau khi thêm/bớt từ. */
    function relayoutLine(ln, spaceW) {
        let x = 0, chars = 0;
        for (let i = 0; i < ln.items.length; i++) {
            const it = ln.items[i];
            it.x = x;
            x += it.w + spaceW;
            chars += (i ? 1 : 0) + it.text.length;
        }
        ln.w = ln.items.length ? x - spaceW : 0;
        ln.chars = chars;
    }

    /**
     * Cân dòng cuối. Xếp dòng kiểu tham lam hay để lại một từ ngắn treo lủng lẳng
     * ở dòng dưới ("trong đầu của một người cụ / thể") — cùng một cái gai mắt với
     * cụm mồ côi, chỉ khác cấp độ. Kéo một từ ở dòng trên xuống cho có đôi.
     * Không đổi nội dung cụm, không thêm dòng → không ảnh hưởng gom cụm/sức chứa.
     */
    function balanceLines(lines, spaceW, maxW, charCap) {
        if (lines.length < 2) return lines;
        const last = lines[lines.length - 1];
        const prev = lines[lines.length - 2];
        if (last.items.length !== 1 || prev.items.length < 2) return lines;
        if (Array.from(last.items[0].text).length >= MIN_PHRASE_CHARS) return lines;
        const cand = prev.items[prev.items.length - 1];
        if (last.w + spaceW + cand.w > maxW) return lines;
        if (last.chars + 1 + cand.text.length > charCap) return lines;
        prev.items.pop();
        last.items.unshift(cand);
        relayoutLine(prev, spaceW);
        relayoutLine(last, spaceW);
        return lines;
    }

    // ── Vẽ chữ ──────────────────────────────────────────────────────
    // Bộ chặn fillText của canvas_renderer thay emoji bằng PNG Twemoji, nhưng
    // strokeText KHÔNG được vá → stroke cả chuỗi sẽ vẽ viền quanh glyph tofu
    // của emoji. Vì vậy pha viền BỎ QUA các đoạn emoji (bề rộng vẫn cộng đủ để
    // các đoạn chữ sau nằm đúng chỗ).
    /** Vẽ nguyên một item (không cắt ký tự). Dùng bề rộng ĐÃ ĐO SẴN ở layout. */
    function drawWhole(c, it, ls, mode) {
        if (ls) {                                   // giãn chữ → phải vẽ từng ký tự
            for (let k = 0; k < it.nChars; k++) {
                if (mode === 'stroke') {
                    if (!it.cpEmoji[k]) c.strokeText(it.cps[k], it.absX + it.adv[k], it.baseY);
                } else {
                    c.fillText(it.cps[k], it.absX + it.adv[k], it.baseY);
                }
            }
            return;
        }
        if (mode === 'stroke') {
            if (it.segs) {                          // có emoji → chỉ viền đoạn chữ
                for (const sg of it.segs) {
                    if (!sg.emoji) c.strokeText(sg.text, it.absX + sg.dx, it.baseY);
                }
            } else {
                c.strokeText(it.text, it.absX, it.baseY);
            }
            return;
        }
        c.fillText(it.text, it.absX, it.baseY);     // qua bộ chặn → emoji ra PNG màu
    }

    /**
     * Vẽ (một phần) chữ của item. `visible` = số ký tự đã hiện (số THỰC, phần lẻ
     * → ký tự đang gõ mờ dần, nên typewriter liên tục chứ không giật từng ký tự).
     */
    function drawItem(c, it, ls, visible, mode) {
        if (visible === undefined || visible >= it.nChars) { drawWhole(c, it, ls, mode); return; }
        if (visible <= 0) return;
        const full = Math.floor(visible);
        const frac = visible - full;
        for (let k = 0; k < full; k++) {
            if (mode === 'stroke') {
                if (!it.cpEmoji[k]) c.strokeText(it.cps[k], it.absX + it.adv[k], it.baseY);
            } else {
                c.fillText(it.cps[k], it.absX + it.adv[k], it.baseY);
            }
        }
        if (frac > 0.02 && full < it.nChars) {
            const a = c.globalAlpha;
            c.globalAlpha = a * frac;
            if (mode === 'stroke') {
                if (!it.cpEmoji[full]) c.strokeText(it.cps[full], it.absX + it.adv[full], it.baseY);
            } else {
                c.fillText(it.cps[full], it.absX + it.adv[full], it.baseY);
            }
            c.globalAlpha = a;
        }
    }

    function roundRectPath(c, x, y, w, h, r) {
        r = Math.max(0, Math.min(r, Math.min(w, h) / 2));
        c.beginPath();
        c.moveTo(x + r, y);
        c.lineTo(x + w - r, y);
        c.arcTo(x + w, y, x + w, y + r, r);
        c.lineTo(x + w, y + h - r);
        c.arcTo(x + w, y + h, x + w - r, y + h, r);
        c.lineTo(x + r, y + h);
        c.arcTo(x, y + h, x, y + h - r, r);
        c.lineTo(x, y + r);
        c.arcTo(x, y, x + r, y, r);
        c.closePath();
    }

    function setShadow(c, on, colorRgba, blur, dx, dy) {
        if (on && blur > 0) {
            c.shadowColor = cssColor(colorRgba);
            c.shadowBlur = blur;
            c.shadowOffsetX = dx;
            c.shadowOffsetY = dy;
        } else {
            c.shadowColor = 'rgba(0,0,0,0)';
            c.shadowBlur = 0;
            c.shadowOffsetX = 0;
            c.shadowOffsetY = 0;
        }
    }

    /**
     * Bao hình (envelope) của MỘT từ — dùng cho mọi hiệu ứng từ.
     * attack 0.12s từ lúc từ vang lên, giữ nguyên trong lúc đọc, release 0.16s
     * sau khi từ kết thúc. Nhờ release, từ trước KHÔNG bị tắt phụt khi từ sau
     * lên → không có bước nhảy giữa 2 frame liên tiếp.
     */
    function wordEnv(tw, it) {
        if (tw <= it.wStart) return 0;
        const atk = easeOutCubic((tw - it.wStart) / 0.10);
        if (tw <= it.wEnd) return atk;
        const rel = easeInOutCubic((tw - it.wEnd) / 0.11);
        return atk * (1 - rel);
    }
    /** Tiến độ đọc bên trong từ (0→1) cho underline / box_wipe. */
    function wordProg(tw, it) {
        const d = Math.max(0.001, it.wEnd - it.wStart);
        return clamp01((tw - it.wStart) / d);
    }

    /**
     * LỚP BÓNG — dựng MỘT LẦN cho mỗi cụm rồi tái dùng (drawImage ~0.001ms).
     *
     * Vì sao phải cache: đo thật trên máy này, một lệnh fillText có shadowBlur=12
     * tốn 8.3ms. Vẽ bóng cho từng từ (12 từ) = ~100ms/frame → phụ đề còn đắt hơn
     * cả cảnh nền. Cache lại: 1 lần blur lúc dựng cụm, mỗi frame chỉ blit.
     *
     * Mẹo "chỉ lấy bóng": vẽ NGUỒN lệch hẳn ra ngoài khung (-SH_OFF theo x) và bù
     * lại bằng shadowOffsetX = SH_OFF + dx → ruột chữ rơi ngoài khung (bị cắt),
     * chỉ còn BÓNG rơi đúng chỗ. Nhờ vậy lớp bóng KHÔNG chứa ruột chữ → từ nhún/
     * nảy (scale_bump/bounce) không để lộ "bóng ma" chữ đứng yên phía dưới.
     *
     * Lớp bóng dựng ở NỬA ĐỘ PHÂN GIẢI (bóng vốn nhoè, phóng to lại không ai
     * thấy) → tốn 1/4 bộ nhớ và blur nhanh gấp ~4.
     */
    function shadowLayer(c, L, ph, ink) {
        const slot = '_shadow_' + ink;
        if (ph[slot] !== undefined) return ph[slot];
        const sh = P.color.shadow;
        if (!(sh.blur > 0) || C.shadow[3] <= 0.01) { ph[slot] = null; return null; }
        if (ink === 'box' && !P.color.box.enabled) { ph[slot] = null; return null; }
        try {
            const m = Math.ceil(sh.blur * 2 + Math.abs(sh.dx) + Math.abs(sh.dy) +
                P.color.strokeWidth * 2 + L.px * 0.6 + 8);
            const x0 = ph.boxX - m, y0 = ph.boxY - m;
            const w = Math.ceil(ph.boxW + 2 * m), h = Math.ceil(ph.boxH + 2 * m);
            if (w < 2 || h < 2 || w > 4096 || h > 4096) { ph[slot] = null; return null; }
            const S = 0.5;                          // nửa độ phân giải
            // q = hệ số của canvas phụ so với TOẠ ĐỘ LOGIC: vẫn nửa độ phân giải
            // như cũ, nhưng ăn theo RS để ở 2K/4K lớp bóng cũng dày pixel hơn
            // (bóng nhoè thật, không phải bóng 1080p bị kéo giãn).
            const q = S * RS;
            const sw2 = Math.max(2, Math.round(w * q)), sh2 = Math.max(2, Math.round(h * q));
            // Mẹo SH_OFF chỉ đúng khi A nằm TRỌN ngoài khung. sw2 lớn hơn SH_OFF
            // (chỉ có thể xảy ra ở RS cao + cụm rộng bất thường) sẽ để ruột chữ
            // lọt lại vào lớp bóng → thà bỏ bóng còn hơn vẽ sai.
            // RS=1: sw2 ≤ 2048 « 8000 → cổng này KHÔNG BAO GIỜ chạm.
            if (sw2 >= SH_OFF) { ph[slot] = null; return null; }

            // A: ruột (hộp và/hoặc chữ), KHÔNG bóng, KHÔNG hiệu ứng từ
            const A = mkCanvas(sw2, sh2);
            const ac = A.getContext('2d');
            ac.scale(q, q);
            ac.translate(-x0, -y0);
            ac.textAlign = 'left';
            ac.textBaseline = 'alphabetic';
            ac.font = L.font;
            drawPhrase(ac, L, ph, { tw: -1e9, ls: L.ls, plain: true, ink: ink });

            // B: chỉ BÓNG của A
            const B = mkCanvas(sw2, sh2);
            const bc = B.getContext('2d');
            bc.shadowColor = cssColor(C.shadow);
            bc.shadowBlur = sh.blur * q;
            bc.shadowOffsetX = SH_OFF + sh.dx * q;
            bc.shadowOffsetY = sh.dy * q;
            bc.drawImage(A, -SH_OFF, 0);

            // D: phóng SẴN về đúng cỡ thật, MỘT LẦN cho cả cụm.
            // Trước đây mỗi frame blit lớp nửa độ phân giải kèm phóng to 2x →
            // cairo lọc song tuyến 300k pixel MỖI FRAME: đo được 2.0–2.3 ms/frame,
            // đắt hơn TOÀN BỘ phần chữ cộng lại. Phóng sẵn ở đây thì mỗi frame chỉ
            // còn chép 1:1 (~0.3 ms) mà ảnh ra y hệt (cùng nguồn, cùng bộ lọc,
            // cùng lưới toạ độ nguyên).
            // "Cỡ thật" = cỡ logic × RS (pixel của canvas đích), KHÔNG phải cỡ
            // logic — nhờ vậy blit ở dưới vẫn là chép 1:1 khi ctx đã scale RS.
            const dw = Math.max(1, Math.round(w * RS)), dh = Math.max(1, Math.round(h * RS));
            const D = mkCanvas(dw, dh);
            D.getContext('2d').drawImage(B, 0, 0, dw, dh);

            // w/h giữ nguyên TOẠ ĐỘ LOGIC — đó là dw/dh của drawImage lúc blit
            // (xem paintShadow), còn pixel thật thì D đã có sẵn.
            ph[slot] = { canvas: D, x: x0, y: y0, w: w, h: h };
        } catch (e) {
            ph[slot] = null;                        // không dựng được → chỉ mất bóng
        }
        return ph[slot];
    }

    /**
     * Vẽ lớp bóng cho cụm. Với typewriter, bóng của phần chữ CHƯA GÕ phải bị
     * giấu đi (nếu không sẽ thấy "bóng ma" cả câu hiện sẵn) → tách hai lớp:
     * bóng của HỘP vẽ nguyên, bóng của CHỮ bị xén theo đúng phần đã gõ.
     */
    function paintShadow(c, L, ph, st) {
        // drawImage 4 tham số: dw/dh là TOẠ ĐỘ LOGIC, còn lớp D đã đúc sẵn ở
        // logic×RS pixel → dưới ctx đã scale RS vẫn là chép 1:1, không lọc lại
        // mỗi frame. (RS=1: dw/dh = đúng cỡ tự nhiên của D = y hệt bản 2 tham số.)
        if (st.reveal === undefined) {
            const sl = shadowLayer(c, L, ph, 'all');
            if (sl) c.drawImage(sl.canvas, sl.x, sl.y, sl.w, sl.h);
            return;
        }
        const sb = shadowLayer(c, L, ph, 'box');
        if (sb) c.drawImage(sb.canvas, sb.x, sb.y, sb.w, sb.h);
        const stx = shadowLayer(c, L, ph, 'text');
        if (!stx) return;
        const pad = Math.max(2, P.color.shadow.blur * 0.5);
        c.save();
        c.beginPath();
        let any = false;
        for (const ln of ph.lines) {
            const first = ln.items[0], last = ln.items[ln.items.length - 1];
            if (!first || st.reveal <= first.cStart) continue;
            let xEnd = last.absX + last.w;
            if (st.reveal < last.cEnd) {
                for (const it of ln.items) {
                    if (st.reveal >= it.cEnd) { xEnd = it.absX + it.w; continue; }
                    const k = Math.max(0, Math.min(it.nChars, Math.floor(st.reveal - it.cStart)));
                    xEnd = it.absX + (it.adv ? it.adv[k] : it.w);
                    break;
                }
            }
            c.rect(stx.x, ln.baseY - L.asc - pad, (xEnd + pad) - stx.x, L.asc + L.desc + 2 * pad);
            any = true;
        }
        if (any) {
            c.clip();
            c.drawImage(stx.canvas, stx.x, stx.y, stx.w, stx.h);
        }
        c.restore();
    }

    /**
     * ẢNH CHỮ DỰNG SẴN CỦA TỪNG TỪ — cách chữa "vẽ từng code point mỗi frame".
     *
     * Vì sao đắt: node-canvas 3.x KHÔNG áp dụng ctx.letterSpacing (đã đo), nên
     * preset có letterSpacing ≠ 0 (10/16 preset) phải tự vẽ TỪNG KÝ TỰ — và làm
     * lại ở CẢ pha viền lẫn pha ruột, MỖI FRAME: outline_only ~120 lệnh
     * fill/strokeText mỗi frame → 28.1 ms/frame so với 17.7 ms khi không có phụ đề.
     * strokeText của chữ đậm cũng đắt kể cả khi letterSpacing = 0.
     *
     * Cách chữa: raster MỘT LẦN cho mỗi cụm — mỗi từ 2 ảnh nhỏ (viền, ruột) ở
     * TRẠNG THÁI GỐC (chưa highlight, chưa nhún). Mỗi frame chỉ blit các từ đứng
     * yên; từ ĐANG ĐỌC (env > 0) / đang gõ (typewriter) vẫn vẽ SỐNG như cũ, nên
     * mọi hiệu ứng (đổi màu, phóng to, nảy, quét ô, quầng sáng) chạy y nguyên.
     *
     * Giữ NGUYÊN pixel:
     *   • ảnh dựng ở đúng phần lẻ toạ độ x của từ (x0 = floor(absX) - lề) và blit
     *     ở toạ độ NGUYÊN → cairo raster y hệt lúc vẽ thẳng.
     *   • chỉ blit khi alpha = 1 và cụm không bị phóng/trượt (in/out anim): khi
     *     alpha < 1, viền các chữ chồng nhau trong một ảnh sẽ trộn khác với vẽ
     *     rời từng chữ → 5–7 frame vào/ra vẫn đi đường vẽ sống cho chắc.
     *   • thứ tự pha KHÔNG đổi: vẫn viền TẤT CẢ trước, ruột TẤT CẢ sau (blit thay
     *     đúng một lệnh vẽ, đúng chỗ cũ của nó trong vòng lặp).
     *
     * RAM: chỉ giữ ảnh của CỤM ĐANG HIỆN — render đi tới theo thời gian, mà 8
     * worker chunk chạy song song nên không được giữ ảnh của cả step (xem
     * releaseCaches).
     */
    let curPhrase = null;

    /**
     * Trả lại RAM của cụm vừa rời màn hình: ảnh chữ + lớp bóng + ảnh mờ.
     * Mỗi cụm giữ tới ~5 MB canvas; một step có cả chục cụm và 8 worker chạy
     * song song → giữ hết là hàng trăm MB. Cụm chỉ hiện đúng một lần theo thời
     * gian nên bỏ đi là xong; có tua ngược thì dựng lại y hệt (hàm thuần).
     */
    function releaseCaches(ph) {
        if (!ph) return;
        if (ph._bmp !== undefined) {
            for (const ln of ph.lines) {
                for (const it of ln.items) { it._bs = null; it._bf = null; }
            }
            ph._bmp = undefined;
        }
        ph._shadow_all = undefined;
        ph._shadow_box = undefined;
        ph._shadow_text = undefined;
        ph._blur = undefined;
    }

    function renderItemBmp(L, it, x0, y0, w, h, mode) {
        // Ảnh đúc ở RS× cỡ logic. ĐÂY là chỗ quyết định chữ phụ đề có nét thật ở
        // 2K/4K hay không: mọi từ đứng yên đều đi đường blit, nên nếu đúc ở cỡ
        // logic thì chữ sẽ bị PHÓNG TO MỜ trong khi từ đang đọc (vẽ sống) lại
        // nét — mờ/nét xen kẽ ngay trong một câu.
        const cv = mkCanvas(Math.max(1, Math.round(w * RS)),
                            Math.max(1, Math.round(h * RS)));
        const c = cv.getContext('2d');
        c.setTransform(RS, 0, 0, RS, 0, 0);   // RS=1 → đồng nhất, no-op
        c.textAlign = 'left';
        c.textBaseline = 'alphabetic';
        c.font = L.font;
        c.translate(-x0, -y0);                // giữ nguyên phần lẻ của absX
        if (mode === 'stroke') {
            c.strokeStyle = cssColor(C.stroke);
            c.lineWidth = P.color.strokeWidth * 2;
            c.lineJoin = 'round';
            c.lineCap = 'round';
            c.miterLimit = 2;
        } else {
            c.fillStyle = cssColor(C.fill);
        }
        drawWhole(c, it, L.ls, mode);
        return cv;
    }

    function itemBitmaps(c, L, ph) {
        if (ph._bmp !== undefined) return ph._bmp;
        try {
            const sw = P.color.strokeWidth;
            const m = Math.ceil(sw * 2 + L.px * 0.35 + 6);   // lề: viền + phần chữ tràn
            const h = Math.ceil(L.asc + L.desc) + 2 * m;
            if (h < 2 || h > 4096) { ph._bmp = null; return null; }
            for (const ln of ph.lines) {
                for (const it of ln.items) {
                    const x0 = Math.floor(it.absX) - m;
                    const y0 = it.baseY - Math.ceil(L.asc) - m;
                    const w = Math.ceil(it.w) + 2 * m;
                    if (w < 2 || w > 4096) { releaseCaches(ph); ph._bmp = null; return null; }
                    it._bx = x0;
                    it._by = y0;
                    it._bw = w;               // cỡ LOGIC → dw/dh của drawImage
                    it._bh = h;               // (pixel thật đã là w*RS × h*RS)
                    it._bf = renderItemBmp(L, it, x0, y0, w, h, 'fill');
                    it._bs = sw > 0 ? renderItemBmp(L, it, x0, y0, w, h, 'stroke') : null;
                }
            }
            ph._bmp = true;
        } catch (e) {
            releaseCaches(ph);
            ph._bmp = null;                   // dựng không nổi → vẽ sống như cũ
        }
        return ph._bmp;
    }

    /** Từ này có được phép blit ảnh dựng sẵn không? (phải giống HỆT vẽ sống) */
    function canBlit(st, it, env, vis, fx) {
        // word.kind 'none' (テロップ Nhật: không sáng theo từ): từ đang đọc vẽ y hệt từ khác nên KHÔNG có lý do
        // gì bắt nó đi đường vẽ sống — đường ấy là thứ làm câu dài dựng chậm gấp 6 lần.
        return st.blit === true && fx === FX_NONE && (env <= 0 || P.word.kind === 'none') &&
            (vis === undefined || vis >= it.nChars);
    }

    /**
     * Vẽ toàn bộ cụm ở TOẠ ĐỘ TUYỆT ĐỐI (không đụng transform — caller lo).
     * st = { tw, ls, reveal, plain }
     *   plain = true → bỏ hiệu ứng từ + bỏ lớp bóng (dùng để dựng chính lớp bóng
     *   và ảnh mờ của blur_in). KHÔNG hàm nào ở đây bật shadow, trừ hiệu ứng
     *   'glow' của từ đang đọc (1–2 từ/frame, vùng nhỏ → rẻ).
     */
    function drawPhrase(c, L, ph, st) {
        const wk = st.plain ? 'none' : P.word.kind;
        const amount = P.word.amount;
        const sw = P.color.strokeWidth;
        const ink = st.ink || 'all';          // 'box' | 'text' | 'all' (dựng lớp bóng)

        // 0. Bóng (lớp cache) — nằm dưới tất cả
        if (!st.plain) paintShadow(c, L, ph, st);

        // 1. Hộp nền cả cụm
        if (P.color.box.enabled && ink !== 'text' && !ph.split) {
            c.fillStyle = cssColor(C.box);
            roundRectPath(c, ph.boxX, ph.boxY, ph.boxW, ph.boxH, P.color.box.radius);
            c.fill();
        }
        if (ink === 'box') return;            // lớp bóng của riêng hộp → xong

        // 2. Nền/gạch chân của từ đang đọc (dưới chữ)
        if (wk === 'box_wipe' || wk === 'underline') {
            for (const ln of ph.lines) {
                for (const it of ln.items) {
                    if (st.reveal !== undefined && st.reveal - it.cStart <= 0) continue;
                    const env = wordEnv(st.tw, it);
                    if (env <= 0.004) continue;
                    const prog = wordProg(st.tw, it);
                    c.save();
                    applyItemFx(c, L, it, itemFx(L, it, st, wk, amount));
                    if (wk === 'box_wipe') {
                        const padX = Math.max(4, L.px * 0.10), padY = Math.max(3, L.px * 0.08);
                        const bw = (it.w + padX * 2) * easeOutCubic(Math.min(1, prog * 1.25));
                        c.globalAlpha = c.globalAlpha * Math.min(1, env * 1.4);
                        c.fillStyle = cssColor(C.active);
                        roundRectPath(c, it.absX - padX, it.baseY - L.asc - padY,
                            bw, L.asc + L.desc + padY * 2, Math.max(4, L.px * 0.16));
                        c.fill();
                    } else {
                        const uh = Math.max(3, L.px * (0.06 + amount * 0.25));
                        const uw = it.w * easeOutCubic(Math.min(1, prog * 1.2));
                        c.globalAlpha = c.globalAlpha * env;
                        c.fillStyle = cssColor(C.active);
                        roundRectPath(c, it.absX, it.baseY + L.desc * 0.55, uw, uh, uh / 2);
                        c.fill();
                    }
                    c.restore();
                }
            }
        }

        // 3. Pha VIỀN — vẽ TOÀN BỘ trước, để viền của từ sau không đè lên
        //    ruột chữ của từ trước (viền LUÔN nằm dưới ruột).
        //    Từ đứng yên → blit ảnh viền dựng sẵn, ĐÚNG VỊ TRÍ CŨ trong vòng lặp
        //    nên thứ tự chồng lớp không đổi một ly.
        if (sw > 0) {
            c.strokeStyle = cssColor(C.stroke);
            c.lineWidth = sw * 2;            // vẽ dưới ruột → nhìn ra viền ngoài dày sw
            c.lineJoin = 'round';
            c.lineCap = 'round';
            c.miterLimit = 2;
            for (const ln of ph.lines) {
                for (const it of ln.items) {
                    const vis = (st.reveal === undefined) ? undefined : (st.reveal - it.cStart);
                    if (vis !== undefined && vis <= 0) continue;
                    const env = st.plain ? 0 : wordEnv(st.tw, it);
                    // box_wipe: từ nằm trên ô màu → bỏ viền cho sạch
                    if (wk === 'box_wipe' && env > 0.5) continue;
                    const fx = itemFx(L, it, st, wk, amount);
                    if (it._bs && canBlit(st, it, env, vis, fx)) {
                        c.drawImage(it._bs, it._bx, it._by, it._bw, it._bh);
                        continue;
                    }
                    c.save();
                    applyItemFx(c, L, it, fx);
                    if (wk === 'box_wipe' && env > 0) c.globalAlpha = c.globalAlpha * (1 - env);
                    drawItem(c, it, st.ls, vis, 'stroke');
                    c.restore();
                }
            }
        }

        // 4. Pha RUỘT chữ
        for (const ln of ph.lines) {
            for (const it of ln.items) {
                const vis = (st.reveal === undefined) ? undefined : (st.reveal - it.cStart);
                if (vis !== undefined && vis <= 0) continue;
                const env = st.plain ? 0 : wordEnv(st.tw, it);
                const fx = itemFx(L, it, st, wk, amount);
                // env = 0 → màu đúng bằng C.fill (mixColor(...,0)) và không quầng
                // sáng → ảnh dựng sẵn giống hệt. Từ đang đọc rơi xuống đường dưới.
                if (it._bf && canBlit(st, it, env, vis, fx)) {
                    c.drawImage(it._bf, it._bx, it._by, it._bw, it._bh);
                    continue;
                }
                c.save();
                applyItemFx(c, L, it, fx);

                let col = C.fill;
                if (wk === 'box_wipe') {
                    col = mixColor(C.fill, contrastOn(C.active), Math.min(1, env * 1.6));
                } else if (wk !== 'none') {
                    col = mixColor(C.fill, C.active, env);
                }
                // Quầng sáng của TỪ đang đọc là thứ DUY NHẤT còn dùng shadowBlur lúc
                // chạy — chỉ 1–2 từ/frame và vùng nhỏ nên chấp nhận được.
                const glow = (wk === 'glow' && env > 0.004);
                if (glow) {
                    setShadow(c, true, withAlpha(C.active, Math.min(1, env)),
                        (14 + 26 * amount) * env, 0, 0);
                }
                c.fillStyle = cssColor(col);
                drawItem(c, it, st.ls, vis, 'fill');
                if (glow) setShadow(c, false);
                c.restore();
            }
        }
    }

    /**
     * Biến hình riêng của một từ (scale_bump / bounce). Tách khỏi applyItemFx để
     * pha vẽ còn HỎI ĐƯỢC "từ này có đang bị biến hình không?" — từ đứng yên mới
     * được phép blit ảnh dựng sẵn.
     * Trả FX_NONE (đúng một object) khi không biến hình → so sánh bằng ===.
     */
    function itemFx(L, it, st, wk, amount) {
        if (st.plain) return FX_NONE;
        let s = 1, dy = 0;
        if (wk === 'scale_bump') {
            s = 1 + amount * wordEnv(st.tw, it);
        } else if (wk === 'bounce') {
            const el = st.tw - it.wStart;
            if (el > 0) {
                const b = Math.sin(Math.PI * clamp01(el / 0.30));   // lên rồi về, liên tục
                dy = -amount * L.px * b * Math.max(wordEnv(st.tw, it), b);
            }
        }
        if (s === 1 && dy === 0) return FX_NONE;
        return { s: s, dy: dy };
    }

    /** Áp biến hình của một từ. Gọi trong save/restore. */
    function applyItemFx(c, L, it, fx) {
        if (fx === FX_NONE) return;
        const cx = it.absX + it.w / 2, cy = it.baseY - L.asc * 0.35;
        c.translate(cx, cy + fx.dy);
        c.scale(fx.s, fx.s);
        c.translate(-cx, -cy);
    }

    /**
     * Số ký tự đã "gõ" tới thời điểm tSec (typewriter) — trả số THỰC (phần lẻ =
     * ký tự đang gõ mờ dần → mượt, không giật từng ký tự).
     * Tốc độ theo KÝ TỰ, đều tăm tắp như máy chữ thật, gõ xong trong ph.typeDur
     * (≤30% cửa sổ hiện, ≤0.7s) — KHÔNG bám theo giọng đọc nữa: bám giọng nghĩa
     * là gõ xong đúng lúc cụm tắt, người xem không có lấy một giây đọc trọn câu.
     */
    function typeReveal(ph, tSec) {
        const d = ph.typeDur > 0 ? ph.typeDur : 0.35;
        return ph.nChars * clamp01((tSec - ph.dispStart) / d);
    }

    /**
     * Ảnh MỜ của cụm cho hiệu ứng blur_in. node-canvas 3 có nhận ctx.filter =
     * 'blur(...)' nhưng KHÔNG áp dụng (đã đo: ảnh ra y hệt) → phải tự giả lập.
     * Cách rẻ nhất: vẽ cụm vào một canvas THU NHỎ 9 lần rồi phóng to lại khi vẽ
     * (drawImage có nội suy) → đúng một ảnh mờ. Dựng 1 lần/cụm, mỗi frame chỉ blit.
     *
     * ⚠️ CANVAS PHỤ DUY NHẤT CỐ Ý *KHÔNG* NHÂN RS — đừng "sửa" cho đồng bộ.
     * Nó là ảnh MỜ: không có chi tiết tần số cao để mà giữ. Nguồn w/9 pixel được
     * phóng lên w đơn vị logic (blit đã sẵn 4 tham số), nên ở RS nào thì hạt mờ
     * cũng đúng 9 ĐƠN VỊ LOGIC → hiệu ứng nhìn y hệt ở 1080p lẫn 4K.
     * Nhân RS vào canvas nhỏ sẽ làm hạt mờ còn 9/RS logic = BỚT MỜ ở 4K, tức
     * ĐỔI hiệu ứng chứ không phải làm nét. Chỉ tốn RAM để làm sai.
     */
    function blurSnapshot(c, L, ph) {
        if (ph._blur !== undefined) return ph._blur;
        try {
            const m = Math.ceil(L.px * 0.9 + 24);   // chừa lề cho viền/chữ tràn ra
            const x0 = ph.boxX - m, y0 = ph.boxY - m;
            const w = Math.ceil(ph.boxW + m * 2), h = Math.ceil(ph.boxH + m * 2);
            if (w <= 0 || h <= 0 || w > 4096 || h > 4096) { ph._blur = null; return null; }
            const k = 9;
            const sw = Math.max(2, Math.round(w / k)), sh2 = Math.max(2, Math.round(h / k));
            const small = mkCanvas(sw, sh2);
            const sc = small.getContext('2d');
            sc.scale(1 / k, 1 / k);
            sc.translate(-x0, -y0);
            sc.textAlign = 'left';
            sc.textBaseline = 'alphabetic';
            sc.font = L.font;
            drawPhrase(sc, L, ph, { tw: -1e9, ls: L.ls, plain: true });
            ph._blur = { canvas: small, x: x0, y: y0, w: w, h: h };
        } catch (e) {
            ph._blur = null;   // không dựng được → blur_in tự thoái hoá thành fade
        }
        return ph._blur;
    }

    // ── DRAW ────────────────────────────────────────────────────────
    function draw(ctx, W, H, step, tSec, fps) {
        if (!step) return;
        if (step.subtitle === false || step.no_subtitle === true) return;   // step tự tắt phụ đề

        let L;
        try { L = layoutFor(ctx, W, H, step); } catch (e) { warn('layout: ' + e.message); return; }
        if (!L || !L.phrases.length) return;

        let ph = null;
        for (const p of L.phrases) {
            if (tSec >= p.dispStart && tSec < p.dispEnd) { ph = p; break; }
        }
        if (!ph) return;

        // T2_EDIT (app sửa bố cục): ghi bbox NGHỈ của cụm đang hiện vào sổ toàn
        // cục — cùng cổng gác với canvas_renderer, cờ tắt = không dòng nào chạy.
        // i=-1: phụ đề không phải element của step. Hộp KHÔNG cộng offset
        // animation vào/ra (đúng vị trí nghỉ — tránh lớp lỗi neo lệch offset).
        if (globalThis.T2_EDIT === true && Array.isArray(globalThis.T2_BOXES)) {
            globalThis.T2_BOXES.push({ i: -1, type: 'subtitle',
                x: ph.boxX, y: ph.boxY, w: ph.boxW, h: ph.boxH, yPct: ph.yPctEff });
        }

        // Đổi cụm → trả RAM của cụm cũ (ảnh chữ, lớp bóng, ảnh mờ). Chỉ MỘT cụm
        // giữ canvas tại một thời điểm.
        if (curPhrase !== ph) {
            releaseCaches(curPhrase);
            curPhrase = ph;
        }

        const inK = P.in.kind, outK = P.out.kind;
        const inP = ph.inDur > 0 ? clamp01((tSec - ph.dispStart) / ph.inDur) : 1;
        const outStart = ph.dispEnd - ph.outDur;
        const outP = (ph.outDur > 0 && tSec > outStart) ? clamp01((tSec - outStart) / ph.outDur) : 0;

        // Alpha / scale / dịch chuyển — nội suy trên thời gian liên tục, KHÔNG
        // làm tròn (làm tròn = giật từng pixel ở 30fps).
        let alpha = 1, scale = 1, dy = 0;
        // Alpha vào dùng easeInOutCubic (KHÔNG phải easeOutCubic): ở 30fps, in-anim
        // 180ms chỉ có ~5 frame — easeOutCubic nhảy thẳng lên ~0.7 ngay frame đầu,
        // mắt thấy "bụp". easeInOutCubic cho 0 → .03 → .2 → .55 → .8 → 1: mượt.
        // Chuyển động (scale/trượt) vẫn dùng ease "bật" để giữ chất CapCut.
        const eIn = easeOutCubic(inP);
        const aIn = easeInOutCubic(inP);

        if (inK === 'pop') {
            alpha = aIn;
            scale = 0.86 + 0.14 * easeOutBack(inP);          // vọt lố nhẹ rồi về 1
        } else if (inK === 'slide_up') {
            alpha = aIn;
            dy = (1 - eIn) * L.px * 0.55;
        } else if (inK === 'blur_in') {
            alpha = aIn;
            scale = 1 + 0.03 * (1 - eIn);
        } else if (inK === 'fade') {
            alpha = aIn;
        } else if (inK === 'typewriter') {
            alpha = easeInOutCubic(Math.min(1, inP * 2));    // nền/khung hiện nhanh hơn chữ gõ
        } // 'none' → giữ nguyên

        if (outK === 'fade') {
            alpha *= 1 - easeInOutCubic(outP);
        } else if (outK === 'slide_down') {
            alpha *= 1 - easeInOutCubic(outP);
            dy += easeInCubic(outP) * L.px * 0.5;
        } // 'none' → không mờ

        if (alpha <= 0.004) return;

        const tw = tSec + P.word.leadMs / 1000;   // highlight chạy sớm hơn tiếng một nhịp
        const st = {
            tw: tw, ls: L.ls,
            reveal: (inK === 'typewriter') ? typeReveal(ph, tSec) : undefined
        };

        // Đường NHANH: cụm đã hiện xong (alpha = 1, không phóng/trượt) → các từ
        // đứng yên được blit từ ảnh dựng sẵn thay vì vẽ lại từng ký tự.
        // Trong 5–7 frame vào/ra (alpha < 1 hoặc đang biến hình) vẫn vẽ sống để
        // giữ NGUYÊN cách trộn alpha của các nét viền chồng nhau.
        if (alpha >= 0.999 && scale === 1 && dy === 0) {
            st.blit = itemBitmaps(ctx, L, ph) === true;
        }

        ctx.save();
        try {
            ctx.globalCompositeOperation = 'source-over';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'alphabetic';
            ctx.font = L.font;
            ctx.globalAlpha = alpha;

            if (scale !== 1 || dy !== 0) {
                const cx = W / 2, cy = ph.top + ph.blockH / 2;
                ctx.translate(cx, cy + dy);
                ctx.scale(scale, scale);
                ctx.translate(-cx, -cy);
            }

            if (inK === 'blur_in' && inP < 1) {
                const snap = blurSnapshot(ctx, L, ph);
                const p = eIn;
                if (snap) {
                    ctx.globalAlpha = alpha * (1 - p);
                    ctx.drawImage(snap.canvas, snap.x, snap.y, snap.w, snap.h);
                }
                ctx.globalAlpha = alpha * (snap ? p : 1);
                drawPhrase(ctx, L, ph, st);
            } else {
                drawPhrase(ctx, L, ph, st);
            }
        } catch (e) {
            warn('draw: ' + e.message);
        } finally {
            ctx.restore();
        }
    }

    return { draw: draw, preset: P, layoutFor: layoutFor };
}

module.exports = {
    makeSubtitle: makeSubtitle,
    loadPresets: loadPresets,
    getPreset: getPreset,
    normalizePreset: normalizePreset,
    defaultPresetsPath: defaultPresetsPath
};
