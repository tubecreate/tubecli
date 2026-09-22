/**
 * engines/display_list.js — Tách "VẼ GÌ" khỏi "VẼ BẰNG GÌ".
 *
 * canvas_renderer.js vẽ thẳng lên node-canvas → chỉ chạy được trên Node.
 * File này chèn một lớp ở giữa: renderer vẽ lên RecordingContext (ghi lại lệnh),
 * rồi backend nào cũng PHÁT LẠI được danh sách đó — node-canvas (desktop),
 * Flutter Canvas (mobile), canvas HTML5 (xem trước web). MỘT bộ mã vẽ, nhiều
 * backend. Xem docs/display-list.md.
 *
 * ĐIỂM MẤU CHỐT (đo bằng T2_SPY, xem docs): display list KHÔNG phải cuốn băng
 * câm. Renderer ĐỌC NGƯỢC trạng thái (fillStyle 939 lần/59 khung, shadow*, font…)
 * và gọi measureText 9.303 lần — nhiều nhất trong mọi lệnh. Nên RecordingContext
 * phải là MÁY TRẠNG THÁI biết trả lời:
 *   • đọc trạng thái → trả từ bản sao của chính nó (không cần canvas thật)
 *   • measureText    → hỏi HOST. Đây là cầu nối HAI CHIỀU duy nhất giữa JS và
 *                      nền tảng. Trên mobile, Flutter đo hộ qua QuickJS.
 *
 * Tài nguyên (gradient, ảnh, canvas phụ) KHÔNG serialize thẳng được → chúng vào
 * bảng `res` và lệnh chỉ tham chiếu bằng chỉ số. Đó chính là ĐƯỜNG NỐI: desktop
 * giải chỉ số đó ra đối tượng node-canvas; mobile giải ra đối tượng của Flutter.
 */

'use strict';

// Trạng thái vẽ được save()/restore() bao bọc. Danh sách này = 17 thuộc tính đo
// được thật + strokeStyle. Thiếu một khoá ở đây thì restore() sẽ trả về sai giá
// trị và hình lệch — mà lệch rất khó thấy, nên đừng "dọn bớt" cho gọn.
const STATE_KEYS = [
    'fillStyle', 'strokeStyle', 'font', 'globalAlpha',
    'shadowBlur', 'shadowColor', 'shadowOffsetX', 'shadowOffsetY',
    'lineWidth', 'lineCap', 'lineJoin', 'miterLimit', 'lineDashOffset',
    'textAlign', 'textBaseline', 'globalCompositeOperation', 'filter',
];

const DEFAULTS = {
    fillStyle: '#000000', strokeStyle: '#000000',
    font: '10px sans-serif', globalAlpha: 1,
    shadowBlur: 0, shadowColor: 'rgba(0, 0, 0, 0)',
    shadowOffsetX: 0, shadowOffsetY: 0,
    lineWidth: 1, lineCap: 'butt', lineJoin: 'miter',
    miterLimit: 10, lineDashOffset: 0,
    textAlign: 'start', textBaseline: 'alphabetic',
    globalCompositeOperation: 'source-over', filter: 'none',
};

// Lệnh KHÔNG vẽ, chỉ hỏi/tạo → không được ghi vào danh sách.
const NOT_AN_OP = new Set(['measureText', 'createLinearGradient',
                           'createRadialGradient', 'createPattern',
                           'getImageData', 'putImageData', 'createImageData']);

// ── Chuẩn hoá màu — BẪY TINH VI, đọc kỹ trước khi sửa ────────────────
// node-canvas KHÔNG trả lại nguyên văn chuỗi màu bạn gán: nó lượng tử alpha
// xuống 8 bit bằng cách CẮT CỤT (floor(a*255)) rồi in ra 2 chữ số.
//     gán  'rgba(255,255,255,0.045)'  →  đọc lại  'rgba(255, 255, 255, 0.04)'
//     gán  '#abc'                     →  đọc lại  '#aabbcc'
// Mà renderer CÓ đọc ngược: `ctx.strokeStyle = ctx.fillStyle` (canvas_renderer.js
// :4849, :4935, :4957) — tức nó dùng lại giá trị ĐÃ BỊ LÀM TRÒN.
//
// Bộ ghi lệnh phải mô phỏng ĐÚNG hành vi đó, nếu không:
//   • đọc ngược trả về 0.045 thay vì 0.04 → nét vẽ đậm hơn 1/255
//   • 257 pixel lệch quanh một icon mờ — nhỏ tới mức suýt bỏ qua, mà bỏ qua thì
//     display list KHÔNG còn là bằng chứng nữa.
// Đã kiểm khớp tuyệt đối trên 81 màu thật của renderer.
//
// GHI vs ĐỌC là hai chuyện khác nhau: canvas VẼ bằng giá trị GỐC (0.045), chỉ
// ĐỌC LẠI mới ra dạng cắt cụt. Nên ops ghi NGUYÊN VĂN, còn _s giữ dạng chuẩn hoá.
const COLOR_KEYS = new Set(['fillStyle', 'strokeStyle', 'shadowColor']);

