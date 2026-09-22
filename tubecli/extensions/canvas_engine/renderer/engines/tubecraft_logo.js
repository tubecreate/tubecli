/* engines/tubecraft_logo.js — TubeCraft brand mark: MỘT nguồn vẽ TẤT ĐỊNH.
 *
 * Nguyên tắc "khớp từng byte":
 *   - Mọi ngẫu nhiên đi qua mulberry32(SEED) gọi theo THỨ TỰ CỐ ĐỊNH lúc build
 *     map — không Math.random, không Date.now ⇒ cùng t là cùng hình, mãi mãi.
 *   - Logo tĩnh = drawMark(t=1). Icon/outro/preview đều render từ chính hàm này
 *     ⇒ không tồn tại "logo vẽ tay bản thứ hai" để mà lệch.
 *   - KHÔNG shadowBlur (mỗi backend rasterize khác nhau) — quầng sáng làm bằng
 *     radial gradient thường.
 *   - ĐỔI BẤT KỲ HẰNG NÀO dưới đây là đổi logo ⇒ phải bump VERSION.
 *
 * Câu chuyện animation (t 0→1):  pixel dữ liệu (lưới) → AI nghĩ (trôi dạt)
 *   → hội tụ (bay về vị trí) → nút Play pixel hoàn chỉnh (= logo chính thức,
 *   mũi tên đặc dần về bên phải, rìa trái tan thành hạt như đang hình thành).
 *
 * Chạy được ở cả 3 não: browser (window.TCLogo), Node/node-canvas (require),
 * và nhúng vào canvas_renderer.js cho cảnh outro.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TCLogo = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var VERSION = '1.0.0';
  var SEED = 0x54435631; // 'TCV1'

  // ── PRNG tất định ──────────────────────────────────────────────────
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ── Easing ─────────────────────────────────────────────────────────
  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
  function easeInOutQuad(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
  function lerp(a, b, t) { return a + (b - a) * t; }

  // ── Bảng màu thương hiệu ───────────────────────────────────────────
  var PALETTE = {
    purple: '#7C3AED', indigo: '#4F46E5', blue: '#3B82F6',
    sky: '#0EA5E9', cyan: '#22D3EE',
    ink: '#0F172A', inkDark: '#F1F5F9',          // chữ "Tube" nền sáng / nền tối
    slate: '#64748B', slateDark: '#94A3B8',       // tagline
    outroBg0: '#0B1020', outroBg1: '#131A33',     // nền outro video
  };
  // Gradient dọc theo trục X của mũi tên (0 = đuôi trái tím, 1 = mũi phải cyan)
  var GRAD = [
    [0.00, 0x7C, 0x3A, 0xED],
    [0.34, 0x4F, 0x46, 0xE5],
    [0.62, 0x3B, 0x82, 0xF6],
    [0.86, 0x0E, 0xA5, 0xE9],
    [1.00, 0x22, 0xD3, 0xEE],
  ];
  function gradAt(x) {
    x = clamp01(x);
    for (var i = 1; i < GRAD.length; i++) {
      if (x <= GRAD[i][0]) {
        var a = GRAD[i - 1], b = GRAD[i];
        var q = (x - a[0]) / (b[0] - a[0]);
        return [Math.round(lerp(a[1], b[1], q)),
                Math.round(lerp(a[2], b[2], q)),
                Math.round(lerp(a[3], b[3], q))];
      }
    }
    var g = GRAD[GRAD.length - 1]; return [g[1], g[2], g[3]];
  }

  // ── Mốc thời gian các pha (phần của t 0..1) ────────────────────────
  // Chuyển động "PHI THUYỀN": mũi (cột phải) lao vào trước như vệt phản lực,
  // thân nạp dần PHÍA SAU, hạt exhaust phụt ra từ đuôi sau cùng.
  var T = {
    FLY:     [0.03, 0.80],   // vệt pixel lao từ trái vào, mũi đáp trước
    SETTLE:  [0.78, 0.93],   // nhún đàn hồi 1 nhịp rồi đứng yên
    HOLD:    0.93,           // từ đây trở đi: BẤT BIẾN — mọi t≥0.93 cho cùng hình
  };

  // ── Build pixel map (chạy đúng MỘT lần, thứ tự gọi rnd cố định) ────
  // Toạ độ "đơn vị mark": gốc = tâm thân mũi tên, 1 đơn vị = 1 ô lưới.
  var COLS = 10, ROWS = 13, MID = 6;
  var PX = [];                       // {gx,gy, tx,ty, su, a, cG, cF, ...lịch bay}
  (function build() {
    var rnd = mulberry32(SEED);
    // Xói mòn CHỈ Ở RÌA: 3 cột trái, và trong mỗi cột chỉ 2 ô ngoài cùng
    // (edgeDist 0/1) mới được phép tan — LÕI LUÔN ĐẶC, không thủng giữa thân.
    var keepByCol = [0.42, 0.60, 0.78];
    var body = [], nearTrail = [];
    for (var c = 0; c < COLS; c++) {
      var halfH = Math.round(MID * (1 - c / (COLS - 1)));
      for (var r = MID - halfH; r <= MID + halfH; r++) {
        var edgeDist = halfH - Math.abs(r - MID);
        var keep = (c < 3 && edgeDist < 2)
          ? keepByCol[c] + edgeDist * 0.30
          : 1;
        if (rnd() < keep) body.push([c, r]);
        else nearTrail.push([c, r]);          // ô rìa "tan" → hạt lơ lửng gần đó
      }
    }
    var i, e;
    for (i = 0; i < body.length; i++) {
      e = body[i];
      PX.push({
        tx: e[0] - (COLS - 1) / 2,
        ty: e[1] - MID,
        su: 0.92,                             // đồng cỡ toàn thân, kể cả ô mũi
        a: 1,
        gcol: gradAt(e[0] / (COLS - 1) + (rnd() - 0.5) * 0.07),
        col: e[0],
      });
    }
    for (i = 0; i < nearTrail.length; i++) {
      e = nearTrail[i];
      PX.push({
        tx: e[0] - (COLS - 1) / 2 - (0.4 + rnd() * 1.6),
        ty: e[1] - MID + (rnd() - 0.5) * 1.8,
        su: 0.50 + rnd() * 0.30,
        a: 0.55 + rnd() * 0.40,
        gcol: gradAt(rnd() * 0.22),           // hạt tan thiên tím
        col: e[0],
        // Biến thể SOLID (icon cỡ nhỏ): ô tan vẽ lại ĐÚNG Ô GỐC, đầy đặn
        solid: {
          tx: e[0] - (COLS - 1) / 2,
          ty: e[1] - MID,
          su: 0.92, a: 1,
          gcol: gradAt(e[0] / (COLS - 1) + (rnd() - 0.5) * 0.07),
        },
      });
    }
    var FAR = 10;                              // hạt bay xa phía sau đuôi
    for (i = 0; i < FAR; i++) {
      PX.push({
        tx: -(COLS - 1) / 2 - (0.8 + rnd() * 4.2),
        ty: (rnd() - 0.5) * 10.5,
        su: 0.42 + rnd() * 0.30,
        a: 0.45 + rnd() * 0.40,
        gcol: gradAt(rnd() * 0.18),
        col: 0,
      });
    }
    // Lịch bay "phi thuyền" từng pixel. LƯU Ý byte-exact: mọi giá trị QUYẾT
    // ĐỊNH HÌNH CUỐI (tx/ty/su/a/gcol) đã chốt Ở TRÊN — khối này chỉ sinh
    // tham số HÀNH TRÌNH, đổi thoải mái không làm logo tĩnh xê dịch 1 byte.
    var N = PX.length;
    for (i = 0; i < N; i++) {
      var p = PX[i];
      var isTrailPx = p.a !== 1;
      var stag = isTrailPx
        ? 0.58 + rnd() * 0.30                              // exhaust: phụt SAU CÙNG
        : (1 - p.col / (COLS - 1)) * 0.60 + rnd() * 0.16;  // thân: MŨI đáp trước
      p.fs = T.FLY[0] + stag * (T.FLY[1] - T.FLY[0] - 0.30);
      p.fd = 0.20 + rnd() * 0.10;
      if (p.fs + p.fd > T.FLY[1]) p.fd = T.FLY[1] - p.fs;
      p.dist = 9 + rnd() * 8;        // quãng lao tới từ bên trái (đơn vị ô)
      p.lane = (rnd() - 0.5) * 2.4;  // lệch làn dọc lúc xuất phát
      p.curve = (rnd() - 0.5) * 1.4; // cong nhẹ đường bay
      p.p1 = rnd(); p.p2 = rnd();    // pha riêng cho idle "thở"
    }
    PX.MARK_N = N;
  })();

  var TAU = Math.PI * 2;

  // ── Hàm vẽ cốt lõi ─────────────────────────────────────────────────
  // o = { cx, cy, size,           tâm THÂN mũi tên + bề rộng thân (px)
  //       t = 1,                  tiến trình câu chuyện 0..1 (t≥0.86 bất biến)
  //       alpha = 1, trail = true, halo = false,
  //       idle = 0 }              giây "thở" nhè nhẹ — CHỈ dùng cho preview UI
  function drawMark(ctx, o) {
    // o.wrapColor: bọc màu string thành paint bất biến (CanvasGradient) —
    // né Proxy đổi màu theo art style của renderer khi vẽ outro (chỉ
    // string bị can thiệp, gradient đi xuyên nguyên vẹn).
    var wrap = o.wrapColor || function (c) { return c; };
    var t = o.t == null ? 1 : o.t;
    var u = o.size / COLS;
    var galpha = o.alpha == null ? 1 : o.alpha;
    if (galpha <= 0 || t <= 0) return;

    // Nhún đàn hồi toàn khối pha SETTLE — kết thúc CHÍNH XÁC = 1 (bất biến)
    var ss = clamp01((t - T.SETTLE[0]) / (T.SETTLE[1] - T.SETTLE[0]));
    var s = 1 + 0.05 * Math.sin(Math.PI * ss) * (1 - ss);

    if (o.halo) {
      var ht = clamp01((t - 0.5) / 0.3) * 0.16 * galpha;
      if (ht > 0) {
        var hg = ctx.createRadialGradient(o.cx + o.size * 0.05, o.cy, 0,
                                          o.cx + o.size * 0.05, o.cy, o.size * 0.85);
        hg.addColorStop(0, 'rgba(79,70,229,' + ht.toFixed(4) + ')');
        hg.addColorStop(0.6, 'rgba(34,211,238,' + (ht * 0.45).toFixed(4) + ')');
        hg.addColorStop(1, 'rgba(34,211,238,0)');
        ctx.fillStyle = hg;
        ctx.fillRect(o.cx - o.size * 0.95, o.cy - o.size * 0.9,
                     o.size * 1.9, o.size * 1.8);
      }
    }

    for (var i = 0; i < PX.length; i++) {
      var p = PX[i];
      var isTrail = p.a !== 1;
      // o.solid: ô rìa "tan" vẽ lại đúng ô gốc (icon nhỏ cần tam giác đầy);
      // hạt bay xa (không có .solid) vẫn theo o.trail như thường.
      var dst = (o.solid && p.solid) ? p.solid : p;
      if (isTrail && !(o.solid && p.solid) && o.trail === false) continue;

      var fq = clamp01((t - p.fs) / p.fd);            // tiến trình bay 0..1
      if (fq <= 0) continue;                          // chưa xuất phát — vô hình
      var e = easeOutCubic(fq);

      // Xuất phát: thân lao NGANG từ bên trái như phi thuyền; hạt exhaust
      // phụt ra từ đuôi rồi tản về sau.
      var isExhaust = isTrail && dst === p;
      var sx, sy;
      if (isExhaust) {
        sx = -(COLS - 1) / 2 + 0.6;
        sy = dst.ty * 0.3;
      } else {
        sx = dst.tx - p.dist;
        sy = dst.ty + p.lane;
      }
      var mx = (sx + dst.tx) / 2;
      var my = (sy + dst.ty) / 2 + p.curve;
      var i1 = 1 - e;
      var x = i1 * i1 * sx + 2 * i1 * e * mx + e * e * dst.tx;
      var y = i1 * i1 * sy + 2 * i1 * e * my + e * e * dst.ty;
      var size = lerp(isExhaust ? 0.30 : 0.66, dst.su, e);
      // Vệt nóng: pha trắng lúc tốc độ cao, nguội dần về màu thật khi đáp
      var hot = (isExhaust ? 0.20 : 0.45) * (1 - e);
      var cr = Math.round(dst.gcol[0] + (255 - dst.gcol[0]) * hot);
      var cg = Math.round(dst.gcol[1] + (255 - dst.gcol[1]) * hot);
      var cb = Math.round(dst.gcol[2] + (255 - dst.gcol[2]) * hot);
      var a = Math.min(1, fq * 4) * lerp(1, dst.a, e) * galpha;

      if (o.idle && t >= 1) {
        x += Math.cos(o.idle * 1.1 + p.p2 * TAU) * 0.045;
        y += Math.sin(o.idle * 1.4 + p.p1 * TAU) * 0.055;
      }

      // Kéo giãn ngang theo tốc độ (motion streak) — về đúng hình vuông khi đáp
      var stretch = isExhaust ? 1 : 1 + 2.2 * (1 - e);
      var w2 = size * u * s * stretch;
      var h2 = size * u * s;
      var px = o.cx + x * u * s - w2 / 2;
      var py = o.cy + y * u * s - h2 / 2;
      ctx.fillStyle = wrap('rgba(' + cr + ',' + cg + ',' + cb + ',' + +a.toFixed(4) + ')');
      rr(ctx, px, py, w2, h2, Math.min(w2, h2) * 0.34);
      ctx.fill();
    }
  }

  // Bo góc thủ công — roundRect() không có ở node-canvas cũ
  function rr(ctx, x, y, w, h, r) {
    if (r > w / 2) r = w / 2;
    if (r > h / 2) r = h / 2;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // ── Wordmark "TubeCraft" + tagline ─────────────────────────────────
  // o = { cx, topY, size, theme='light', t=1, font, weight='800',
  //       faux=0, tagline=true }
  // faux: độ dày giả (tỷ lệ theo size) — dùng khi font chỉ có Regular
  // (node-canvas + font bundle): fill + stroke cùng màu = nét đậm tất định.
  function drawWordmark(ctx, o) {
    var t = o.t == null ? 1 : o.t;
    if (t <= 0) return;
    var e = easeOutCubic(clamp01(t));
    var rise = (1 - e) * o.size * 0.22;
    var font = o.font || "-apple-system, 'Segoe UI', Roboto, sans-serif";
    var weight = o.weight || '800';
    var faux = o.faux || 0;
    var dark = o.theme === 'dark';

    ctx.save();
    ctx.globalAlpha *= e;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    ctx.lineJoin = 'round';
    var wrap = o.wrapColor || function (c) { return c; };
    function paint(text, x, y, style, lw) {
      style = (typeof style === 'string') ? wrap(style) : style;
      ctx.fillStyle = style;
      if (faux > 0) {
        ctx.strokeStyle = style;
        ctx.lineWidth = lw;
        ctx.strokeText(text, x, y);
      }
      ctx.fillText(text, x, y);
    }
    ctx.font = weight + ' ' + o.size + 'px ' + font;
    var wTube = ctx.measureText('Tube').width;
    var wCraft = ctx.measureText('Craft').width;
    var x0 = o.cx - (wTube + wCraft) / 2;
    var by = o.topY + o.size + rise;
    // o.ink/o.muted: màu chữ theo THEME CỦA VIDEO (outro "ăn" style) —
    // vắng thì dùng bảng màu brand mặc định.
    paint('Tube', x0, by, o.ink || (dark ? PALETTE.inkDark : PALETTE.ink),
          o.size * faux);
    var g = ctx.createLinearGradient(x0 + wTube, 0, x0 + wTube + wCraft, 0);
    g.addColorStop(0, PALETTE.indigo);
    g.addColorStop(0.55, PALETTE.blue);
    g.addColorStop(1, PALETTE.cyan);
    paint('Craft', x0 + wTube, by, g, o.size * faux);

    if (o.tagline !== false) {
      var ts = o.size * 0.235;
      var lsp = ts * 0.42;
      ctx.font = weight + ' ' + ts + 'px ' + font;
      var text = 'AI VIDEO CREATION';
      var tw = 0, ci;
      for (ci = 0; ci < text.length; ci++) tw += ctx.measureText(text[ci]).width + lsp;
      tw -= lsp;
      var tx = o.cx - tw / 2;
      var ty = by + o.size * 0.52;
      var tstyle = o.muted || (dark ? PALETTE.slateDark : PALETTE.slate);
      for (ci = 0; ci < text.length; ci++) {
        paint(text[ci], tx, ty + rise * 0.5, tstyle, ts * faux * 0.6);
        tx += ctx.measureText(text[ci]).width + lsp;
      }
    }
    ctx.restore();
  }

  // ── Outro video (bản Free): full-frame, ~3 giây ────────────────────
  // o = { w, h, t 0..1, font, caption='TUBECREATE.COM', fadeIn=true,
  //       bg='paint'|'none',       'none' = KHÔNG vẽ nền, lộ nền thật của
  //                                video (outro "ăn" theo style — pipeline)
  //       ink, muted, accent }     màu chữ/URL theo token theme của video
  // Mark kể chuyện trong t∈[0,0.72], wordmark hiện [0.52,0.78], hold tới 1.
  function drawOutro(ctx, o) {
    var t = clamp01(o.t == null ? 1 : o.t);
    var w = o.w, h = o.h;
    if (o.bg !== 'none') {
      var bg = ctx.createLinearGradient(0, 0, 0, h);
      bg.addColorStop(0, PALETTE.outroBg0);
      bg.addColorStop(1, PALETTE.outroBg1);
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);
    }

    var portrait = h > w;
    var mSize = Math.min(w, h) * (portrait ? 0.26 : 0.19);
    var cy = h * (portrait ? 0.42 : 0.40);
    drawMark(ctx, {
      cx: w / 2, cy: cy, size: mSize,
      t: Math.min(1, t / 0.72),
      halo: true, wrapColor: o.wrapColor,
    });
    var wmSize = mSize * 0.38;   // mark nhỏ lại nhưng chữ giữ cỡ — cân bố cục
    drawWordmark(ctx, {
      cx: w / 2, topY: cy + mSize * 0.85, size: wmSize,
      theme: 'dark', font: o.font, weight: o.weight, faux: o.faux,
      ink: o.ink, muted: o.muted, wrapColor: o.wrapColor,
      t: clamp01((t - 0.52) / 0.26),
    });
    if (o.caption !== '') {
      var ct = clamp01((t - 0.66) / 0.22);
      if (ct > 0) {
        // URL kiểu "kicker": cùng họ font với TubeCraft, in hoa + giãn chữ
        // như tagline, màu CYAN đúng màu mũi thuyền → đọc như call-to-action.
        var capSize = wmSize * 0.30;
        var capText = o.caption || 'TUBECREATE.COM';
        var capY = cy + mSize * 0.85 + wmSize * 2.40;
        var clsp = capSize * 0.32;
        ctx.save();
        ctx.globalAlpha *= ct * 0.95;
        ctx.font = (o.weight || '700') + ' ' + capSize + 'px ' +
          (o.font || "-apple-system, 'Segoe UI', Roboto, sans-serif");
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
        ctx.lineJoin = 'round';
        var capCol = o.accent || PALETTE.cyan;   // URL ăn màu accent của theme
        if (o.wrapColor) capCol = o.wrapColor(capCol);
        ctx.fillStyle = capCol;
        ctx.strokeStyle = capCol;
        var cw = 0, k;
        for (k = 0; k < capText.length; k++) cw += ctx.measureText(capText[k]).width + clsp;
        cw -= clsp;
        var cx2 = w / 2 - cw / 2;
        for (k = 0; k < capText.length; k++) {
          if (o.faux > 0) {
            ctx.lineWidth = capSize * o.faux * 0.7;
            ctx.strokeText(capText[k], cx2, capY);
          }
          ctx.fillText(capText[k], cx2, capY);
          cx2 += ctx.measureText(capText[k]).width + clsp;
        }
        ctx.restore();
      }
    }
    // Vào từ đen 0.3s đầu (nối mượt từ cảnh cuối của video)
    if (o.fadeIn !== false && t < 0.10) {
      ctx.fillStyle = 'rgba(7,10,22,' + (1 - t / 0.10).toFixed(4) + ')';
      ctx.fillRect(0, 0, w, h);
    }
  }

  return {
    VERSION: VERSION,
    SEED: SEED,
    PALETTE: PALETTE,
    T: T,
    COLS: COLS,
    ROWS: ROWS,
    PIXEL_COUNT: PX.length,
    // Dữ liệu hình HỌC thô của mark (đơn vị ô, gốc = tâm thân mũi tên) — cho
    // nơi cần dựng SVG/icon tĩnh từ đúng nguồn này (t2app tao-icon.mjs,
    // components/logo.tsx). c = [r,g,b]; solid = biến thể ô-xói-lấp-đầy.
    markPixels: PX.map(function (p) {
      var o = { x: p.tx, y: p.ty, s: p.su, a: p.a, c: p.gcol };
      if (p.solid) o.solid = { x: p.solid.tx, y: p.solid.ty, s: p.solid.su, a: 1, c: p.solid.gcol };
      return o;
    }),
    drawMark: drawMark,
    drawWordmark: drawWordmark,
    drawOutro: drawOutro,
  };
}));