function normColor(v) {
    if (typeof v !== 'string') return v;
    let r, g, b, a, m;
    if ((m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(v))) {
        r = parseInt(m[1] + m[1], 16); g = parseInt(m[2] + m[2], 16);
        b = parseInt(m[3] + m[3], 16); a = 1;
    } else if ((m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(v))) {
        r = parseInt(m[1], 16); g = parseInt(m[2], 16); b = parseInt(m[3], 16); a = 1;
    } else if ((m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.eE+-]+)\s*)?\)$/i.exec(v))) {
        r = Math.round(+m[1]); g = Math.round(+m[2]); b = Math.round(+m[3]);
        a = m[4] === undefined ? 1 : +m[4];
    } else {
        return v;                     // tên màu ('transparent', 'red'…) — giữ nguyên
    }
    a = Math.max(0, Math.min(1, a));
    const a8 = Math.floor(a * 255);
    if (a8 >= 255) {
        return '#' + [r, g, b].map((x) => x.toString(16).padStart(2, '0')).join('');
    }
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + (a8 / 255).toFixed(2) + ')';
}

/** Gradient giả: mang id, ghi lại addColorStop. Backend dựng lại gradient thật. */
class RecGradient {
    constructor(id) { this.__grad = id; }
    addColorStop(off, color) { this.__stops.push([off, color]); }
}

class RecordingContext {
    /**
     * @param {number} width
     * @param {number} height
     * @param {object} measurer   ctx THẬT, chỉ dùng để đo chữ (measureText).
     *        Trên mobile: một shim gọi ngược sang Flutter TextPainter.
     * @param {Function} CanvasCtor  Lớp Canvas của backend.
     *        BẮT BUỘC: subtitle_engine.js:1205 lấy lớp này bằng
     *        `ctx.canvas.constructor` để đúc ảnh chữ dựng sẵn. Nếu `canvas` chỉ
     *        là object thường thì constructor = Object → đúc ảnh ném lỗi → phụ
     *        đề rơi về đường vẽ dự phòng và SAI bố cục. Đã dính đúng bẫy này.
     */
    constructor(width, height, measurer, CanvasCtor) {
        this._m = measurer;
        this._mFont = null;              // font đang đặt trên measurer
        this.canvas = { width: width, height: height };
        if (CanvasCtor) {
            Object.defineProperty(this.canvas, 'constructor',
                                  { value: CanvasCtor, enumerable: false });
        }
        this.reset();
    }

    /** Khởi tạo. CHỈ gọi một lần — xem clearOps() cho việc sang khung mới. */
    reset() {
        this.clearOps();
        this._s = Object.assign({}, DEFAULTS);
        this._stack = [];
    }

    /**
     * Sang khung hình mới: xoá danh sách lệnh, GIỮ NGUYÊN trạng thái vẽ.
     *
     * Trạng thái PHẢI mang qua giữa các khung, vì ctx thật cũng vậy. Bản đầu
     * tiên reset cả trạng thái mỗi khung → mọi thiết lập ctx ở CẤP MODULE (chạy
     * một lần lúc nạp, TRƯỚC khung đầu) bị vứt đi, còn canvas thật thì vẫn giữ.
     * Hậu quả: 257 pixel lệch 1/255 quanh icon — nhỏ tới mức suýt bỏ qua.
     */
    clearOps() {
        this.ops = [];
        this.res = [];                   // gradient / ảnh / canvas phụ
        this._grads = [];                // stops của từng gradient
        this._resIdx = new Map();        // đối tượng -> chỉ số trong res
    }

    /** Danh sách hoàn chỉnh của MỘT khung hình. */
    finish() {
        return {
            w: this.canvas.width, h: this.canvas.height,
            res: this.res, grads: this._grads, ops: this.ops,
        };
    }

    // ── Tài nguyên ───────────────────────────────────────────────────
    _ref(obj) {
        // Ảnh/canvas phụ: giữ nguyên đối tượng trong bảng res, lệnh chỉ tham
        // chiếu chỉ số. Desktop dùng thẳng; mobile thay bảng res bằng đối
        // tượng của nó — phần `ops` KHÔNG đổi một byte.
        let i = this._resIdx.get(obj);
        if (i === undefined) {
            i = this.res.length;
            this.res.push(obj);
            this._resIdx.set(obj, i);
        }
        return { __res: i };
    }

    _val(v) {
        if (v && typeof v === 'object') {
            if (v.__grad !== undefined) return { __grad: v.__grad };
            return this._ref(v);         // pattern/ảnh gán vào fillStyle
        }
        return v;
    }

    createLinearGradient(x0, y0, x1, y1) {
        const id = this._grads.length;
        const g = new RecGradient(id);
        g.__stops = [];
        this._grads.push({ kind: 'linear', a: [x0, y0, x1, y1], stops: g.__stops });
        return g;
    }

    createRadialGradient(x0, y0, r0, x1, y1, r1) {
        const id = this._grads.length;
        const g = new RecGradient(id);
        g.__stops = [];
        this._grads.push({ kind: 'radial', a: [x0, y0, r0, x1, y1, r1], stops: g.__stops });
        return g;
    }

    // ── Đo chữ: cầu nối HAI CHIỀU duy nhất ───────────────────────────
    measureText(text) {
        // measurer phải mang đúng font hiện tại, nếu không mọi bố cục lệch.
        if (this._mFont !== this._s.font) {
            this._m.font = this._s.font;
            this._mFont = this._s.font;
        }
        return this._m.measureText(text);
    }

    // ── save / restore ───────────────────────────────────────────────
    save() {
        this._stack.push(Object.assign({}, this._s));
        this.ops.push(['save']);
    }

    restore() {
        if (this._stack.length) this._s = this._stack.pop();
        this.ops.push(['restore']);
    }
}

// ── Sinh các phương thức VẼ: mọi lệnh còn lại chỉ là ghi [tên, ...tham số] ──
// Liệt kê TƯỜNG MINH thay vì bắt bừa: lệnh lạ lọt vào sẽ im lặng biến mất khỏi
// display list (backend không biết phát lại) → hình thiếu mà không ai báo lỗi.
const DRAW_OPS = [
    'beginPath', 'closePath', 'moveTo', 'lineTo', 'bezierCurveTo',
    'quadraticCurveTo', 'arc', 'arcTo', 'ellipse', 'rect', 'roundPath', 'roundRect',
    'fill', 'stroke', 'clip',
    'fillRect', 'strokeRect', 'clearRect',
    'fillText', 'strokeText',
    'translate', 'scale', 'rotate', 'transform', 'setTransform', 'resetTransform',
    'setLineDash',
];
for (const name of DRAW_OPS) {
    RecordingContext.prototype[name] = function () {
        const a = new Array(arguments.length);
        for (let i = 0; i < arguments.length; i++) a[i] = arguments[i];
        this.ops.push([name].concat(a));
    };
}

// drawImage: tham số ĐẦU là Canvas/Image → thay bằng tham chiếu chỉ số.
RecordingContext.prototype.drawImage = function () {
    const a = new Array(arguments.length);
    a[0] = this._ref(arguments[0]);
    for (let i = 1; i < arguments.length; i++) a[i] = arguments[i];
    this.ops.push(['drawImage'].concat(a));
};

// ── Thuộc tính: gán thì GHI, đọc thì TRẢ TỪ BẢN SAO ──────────────────
for (const k of STATE_KEYS) {
    const isColor = COLOR_KEYS.has(k);
    Object.defineProperty(RecordingContext.prototype, k, {
        get() { return this._s[k]; },
        set(v) {
            // ops = NGUYÊN VĂN (canvas vẽ bằng giá trị gốc).
            // _s  = CHUẨN HOÁ (đọc ngược phải giống node-canvas). Xem normColor.
            this._s[k] = isColor ? normColor(v) : v;
            this.ops.push(['=', k, this._val(v)]);
        },
    });
}

/**
 * Phát lại display list lên một ctx THẬT.
 * @param {object}   ctx
 * @param {object}   dl        kết quả của RecordingContext.finish()
 * @param {function} [resolve] res[i] -> đối tượng ảnh của backend.
 *                             Bỏ trống = dùng thẳng (desktop: đã là node-canvas).
 */
function playDisplayList(ctx, dl, resolve) {
    const R = resolve || function (x) { return x; };
    const grads = new Array(dl.grads.length);

    const gradOf = (id) => {
        if (grads[id]) return grads[id];
        const g = dl.grads[id];
        const a = g.a;
        const obj = g.kind === 'linear'
            ? ctx.createLinearGradient(a[0], a[1], a[2], a[3])
            : ctx.createRadialGradient(a[0], a[1], a[2], a[3], a[4], a[5]);
        for (const s of g.stops) obj.addColorStop(s[0], s[1]);
        grads[id] = obj;
        return obj;
    };

    const val = (v) => {
        if (v && typeof v === 'object') {
            if (v.__grad !== undefined) return gradOf(v.__grad);
            if (v.__res !== undefined) return R(dl.res[v.__res], v.__res);
        }
        return v;
    };

    for (const op of dl.ops) {
        const name = op[0];
        if (name === '=') { ctx[op[1]] = val(op[2]); continue; }
        if (name === 'save') { ctx.save(); continue; }
        if (name === 'restore') { ctx.restore(); continue; }
        const n = op.length - 1;
        if (name === 'drawImage') {
            const a = new Array(n);
            a[0] = val(op[1]);
            for (let i = 1; i < n; i++) a[i] = op[i + 1];
            ctx.drawImage.apply(ctx, a);
            continue;
        }
        const a = new Array(n);
        for (let i = 0; i < n; i++) a[i] = op[i + 1];
        ctx[name].apply(ctx, a);
    }
}

module.exports = { RecordingContext, playDisplayList, STATE_KEYS, DRAW_OPS };
