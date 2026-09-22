#!/usr/bin/env node

/**

 * EduVideo Studio — Canvas Frame Renderer v5

 * Auto-layout + Geometry Zone + Dynamic Box

 */

global.window = global;

const fs = require('fs');

const path = require('path');

function parseArgs(argv) {

    const r = {};

    for (let i = 0; i < argv.length; i++) {

        if (argv[i].startsWith('--')) {

            const key = argv[i].slice(2);

            const val = argv[i + 1];

            if (val !== undefined && !val.startsWith('--')) {

                r[key] = val;

                i++;

            } else {

                r[key] = true;

            }

        }

    }

    return r;

}

// ══ BOOT ════════════════════════════════════════════════════════════
// Node lay tham so tu DONG LENH va kich ban tu FILE. Trinh duyet va QuickJS
// khong co ca hai thu do — chung BOM thang vao qua globalThis.T2_BOOT:
//     { args, script, timing, canvas?, host? }
// Nho vay code ve ben duoi KHONG can biet minh dang chay o dau.
// Xem engines/host.js va docs/display-list.md.
const BOOT = (typeof globalThis !== 'undefined' && globalThis.T2_BOOT) || null;

const args = BOOT ? (BOOT.args || {}) : parseArgs(process.argv.slice(2));

const scriptPath = args.script, timingPath = args.timing, outputDir = args.output;

const themeName = args.theme || 'dark', FPS = parseInt(args.fps || '30');

// ── Tuỳ biến NỀN, độc lập với phong cách ────────────────────────────
//   --bg-color "#111"           nền trơn một màu
//   --bg-grad  "#0a0a1a,#1a1030" nền gradient 2 màu (ưu tiên hơn bg-color)
//   --bg-fx    off | auto        auto = giữ hiệu ứng nền của phong cách
//                                off  = nền phẳng, bỏ lưới/sao/quả cầu
// LƯU Ý: phải áp SAU khối STYLE_PALETTES (dòng ~304) vì phong cách ghi đè
// T.bgGrad — trước đây bg-color đặt trước nên bị nuốt, không bao giờ có tác dụng.
// Ưu tiên CLI arg, fallback env T2_* (render_service/video_encoder set env cho
// worker song song — giống cách làm của title-color/text-color/font).
const customBgColor = args['bg-color'] || '';
const customBgGrad = (args['bg-grad'] || process.env.T2_BG_GRAD || '')
    .split(',').map(function (s) { return s.trim(); }).filter(Boolean);
const bgFx = (args['bg-fx'] || process.env.T2_BG_FX || 'auto').toLowerCase();
global.bgFxOff = (bgFx === 'off' || bgFx === 'none');

if (!BOOT && (!scriptPath || !timingPath || !outputDir)) {

    console.log(JSON.stringify({status:'error',message:'--script, --timing, --output required'}));

    process.exit(1);

}

const script = BOOT ? BOOT.script : JSON.parse(fs.readFileSync(scriptPath, 'utf-8'));

const timing = BOOT ? BOOT.timing : JSON.parse(fs.readFileSync(timingPath, 'utf-8'));

if (!BOOT) fs.mkdirSync(outputDir, { recursive: true });

const aspect_ratio = args.aspect || '9:16';

const W = aspect_ratio === '16:9' ? 1920 : (aspect_ratio === '1:1' ? 1080 : 1080);

const H = aspect_ratio === '16:9' ? 1080 : (aspect_ratio === '1:1' ? 1080 : 1920);

const MX = 60; // horizontal margin

// ══ RSCALE — HỆ SỐ PHÓNG ĐỘ PHÂN GIẢI ═══════════════════════════════
// W/H/MX ở TRÊN là KHÔNG GIAN TOẠ ĐỘ LOGIC, VĨNH VIỄN 1080×1920 (hoặc
// 1920×1080 / 1080×1080). Toàn bộ 7.8k dòng code vẽ bên dưới vẫn "nghĩ" bằng
// 1080 — không một hằng nào trong đó đổi.
//
// RSCALE chỉ nhân ở ĐÚNG HAI CHỖ:
//   1. cỡ THẬT của canvas đích (1080·RSCALE × 1920·RSCALE)
//   2. 15 lệnh ctx.setTransform(...) đầu mỗi lớp vẽ
// Nhờ vậy chữ/hình/gradient (vốn là VECTOR) được rasterize thẳng ở độ phân giải
// cao = NÉT THẬT, không phải phóng to ảnh 1080p.
//
// RSCALE = 1 (mặc định, khi vắng --scale) → desktop chạy y hệt hôm nay.
// RSCALE = 2 → 2160×3840 (4K dọc). 1.333 → 1440×2560 (2K).
//
// ⚠️ MỌI CANVAS PHỤ (lớp bóng, quầng glow, ảnh chữ đúc sẵn, lớp phủ nghệ thuật)
// PHẢI dựng ở RSCALE× và blit bằng drawImage CÓ dw/dh (toạ độ logic). Dựng ở cỡ
// logic rồi blit dưới ctx đã scale = ảnh bị PHÓNG TO MỜ — chữ nét mà bóng mờ còn
// tệ hơn 1080p thật. Xem từng chỗ HOST.createCanvas + subtitle_engine.js.
const RSCALE = (function () {
    const raw = args.scale || (BOOT && BOOT.scale) || process.env.T2_SCALE || 1;
    const v = parseFloat(raw);
    if (!isFinite(v) || v <= 0) return 1;
    return Math.min(4, Math.max(0.25, v));   // chặn giá trị điên → không nổ RAM
})();

// NOTE: 'sans-serif' MUST come before "Segoe UI" — the fontconfig alias prefers
// "Be Vietnam Pro"; direct family lookup can fail under pango-win32, so the alias
// is the reliable path to BVP. Putting Segoe first would silently win the fallback.
// Font phải liệt kê TƯỜNG MINH cho từng hệ chữ: fontconfig không tự nhảy sang
// font CJK/Devanagari nếu family không có trong stack → chữ Nhật/Hàn/Trung/Hindi
// ra ô vuông mã codepoint (tofu). Thứ tự: Latin+Việt trước, rồi các hệ chữ khác.
/**
 * ⚠️ NGĂN NÀY PHẢI PHỦ CẢ WINDOWS LẪN ANDROID/iOS.
 *
 * Trước đây nó TOÀN FONT WINDOWS: Yu Gothic UI, Malgun Gothic, Microsoft YaHei,
 * Nirmala UI, Leelawadee UI, Segoe UI. Trên điện thoại KHÔNG CÓ CÁI NÀO — nên
 * video render trên mobile mất sạch chữ Nhật/Hàn/Trung/Ấn/Thái, và chữ Cyrillic
 * /Ả Rập rơi về font mặc định.
 *
 * Lỗi này KHÔNG LỘ RA khi thử trên máy tính. Nó chỉ chết trên điện thoại.
 *
 * Thứ tự: font riêng của app → font Windows → font Apple → font Android (Noto).
 * Máy nào có gì thì lấy cái đó; máy không có thì rơi xuống tên tiếp theo.
 * Đừng bỏ font Windows đi — bản desktop vẫn phải chạy đúng như cũ.
 */
const SYSTEM_FONT_STACK = '"Be Vietnam Pro", sans-serif, ' +
    // 日本語 — Windows · Apple · Android
    '"Yu Gothic UI", "Meiryo", "MS Gothic", "Hiragino Sans", "Noto Sans JP", ' +
    // 한국어
    '"Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", ' +
    // 中文
    '"Microsoft YaHei", "SimSun", "PingFang SC", "Noto Sans SC", ' +
    // हिन्दी + Ấn Độ
    '"Nirmala UI", "Devanagari Sangam MN", "Noto Sans Devanagari", ' +
    // ไทย
    '"Leelawadee UI", "Thonburi", "Noto Sans Thai", ' +
    // Cyrillic / Ả Rập / Hy Lạp
    '"Segoe UI", "Geeza Pro", "Noto Sans Arabic", "Noto Sans", ' +
    // Emoji — Windows · Apple · Android
    '"Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Segoe UI Symbol"';

// MỌI font của theme PHẢI nối SYSTEM_FONT_STACK vào đuôi. Font hiển thị
// (Orbitron, EB Garamond, Pangolin…) hầu hết KHÔNG có dấu tiếng Việt/CJK —
// mà pango chỉ mượn glyph từ font ĐỨNG SAU trong danh sách. Thiếu đuôi này
// thì "CHIP MỚI" render ra "CHIP M□I" (ô .notdef có mã hex).
// Bẫy: lỗi PHỤ THUỘC MÁY — font nào KHÔNG cài thì rơi về sans-serif nên
// trông vẫn đúng; máy có cài font đó mới vỡ. Đừng bỏ đuôi vì "máy tôi ổn".
const THEMES = {

    dark: {

        bgGrad: ['#0a0a1a', '#1a1030'],

        cardBg: 'rgba(255,255,255,0.06)', cardBorder: 'rgba(255,255,255,0.12)',

        titleColor: '#FFD700', textColor: '#F0F0F0', mutedColor: '#888',

        hlColor: '#FFD700', hlBg: 'rgba(255,215,0,0.15)',

        resultBg: 'rgba(0,255,136,0.1)', resultBorder: '#00FF88',

        eqBg: 'rgba(124,58,237,0.12)', eqBorder: 'rgba(167,139,250,0.4)',

        tipBg: 'rgba(251,191,36,0.1)', tipBorder: 'rgba(251,191,36,0.4)',

        progressBg: 'rgba(255,255,255,0.08)', progressFill: '#FFD700',

        geoBg: 'rgba(255,255,255,0.03)', geoBorder: 'rgba(255,255,255,0.1)',

        font: SYSTEM_FONT_STACK,

    },

    whiteboard: {

        bgGrad: ['#F5F0E8', '#E8E0D0'],

        cardBg: 'rgba(0,0,0,0.03)', cardBorder: 'rgba(0,0,0,0.1)',

        titleColor: '#1a1a1a', textColor: '#333', mutedColor: '#888',

        hlColor: '#E53E3E', hlBg: 'rgba(229,62,62,0.1)',

        resultBg: 'rgba(56,161,105,0.1)', resultBorder: '#38A169',

        eqBg: 'rgba(49,130,206,0.08)', eqBorder: 'rgba(49,130,206,0.3)',

        tipBg: 'rgba(237,137,54,0.1)', tipBorder: 'rgba(237,137,54,0.4)',

        progressBg: 'rgba(0,0,0,0.06)', progressFill: '#3182CE',

        geoBg: 'rgba(0,0,0,0.02)', geoBorder: 'rgba(0,0,0,0.08)',

        font: SYSTEM_FONT_STACK,

    },

    chalkboard: {

        bgGrad: ['#1a3528', '#2D4A3E'],

        cardBg: 'rgba(255,255,255,0.04)', cardBorder: 'rgba(255,255,255,0.1)',

        titleColor: '#FFFFFF', textColor: '#E0E0D0', mutedColor: '#8A8A7A',

        hlColor: '#FFE066', hlBg: 'rgba(255,224,102,0.12)',

        resultBg: 'rgba(255,224,102,0.1)', resultBorder: '#FFE066',

        eqBg: 'rgba(255,255,255,0.05)', eqBorder: 'rgba(255,255,255,0.15)',

        tipBg: 'rgba(144,238,144,0.1)', tipBorder: 'rgba(144,238,144,0.3)',

        progressBg: 'rgba(255,255,255,0.06)', progressFill: '#FFE066',

        geoBg: 'rgba(255,255,255,0.03)', geoBorder: 'rgba(255,255,255,0.08)',

        font: SYSTEM_FONT_STACK,

    },

};

let T = THEMES[themeName] || THEMES.dark;

// (nền tuỳ biến áp ở CUỐI, sau khi phong cách ghi đè bgGrad)

// ── Overwrite Theme & Font Family by Selected Art Style ────────────────

const artStyle = args.style || 'default';

global.artStyle = artStyle;

const STYLE_PALETTES = {

    cyberpunk: {

        bgGrad: ['#070714', '#0d0d29'],

        font: "'Orbitron', " + SYSTEM_FONT_STACK,

        titleColor: '#00ffff', textColor: '#f0f0f5', hlColor: '#ff007f', mutedColor: '#7a7a9a',

        greenColor: '#39ff14', redColor: '#ff073a', yellowColor: '#efff14', whiteColor: '#ffffff', cyanColor: '#00ffff',

    },

    watercolor: {

        bgGrad: ['#fcf8f2', '#f5eedc'],

        // EB Garamond CHƯA BAO GIỜ được bundle (static/fonts rỗng) → xưa nay
        // theme này rơi về font 'serif' chung chung của fontconfig, mà font đó
        // thiếu dấu tiếng Việt → "CHIP MỚI" ra "CHIP M□I". Nêu tên một font
        // serif CÓ THẬT và CÓ dấu (Times New Roman: Windows; Liberation/DejaVu:
        // Linux) để giữ đúng nét serif của phong cách MÀ chữ vẫn đọc được.
        font: "'EB Garamond', 'Times New Roman', 'Liberation Serif', 'DejaVu Serif', "
              + SYSTEM_FONT_STACK,

        titleColor: '#2c4c38', textColor: '#3a3532', hlColor: '#c85a53', mutedColor: '#8e8680',

        greenColor: '#6b8e23', redColor: '#b22222', yellowColor: '#daa520', whiteColor: '#fdfbf7', cyanColor: '#4682b4',

    },

    inkwash: {

        bgGrad: ['#efe9db', '#e4dcce'],

        font: "'YouthTouch', " + SYSTEM_FONT_STACK,

        titleColor: '#0e1111', textColor: '#2f3e46', hlColor: '#621708', mutedColor: '#6c757d',

        greenColor: '#2d4a22', redColor: '#800808', yellowColor: '#9b7a36', whiteColor: '#f5f2eb', cyanColor: '#4a5759',

    },

    pastel: {

        bgGrad: ['#fff5f5', '#f0e6ff'],

        font: "'Outfit', " + SYSTEM_FONT_STACK,

        titleColor: '#4a4e69', textColor: '#5c677d', hlColor: '#ffb5a7', mutedColor: '#9a8c98',

        greenColor: '#b5e2fa', redColor: '#ffcad4', yellowColor: '#ffe5ec', whiteColor: '#ffffff', cyanColor: '#b5f2ea',

    },

    // aurora — TÔNG SÁNG premium (mesh pastel + bokeh), mực TỐI tương phản cao.
    // Khác pastel: accent đậm rõ (đọc được trên nền sáng), whiteColor = mực tối
    // để rc('white') trong mọi cảnh tự thành chữ tối. Proxy light-style lo phần
    // còn lại (hạ card tối thành kính trắng, đổi màu chuỗi sáng thành tối).
    aurora: {

        bgGrad: ['#fdfdff', '#edf0fb'],

        font: "'Outfit', " + SYSTEM_FONT_STACK,

        // LƯU Ý: mực KHÔNG được trùng các hex slate trong isDarkColor
        // (#0f172a, #1a1a2e...) — chúng bị remap thành kính trắng (dành cho
        // CARD bg của cảnh tối). Dùng navy khác: #152238 / #223154.
        titleColor: '#152238', textColor: '#223154', hlColor: '#1d4ed8', mutedColor: '#57627a',

        greenColor: '#15803d', redColor: '#dc2626', yellowColor: '#b45309', whiteColor: '#152238', cyanColor: '#0e7490',

    },

    // Math Noir: đen tuyền + nét trắng mảnh kiểu manim/3Blue1Brown — toán
    // học tối giản, hình tự vẽ nét (template math_noir, cảnh mn_*).
    mathnoir: {

        bgGrad: ['#060607', '#0b0b0d'],

        font: "'Segoe UI', " + SYSTEM_FONT_STACK,

        titleColor: '#e8e8ea', textColor: '#c9c9ce', hlColor: '#facc15', mutedColor: '#8b8b92',

        greenColor: '#4ade80', redColor: '#f87171', yellowColor: '#facc15', whiteColor: '#e8e8ea', cyanColor: '#60a5fa',

    },

    // Codex Sacra: cổ thư mực-ấm gần-đen + nét khắc vellum + accent song nhiệt
    // độ (amber ấm ↔ cold/oxblood lạnh) — tài liệu Kinh Thánh (template
    // codex_sacra, cảnh cx_*). Cảnh cx_ tự quản màu (hardcode rgba) nên KHÔNG
    // đưa vào isLightStyle; bake ở đây để preview/desktop có nền mực-ấm (client
    // vẫn nhận qua engine_palettes.codex OTA — cùng giá trị nên merge idempotent).
    codex: {

        bgGrad: ['#17110B', '#0E0C0A'],

        font: "'Segoe UI', " + SYSTEM_FONT_STACK,

        titleColor: '#E7D8B4', textColor: '#E7D8B4', hlColor: '#D4A24C', mutedColor: '#6E655A',

        greenColor: '#5C7C9A', redColor: '#8B3A2F', yellowColor: '#D4A24C', whiteColor: '#E7D8B4', cyanColor: '#5C7C9A',

    },

    // Giấy ấm bình luận: nền kem ấm + lưới nhạt + glow cam nhẹ — bình luận
    // công nghệ kiểu poster giấy (template paper_explainer). Cảnh wp_* tự
    // quản màu — KHÔNG đưa vào isLightStyle (proxy remap sẽ phá card trắng).
    warmpaper: {

        bgGrad: ['#fdf8f0', '#f6e9d5'],

        font: "'Segoe UI', " + SYSTEM_FONT_STACK,

        titleColor: '#211a12', textColor: '#3d362c', hlColor: '#e8590c', mutedColor: '#a4917a',

        greenColor: '#2f9e44', redColor: '#d9480f', yellowColor: '#e8590c', whiteColor: '#211a12', cyanColor: '#1c7ed6',

    },

    // Mổ xẻ công nghệ: than chì + lưới chéo mờ + vignette — chuyên đề
    // giải thích kỹ thuật kiểu editorial (template tech_explainer).
    techdark: {

        bgGrad: ['#0a0d10', '#12171c'],

        font: "'Segoe UI', " + SYSTEM_FONT_STACK,

        titleColor: '#f5f7f9', textColor: '#e7ebef', hlColor: '#fbbf24', mutedColor: '#9aa3ad',

        greenColor: '#34d399', redColor: '#f87171', yellowColor: '#fbbf24', whiteColor: '#f5f7f9', cyanColor: '#22d3ee',

    },

    // Editorial Cream: nền cream/beige ấm + infographic tối giản cam/đen —
    // phong cách giải thích khái niệm tối giản kiểu Substack/editorial motion.
    // (template editorial_cream — scenes ec_*)
    editcream: {

        bgGrad: ['#ECEAE4', '#E3E0D8'],

        // Font mặc định = Be Vietnam Pro (geometric sans đậm, đủ dấu Việt) —
        // giống video mẫu editorial. KHÔNG để 'Segoe UI' đứng đầu: Segoe có
        // trên desktop nên sẽ NUỐT fallback, BVP không bao giờ được dùng.
        // SYSTEM_FONT_STACK mở đầu bằng "Be Vietnam Pro", sans-serif → chuẩn.
        font: SYSTEM_FONT_STACK,

        titleColor: '#1A1A1A', textColor: '#1A1A1A', hlColor: '#E8440A', mutedColor: '#888580',

        greenColor: '#2C7A3B', redColor: '#C4380A', yellowColor: '#E8440A', whiteColor: '#ECEAE4', cyanColor: '#1c7ed6',

    },

    // Bản Tin AI (ai_briefing — scenes ab_*): nền xanh-đen tech, hub grid 6 thẻ
    // viền neon + hexagon trung tâm, waveform, thanh tiến độ. Ngang 16:9 kiểu
    // "AI weekly briefing". Accent xanh sáng #4da3ff.
    aibrief: {

        bgGrad: ['#0e1830', '#1a2543'],

        font: SYSTEM_FONT_STACK,

        titleColor: '#f4f8ff', textColor: '#cbd6ee', hlColor: '#4da3ff', mutedColor: '#8394b8',

        greenColor: '#4ade80', redColor: '#fb7185', yellowColor: '#fbbf24', whiteColor: '#f4f8ff', cyanColor: '#4da3ff',

    },

    // Japan Social: giấy washi nhạt ấm + mực đen mềm + accent đỏ-cam Nhật.
    // Kênh giải thích TÂM LÝ XÃ HỘI NHẬT (honne/tatemae, kuuki, enryo...) —
    // nhân vật chibi PNG (kho chibi-learning) là hero mỗi step, quanh nó là
    // chú thích nét mảnh. KHÔNG card/panel: trang giấy CHÍNH LÀ nền.
    // Font: SYSTEM_FONT_STACK thuần — KHÔNG để 'Segoe UI' đứng đầu (Segoe có
    // sẵn trên desktop sẽ NUỐT fallback, Be Vietnam Pro không bao giờ dùng tới;
    // bài học từ editcream). (template japan_social)
    jpsocial: {

        bgGrad: ['#F5F1EA', '#EBE5DA'],

        font: SYSTEM_FONT_STACK,

        // mutedColor ĐẬM HƠN bản đầu (#8A8378): màu cũ chỉ đạt tương phản 2.99
        // trên đầu tối của gradient washi — DƯỚI chuẩn đọc WCAG 4.5, và đó
        // chính là dòng phụ dưới tiêu đề mà người dùng báo "chữ mờ khó đọc".
        // #68625A giữ NGUYÊN hue 37° và độ bão hoà 7% của màu cũ (vẫn đúng tông
        // giấy washi ấm), chỉ hạ độ sáng 51%→38% → đạt 4.81.
        titleColor: '#2B2B2B', textColor: '#2B2B2B', hlColor: '#C8452F', mutedColor: '#68625A',

        greenColor: '#4F7A52', redColor: '#C8452F', yellowColor: '#D9A441', whiteColor: '#F5F1EA', cyanColor: '#3B6E8F',

    },

    // Green Guide ("Cẩm nang Xanh"): giấy kem ô ly + thẻ trắng bo góc + accent
    // xanh lá — cẩm nang sống xanh, mascot "Mầm" (template green_guide, cảnh
    // gg_*). Cảnh gg_ tự quản màu (hardcode hex trong GG_KIT) nên KHÔNG đưa vào
    // isLightStyle (proxy remap sẽ phá thẻ trắng, đúng bài học editcream/
    // warmpaper); bake ở đây để nền + phụ đề + tiêu đề đúng tông trên desktop
    // (client web/mobile nhận CÙNG bảng này qua engine_palettes.greenguide OTA
    // — cùng giá trị nên merge idempotent).
    // Không nêu font riêng: SYSTEM_FONT_STACK thuần (GG_KIT vẽ chữ qua alias
    // 'sans-serif' → proxy sang T.font, luật Pango).
    greenguide: {

        bgGrad: ['#F7F7F2', '#F1EFE3'],

        font: SYSTEM_FONT_STACK,

        titleColor: '#113622', textColor: '#1A1A1A', hlColor: '#456B33', mutedColor: '#9AA096',

        greenColor: '#456B33', redColor: '#C4380A', yellowColor: '#D9A441', whiteColor: '#FDFDFD', cyanColor: '#113622',

    },

    // Algo Grid: lưới mini-animation thuật toán neon trên nền đen (template
    // algo_grid, cảnh ag_*). Cảnh ag_ tự quản màu (hardcode hex trong AG_KIT)
    // — style tối nên không liên quan isLightStyle; bake ở đây để nền + phụ đề
    // + tiêu đề đúng tông (client web/mobile nhận CÙNG bảng này qua
    // engine_palettes.algogrid OTA — cùng giá trị nên merge idempotent).
    // Không nêu font riêng: AG_KIT vẽ chữ qua alias 'sans-serif' (luật Pango).
    algogrid: {

        bgGrad: ['#060606', '#060606'],

        font: SYSTEM_FONT_STACK,

        titleColor: '#FFFFFF', textColor: '#EAEAEA', hlColor: '#2CE871', mutedColor: '#8A8F98',

        greenColor: '#35E08C', redColor: '#E85D5D', yellowColor: '#F5C93B', whiteColor: '#FFFFFF', cyanColor: '#3FD6E8',

    },

    // Sys Grid: HUD terminal mạng/hệ thống trên nền vũ trụ tối có sao li ti
    // (template sys_grid, cảnh sg_*). Cảnh sg_ tự quản màu (hardcode hex
    // trong SG_KIT) — bake ở đây để nền + phụ đề + tiêu đề đúng tông (client
    // web/mobile nhận CÙNG bảng này qua engine_palettes.sysgrid OTA — cùng
    // giá trị nên merge idempotent). Không nêu font riêng: SG_KIT vẽ chữ qua
    // alias 'sans-serif'/'monospace' (luật Pango).
    sysgrid: {

        bgGrad: ['#05070D', '#05070D'],

        font: SYSTEM_FONT_STACK,

        titleColor: '#FFFFFF', textColor: '#EAEDF2', hlColor: '#F5D34B', mutedColor: '#8A93A6',

        greenColor: '#2EE6A8', redColor: '#E85D5D', yellowColor: '#F5D34B', whiteColor: '#FFFFFF', cyanColor: '#3FD6E8',

    },

    // Code Lab: bảng xếp hạng pattern thuật toán — hàng tối #0A0A0E trên nền
    // gần đen, code syntax mono + huy hiệu Big-O theo thang độ phức tạp
    // (template code_lab, cảnh cd_*). Cảnh cd_ tự quản màu (hardcode hex
    // trong CD_KIT) — bake ở đây để nền + phụ đề + tiêu đề đúng tông (client
    // web/mobile nhận CÙNG bảng này qua engine_palettes.codelab OTA — cùng
    // giá trị nên merge idempotent). Không nêu font riêng: CD_KIT vẽ chữ qua
    // alias 'sans-serif'/'monospace' (luật Pango).
    codelab: {

        bgGrad: ['#050507', '#050507'],

        font: SYSTEM_FONT_STACK,

        titleColor: '#FFFFFF', textColor: '#E8EAF2', hlColor: '#04B4FC', mutedColor: '#8A93A6',

        greenColor: '#30BE80', redColor: '#E85D5D', yellowColor: '#E4AC3C', whiteColor: '#FFFFFF', cyanColor: '#4CBCEC',

    },

    // Phác thảo neon: nền đen ánh rêu + lưới blueprint, nhân vật que neon vẽ
    // tay, panel terminal viền mảnh + label mono in hoa. (template neon_sketch)
    neonsketch: {

        bgGrad: ['#060a04', '#0c1207'],

        font: "'Arial Black', 'Segoe UI', " + SYSTEM_FONT_STACK,

        titleColor: '#f2f7ec', textColor: '#dbe5d0', hlColor: '#fde047', mutedColor: '#93a58a',

        greenColor: '#a3e635', redColor: '#f87171', yellowColor: '#fde047', whiteColor: '#f2f7ec', cyanColor: '#38bdf8',

    },

    pixel: {

        bgGrad: ['#05010f', '#1a0820'],

        font: "Orbitron, 'JetBrains Mono', " + SYSTEM_FONT_STACK,

        titleColor: '#00ffff', textColor: '#e0f7ff', hlColor: '#ff00aa', mutedColor: '#7a5a9a',

        greenColor: '#00ff00', redColor: '#ff0000', yellowColor: '#ffff00', whiteColor: '#ffffff', cyanColor: '#00ffff',

    },

    sketch: {

        bgGrad: ['#ffffff', '#f0f0f0'],

        font: "Pangolin, " + SYSTEM_FONT_STACK,

        titleColor: '#000000', textColor: '#1c1c1c', hlColor: '#4b5563', mutedColor: '#9ca3af',

        greenColor: '#374151', redColor: '#111827', yellowColor: '#4b5563', whiteColor: '#ffffff', cyanColor: '#1f2937',

    },

    sketchnote: {

        bgGrad: ['#fcfbfa', '#f7f5f0'],

        font: "Pangolin, " + SYSTEM_FONT_STACK,

        titleColor: '#1e3a8a', textColor: '#1e293b', hlColor: '#ea580c', mutedColor: '#64748b',

        greenColor: '#16a34a', redColor: '#dc2626', yellowColor: '#f59e0b', whiteColor: '#fcfbfa', cyanColor: '#2563eb',

    },

    cartoon: {

        bgGrad: ['#ffdf00', '#ff4b5c'],

        font: "'Fredoka', " + SYSTEM_FONT_STACK,

        titleColor: '#000000', textColor: '#ffffff', hlColor: '#00d2fc', mutedColor: '#1d2d50',

        greenColor: '#00e676', redColor: '#ff1744', yellowColor: '#ffea00', whiteColor: '#ffffff', cyanColor: '#00e5ff',

    },

    liquidglass: {

        bgGrad: ['#05070d', '#0d1424'],

        font: SYSTEM_FONT_STACK,

        titleColor: '#ffffff', textColor: '#e8edf5', hlColor: '#ff5a47', mutedColor: '#8a94a8',

        greenColor: '#34d399', redColor: '#ff5a47', yellowColor: '#fbbf24', whiteColor: '#ffffff', cyanColor: '#60d4ff',

        glass: {

            cardBg: 'rgba(255,255,255,0.055)', cardBorder: 'rgba(255,255,255,0.22)',

            hlBg: 'rgba(255,90,71,0.14)',

            resultBg: 'rgba(255,255,255,0.06)', resultBorder: 'rgba(255,255,255,0.28)',

            eqBg: 'rgba(96,212,255,0.10)', eqBorder: 'rgba(96,212,255,0.32)',

            tipBg: 'rgba(52,211,153,0.10)', tipBorder: 'rgba(52,211,153,0.32)',

            progressBg: 'rgba(255,255,255,0.08)', progressFill: '#ff5a47',

            geoBg: 'rgba(255,255,255,0.04)', geoBorder: 'rgba(255,255,255,0.14)',

        },

    }

};

// ── Đường B: palette OTA từ pack.json ─────────────────────────────────
// App có thể đặt globalThis.__T2_PALETTES = { <art_style>: {bgGrad, màu…} }
// TRƯỚC khi nạp engine → theme MỚI đến thẳng từ kho template (pack.json),
// KHÔNG cần build lại app. Merge TỪNG theme (không thay nguyên object) vì
// palette trong JSON cố ý KHÔNG mang `font` (JSON không chở được biểu thức
// SYSTEM_FONT_STACK) — thay nguyên object là `pal.font` bên dưới thành
// undefined và T.font vỡ. Theme mới hoàn toàn mà thiếu font → rơi về
// SYSTEM_FONT_STACK. Máy không đặt global (desktop node, app cũ) → khối
// này no-op → hành vi y hệt cũ, từng pixel.
if (typeof globalThis !== 'undefined' && globalThis.__T2_PALETTES
        && typeof globalThis.__T2_PALETTES === 'object') {

    Object.keys(globalThis.__T2_PALETTES).forEach(function (ten) {

        const palOta = globalThis.__T2_PALETTES[ten];

        if (!palOta || typeof palOta !== 'object') return;

        // Object.assign bỏ qua source undefined → theme chưa có sẵn vẫn ổn.
        STYLE_PALETTES[ten] = Object.assign({}, STYLE_PALETTES[ten], palOta);

        if (!STYLE_PALETTES[ten].font) STYLE_PALETTES[ten].font = SYSTEM_FONT_STACK;

    });

}

if (artStyle !== 'default' && STYLE_PALETTES[artStyle]) {

    const pal = STYLE_PALETTES[artStyle];

    T = Object.assign({}, T, {

        bgGrad: pal.bgGrad,

        font: pal.font,

        titleColor: pal.titleColor,

        textColor: pal.textColor,

        hlColor: pal.hlColor,

        mutedColor: pal.mutedColor

    });

    // Apply accent colors (used by rc()) when the palette defines them

    ['greenColor','redColor','yellowColor','whiteColor','cyanColor'].forEach(function(k){

        if (pal[k]) T[k] = pal[k];

    });

    // Glassmorphism: override card/box surfaces and enable frosted rendering

    if (pal.glass) {

        T = Object.assign({}, T, pal.glass);

        T.glassEffect = true;

    }

}

// ── User overrides: màu tiêu đề / font / màu chữ (thắng cả theme lẫn style) ──
// Ưu tiên CLI arg, fallback biến môi trường (T2_*) do render_service set.
const _ovTitle = args['title-color'] || process.env.T2_TITLE_COLOR || '';
const _ovText  = args['text-color']  || process.env.T2_TEXT_COLOR  || '';
const _ovFont  = args['font']        || process.env.T2_FONT        || '';
if (_ovTitle && String(_ovTitle).trim()) {
    T = Object.assign({}, T, { titleColor: _ovTitle, hlColor: _ovTitle });
}
if (_ovText && String(_ovText).trim()) {
    T = Object.assign({}, T, { textColor: _ovText });
}
// MỐC "người dùng CHỦ ĐỘNG chọn font" (tab Phong cách → font_family → --font).
// KHÁC với T.font sẵn của theme/style (Orbitron, Pangolin…): những cái đó là
// diện mạo GỐC của mẫu, ui.* KHÔNG được đụng (đổi = vỡ golden). CHỈ khi user
// chọn font mới bật cờ này → ui.* (makeUiKit) mới ưu tiên T.font thay cho
// SYSTEM_FONT_STACK cứng. Vắng --font → cờ = false → ui.* y HỆT HEAD (pixel-identical).
let USER_FONT_OVERRIDE = false;
if (_ovFont && String(_ovFont).trim()) {
    T = Object.assign({}, T, { font: _ovFont });
    USER_FONT_OVERRIDE = true;
}

// ── PHỤ ĐỀ (subtitle) ─────────────────────────────────────────────────
//   --subtitle '{"enabled":true,"preset":"capcut_bold","fontScale":1.0,
//                "yPct":null,"maxLines":null}'      (null = theo preset)
// Fallback env T2_SUBTITLE: video_encoder dựng lệnh node ở 4 chỗ khác nhau,
// set env một lần là mọi worker chunk đều nhận (giống T2_TITLE_COLOR/T2_BG_*).
// Không có / enabled=false → KHÔNG vẽ gì (đúng hành vi cũ).
const _subRaw = (typeof args['subtitle'] === 'string' ? args['subtitle'] : '') ||
    process.env.T2_SUBTITLE || '';
let SUB_CFG = null;
if (_subRaw && String(_subRaw).trim()) {
    try {
        const c = JSON.parse(String(_subRaw));
        if (c && c.enabled) SUB_CFG = c;
    } catch (e) {
        process.stderr.write(`[Subtitle] --subtitle không phải JSON hợp lệ: ${e.message}\n`);
    }
}

// ── Ghi đè NỀN (sau phong cách → thắng bgGrad của phong cách) ──────────
if (customBgGrad.length >= 2) {
    T = Object.assign({}, T, { bgGrad: [customBgGrad[0], customBgGrad[1]] });
} else if (customBgGrad.length === 1) {
    T = Object.assign({}, T, { bgGrad: [customBgGrad[0], customBgGrad[0]] });
} else if (customBgColor && String(customBgColor).trim()) {
    T = Object.assign({}, T, { bgGrad: [customBgColor, customBgColor] });
}

global.glassEffect = !!T.glassEffect;

let createCanvas, loadImage, registerFont, NodeImage;

// ── Fix: enable custom & system fonts under node-canvas/Pango on Windows ──
// Pango on Windows defaults to the win32 backend which IGNORES registerFont(),
// causing "couldn't load font ... falling back to Sans" and breaking Vietnamese
// diacritics. Force the fontconfig backend and provide a config pointing at our
// bundled fonts + the Windows system fonts so every family resolves correctly.
(function setupFontconfig() {
    try {
        if (process.platform !== 'win32') return;
        const os = require('os');
        const staticAbs = path.resolve(path.join(__dirname, '..', 'static')).replace(/\\/g, '/');
        const winFonts = (process.env.WINDIR ? process.env.WINDIR.replace(/\\/g, '/') : 'C:/Windows') + '/Fonts';
        const cacheDir = path.join(os.tmpdir(), 'edu_fontconfig_cache');
        try { fs.mkdirSync(cacheDir, { recursive: true }); } catch (e) {}
        const cacheAbs = cacheDir.replace(/\\/g, '/');
        const confXml = '<?xml version="1.0"?>\n' +
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n' +
            '<fontconfig>\n' +
            '  <dir>' + staticAbs + '</dir>\n' +
            '  <dir>' + winFonts + '</dir>\n' +
            '  <cachedir>' + cacheAbs + '</cachedir>\n' +
            '  <alias><family>sans-serif</family><prefer><family>Be Vietnam Pro</family><family>Arial</family><family>Segoe UI</family><family>Tahoma</family></prefer></alias>\n' +
            '  <alias><family>serif</family><prefer><family>Times New Roman</family><family>Georgia</family></prefer></alias>\n' +
            '  <alias><family>monospace</family><prefer><family>Consolas</family><family>Courier New</family></prefer></alias>\n' +
            '</fontconfig>\n';
        const confPath = path.join(cacheDir, 'fonts.conf');
        fs.writeFileSync(confPath, confXml, 'utf8');
        process.env.PANGOCAIRO_BACKEND = 'fc';
        process.env.FONTCONFIG_FILE = confPath;
        process.env.FONTCONFIG_PATH = cacheDir;
    } catch (e) {
        process.stderr.write('[Renderer] Fontconfig setup skipped: ' + e.message + '\n');
    }
})();

try { ({ createCanvas, loadImage, registerFont, Image: NodeImage } = require('canvas')); } catch(e) {

    try { ({ createCanvas, loadImage, registerFont, Image: NodeImage } = require(path.join(process.env.NODE_PATH||'','canvas'))); } catch(e2) {

        console.log(JSON.stringify({status:'error',message:'canvas not installed'}));

        process.exit(1);

    }

}

// ══ TẦNG HOST ═══════════════════════════════════════════════════════
// Mọi thứ renderer cần từ NỀN TẢNG (không phải từ canvas API) đi qua đây.
// Node cắm nodeHost; trình duyệt và QuickJS (mobile) sẽ cắm host của chúng —
// mà KHÔNG phải sửa một dòng code vẽ nào. Xem engines/host.js.
const HOST = (BOOT && BOOT.host) || require('./host.js').nodeHost({
    canvas: { createCanvas, loadImage, registerFont },
    fs: fs, path: path, https: require('https'),
});

// ── Register Youth Touch demo font for Ink Wash Calligraphy style ───

if (registerFont) {

    const fontPath = path.join(__dirname, '..', 'static', 'YouthTouch.ttf');

    if (fs.existsSync(fontPath)) {

        HOST.registerFont(fontPath, 'YouthTouch');

        process.stderr.write(`[Renderer] Registered font family: YouthTouch\n`);

    } else {

        process.stderr.write(`[Renderer] Font file not found at: ${fontPath}\n`);

    }

    // Register Be Vietnam Pro — primary UI font (full Vietnamese diacritics)
    const bvpWeights = [["Regular", "normal"], ["SemiBold", "600"], ["Bold", "bold"]];
    for (const [w, weight] of bvpWeights) {
        const bvpPath = path.join(__dirname, '..', 'static', `BeVietnamPro-${w}.ttf`);
        if (HOST.exists(bvpPath)) {
            HOST.registerFont(bvpPath, 'Be Vietnam Pro', weight);
        }
    }

    // Register Pangolin handwriting font for Sketchnote style

    const pangolinPath = path.join(__dirname, '..', 'static', 'Pangolin-Regular.ttf');

    if (fs.existsSync(pangolinPath)) {

        HOST.registerFont(pangolinPath, 'Pangolin', 'normal');

        HOST.registerFont(pangolinPath, 'Pangolin', 'bold');

        process.stderr.write(`[Renderer] Registered font family: Pangolin\n`);

    }

    // Font người dùng thêm (data/fonts.json) — do core/fonts.py ghi
    try {
        const manifest = path.join(__dirname, '..', 'data', 'fonts.json');
        if (fs.existsSync(manifest)) {
            const list = JSON.parse(fs.readFileSync(manifest, 'utf8'));
            for (const it of (Array.isArray(list) ? list : [])) {
                if (it && it.file && it.family && fs.existsSync(it.file)) {
                    try {
                        HOST.registerFont(it.file, it.family);
                        process.stderr.write(`[Renderer] Registered user font: ${it.family}\n`);
                    } catch (e) {
                        process.stderr.write(`[Renderer] Font register failed ${it.family}: ${e.message}\n`);
                    }
                }
            }
        }
    } catch (e) {
        process.stderr.write(`[Renderer] User fonts skipped: ${e.message}\n`);
    }

}

// ── Outro logo bản FREE (TCLogo — engines/tubecraft_logo.js) ─────────────
// Cảnh outro do render_service (Python) append (step clear:false) gọi
// global.tcOutroDraw qua custom_js. Yêu cầu 29/07: outro phải LIỀN MẠCH với
// video, không "tách thành video riêng" — nền theme phẳng KHÔNG đủ vì các
// template (Codex Sacra...) tự vẽ nền riêng trong cảnh. Cách làm:
//   1. Khung outro SỚM NHẤT từng thấy: canvas còn nguyên CẢNH CUỐI của video
//      (step không clear) → CHỤP lại làm backdrop. An toàn với worker render
//      theo chunk: mọi đường replay đều đi qua chính hàm này theo t tăng dần.
//   2. Mỗi khung: vẽ lại backdrop (đè sạch khung trước — không ghosting) +
//      màn scrim tối/sáng THEO ĐỘ SÁNG THẬT của backdrop hiện dần + logo.
//   3. Vẫn vẽ qua ctx Proxy → font 'sans-serif' tự thành T.font, màu được
//      style hoá đúng như mọi cảnh khác. Accent URL: sáng → indigo brand,
//      tối → màu nhấn của theme (T.hlColor).
// Browser (mobile preview) chưa có require → try/catch nuốt, outro chỉ
// hiện ở bản xuất desktop (mobile làm riêng khi sync TCLogo sang t2app).
let _tcLogoMod = null, _tcBd = null, _tcBdT = Infinity;
global.tcOutroDraw = function (dstCtx, w, h, t) {
    try {
        // Browser (t2app): tubecraft_logo.js nạp bằng <script> thường → UMD đặt
        // window.TCLogo; Node (desktop): require cạnh file. Thử global TRƯỚC —
        // nhánh require đụng path/__dirname không tồn tại trong WebView.
        if (!_tcLogoMod)
            _tcLogoMod = (typeof TCLogo !== 'undefined' && TCLogo)
                || require(path.join(__dirname, 'tubecraft_logo.js'));
        const cv = dstCtx.canvas;
        const cw = cv.width, ch = cv.height;
        if (!_tcBd || t < _tcBdT) {
            _tcBdT = t;
            _tcBd = HOST.createCanvas(cw, ch);
            const bctx = _tcBd.getContext('2d');
            bctx.drawImage(cv, 0, 0);
            // Độ sáng trung bình (lấy mẫu thưa, bước cố định → tất định)
            const d = bctx.getImageData(0, 0, cw, ch).data;
            let s = 0, n = 0;
            for (let i = 0; i < d.length; i += 4 * 1009) {
                s += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
                n++;
            }
            _tcBd._light = (s / Math.max(1, n)) > 140;
        }
        const P = _tcLogoMod.PALETTE;
        const light = _tcBd._light;
        // wrapColor: Proxy art style can thiệp MỌI fillStyle dạng CHUỖI
        // (grayscale/translucent ở phong cách sáng) → scrim + màu endcard bị
        // nuốt (đo 29/07: watercolor mất sạch scrim). Bọc màu vào
        // CanvasGradient hằng màu thì proxy cho đi xuyên — màu outro chính
        // xác tuyệt đối mà font vẫn được proxy thay theo T.font.
        if (!global.__tcWrapCache) global.__tcWrapCache = new Map();
        const wrapColor = (css) => {
            let g = global.__tcWrapCache.get(css);
            if (!g) {
                g = dstCtx.createLinearGradient(0, 0, 1, 0);
                g.addColorStop(0, css);
                g.addColorStop(1, css);
                global.__tcWrapCache.set(css, g);
            }
            return g;
        };
        dstCtx.save();
        dstCtx.setTransform(1, 0, 0, 1, 0, 0);
        dstCtx.globalAlpha = 1;
        dstCtx.drawImage(_tcBd, 0, 0);
        const sa = Math.min(1, t / 0.14);          // scrim hiện dần — không cắt gắt
        dstCtx.fillStyle = wrapColor(light
            ? 'rgba(249,250,253,' + (0.90 * sa).toFixed(4) + ')'
            : 'rgba(6,9,20,' + (0.88 * sa).toFixed(4) + ')');
        dstCtx.fillRect(0, 0, cw, ch);
        _tcLogoMod.drawOutro(dstCtx, {
            w: cw, h: ch, t: t,
            font: 'sans-serif', weight: '700', faux: 0.018,
            bg: 'none', fadeIn: false, wrapColor: wrapColor,
            ink: light ? P.ink : P.inkDark,
            muted: light ? P.slate : P.slateDark,
            accent: light ? P.indigo : ((T && T.hlColor) || P.cyan),
        });
        dstCtx.restore();
    } catch (e) { /* outro không được phép làm hỏng render chính */ }
};

// Canvas đích: trình duyệt bơm thẳng canvas của trang vào (vẽ trực tiếp lên
// màn hình, không qua ảnh trung gian) — chính là cách xem trước có tua.
// Cỡ THẬT của khung ảnh xuất ra (pixel). Bên gọi qua BOOT tự tạo canvas nên
// nhận nguyên xi — nó tự lo cỡ (trình duyệt bơm canvas của trang vào).
const CW = Math.round(W * RSCALE), CH = Math.round(H * RSCALE);
const canvas = (BOOT && BOOT.canvas) || HOST.createCanvas(CW, CH);
const _ctx0 = canvas.getContext('2d');

// ── MEMOIZE measureText — nút thắt SỐ MỘT đo được của render chữ ─────────
// Bisect thực nghiệm 29/07 (script Nefilim, cx_verse): khung ĐO-không-VẼ chậm
// y hệt khung vẽ đủ ⇒ fillText vô tội, measureText chiếm ~250ms/khung (cảnh
// small-caps đo TỪNG KÝ TỰ + vòng autoshrink đo lại cả khối mỗi lần hạ cỡ,
// hàng nghìn lượt/khung — mỗi lượt xuống Pango/Cairo là syscall, profile thấy
// 44% ntdll). Metrics CHỈ phụ thuộc (font, chuỗi) — hai thứ lặp gần như 100%
// giữa các khung ⇒ cache Map trả về ĐÚNG object TextMetrics đã đo lần đầu.
// An toàn: cùng font + cùng chuỗi luôn cho cùng metrics (không phụ thuộc
// transform/baseline/fillStyle). Chặn trần 50k entry — tràn thì xoá làm mới
// (tiến trình render sống theo lượt/chunk, thực tế chỉ vài nghìn khoá).
{
    // Tra PROTOTYPE ĐỘNG lúc gọi, KHÔNG bind cứng lúc cài: phía dưới file còn
    // một lượt thay measureText trên prototype (bản đo CÔNG THỨC toán cho
    // mn_/vl_) — bind cứng ở đây là instance property che mất bản đó ⇒ đo
    // công thức sai. Proto method cũng thuần theo (font, chuỗi) nên cache
    // luôn cả kết quả công thức là an toàn.
    const _mtProto = Object.getPrototypeOf(_ctx0);
    const _mtCache = new Map();
    _ctx0.measureText = function (text) {
        const key = this.font + '|' + text;
        let m = _mtCache.get(key);
        if (m === undefined) {
            if (_mtCache.size > 50000) _mtCache.clear();
            m = _mtProto.measureText.call(this, text);
            _mtCache.set(key, m);
        }
        return m;
    };
}

// ══ GIÁN ĐIỆP TẠM (bật bằng env T2_SPY=<file>) ══════════════════════
// Đo BỀ MẶT canvas API mà renderer thật sự dùng — để thiết kế display list
// theo SỰ THẬT, không theo phỏng đoán. Không đổi hành vi: mọi lệnh vẫn được
// chuyển tiếp xuống ctx thật, nên ảnh render ra y hệt.
// ── DISPLAY LIST (T2_DL=1) ───────────────────────────────────────────
// ctx trở thành BỘ GHI LỆNH thay vì vẽ thẳng. Cuối mỗi khung, danh sách được
// PHÁT LẠI lên canvas thật. Ảnh phải giống HỆT bản vẽ thẳng — đó là bằng chứng
// display list ghi ĐỦ mọi lệnh. Xem docs/display-list.md.
let ctx = _ctx0;
let DL_REC = null;
if (process.env.T2_DL) {
    const { RecordingContext, playDisplayList } = require('./display_list.js');
    // Bộ đo chữ phải là canvas RIÊNG, tuyệt đối KHÔNG dùng canvas đích:
    // node-canvas trả về CÙNG một ctx cho mọi lần getContext('2d'), nên đo chữ
    // sẽ ghi đè ctx.font của canvas đích → phát lại bị nhiễm trạng thái.
    // (Kích thước không ảnh hưởng phép đo chữ.)
    // Trên mobile chỗ này gọi ngược sang Flutter TextPainter — cầu nối hai chiều.
    const _mc = HOST.createCanvas(8, 8);
    // CW/CH = bề mặt THẬT mà danh sách lệnh sẽ được phát lại lên (bộ vẽ Flutter
    // đọc số này để cấp buffer). Bản thân các lệnh vẫn mang toạ độ LOGIC — lệnh
    // setTransform(RSCALE…) đầu khung nằm sẵn trong danh sách nên phát lại tự
    // phóng đúng. (_mc 8×8 chỉ để ĐO CHỮ, cỡ không liên quan.)
    DL_REC = new RecordingContext(CW, CH, _mc.getContext('2d'), _mc.constructor);
    DL_REC._play = playDisplayList;
    ctx = DL_REC;
}
const NOT_OP_SPY = new Set(['measureText', 'createLinearGradient', 'createRadialGradient']);
function sane(x) {
    if (x && typeof x === 'object') return '<' + (x.constructor ? x.constructor.name : '?') + '>';
    return x;
}
if (process.env.T2_SPY_OPS) {
    global.__T2_OPS = [];
    process.on('exit', function () {
        try { require('fs').writeFileSync(process.env.T2_SPY_OPS, JSON.stringify(global.__T2_OPS)); } catch (e) { }
    });
}
if (process.env.T2_SPY || process.env.T2_SPY_OPS) {
    const hits = { call: {}, set: {}, get: {} };
    const bump = function (k, n) { hits[k][n] = (hits[k][n] || 0) + 1; };
    ctx = new Proxy(_ctx0, {
        get: function (t, k) {
            const v = t[k];
            if (typeof v === 'function') {
                return function () {
                    bump('call', String(k));
                    if (global.__T2_OPS && !NOT_OP_SPY.has(String(k))) {
                        global.__T2_OPS.push([String(k)].concat(
                            Array.prototype.slice.call(arguments).map(sane)));
                    }
                    if (k === 'drawImage' && arguments[0]) {
                        hits.val = hits.val || {};
                        var src = arguments[0].constructor ? arguments[0].constructor.name : '?';
                        hits.val['drawImage_src_' + src] = (hits.val['drawImage_src_' + src] || 0) + 1;
                    }
                    return v.apply(t, arguments);
                };
            }
            if (typeof k === 'string') bump('get', k);
            return v;
        },
        set: function (t, k, v) {
            bump('set', String(k));
            if (global.__T2_OPS) global.__T2_OPS.push(['=', String(k), sane(v)]);
            // GIÁ TRỊ của filter/composite quyết định có port sang Flutter được không
            if (k === 'filter' || k === 'globalCompositeOperation') {
                hits.val = hits.val || {};
                var key = k + '=' + String(v);
                hits.val[key] = (hits.val[key] || 0) + 1;
            }
            if ((k === 'fillStyle' || k === 'strokeStyle') && typeof v === 'object') {
                hits.val = hits.val || {};
                hits.val['GRADIENT_as_' + k] = (hits.val['GRADIENT_as_' + k] || 0) + 1;
            }
            t[k] = v; return true;
        }
    });
    process.on('exit', function () {
        try { require('fs').appendFileSync(process.env.T2_SPY, JSON.stringify(hits) + String.fromCharCode(10)); }
        catch (e) { }
    });
}

// ── Icon thay cho emoji ──────────────────────────────────────────────
// KHÔNG còn tải Twemoji. Emoji trong kịch bản được vẽ bằng icon Lucide
// (EMOJI_TO_LUCIDE + drawLucide), xem global.drawEmoji bên dưới.
// Gỡ Twemoji cũng gỡ luôn: phụ thuộc CDN lúc render, đua ghi cache giữa các
// worker song song, ~2 giây khởi động, và cho phép render OFFLINE.

// ── drawEmoji global helper ─────────────────────────────

/**
 * Vẽ MỘT ICON tại vị trí emoji — KHÔNG dùng emoji màu nữa.
 *
 * Trước đây: tải PNG Twemoji từ CDN → hình cartoon nhiều màu, lệch hẳn tông
 * nét mảnh premium của template (user chốt 2026-07-14: "thay bằng bộ icon
 * tương thích", "bỏ emoji").
 *
 * Bỏ Twemoji còn gỡ được bốn thứ cùng lúc:
 *   • hết phụ thuộc CDN LÚC RENDER (một socket chết của CDN từng treo cả lượt)
 *   • hết đua ghi cùng file cache giữa các worker song song
 *   • hết ~2 giây khởi động cho khâu nạp emoji
 *   • render được OFFLINE
 *
 * Thứ tự: icon Lucide (nét mảnh, ăn màu hiện tại) → nếu không có ánh xạ thì vẽ
 * ký tự đó bằng font, ĐƠN SẮC theo màu hiện tại (vẫn giữ nghĩa, vẫn đúng tông).
 */
global.drawEmoji = function (ctx, emoji, x, y, size) {
    if (!emoji) return;
    const key = String(emoji).replace(/️/g, '');   // bỏ VS16

    const luc = EMOJI_TO_LUCIDE[emoji] || EMOJI_TO_LUCIDE[key];
    if (luc && typeof drawLucide === 'function') {
        // Màu icon = fillStyle hiện tại nếu là màu thuần; không thì trắng ngà.
        const cur = (typeof ctx.fillStyle === 'string') ? ctx.fillStyle : '';
        if (drawLucide(ctx, luc, x, y, size * 0.92, cur || 'rgba(255,255,255,0.95)')) return;
    }

    // ══════════════════════════════════════════════════════════════════════
    //  KHÔNG CÓ ICON LUCIDE → VẼ RỖNG. TUYỆT ĐỐI KHÔNG fillText(emoji).
    //
    //  ĐÂY LÀ "CÁI Ô VUÔNG HIỆN NGẪU NHIÊN KHẮP MÀN HÌNH" mà user báo.
    //
    //  Trước đây nhánh này vẽ ký tự emoji bằng `fillText(key)` với
    //  SYSTEM_FONT_STACK — mà stack đó KHÔNG có font emoji màu. Nên mọi emoji
    //  KHÔNG nằm trong EMOJI_TO_LUCIDE (🖼, 💨, 📱, 📲, 🖥️, 🎮, 📷, …) render ra
    //  Ô VUÔNG TOFU (□). 🖼 tệ nhất: glyph khung-ảnh của nó trông y hệt một ô bo
    //  góc rỗng. AI rải các emoji này ở header/caption/badge tuỳ cảnh → cái ô
    //  "nhấp nháy khắp nơi, template nào cũng có".
    //
    //  User đã chốt 2026-07-14: CHỈ DÙNG ICON LUCIDE, BỎ EMOJI. Nên emoji không
    //  có icon thì im lặng bỏ qua — một khoảng trống nhỏ tốt hơn một ô vuông vô
    //  nghĩa đè lên tiêu đề. Muốn có icon thì THÊM ánh xạ vào EMOJI_TO_LUCIDE
    //  (và icon đó phải tồn tại trong lucide_icons.js), KHÔNG mở lại fillText.
    // ══════════════════════════════════════════════════════════════════════
};

// ── getElementCoords offline helper ─────────────────────────────

function getElementCoords(el, fallbackY) {

    let x = null, y = null, isAbsolute = false;

    if (aspect_ratio === '16:9') {

        if (el.x_16_9 !== undefined && el.y_16_9 !== undefined) {

            x = el.x_16_9 * W; y = el.y_16_9 * H; isAbsolute = true;

        } else if (el.x !== undefined && el.y !== undefined) {

            x = el.x * W; y = el.y * H; isAbsolute = true;

        }

    } else {

        if (el.x_9_16 !== undefined && el.y_9_16 !== undefined) {

            x = el.x_9_16 * W; y = el.y_9_16 * H; isAbsolute = true;

        } else if (el.x !== undefined && el.y !== undefined) {

            x = el.x * W; y = el.y * H; isAbsolute = true;

        }

    }

    if (isAbsolute) {

        return { x, y, isAbsolute: true };

    } else {

        const tx = el.align === 'center' ? W/2 : el.align === 'right' ? W-MX : MX;

        return { x: tx, y: fallbackY, isAbsolute: false };

    }

}

// ── Path2D Polyfill for node-canvas ─────────────────────────────

if (typeof global.Path2D === 'undefined') {

    global.Path2D = class Path2D {

        constructor(pathStr) {

            this.commands = [];

            if (!pathStr) return;

            const tokenRegex = /([MmLlHhVvCcSsQqTtAaZz])|(-?\d*\.?\d+(?:[eE][-+]?\d+)?)/g;

            let match;

            let currentCmd = null;

            let currentArgs = [];

            while ((match = tokenRegex.exec(pathStr)) !== null) {

                if (match[1]) {

                    if (currentCmd) {

                        this.commands.push({ cmd: currentCmd, args: currentArgs });

                    }

                    currentCmd = match[1];

                    currentArgs = [];

                } else if (match[2]) {

                    currentArgs.push(parseFloat(match[2]));

                }

            }

            if (currentCmd) {

                this.commands.push({ cmd: currentCmd, args: currentArgs });

            }

        }

    };

    function applyPathToContext(c, path) {

        c.beginPath();

        let cx = 0, cy = 0;

        let startX = 0, startY = 0;

        for (const item of path.commands) {

            let { cmd, args } = item;

            let argIdx = 0;

            const nextArgs = (count) => {

                if (argIdx + count > args.length) return null;

                const slice = args.slice(argIdx, argIdx + count);

                argIdx += count;

                return slice;

            };

            do {

                if (cmd === 'M' || cmd === 'm') {

                    const pt = nextArgs(2);

                    if (!pt) break;

                    if (cmd === 'm') {

                        cx += pt[0];

                        cy += pt[1];

                    } else {

                        cx = pt[0];

                        cy = pt[1];

                    }

                    c.moveTo(cx, cy);

                    startX = cx;

                    startY = cy;

                    cmd = (cmd === 'm') ? 'l' : 'L';

                } else if (cmd === 'L' || cmd === 'l') {

                    const pt = nextArgs(2);

                    if (!pt) break;

                    if (cmd === 'l') {

                        cx += pt[0];

                        cy += pt[1];

                    } else {

                        cx = pt[0];

                        cy = pt[1];

                    }

                    c.lineTo(cx, cy);

                } else if (cmd === 'H' || cmd === 'h') {

                    const xVal = nextArgs(1);

                    if (!xVal) break;

                    if (cmd === 'h') {

                        cx += xVal[0];

                    } else {

                        cx = xVal[0];

                    }

                    c.lineTo(cx, cy);

                } else if (cmd === 'V' || cmd === 'v') {

                    const yVal = nextArgs(1);

                    if (!yVal) break;

                    if (cmd === 'v') {

                        cy += yVal[0];

                    } else {

                        cy = yVal[0];

                    }

                    c.lineTo(cx, cy);

                } else if (cmd === 'C' || cmd === 'c') {

                    const pts = nextArgs(6);

                    if (!pts) break;

                    let cp1x, cp1y, cp2x, cp2y, destx, desty;

                    if (cmd === 'c') {

                        cp1x = cx + pts[0]; cp1y = cy + pts[1];

                        cp2x = cx + pts[2]; cp2y = cy + pts[3];

                        destx = cx + pts[4]; desty = cy + pts[5];

                    } else {

                        cp1x = pts[0]; cp1y = pts[1];

                        cp2x = pts[2]; cp2y = pts[3];

                        destx = pts[4]; desty = pts[5];

                    }

                    c.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, destx, desty);

                    cx = destx;

                    cy = desty;

                } else if (cmd === 'Q' || cmd === 'q') {

                    const pts = nextArgs(4);

                    if (!pts) break;

                    let cpx, cpy, destx, desty;

                    if (cmd === 'q') {

                        cpx = cx + pts[0]; cpy = cy + pts[1];

                        destx = cx + pts[2]; desty = cy + pts[3];

                    } else {

                        cpx = pts[0]; cpy = pts[1];

                        destx = pts[2]; desty = pts[3];

                    }

                    c.quadraticCurveTo(cpx, cpy, destx, desty);

                    cx = destx;

                    cy = desty;

                } else if (cmd === 'Z' || cmd === 'z') {

                    c.closePath();

                    cx = startX;

                    cy = startY;

                    break;

                } else {

                    break;

                }

            } while (argIdx < args.length);

        }

    }

    const canvasPrototype = ctx.constructor.prototype;

    const originalFill = canvasPrototype.fill;

    const originalStroke = canvasPrototype.stroke;

    canvasPrototype.fill = function(arg1, arg2) {

        if (arg1 instanceof global.Path2D) {

            applyPathToContext(this, arg1);

            return originalFill.call(this, arg2);

        }

        return originalFill.apply(this, arguments);

    };

    canvasPrototype.stroke = function(arg1) {

        if (arg1 instanceof global.Path2D) {

            applyPathToContext(this, arg1);

            return originalStroke.call(this);

        }

        return originalStroke.apply(this, arguments);

    };

}

// ── Global Emoji Rendering Optimization for node-canvas ──────────

const canvasPrototype = ctx.constructor.prototype;

const originalFillText = canvasPrototype.fillText || ctx.fillText;
const originalMeasureText = canvasPrototype.measureText || ctx.measureText;

// ── TYPESET CÔNG THỨC MỘT DÒNG (căn thức + chỉ số trên/dưới) ────────────────
//  Cảnh (vl_congthuc/mn_formula/al_*) vẽ công thức bằng ctx.fillText nên KHÔNG
//  đi qua typesetter đầy đủ. Ở đây tự layout: √(nhóm) → căn thật (móc vector +
//  vinculum, bỏ ngoặc ngoài); _x/^x (đơn hoặc {…}) → chỉ số nhỏ hạ/nâng. Đo và
//  vẽ DÙNG CHUNG _mathRun nên override cả measureText → cảnh đo = render, layout
//  (căn giữa/clip/accent/underline) KHÔNG lệch. GÁC CHẶT bằng _isFormula để
//  chữ thường (tên kênh my_lab…) không bị đụng.
function _mathBaseY(y, fs, bl) {
    if (bl === 'top') return y + fs * 0.78;
    if (bl === 'middle') return y + fs * 0.30;
    if (bl === 'bottom') return y - fs * 0.02;
    return y;                                   // alphabetic
}

function _isFormula(s) {
    if (s.indexOf('√') >= 0) return true;
    // BIẾN CÓ CHỈ SỐ: (ranh giới) 1 chữ/số + _/^ + chữ/số — bắt 'E_k','X_C','v_0'
    // nhưng KHÔNG bắt gạch dưới GIỮA TỪ ('my_lab' → base 'y' không ở ranh giới).
    if (/(?:^|[\s=+\-−·×÷/(,])[A-Za-z0-9][_^][A-Za-z0-9{]/.test(s)) return true;
    // PHÂN SỐ có operand NGOẶC: ')/' hoặc '/(' | '/√' — né đơn vị 'm/s' (không ngoặc)
    if (/\)\s*\/|\/\s*[(√]/.test(s)) return true;
    // PHÂN SỐ đơn giản 'a / b' — CÓ khoảng trắng 2 bên '/' VÀ có '=' (là phương
    // trình). Đơn vị 'm/s'/'kg·m/s' dính liền (không space) → KHÔNG dính.
    if (/\s\/\s/.test(s) && s.indexOf('=') >= 0) return true;
    return false;
}

// Bỏ CẶP ngoặc ngoài nếu chúng ôm trọn (fraction operand không cần ngoặc — gạch
// phân số làm nhiệm vụ nhóm).
function _stripOuterParens(s) {
    s = s.trim();
    if (s.length >= 2 && s[0] === '(' && s[s.length - 1] === ')') {
        let d = 0;
        for (let i = 0; i < s.length; i++) {
            if (s[i] === '(') d++;
            else if (s[i] === ')') { d--; if (d === 0 && i < s.length - 1) return s; }  // đóng sớm → không phải ngoặc ngoài
        }
        return s.slice(1, -1);
    }
    return s;
}
// Atom TRƯỚC index e (tử số): nhóm ')...(' hoặc run tới ranh giới toán tử/space.
function _atomBack(str, e) {
    if (e <= 0) return e;
    if (str[e - 1] === ')') {
        let d = 1, i = e - 2;
        while (i >= 0 && d > 0) { if (str[i] === ')') d++; else if (str[i] === '(') d--; i--; }
        return i + 1;
    }
    let i = e - 1;
    while (i >= 0 && '=+−-·×÷/∝≈≤≥<>(, '.indexOf(str[i]) < 0) i--;
    return i + 1;
}
// Atom SAU index s (mẫu số): nhóm '(...)', √(...) hoặc run tới ranh giới.
function _atomFwd(str, s) {
    if (s >= str.length) return s;
    if (str[s] === '(') { let d = 1, i = s + 1; while (i < str.length && d > 0) { if (str[i] === '(') d++; else if (str[i] === ')') d--; i++; } return i; }
    if (str[s] === '√' && str[s + 1] === '(') { let d = 1, i = s + 2; while (i < str.length && d > 0) { if (str[i] === '(') d++; else if (str[i] === ')') d--; i++; } return i; }
    let i = s;
    while (i < str.length && '=+−·×÷/∝≈≤≥<>), '.indexOf(str[i]) < 0) i++;
    return i;
}

// draw=false → chỉ đo (trả bề rộng); `ext` (nếu truyền) nhận {asc,desc} = chiều
// cao TRÊN/DƯỚI baseline (để căn/phân số tự nong theo nội dung). draw=true → vẽ
// tại baseline yb (alphabetic).
function _mathRun(ctx, str, x, yb, fs, draw, ext) {
    const fullFont = ctx.font;
    const smallFont = fullFont.replace(/(\d+(?:\.\d+)?)px/, function (m, n) { return (parseFloat(n) * 0.72) + 'px'; });
    const RUN = /[0-9A-Za-z.²³]/;
    function measW(t) { return originalMeasureText.call(ctx, t).width; }
    let asc = 0, desc = 0;
    function grow(a, d) { if (a > asc) asc = a; if (d > desc) desc = d; }
    function done(w) { if (ext) { ext.asc = asc; ext.desc = desc; } return w; }

    // ── (0) PHÂN SỐ: '/' top-level có tử+mẫu → xếp CHỒNG (tử / gạch / mẫu) ──
    //  Chuẩn quốc tế: tử trên, mẫu dưới, gạch ngang giữa (bỏ ngoặc operand). Chỉ
    //  vào đây với chuỗi công thức (đơn vị m/s bị _isFormula chặn ngoài).
    {
        let depth = 0;
        for (let k = 0; k < str.length; k++) {
            const c = str[k];
            if (c === '(') depth++;
            else if (c === ')') depth--;
            else if (c === '/' && depth === 0) {
                let ne = k; while (ne > 0 && str[ne - 1] === ' ') ne--;
                const ns = _atomBack(str, ne);
                let ds = k + 1; while (ds < str.length && str[ds] === ' ') ds++;
                const de = _atomFwd(str, ds);
                if (ne > ns && de > ds) {
                    const prefix = str.slice(0, ns);
                    const numStr = _stripOuterParens(str.slice(ns, ne));
                    const denStr = _stripOuterParens(str.slice(ds, de));
                    const suffix = str.slice(de);
                    const nfs = fs * 0.86;
                    const ndFont = fullFont.replace(/(\d+(?:\.\d+)?)px/, function (m, n) { return (parseFloat(n) * 0.86) + 'px'; });
                    const eP = {}, eN = {}, eD = {}, eS = {};
                    const wPrefix = _mathRun(ctx, prefix, 0, 0, fs, false, eP);
                    ctx.font = ndFont;
                    const wNum = _mathRun(ctx, numStr, 0, 0, nfs, false, eN);
                    const wDen = _mathRun(ctx, denStr, 0, 0, nfs, false, eD);
                    ctx.font = fullFont;
                    const fracW = Math.max(wNum, wDen) + fs * 0.30;
                    const wSuffix = _mathRun(ctx, suffix, 0, 0, fs, false, eS);
                    // gạch tại −0.30fs; tử/mẫu đặt theo CHIỀU CAO THẬT của chúng
                    // (đáy tử / đỉnh mẫu cách gạch đúng `gap`) — mẫu có căn/mũ cao
                    // sẽ tự đẩy xuống, KHÔNG dính vào gạch.
                    const barRel = -fs * 0.30, gap = fs * 0.14;
                    const numBase = barRel - gap - eN.desc, denBase = barRel + gap + eD.asc;
                    grow(-numBase + eN.asc, denBase + eD.desc);   // chiều cao phân số
                    grow(eP.asc, eP.desc); grow(eS.asc, eS.desc); // prefix/suffix
                    if (draw) {
                        let dx = x;
                        _mathRun(ctx, prefix, dx, yb, fs, true);
                        dx += wPrefix;
                        ctx.font = ndFont;
                        _mathRun(ctx, numStr, dx + (fracW - wNum) / 2, yb + numBase, nfs, true);
                        _mathRun(ctx, denStr, dx + (fracW - wDen) / 2, yb + denBase, nfs, true);
                        ctx.font = fullFont;
                        ctx.save();
                        ctx.strokeStyle = ctx.fillStyle;
                        ctx.lineWidth = Math.max(1.8, fs * 0.05);
                        ctx.lineCap = 'round';
                        ctx.beginPath();
                        ctx.moveTo(dx + fs * 0.04, yb - fs * 0.30);
                        ctx.lineTo(dx + fracW - fs * 0.04, yb - fs * 0.30);
                        ctx.stroke();
                        ctx.restore();
                        dx += fracW;
                        _mathRun(ctx, suffix, dx, yb, fs, true);
                    }
                    return done(wPrefix + fracW + wSuffix);
                }
            }
        }
    }

    let cx = x, i = 0, buf = '';
    function flush() {
        if (!buf) return;
        if (draw) { const sb = ctx.textBaseline; ctx.textBaseline = 'alphabetic'; originalFillText.call(ctx, buf, cx, yb); ctx.textBaseline = sb; }
        grow(fs * 0.72, fs * 0.20);
        cx += measW(buf); buf = '';
    }
    while (i < str.length) {
        const ch = str[i];
        // (A) CĂN √(nhóm) → móc vector CAO BẰNG radicand + vinculum, BỎ ngoặc ngoài
        if (ch === '√' && str[i + 1] === '(') {
            let d = 1, j = i + 2;
            while (j < str.length && d > 0) { const c = str[j]; if (c === '(') d++; else if (c === ')') d--; j++; }
            if (d === 0) {
                flush();
                const rad = str.slice(i + 2, j - 1);
                const eR = {};
                const radW = _mathRun(ctx, rad, 0, 0, fs, false, eR);
                const rAsc = Math.max(eR.asc, fs * 0.70), rDesc = Math.max(eR.desc, 0);
                const topA = rAsc + fs * 0.16;                       // vinculum trên baseline
                const hookW = Math.max(fs * 0.5, (topA + rDesc) * 0.42);
                grow(topA, rDesc);
                if (draw) {
                    const top = yb - topA;                          // đỉnh (vinculum)
                    const bot = yb + rDesc + fs * 0.02;             // đáy chữ V
                    const mid = yb - fs * 0.06;
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(cx + hookW * 0.04, mid);
                    ctx.lineTo(cx + hookW * 0.26, (mid + bot) / 2);
                    ctx.lineTo(cx + hookW * 0.50, bot);
                    ctx.lineTo(cx + hookW * 0.88, top);
                    ctx.lineTo(cx + hookW + radW + fs * 0.08, top);
                    ctx.strokeStyle = ctx.fillStyle;
                    ctx.lineWidth = Math.max(1.8, fs * 0.06);
                    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
                    ctx.stroke();
                    ctx.restore();
                    _mathRun(ctx, rad, cx + hookW, yb, fs, true);
                }
                cx += hookW + radW;
                i = j;
                continue;
            }
        }
        // (B) CĂN √ + run (không ngoặc) → glyph √ + thanh ngang trên run
        if (ch === '√' && str[i + 1] && (RUN.test(str[i + 1]) || str[i + 1] === '-' || str[i + 1] === '+')) {
            flush();
            let j = i + 1;
            if (str[j] === '+' || str[j] === '-') j++;
            while (j < str.length && RUN.test(str[j])) j++;
            const run = str.slice(i, j);
            grow(fs * 0.86, fs * 0.20);
            if (draw) {
                const sb = ctx.textBaseline; ctx.textBaseline = 'alphabetic';
                originalFillText.call(ctx, run, cx, yb);
                ctx.textBaseline = sb;
                const by = yb - fs * 0.76;
                ctx.save();
                ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = Math.max(1.6, fs * 0.05); ctx.lineCap = 'butt';
                ctx.beginPath();
                ctx.moveTo(cx + measW('√') - fs * 0.05, by);
                ctx.lineTo(cx + measW(run) + fs * 0.04, by);
                ctx.stroke();
                ctx.restore();
            }
            cx += measW(run);
            i = j;
            continue;
        }
        // (C) CHỈ SỐ _x/^x (đơn hoặc {…}) → nhỏ, hạ/nâng
        if ((ch === '_' || ch === '^') && i + 1 < str.length && str[i + 1] !== ' ') {
            flush();
            const sup = ch === '^';
            let content, ni;
            if (str[i + 1] === '{') { let j = i + 2; while (j < str.length && str[j] !== '}') j++; content = str.slice(i + 2, j); ni = (j < str.length) ? j + 1 : j; }
            else { content = str[i + 1]; ni = i + 2; }
            ctx.font = smallFont;
            const cw = originalMeasureText.call(ctx, content).width;
            ctx.font = fullFont;
            if (sup) grow(fs * 0.92, fs * 0.20); else grow(fs * 0.72, fs * 0.38);
            if (draw) { const sb = ctx.textBaseline; ctx.textBaseline = 'alphabetic'; ctx.font = smallFont; originalFillText.call(ctx, content, cx, yb + (sup ? -fs * 0.42 : fs * 0.20)); ctx.font = fullFont; ctx.textBaseline = sb; }
            cx += cw;
            i = ni;
            continue;
        }
        buf += ch; i++;
    }
    flush();
    return done(cx - x);
}

// measureText: chuỗi công thức → bề rộng THEO layout (để cảnh đo khớp render).
canvasPrototype.measureText = function (text) {
    if (text != null && !this._isDrawingEmoji) {
        const s = String(text);
        if (_isFormula(s)) {
            let _fs = 24; const m = this.font.match(/(\d+(?:\.\d+)?)px/); if (m) _fs = parseFloat(m[1]);
            const w = _mathRun(this, s, 0, 0, _fs, false);
            const base = originalMeasureText.call(this, s);
            return {
                width: w,
                actualBoundingBoxAscent: base.actualBoundingBoxAscent,
                actualBoundingBoxDescent: base.actualBoundingBoxDescent,
                actualBoundingBoxLeft: base.actualBoundingBoxLeft,
                actualBoundingBoxRight: base.actualBoundingBoxRight,
                fontBoundingBoxAscent: base.fontBoundingBoxAscent,
                fontBoundingBoxDescent: base.fontBoundingBoxDescent,
            };
        }
    }
    return originalMeasureText.apply(this, arguments);
};

canvasPrototype.fillText = function(text, x, y, maxWidth) {
    if (this._isDrawingEmoji) {
        return originalFillText.apply(this, arguments);
    }
    if (text) {
        const str = String(text);
        const isEmoji = /[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]/.test(str);
        if (isEmoji) {
            this.save();

            // Resolve a bright, solid color from transparent styles
            let currentFill = this.fillStyle;
            let solidColor = '#ffffff';

            if (typeof currentFill === 'string') {
                currentFill = currentFill.trim();
                if (currentFill.startsWith('#')) {
                    if (currentFill.length === 9) {
                        solidColor = currentFill.slice(0, 7); // #RRGGBBAA -> #RRGGBB
                    } else {
                        solidColor = currentFill;
                    }
                } else if (currentFill.startsWith('rgba')) {
                    const match = currentFill.match(/rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)/);
                    if (match) {
                        const r = parseInt(match[1]), g = parseInt(match[2]), b = parseInt(match[3]);
                        if (r < 65 && g < 65 && b < 65) {
                            solidColor = '#ffffff'; // Fallback if current fill is dark/background color
                        } else {
                            solidColor = `rgb(${r},${g},${b})`;
                        }
                    }
                } else if (currentFill.startsWith('rgb')) {
                    solidColor = currentFill;
                }
            }
            // Split string into text and emoji segments
            const emojiRegex = /([\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF])/g;
            const parts = str.split(emojiRegex);
            const totalWidth = this.measureText(str).width;

            const align = this.textAlign || 'left';
            const baseline = this.textBaseline || 'alphabetic';

            let startX = x;
            if (align === 'center') {
                startX = x - totalWidth / 2;
            } else if (align === 'right') {
                startX = x - totalWidth;
            }

            let fontSize = 24;
            const fontMatch = this.font.match(/(\d+)px/);
            if (fontMatch) {
                fontSize = parseInt(fontMatch[1]);
            }

            let emojiY = y;
            if (baseline === 'top') {
                emojiY = y + fontSize / 2;
            } else if (baseline === 'bottom') {
                emojiY = y - fontSize / 2;
            } else if (baseline === 'middle') {
                emojiY = y;
            } else {
                emojiY = y - fontSize * 0.35;
            }

            let currentX = startX;
            this._isDrawingEmoji = true;
            try {
                for (const part of parts) {
                    if (!part) continue;
                    const isPartEmoji = /[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]/.test(part);
                    const partWidth = this.measureText(part).width;
                    if (isPartEmoji) {
                        if (global.drawEmoji) {
                            global.drawEmoji(this, part, currentX + partWidth / 2, emojiY, fontSize * 1.1);
                        } else {
                            originalFillText.call(this, part, currentX, y);
                        }
                    } else {
                        this.save();
                        this.textAlign = 'left';
                        this.textBaseline = baseline;
                        originalFillText.call(this, part, currentX, y);
                        this.restore();
                    }
                    currentX += partWidth;
                }
            } finally {
                this._isDrawingEmoji = false;
            }

            this.restore();

            return;

        }

        // ── CÔNG THỨC (căn thức + chỉ số) ──────────────────────────────────
        //  Chuỗi "giống công thức" (_isFormula) → layout riêng qua _mathRun:
        //  √(nhóm) thành căn thật (móc vector + vinculum, bỏ ngoặc ngoài), _x/^x
        //  thành chỉ số dưới/trên. measureText cũng đi qua _mathRun nên bề rộng
        //  ĐO = VẼ → căn giữa/clip/accent/underline của cảnh không lệch.
        if (_isFormula(str)) {
            let _fs = 24; const _fm = this.font.match(/(\d+(?:\.\d+)?)px/); if (_fm) _fs = parseFloat(_fm[1]);
            const _al = this.textAlign || 'left';
            const _bl = this.textBaseline || 'alphabetic';
            const _tot = _mathRun(this, str, 0, 0, _fs, false);
            let _sx = x;
            if (_al === 'center') _sx = x - _tot / 2; else if (_al === 'right') _sx = x - _tot;
            const _yb = _mathBaseY(y, _fs, _bl);
            this.save();
            this.textAlign = 'left';
            _mathRun(this, str, _sx, _yb, _fs, true);
            this.restore();
            return;
        }

    }

    return originalFillText.apply(this, arguments);

};

// ── Drawing helpers ─────────────────────────────────────────────

function drawBg() {

    const g = ctx.createLinearGradient(0, 0, W, H);

    g.addColorStop(0, T.bgGrad[0]); g.addColorStop(1, T.bgGrad[1]);

    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

    // Cyberpunk pixel ambience for the 'pixel' art style — neon grid + horizon + scanlines.

    // Chữ giữ nét căng vì chỉ vẽ ở lớp nền, không động vào font hay text layer.

    // --bg-fx off: nền phẳng (bỏ lưới/sao/quả cầu của phong cách)
    if (global.bgFxOff) return;

    // Mathnoir: grain phấn TĨNH + vignette — bake sẵn MỘT LẦN vào layer
    // offscreen (getMathnoirBgFxCanvas), mỗi frame chỉ 1 drawImage → máy yếu OK.
    // Grain hash tất định theo (x,y), KHÔNG Math.random — worker chunk nào
    // render cũng ra đúng từng pixel, và không nhấp nháy theo frame.
    if (global.artStyle === 'mathnoir') {
        ctx.drawImage(getMathnoirBgFxCanvas(), 0, 0, W, H);
    }

    if (global.artStyle === 'pixel') {

        const horizonY = H * 0.62;

        // Sun-like glow at horizon

        const sunGrad = ctx.createRadialGradient(W/2, horizonY, 0, W/2, horizonY, W * 0.55);

        sunGrad.addColorStop(0, 'rgba(255, 0, 170, 0.22)');

        sunGrad.addColorStop(0.4, 'rgba(120, 0, 200, 0.10)');

        sunGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');

        ctx.fillStyle = sunGrad;

        ctx.fillRect(0, 0, W, H);

        // Perspective neon grid below horizon

        ctx.save();

        ctx.strokeStyle = 'rgba(255, 0, 170, 0.18)';

        ctx.lineWidth = 1.5;

        // Vertical lines converging to vanishing point (W/2, horizonY)

        const cols = 24;

        for (let i = 0; i <= cols; i++) {

            const x = (i / cols) * W;

            ctx.beginPath();

            ctx.moveTo(W/2, horizonY);

            ctx.lineTo(x, H);

            ctx.stroke();

        }

        // Horizontal rows getting denser toward horizon

        ctx.strokeStyle = 'rgba(0, 255, 255, 0.18)';

        for (let r = 1; r <= 14; r++) {

            const t = r / 14;

            const y = horizonY + Math.pow(t, 1.7) * (H - horizonY);

            ctx.beginPath();

            ctx.moveTo(0, y);

            ctx.lineTo(W, y);

            ctx.stroke();

        }

        // Stars above horizon

        for (let i = 0; i < 60; i++) {

            const sx = (i * 73) % W;

            const sy = (i * 41) % horizonY;

            const a = 0.3 + 0.5 * (((i * 17) % 100) / 100);

            ctx.fillStyle = `rgba(${i % 3 === 0 ? '255,255,255' : '160,200,255'},${a * 0.5})`;

            ctx.fillRect(sx, sy, 2, 2);

        }

        // Soft scanlines overlay (Optimized with Offscreen Canvas)
        ctx.drawImage(getPixelScanlinesCanvas(), 0, 0, W, H);

        ctx.restore();

    }

    if (global.artStyle === 'liquidglass') {
        const t = typeof currentFrameTime !== 'undefined' ? currentFrameTime : 0;
        ctx.save();

        // 1. Draw thin background alignment grid
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.035)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        // Vertical center line
        ctx.moveTo(W / 2, 0);
        ctx.lineTo(W / 2, H);
        // Horizontal center line
        ctx.moveTo(0, H / 2);
        ctx.lineTo(W, H / 2);
        ctx.stroke();

        // Draw general grid lines
        ctx.beginPath();
        for (let x = W / 10; x < W; x += W / 10) {
            if (Math.abs(x - W/2) < 2) continue;
            ctx.moveTo(x, 0);
            ctx.lineTo(x, H);
        }
        for (let y = H / 20; y < H; y += H / 20) {
            if (Math.abs(y - H/2) < 2) continue;
            ctx.moveTo(0, y);
            ctx.lineTo(W, y);
        }
        ctx.stroke();

        // 2. Draw 4 floating blurred neon orbs (radial gradients)
        // Orb 1: Teal/Cyan
        const o1x = W * 0.25 + Math.sin(t * 0.3) * 60;
        const o1y = H * 0.3 + Math.cos(t * 0.25) * 60;
        const o1r = W * 0.55;
        const og1 = ctx.createRadialGradient(o1x, o1y, 0, o1x, o1y, o1r);
        og1.addColorStop(0, 'rgba(6, 182, 212, 0.15)');
        og1.addColorStop(1, 'rgba(6, 182, 212, 0)');
        ctx.fillStyle = og1;
        ctx.beginPath();
        ctx.arc(o1x, o1y, o1r, 0, Math.PI * 2);
        ctx.fill();

        // Orb 2: Purple/Violet
        const o2x = W * 0.8 + Math.cos(t * 0.2) * 80;
        const o2y = H * 0.2 + Math.sin(t * 0.35) * 80;
        const o2r = W * 0.65;
        const og2 = ctx.createRadialGradient(o2x, o2y, 0, o2x, o2y, o2r);
        og2.addColorStop(0, 'rgba(168, 85, 247, 0.13)');
        og2.addColorStop(1, 'rgba(168, 85, 247, 0)');
        ctx.fillStyle = og2;
        ctx.beginPath();
        ctx.arc(o2x, o2y, o2r, 0, Math.PI * 2);
        ctx.fill();

        // Orb 3: Green/Emerald
        const o3x = W * 0.3 + Math.sin(t * 0.25) * 70;
        const o3y = H * 0.75 + Math.cos(t * 0.3) * 70;
        const o3r = W * 0.6;
        const og3 = ctx.createRadialGradient(o3x, o3y, 0, o3x, o3y, o3r);
        og3.addColorStop(0, 'rgba(52, 211, 153, 0.12)');
        og3.addColorStop(1, 'rgba(52, 211, 153, 0)');
        ctx.fillStyle = og3;
        ctx.beginPath();
        ctx.arc(o3x, o3y, o3r, 0, Math.PI * 2);
        ctx.fill();

        // Orb 4: Soft Pink/Rose
        const o4x = W * 0.7 + Math.cos(t * 0.3) * 60;
        const o4y = H * 0.8 + Math.sin(t * 0.2) * 60;
        const o4r = W * 0.5;
        const og4 = ctx.createRadialGradient(o4x, o4y, 0, o4x, o4y, o4r);
        og4.addColorStop(0, 'rgba(251, 113, 133, 0.10)');
        og4.addColorStop(1, 'rgba(251, 113, 133, 0)');
        ctx.fillStyle = og4;
        ctx.beginPath();
        ctx.arc(o4x, o4y, o4r, 0, Math.PI * 2);
        ctx.fill();

        // 3. Draw scattered tiny twinkling background stars/particles
        for (let i = 0; i < 40; i++) {
            const sx = (i * 113) % W;
            const sy = (i * 79) % H;
            const size = 1 + (i % 2);
            const twinkle = 0.3 + 0.7 * Math.sin(t * (0.8 + (i % 3) * 0.4) + i);
            ctx.fillStyle = `rgba(255, 255, 255, ${twinkle * 0.35})`;
            ctx.fillRect(sx, sy, size, size);
        }

        ctx.restore();
    }

    ctx.globalAlpha = 1;

}

// ── Background removal via color-keying ──────────────────────

const _bgRemovalCache = {};

function removeImageBackground(img, cacheKey) {

    // Cache by explicit key to avoid reprocessing every frame

    const key = cacheKey || img.src || '';

    if (_bgRemovalCache[key]) return _bgRemovalCache[key];

    try {

        const sw = img.width, sh = img.height;

        if (sw <= 0 || sh <= 0) return img; // safety check

        // CỐ Ý KHÔNG nhân RSCALE: canvas này bám cỡ GỐC của ẢNH BITMAP để lọc
        // nền theo từng pixel nguồn. Phóng nó lên chỉ nội suy thêm pixel bịa —
        // không có chi tiết nào để cứu, mà còn làm hỏng phép dò màu bốn góc.
        // (Ảnh bitmap là thứ DUY NHẤT không nét thêm ở 4K — xem ghi chú RSCALE.)
        const tmpCanvas = HOST.createCanvas(sw, sh);

        const tmpCtx = tmpCanvas.getContext('2d');

        tmpCtx.drawImage(img, 0, 0);

        const imgData = tmpCtx.getImageData(0, 0, sw, sh);

        const d = imgData.data;

        // Sample corners (5x5 blocks) to detect background color

        const samples = [];

        const S = 5;

        const corners = [

            [0, 0], [sw - S, 0],

            [0, sh - S], [sw - S, sh - S],

        ];

        for (const [cx, cy] of corners) {

            for (let y = Math.max(0, cy); y < Math.min(cy + S, sh); y++) {

                for (let x = Math.max(0, cx); x < Math.min(cx + S, sw); x++) {

                    const i = (y * sw + x) * 4;

                    samples.push([d[i], d[i+1], d[i+2]]);

                }

            }

        }

        if (samples.length === 0) return img;

        let bgR = 0, bgG = 0, bgB = 0;

        for (const [r, g, b] of samples) { bgR += r; bgG += g; bgB += b; }

        bgR = Math.round(bgR / samples.length);

        bgG = Math.round(bgG / samples.length);

        bgB = Math.round(bgB / samples.length);

        const TOLERANCE = 48, FADE_RANGE = 20;

        for (let i = 0; i < d.length; i += 4) {

            const dr = d[i] - bgR, dg = d[i+1] - bgG, db = d[i+2] - bgB;

            const dist = Math.sqrt(dr*dr + dg*dg + db*db);

            if (dist < TOLERANCE) { d[i+3] = 0; }

            else if (dist < TOLERANCE + FADE_RANGE) {

                d[i+3] = Math.round(((dist - TOLERANCE) / FADE_RANGE) * d[i+3]);

            }

        }

        tmpCtx.putImageData(imgData, 0, 0);

        _bgRemovalCache[key] = tmpCanvas;

        return tmpCanvas;

    } catch(e) {

        process.stderr.write(`[Renderer] removeImageBackground error: ${e.message}\n`);

        return img; // fallback to original

    }

}

function roundRect(x, y, w, h, r) {

    ctx.beginPath();

    ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y);

    ctx.arcTo(x+w, y, x+w, y+r, r); ctx.lineTo(x+w, y+h-r);

    ctx.arcTo(x+w, y+h, x+w-r, y+h, r); ctx.lineTo(x+r, y+h);

    ctx.arcTo(x, y+h, x, y+h-r, r); ctx.lineTo(x, y+r);

    ctx.arcTo(x, y, x+r, y, r); ctx.closePath();

}

function drawProgress(currentTime, totalDuration) {

    const barW = W - 120, barH = 6, barX = 60, barY = H - 50;

    roundRect(barX, barY, barW, barH, 3);

    ctx.fillStyle = T.progressBg; ctx.fill();

    const pct = Math.min(currentTime / totalDuration, 1);

    if (pct > 0) {

        roundRect(barX, barY, barW * pct, barH, 3);

        ctx.fillStyle = T.progressFill; ctx.fill();

    }

}

function parseMathString(str) {

    let index = 0;

    function parseExpression(endChar) {

        let parts = [];

        while (index < str.length) {

            if (endChar && str[index] === endChar) {

                break;

            }

            // Check for square root

            if (str.startsWith('\\sqrt{', index)) {

                index += 6; // skip '\sqrt{'

                let inner = parseExpression('}');

                if (index < str.length && str[index] === '}') {

                    index++; // skip '}'

                }

                parts.push({ type: 'sqrt', expr: inner });

                continue;

            }

            if (str.startsWith('√{', index)) {

                index += 2; // skip '√{'

                let inner = parseExpression('}');

                if (index < str.length && str[index] === '}') {

                    index++; // skip '}'

                }

                parts.push({ type: 'sqrt', expr: inner });

                continue;

            }

            // Exponents / Superscripts

            if (str[index] === '^') {

                index++; // skip '^'

                let expr;

                if (str[index] === '{') {

                    index++; // skip '{'

                    expr = parseExpression('}');

                    if (index < str.length && str[index] === '}') {

                        index++;

                    }

                } else {

                    // Group contiguous digits (e.g., ^50 -> superscript 50)

                    let textVal = "";

                    if (str[index] && /[0-9]/.test(str[index])) {

                        while (index < str.length && /[0-9]/.test(str[index])) {

                            textVal += str[index];

                            index++;

                        }

                    } else {

                        textVal = str[index] || '';

                        index++;

                    }

                    expr = [{ type: 'text', text: textVal }];

                }

                parts.push({ type: 'sup', expr: expr });

                continue;

            }

            // Subscripts

            if (str[index] === '_') {

                index++; // skip '_'

                let expr;

                if (str[index] === '{') {

                    index++; // skip '{'

                    expr = parseExpression('}');

                    if (index < str.length && str[index] === '}') {

                        index++;

                    }

                } else {

                    // Group contiguous digits (e.g., _10 -> subscript 10)

                    let textVal = "";

                    if (str[index] && /[0-9]/.test(str[index])) {

                        while (index < str.length && /[0-9]/.test(str[index])) {

                            textVal += str[index];

                            index++;

                        }

                    } else {

                        textVal = str[index] || '';

                        index++;

                    }

                    expr = [{ type: 'text', text: textVal }];

                }

                parts.push({ type: 'sub', expr: expr });

                continue;

            }

            // Regular characters

            let char = str[index];

            if (parts.length > 0 && parts[parts.length - 1].type === 'text') {

                parts[parts.length - 1].text += char;

            } else {

                parts.push({ type: 'text', text: char });

            }

            index++;

        }

        return parts;

    }

    return parseExpression();

}

function getFontForSize(size, bold) {

    return `${bold ? 'bold ' : ''}${Math.round(size)}px ${T.font}`;

}

function measureMathBlock(ctx, parts, fontSize) {

    let width = 0;

    const originalFont = ctx.font;

    for (const part of parts) {

        if (part.type === 'text') {

            ctx.font = getFontForSize(fontSize, false);

            width += ctx.measureText(part.text).width;

        } else if (part.type === 'sup') {

            width += measureMathBlock(ctx, part.expr, fontSize * 0.6);

        } else if (part.type === 'sub') {

            width += measureMathBlock(ctx, part.expr, fontSize * 0.6);

        } else if (part.type === 'sqrt') {

            const rw = fontSize * 0.4;

            const w = measureMathBlock(ctx, part.expr, fontSize);

            width += rw + w + 4;

        }

    }

    ctx.font = originalFont;

    return width;

}

function measureMathAwareText(text, font) {

    ctx.font = font;

    if (!text.includes('^') && !text.includes('_') && !text.includes('√') && !text.includes('\\sqrt')) {

        return ctx.measureText(text).width;

    }

    const sizeMatch = font.match(/(\d+)px/);

    const fontSize = sizeMatch ? parseInt(sizeMatch[1]) : 40;

    const parts = parseMathString(text);

    return measureMathBlock(ctx, parts, fontSize);

}

function drawMathBlock(ctx, parts, x, y, fontSize, color, bold) {

    let currentX = x;

    const originalFont = ctx.font;

    for (const part of parts) {

        if (part.type === 'text') {

            ctx.font = getFontForSize(fontSize, bold);

            ctx.fillStyle = color;

            ctx.fillText(part.text, currentX, y);

            currentX += ctx.measureText(part.text).width;

        } else if (part.type === 'sup') {

            const supSize = fontSize * 0.6;

            const supY = y - fontSize * 0.35;

            ctx.font = getFontForSize(supSize, bold);

            drawMathBlock(ctx, part.expr, currentX, supY, supSize, color, bold);

            currentX += measureMathBlock(ctx, part.expr, supSize);

        } else if (part.type === 'sub') {

            const subSize = fontSize * 0.6;

            const subY = y + fontSize * 0.18;

            ctx.font = getFontForSize(subSize, bold);

            drawMathBlock(ctx, part.expr, currentX, subY, subSize, color, bold);

            currentX += measureMathBlock(ctx, part.expr, subSize);

        } else if (part.type === 'sqrt') {

            const rw = fontSize * 0.4;

            const radicandWidth = measureMathBlock(ctx, part.expr, fontSize);

            // Draw radical symbol

            ctx.save();

            ctx.beginPath();

            ctx.moveTo(currentX, y - fontSize * 0.18);

            ctx.lineTo(currentX + rw * 0.3, y - fontSize * 0.08);

            ctx.lineTo(currentX + rw * 0.6, y + fontSize * 0.15);

            ctx.lineTo(currentX + rw, y - fontSize * 0.82);

            ctx.lineTo(currentX + rw + radicandWidth + 2, y - fontSize * 0.82);

            ctx.strokeStyle = color;

            ctx.lineWidth = Math.max(1.8, fontSize * 0.055);

            ctx.lineJoin = 'round';

            ctx.lineCap = 'round';

            ctx.stroke();

            ctx.restore();

            // Draw radicand

            drawMathBlock(ctx, part.expr, currentX + rw, y, fontSize, color, bold);

            currentX += rw + radicandWidth + 4;

        }

    }

    ctx.font = originalFont;

}

function drawRichMathText(ctx, text, x, y, fontSize, color, align, bold, currentBaseline) {

    if (!text.includes('^') && !text.includes('_') && !text.includes('√') && !text.includes('\\sqrt')) {

        ctx.fillStyle = color;

        ctx.textAlign = align;

        ctx.textBaseline = currentBaseline || 'top';

        ctx.font = getFontForSize(fontSize, bold);

        ctx.fillText(text, x, y);

        return;

    }

    const parts = parseMathString(text);

    const originalFont = ctx.font;

    const totalW = measureMathBlock(ctx, parts, fontSize);

    let startX = x;

    if (align === 'center') {

        startX = x - totalW / 2;

    } else if (align === 'right') {

        startX = x - totalW;

    } else {

        startX = x;

    }

    let baselineY = y;

    const bl = currentBaseline || 'top';

    if (bl === 'top') {

        baselineY = y + fontSize * 0.82;

    } else if (bl === 'middle') {

        baselineY = y + fontSize * 0.32;

    }

    ctx.save();

    ctx.textAlign = 'left';

    ctx.textBaseline = 'alphabetic';

    drawMathBlock(ctx, parts, startX, baselineY, fontSize, color, bold);

    ctx.restore();

}

function wrapText(text, maxW, font) {

    ctx.font = font;

    const words = text.split(' ');

    const lines = [];

    let line = '';

    for (const w of words) {

        const test = line ? line + ' ' + w : w;

        if (measureMathAwareText(test, font) > maxW && line) {

            lines.push(line);

            line = w;

        } else {

            line = test;

        }

    }

    if (line) lines.push(line);

    return lines.length > 0 ? lines : [''];

}

/**
 * TRỢ GIÚP DÙNG CHUNG — tiêm vào ĐẦU MỌI khối custom_js.
 *
 * ══════════════════════════════════════════════════════════════════════════
 *  ĐÂY LÀ BẢN VÁ CHO MỘT LỖI IM LẶNG ĐÃ SỐNG RẤT LÂU.
 *
 *  `core/custom_scenes.py` có hằng `PRE` (y hệt đoạn dưới) và nó ghép PRE vào
 *  đầu code của MỌI CẢNH DỰNG SẴN. Nên 37 cảnh mẫu trong few-shot đều mở đầu
 *  bằng `var P=…; function EZ(t){…} function EB(t){…}`.
 *
 *  AI ĐỌC NHỮNG VÍ DỤ ĐÓ. Rồi khi tự viết cảnh riêng, nó CHÉP THÀNH NGỮ —
 *  `EB(P)`, `EZ(P)`, `RR(x,y,w,h,r)` — nhưng KHÔNG chép phần định nghĩa.
 *
 *  Renderer thì chỉ cấp cho code AI đúng 14 tên (ctx, W, H, MX, cursorY,
 *  stepProgress, time, el, T, rc, wrapText, drawEmoji, ui, mnk). Không có P,
 *  không có EB. Kết quả: `ReferenceError: EB is not defined` → cảnh đó VẼ RA
 *  KHÔNG CÓ GÌ. Renderer bắt lỗi rồi đi tiếp — video vẫn render "thành công",
 *  chỉ là thủng một cảnh, và không ai biết vì sao.
 *
 *  Đo được: ~1 trong 11 cảnh AI viết dính lỗi này. Nó xảy ra trên CẢ desktop.
 *
 *  Tiêm lại ở đây thì AI chép thành ngữ là chạy đúng. Cảnh dựng sẵn vốn đã có
 *  PRE sẽ khai lại lần hai — HỢP LỆ trong JS (`var` và `function` được phép
 *  khai trùng trong cùng một thân hàm). Cố ý dùng `var`/`function`, KHÔNG dùng
 *  `let`/`const`: khai trùng bằng `let` là SyntaxError, và sẽ giết mọi cảnh
 *  dựng sẵn.
 * ══════════════════════════════════════════════════════════════════════════
 */
const CUSTOM_JS_PRE =
    'var P=Math.max(0,Math.min(1,stepProgress*4));'
    + 'var P2=Math.max(0,Math.min(1,stepProgress));'
    + 'function RR(x,y,w,h,r){ctx.beginPath();ctx.roundRect(x,y,w,h,r);}'
    + 'function CL(v){return Math.max(0,Math.min(1,v));}'
    + 'function EZ(t){return 1-Math.pow(1-t,3);}'
    + 'function EB(t){var c1=1.70158,c3=c1+1;return 1+c3*Math.pow(t-1,3)+c1*Math.pow(t-1,2);}'
    + '\n';

// Cứu custom_js một-dòng bị comment // nuốt hết lệnh vẽ phía sau: AI hay xuất
// code trên 1 dòng JSON nhưng vẫn chèn "// chú thích" — trong JS, // ăn đến
// hết dòng nên toàn bộ phần sau thành code chết (chạy êm, không vẽ gì).
// Chèn \n ngay trước câu lệnh thật đầu tiên sau mỗi // (bỏ qua // trong chuỗi
// như URL). Chỉ áp dụng cho code gần-một-dòng — code nhiều dòng comment kết
// thúc tự nhiên, không đụng vào.
function fixInlineComments(code) {
    if (!code || code.indexOf('//') === -1) return code;
    if ((code.match(/\n/g) || []).length >= 2 || code.length < 200) return code;
    const STMT = /ctx\.|ctx\[|ui\.|const\s|let\s|var\s|function\s|if\s*\(|for\s*\(|while\s*\(|return\s/g;
    let out = '', i = 0, q = null;
    const n = code.length;
    while (i < n) {
        const c = code[i];
        if (q) {
            if (c === '\\' && i + 1 < n) { out += code.substr(i, 2); i += 2; continue; }
            if (c === q) q = null;
            out += c; i++; continue;
        }
        if (c === '"' || c === "'" || c === '`') { q = c; out += c; i++; continue; }
        if (c === '/' && code[i + 1] === '/') {
            let j = code.indexOf('\n', i);
            const end = j === -1 ? n : j;
            STMT.lastIndex = i + 2;
            const m = STMT.exec(code);
            if (m && m.index < end) {
                out += code.slice(i, m.index) + '\n';
                i = m.index;
                continue;
            }
            out += code.slice(i, end); i = end; continue;
        }
        out += c; i++;
    }
    return out;
}

// ── Bộ icon Lucide (premium, nét mảnh, tô theo màu) ──────────────────────
// Emoji trong kịch bản (kể cả code do AI sinh) được vẽ bằng ICON LUCIDE.
// icon tương ứng trong EMOJI_TO_LUCIDE sẽ vẽ Lucide stroke-based (ăn màu
// Không có ánh xạ → vẽ ký tự đó ĐƠN SẮC theo màu hiện tại. KHÔNG có emoji màu.
let LUCIDE_ICONS = {};
try { LUCIDE_ICONS = require('./lucide_icons.js'); }
catch (e) {
    try { LUCIDE_ICONS = require(path.join(__dirname, 'lucide_icons.js')); }
    catch (e2) { LUCIDE_ICONS = {}; }
}
const EMOJI_TO_LUCIDE = {
    '📥': 'download', '📤': 'upload', '🧭': 'compass', '🛠': 'wrench', '🛠️': 'wrench',
    '⚙': 'settings', '⚙️': 'settings', '🔧': 'wrench', '🔍': 'search', '🔎': 'search',
    '🚀': 'rocket', '🧠': 'brain', '💬': 'message', '🗨': 'message',
    '👍': 'thumbs-up', '⭐': 'star', '🌟': 'sparkles', '✨': 'sparkles',
    '💰': 'coins', '🪙': 'coins', '💵': 'wallet', '👛': 'wallet',
    '✓': 'check', '✔': 'check', '✔️': 'check', '✅': 'check-circle',
    '📄': 'file', '📃': 'file', '📁': 'folder', '📂': 'folder',
    '🔒': 'lock', '🔐': 'lock', '🔑': 'key', '🗝': 'key',
    '🛡': 'shield', '🛡️': 'shield', '⚡': 'zap', '📊': 'chart',
    '📈': 'trending-up', '📉': 'trending-down', '💡': 'lightbulb', '🎯': 'target',
    '▶': 'play', '▶️': 'play', '📺': 'tv', '🎵': 'music', '🎶': 'music',
    '🌐': 'globe', '🌍': 'globe', '☁': 'cloud', '☁️': 'cloud',
    '🗄': 'database', '💾': 'database', '🖥': 'monitor', '💻': 'monitor',
    '📱': 'phone', '⏱': 'timer', '⏳': 'timer', '⏰': 'clock', '🕒': 'clock',
    '📅': 'calendar', '✉': 'mail', '✉️': 'mail', '📧': 'mail', '🔗': 'link',
    '👁': 'eye', '❌': 'x', '✖': 'x', '⚠': 'alert', '⚠️': 'alert',
    '➡': 'arrow-right', '➡️': 'arrow-right', '→': 'arrow-right',
    '🔄': 'refresh', '🔁': 'refresh', '📦': 'package', '🧊': 'box',
    '👥': 'users', '🤝': 'user-check', '🔖': 'bookmark', '🔥': 'flame',
    '📖': 'book', '📚': 'book', '🖊': 'pen', '✏': 'pen', '✏️': 'pen',
    '🧮': 'gauge', '🕸': 'network', '🌿': 'git-branch', '⏺': 'circle-dot',

    // Bổ sung 2026-07-14: user chốt BỎ EMOJI, chỉ dùng icon Lucide.
    // Sinh bằng scripts/gen_lucide.py (tải SVG thật từ lucide-static).
    '😱': 'alert', '➔': 'arrow-right', '👉': 'arrow-right', '⚛': 'atom',
    '🍌': 'banana', '🤑': 'banknote', '🐦': 'bird', '📕': 'book',
    '🤖': 'bot', '💼': 'briefcase', '🏢': 'building-2', '🚗': 'car',
    '🟢': 'circle', '🎬': 'clapperboard', '📋': 'clipboard-list', '💳': 'credit-card',
    '🐘': 'database', '💠': 'diamond', '🏁': 'flag', '🗂': 'folders',
    '🚶': 'footprints', '👾': 'gamepad-2', '💎': 'gem', '🎓': 'graduation-cap',
    '❤': 'heart', '💙': 'heart', '💚': 'heart', '🏦': 'landmark',
    '🔓': 'lock-open', '🏅': 'medal', '🎤': 'mic', '🔬': 'microscope',
    '📰': 'newspaper', '🗞': 'newspaper', '📝': 'notebook-pen', '🎨': 'palette',
    '✍': 'pen-line', '📞': 'phone-call', '💊': 'pill', '✈': 'plane',
    '🧩': 'puzzle', '📐': 'ruler', '📡': 'satellite-dish', '✂': 'scissors',
    '📜': 'scroll', '🛒': 'shopping-cart', '🐌': 'snail', '★': 'star',
    '🏪': 'store', '💉': 'syringe', '🎫': 'ticket', '🏆': 'trophy',
    '🐢': 'turtle', '👤': 'user', '🎥': 'video', '🪄': 'wand-sparkles',
    '✗': 'x',

    // Bổ sung 2026-08-01 (template green-guide, soi PNG thấy tile rỗng):
    // '✕' U+2715 lọt lưới họ ✖✗❌; nhóm eco/đời-sống ánh xạ về icon CÓ SẴN
    // trong lucide_icons.js (KHÔNG thêm icon mới — muốn icon mới thì chạy
    // scripts/gen_lucide.py, đừng trỏ tên icon chưa tồn tại: drawLucide trả
    // false là emoji lại thành ô rỗng đúng cái bug đang vá).
    '✕': 'x', '♻': 'refresh', '♻️': 'refresh', '🔌': 'zap', '🔋': 'zap',
    '📶': 'network', '🛍': 'shopping-cart', '🛍️': 'shopping-cart',
};
// Parser path SVG tự viết (M/L/H/V/C/S/Q/T/A/Z, tuyệt đối + tương đối) —
// Path2D của node-canvas không hỗ trợ lệnh arc nên icon phức tạp vẽ thiếu.
function _svgArcToCtx(c, x1, y1, rx, ry, phi, fa, fs, x2, y2) {
    if (rx === 0 || ry === 0) { c.lineTo(x2, y2); return; }
    const rad = phi * Math.PI / 180;
    const cosP = Math.cos(rad), sinP = Math.sin(rad);
    const dx = (x1 - x2) / 2, dy = (y1 - y2) / 2;
    const x1p = cosP * dx + sinP * dy, y1p = -sinP * dx + cosP * dy;
    let rxs = rx * rx, rys = ry * ry;
    const lam = (x1p * x1p) / rxs + (y1p * y1p) / rys;
    if (lam > 1) { const sl = Math.sqrt(lam); rx *= sl; ry *= sl; rxs = rx * rx; rys = ry * ry; }
    let num = rxs * rys - rxs * y1p * y1p - rys * x1p * x1p;
    if (num < 0) num = 0;
    let coef = Math.sqrt(num / (rxs * y1p * y1p + rys * x1p * x1p));
    if (fa === fs) coef = -coef;
    const cxp = coef * rx * y1p / ry, cyp = -coef * ry * x1p / rx;
    const cxx = cosP * cxp - sinP * cyp + (x1 + x2) / 2;
    const cyy = sinP * cxp + cosP * cyp + (y1 + y2) / 2;
    const ang = (ux, uy, vx, vy) => {
        const dot = ux * vx + uy * vy;
        const len = Math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy));
        let a = Math.acos(Math.max(-1, Math.min(1, dot / len)));
        if (ux * vy - uy * vx < 0) a = -a;
        return a;
    };
    const th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry);
    let dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry);
    if (!fs && dth > 0) dth -= 2 * Math.PI;
    if (fs && dth < 0) dth += 2 * Math.PI;
    const segs = Math.max(1, Math.ceil(Math.abs(dth) / (Math.PI / 2)));
    const delta = dth / segs;
    const t = 4 / 3 * Math.tan(delta / 4);
    let th = th1, px = x1, py = y1;
    for (let i = 0; i < segs; i++) {
        const th2 = th + delta;
        const c1 = Math.cos(th), s1 = Math.sin(th);
        const c2 = Math.cos(th2), s2 = Math.sin(th2);
        const ex = cxx + rx * c2 * cosP - ry * s2 * sinP;
        const ey = cyy + rx * c2 * sinP + ry * s2 * cosP;
        const q1x = px - t * (rx * s1 * cosP + ry * c1 * sinP);
        const q1y = py + t * (-rx * s1 * sinP + ry * c1 * cosP);
        const q2x = ex + t * (rx * s2 * cosP + ry * c2 * sinP);
        const q2y = ey - t * (-rx * s2 * sinP + ry * c2 * cosP);
        c.bezierCurveTo(q1x, q1y, q2x, q2y, ex, ey);
        th = th2; px = ex; py = ey;
    }
}
function strokeSvgPath(c, d) {
    const tok = d.match(/[a-df-z]|[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi) || [];
    let i = 0, cmd = '', x = 0, y = 0, sx = 0, sy = 0;
    let cpx = null, cpy = null, qx = null, qy = null;
    const num = () => parseFloat(tok[i++]);
    c.beginPath();
    while (i < tok.length) {
        const t0 = tok[i];
        if (/[a-z]/i.test(t0) && t0.length === 1) { cmd = t0; i++; }
        const rel = cmd === cmd.toLowerCase() && cmd !== 'z' && cmd !== 'Z';
        switch (cmd.toUpperCase()) {
            case 'M': { const nx = num() + (rel ? x : 0), ny = num() + (rel ? y : 0);
                c.moveTo(nx, ny); x = sx = nx; y = sy = ny; cmd = rel ? 'l' : 'L'; break; }
            case 'L': { const nx = num() + (rel ? x : 0), ny = num() + (rel ? y : 0);
                c.lineTo(nx, ny); x = nx; y = ny; break; }
            case 'H': { const nx = num() + (rel ? x : 0); c.lineTo(nx, y); x = nx; break; }
            case 'V': { const ny = num() + (rel ? y : 0); c.lineTo(x, ny); y = ny; break; }
            case 'C': { const a1 = num() + (rel ? x : 0), a2 = num() + (rel ? y : 0);
                const b1 = num() + (rel ? x : 0), b2 = num() + (rel ? y : 0);
                const nx = num() + (rel ? x : 0), ny = num() + (rel ? y : 0);
                c.bezierCurveTo(a1, a2, b1, b2, nx, ny);
                cpx = b1; cpy = b2; x = nx; y = ny; break; }
            case 'S': { const b1 = num() + (rel ? x : 0), b2 = num() + (rel ? y : 0);
                const nx = num() + (rel ? x : 0), ny = num() + (rel ? y : 0);
                const a1 = cpx !== null ? 2 * x - cpx : x;
                const a2 = cpy !== null ? 2 * y - cpy : y;
                c.bezierCurveTo(a1, a2, b1, b2, nx, ny);
                cpx = b1; cpy = b2; x = nx; y = ny; break; }
            case 'Q': { const a1 = num() + (rel ? x : 0), a2 = num() + (rel ? y : 0);
                const nx = num() + (rel ? x : 0), ny = num() + (rel ? y : 0);
                c.quadraticCurveTo(a1, a2, nx, ny);
                qx = a1; qy = a2; x = nx; y = ny; break; }
            case 'T': { const a1 = qx !== null ? 2 * x - qx : x;
                const a2 = qy !== null ? 2 * y - qy : y;
                const nx = num() + (rel ? x : 0), ny = num() + (rel ? y : 0);
                c.quadraticCurveTo(a1, a2, nx, ny);
                qx = a1; qy = a2; x = nx; y = ny; break; }
            case 'A': { const rx = num(), ry = num(), rot = num();
                const fa = num() ? 1 : 0, fs = num() ? 1 : 0;
                const nx = num() + (rel ? x : 0), ny = num() + (rel ? y : 0);
                _svgArcToCtx(c, x, y, rx, ry, rot, fa, fs, nx, ny);
                x = nx; y = ny; break; }
            case 'Z': { c.closePath(); x = sx; y = sy; break; }
            default: i++; break;
        }
        if ('CS'.indexOf(cmd.toUpperCase()) < 0) { cpx = null; cpy = null; }
        if ('QT'.indexOf(cmd.toUpperCase()) < 0) { qx = null; qy = null; }
    }
    c.stroke();
}
function drawLucide(c, name, cx, cy, size, color) {
    const els = LUCIDE_ICONS[name];
    if (!els || !els.length) return false;
    c.save();
    c.translate(cx - size / 2, cy - size / 2);
    const s = size / 24;
    c.scale(s, s);
    c.strokeStyle = color || '#64748b';
    c.lineWidth = 2;
    c.lineCap = 'round';
    c.lineJoin = 'round';
    try {
        for (const e of els) {
            if (e.t === 'p') { strokeSvgPath(c, e.d); }
            else if (e.t === 'c') { c.beginPath(); c.arc(e.cx, e.cy, e.r, 0, Math.PI * 2); c.stroke(); }
            else if (e.t === 'l') { c.beginPath(); c.moveTo(e.x1, e.y1); c.lineTo(e.x2, e.y2); c.stroke(); }
            else if (e.t === 'r') {
                c.beginPath();
                if (c.roundRect) c.roundRect(e.x, e.y, e.w, e.h, e.rx || 0);
                else c.rect(e.x, e.y, e.w, e.h);
                c.stroke();
            }
            else if (e.t === 'pl') {
                c.beginPath(); c.moveTo(e.pts[0], e.pts[1]);
                for (let i = 2; i < e.pts.length; i += 2) c.lineTo(e.pts[i], e.pts[i + 1]);
                if (e.close) c.closePath();
                c.stroke();
            }
        }
    } catch (err) { c.restore(); return false; }
    c.restore();
    return true;
}
global.drawLucide = drawLucide;
global.EMOJI_TO_LUCIDE = EMOJI_TO_LUCIDE;

// ── Bộ linh kiện PREMIUM cho custom_js (ui.*) ────────────────────────────
// AI vẽ tay hay ra rect phẳng + màu nhạt + emoji trần → không premium.
// Bộ helper này dựng sẵn các linh kiện đã tune kỹ (thẻ kính, chip, KPI,
// gauge, luồng hạt...) — code AI chỉ lắp ráp. Vẽ bằng ctx GỐC (không qua
// proxy remap): màu đã tự chọn theo tông sáng/tối, bóng đổ mềm không bị
// proxy cắt, màu TƯƠI bão hoà cao thay vì màu chữ nhạt.
function makeUiKit(ctx, artStyle, time, rc, drawEmojiFn) {
    // 'editcream' vào nhóm light: nền cream sáng — nếu AI lỡ gọi ui.glass thì
    // ra card trắng/sáng hợp tông thay vì card navy tối (lưới đỡ; prompt đã cấm).
    const light = ['watercolor', 'inkwash', 'pastel', 'sketch', 'sketchnote', 'aurora', 'warmpaper', 'editcream'].includes(artStyle);
    function hexRgb(h) {
        const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(h || '');
        if (!m) return null;
        let s = m[1];
        if (s.length === 3) s = s.split('').map(c => c + c).join('');
        return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
    }
    function mix(a, b, t) {
        const x = hexRgb(a), y = hexRgb(b);
        if (!x || !y) return a;
        return `rgb(${Math.round(x[0] + (y[0] - x[0]) * t)},${Math.round(x[1] + (y[1] - x[1]) * t)},${Math.round(x[2] + (y[2] - x[2]) * t)})`;
    }
    function withA(c, a) {
        const r = hexRgb(c);
        if (r) return `rgba(${r[0]},${r[1]},${r[2]},${a})`;
        const m = /^rgba?\(([^)]+)\)/.exec(c || '');
        if (m) { const p = m[1].split(',').slice(0, 3).map(s => s.trim()); return `rgba(${p.join(',')},${a})`; }
        return light ? `rgba(30,41,59,${a})` : `rgba(255,255,255,${a})`;
    }
    // Màu TƯƠI: bộ bão hoà cao — nền sáng không dùng màu chữ (nhạt nhoà).
    // yellow nền sáng = amber ĐẬM (#d97706): cam nhạt trên trắng rớt chuẩn
    // tương phản WCAG, chữ "cháy" khi xem ngoài trời.
    const VIVID = light
        ? { green: '#16a34a', cyan: '#0284c7', yellow: '#d97706', red: '#ef4444', purple: '#7c3aed', pink: '#db2777', white: '#334155', title: '#2563eb' }
        : (artStyle === 'neonsketch'
            ? { green: '#a3e635', cyan: '#38bdf8', yellow: '#fde047', red: '#f87171', purple: '#c4b5fd', pink: '#f9a8d4', white: '#f2f7ec', title: '#fde047' }
            : { green: '#34d399', cyan: '#22d3ee', yellow: '#fbbf24', red: '#fb7185', purple: '#a78bfa', pink: '#f472b6', white: '#e2e8f0', title: '#60a5fa' });
    function col(c) { return (c && VIVID[c]) || (hexRgb(c) ? c : (c && c.startsWith && c.startsWith('rgb') ? c : VIVID.cyan)); }
    function lite(c) { return mix(hexRgb(col(c)) ? col(c) : '#38bdf8', '#ffffff', light ? 0.22 : 0.45); }
    // Font của kit ui.*: MẶC ĐỊNH stack hệ thống (như HEAD). NHƯNG khi người
    // dùng CHỦ ĐỘNG chọn font (USER_FONT_OVERRIDE, đặt tại khối --font), ưu tiên
    // T.font — nếu không, tiêu đề/chip/kpi do ui.* vẽ KHÔNG đổi theo font đã chọn
    // ("chỗ đổi chỗ không"). ui.* vẽ trên ctx THẬT, không qua Proxy rewrite của
    // custom_js, nên phải tự đọc T.font ở đây. Vắng lựa chọn → cờ false → y HEAD.
    const FONT = (USER_FONT_OVERRIDE && T && T.font)
        ? T.font
        : ((typeof SYSTEM_FONT_STACK !== 'undefined') ? SYSTEM_FONT_STACK : "'Segoe UI', sans-serif");
    function rr(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }
    function noShadow() { ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)'; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0; }
    const CLA = v => Math.max(0, Math.min(1, v));

    const ui = {};
    // Thẻ kính premium: bóng mềm + gradient + viền + vệt sheen + mép nhấn màu
    ui.glass = function (x, y, w, h, o = {}) {
        // neonsketch: panel terminal PHẲNG viền lime — không phải kính xanh
        if (artStyle === 'neonsketch') {
            const r2 = o.r !== undefined ? o.r : 8;
            ctx.save();
            ctx.fillStyle = 'rgba(8,13,5,0.78)';
            rr(x, y, w, h, r2); ctx.fill();
            ctx.shadowColor = 'rgba(163,230,53,0.45)'; ctx.shadowBlur = 12;
            ctx.strokeStyle = 'rgba(163,230,53,0.5)';
            ctx.lineWidth = 2;
            rr(x, y, w, h, r2); ctx.stroke();
            noShadow();
            if (o.accent) {
                const a2 = col(o.accent);
                ctx.shadowColor = withA(a2, 0.8); ctx.shadowBlur = 12;
                ctx.fillStyle = a2;
                rr(x + 12, y + 14, 4, h - 28, 2); ctx.fill();
            }
            ctx.restore();
            return;
        }
        const r = o.r !== undefined ? o.r : 28;
        ctx.save();
        ctx.shadowColor = light ? 'rgba(80,100,160,0.22)' : 'rgba(0,0,0,0.4)';
        ctx.shadowBlur = light ? 22 : 28;
        ctx.shadowOffsetY = 10;
        const g = ctx.createLinearGradient(0, y, 0, y + h);
        if (light) { g.addColorStop(0, 'rgba(255,255,255,0.94)'); g.addColorStop(1, 'rgba(243,246,255,0.88)'); }
        else { g.addColorStop(0, 'rgba(26,34,62,0.88)'); g.addColorStop(1, 'rgba(13,17,36,0.84)'); }
        ctx.fillStyle = g;
        rr(x, y, w, h, r); ctx.fill();
        noShadow();
        ctx.strokeStyle = light ? 'rgba(30,45,90,0.13)' : 'rgba(255,255,255,0.15)';
        ctx.lineWidth = 1.5;
        rr(x, y, w, h, r); ctx.stroke();
        // sheen: vệt sáng mỏng trên đỉnh thẻ
        ctx.save();
        rr(x, y, w, h, r); ctx.clip();
        const s = ctx.createLinearGradient(0, y, 0, y + h * 0.4);
        s.addColorStop(0, light ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.10)');
        s.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = s;
        ctx.fillRect(x, y, w, h * 0.4);
        ctx.restore();
        if (o.accent) {
            const a = col(o.accent);
            if (!light) { ctx.shadowColor = withA(a, 0.7); ctx.shadowBlur = 14; }
            ctx.fillStyle = a;
            rr(x + 14, y + 18, 5, h - 36, 3); ctx.fill();
        }
        ctx.restore();
    };
    // Tiêu đề gradient tươi
    ui.title = function (cx, y, text, o = {}) {
        const size = o.size || 46;
        ctx.save();
        ctx.font = `bold ${size}px ${FONT}`;
        ctx.textAlign = 'center';
        const w = ctx.measureText(text).width;
        const g = ctx.createLinearGradient(cx - w / 2, 0, cx + w / 2, 0);
        g.addColorStop(0, col(o.from || 'title'));
        g.addColorStop(1, col(o.to || 'cyan'));
        if (!light) { ctx.shadowColor = withA(col(o.from || 'title'), 0.55); ctx.shadowBlur = 18; }
        ctx.fillStyle = g;
        ctx.fillText(text, cx, y);
        ctx.restore();
    };
    // Chip/pill nhãn
    ui.chip = function (cx, cy, text, o = {}) {
        const size = o.size || 26, pad = 18;
        ctx.save();
        ctx.font = `600 ${size}px ${FONT}`;
        const c = col(o.color || 'cyan');
        const tw = ctx.measureText(text).width;
        const w = tw + pad * 2, h = size + 20;
        const g = ctx.createLinearGradient(0, cy - h / 2, 0, cy + h / 2);
        g.addColorStop(0, withA(c, light ? 0.14 : 0.22));
        g.addColorStop(1, withA(c, light ? 0.22 : 0.34));
        ctx.fillStyle = g;
        rr(cx - w / 2, cy - h / 2, w, h, h / 2); ctx.fill();
        ctx.strokeStyle = withA(c, 0.6); ctx.lineWidth = 1.5;
        rr(cx - w / 2, cy - h / 2, w, h, h / 2); ctx.stroke();
        ctx.fillStyle = light ? mix(c, '#1e293b', 0.15) : lite(c);
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(text, cx, cy + 1);
        ctx.restore();
    };
    // Số liệu lớn + nhãn
    ui.kpi = function (cx, y, value, label, o = {}) {
        const size = o.size || 86;
        ctx.save();
        ctx.font = `bold ${size}px ${FONT}`;
        ctx.textAlign = 'center';
        const c = col(o.color || 'cyan');
        const w = ctx.measureText(String(value)).width;
        const g = ctx.createLinearGradient(cx - w / 2, 0, cx + w / 2, 0);
        g.addColorStop(0, c); g.addColorStop(1, lite(c));
        if (!light) { ctx.shadowColor = withA(c, 0.6); ctx.shadowBlur = 22; }
        ctx.fillStyle = g;
        ctx.fillText(String(value), cx, y);
        noShadow();
        if (label) {
            ctx.font = `600 24px ${FONT}`;
            ctx.fillStyle = light ? 'rgba(51,65,85,0.85)' : 'rgba(226,232,240,0.8)';
            ctx.fillText(String(label).toUpperCase(), cx, y + 40);
        }
        ctx.restore();
    };
    // Emoji trên đĩa gradient + vành sáng (emoji trần nhìn rẻ)
    ui.icon = function (cx, cy, emoji, size = 64, o = {}) {
        const c = col(o.color || 'cyan');
        const R = size * 0.82;
        ctx.save();
        const g = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R);
        g.addColorStop(0, withA(c, light ? 0.18 : 0.32));
        g.addColorStop(1, withA(c, 0.05));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
        if (!light) { ctx.shadowColor = withA(c, 0.6); ctx.shadowBlur = 16; }
        ctx.strokeStyle = withA(c, 0.55); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
        noShadow();
        // Ưu tiên icon Lucide (nét mảnh premium, tô màu accent) — emoji chỉ
        // là fallback khi không có icon tương ứng.
        const luc = (typeof EMOJI_TO_LUCIDE !== 'undefined') && EMOJI_TO_LUCIDE[emoji];
        if (luc && typeof drawLucide === 'function'
            && drawLucide(ctx, luc, cx, cy, size * 0.92, light ? c : lite(c))) {
            /* đã vẽ lucide */
        } else if (drawEmojiFn) drawEmojiFn(ctx, emoji, cx, cy + size * 0.36, size);
        else { ctx.font = `${size}px ${FONT}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(emoji, cx, cy); }
        ctx.restore();
    };
    // Thanh gauge bo tròn + đầu phát sáng
    ui.bar = function (x, y, w, h, p, o = {}) {
        h = h || 16;
        const c = col(o.color || 'cyan');
        const pw = Math.max(h, w * CLA(p));
        ctx.save();
        ctx.fillStyle = light ? 'rgba(30,41,59,0.08)' : 'rgba(255,255,255,0.10)';
        rr(x, y, w, h, h / 2); ctx.fill();
        const g = ctx.createLinearGradient(x, 0, x + pw, 0);
        g.addColorStop(0, c); g.addColorStop(1, lite(c));
        ctx.fillStyle = g;
        rr(x, y, pw, h, h / 2); ctx.fill();
        if (!light) { ctx.shadowColor = withA(c, 0.8); ctx.shadowBlur = 12; }
        ctx.fillStyle = lite(c);
        ctx.beginPath(); ctx.arc(x + pw - h / 2, y + h / 2, h * 0.62, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
    };
    // Vòng gauge
    ui.ring = function (cx, cy, r, p, o = {}) {
        const lw = o.w || 14, c = col(o.color || 'cyan');
        const a0 = -Math.PI / 2, a1 = a0 + Math.PI * 2 * CLA(p);
        ctx.save();
        ctx.lineCap = 'round';
        ctx.strokeStyle = light ? 'rgba(30,41,59,0.08)' : 'rgba(255,255,255,0.10)';
        ctx.lineWidth = lw;
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
        if (!light) { ctx.shadowColor = withA(c, 0.7); ctx.shadowBlur = 16; }
        ctx.strokeStyle = c;
        ctx.beginPath(); ctx.arc(cx, cy, r, a0, a1); ctx.stroke();
        noShadow();
        ctx.fillStyle = lite(c);
        ctx.beginPath(); ctx.arc(cx + Math.cos(a1) * r, cy + Math.sin(a1) * r, lw * 0.55, 0, Math.PI * 2); ctx.fill();
        if (o.text) {
            ctx.fillStyle = light ? '#1e293b' : '#f1f5f9';
            ctx.font = `bold ${Math.round(r * 0.52)}px ${FONT}`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(o.text, cx, cy + 2);
        }
        ctx.restore();
    };
    // Luồng kết nối + hạt sáng chạy theo đường
    ui.flow = function (pts, o = {}) {
        if (!pts || pts.length < 2) return;
        const c = col(o.color || 'cyan');
        ctx.save();
        ctx.strokeStyle = withA(c, light ? 0.5 : 0.4);
        ctx.lineWidth = o.w || 3;
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        ctx.stroke();
        // tổng chiều dài để rải hạt đều
        let total = 0; const segs = [];
        for (let i = 1; i < pts.length; i++) {
            const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
            segs.push(d); total += d;
        }
        const N = o.n || 3;
        for (let k = 0; k < N; k++) {
            let t = ((time * (o.speed || 0.22)) + k / N) % 1;
            let dist = t * total, i = 0;
            while (i < segs.length && dist > segs[i]) { dist -= segs[i]; i++; }
            if (i >= segs.length) i = segs.length - 1;
            const f = segs[i] ? dist / segs[i] : 0;
            const px = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f;
            const py = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f;
            if (!light) { ctx.shadowColor = withA(c, 0.9); ctx.shadowBlur = 12; }
            ctx.fillStyle = lite(c);
            ctx.beginPath(); ctx.arc(px, py, o.dot || 5, 0, Math.PI * 2); ctx.fill();
            noShadow();
        }
        ctx.restore();
    };
    // Kẻ phân cách mờ dần 2 đầu
    ui.divider = function (x1, x2, y) {
        ctx.save();
        const g = ctx.createLinearGradient(x1, 0, x2, 0);
        const mid = light ? 'rgba(30,45,90,0.25)' : 'rgba(255,255,255,0.25)';
        g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(0.5, mid); g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.strokeStyle = g; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
        ctx.restore();
    };
    // Nhân vật/hình PNG từ kho sprite của template — nhún + lắc nhẹ theo
    // time cho "sống"; thiếu sprite thì vẽ que đơn giản thay (không trắng hình).
    ui.sprite = function (name, cx, cy, size, o = {}) {
        size = size || 420;
        const img = (typeof global !== 'undefined' && global.SPRITES)
            ? global.getSprite(name) : null;
        ctx.save();
        /* ── HIỆU ỨNG VÀO (opt-in qua `o.e`) ──────────────────────────────
         * `o.e` = tiến độ 0..1, thường là `stepProgress` đã ease sẵn của code
         * AI. KHÔNG truyền → `e === 1` → NHÁNH DƯỚI KHÔNG CHẠY và hàm đi
         * nguyên đường cũ, từng pixel.
         *
         * ⚠️ Đó là chủ ý, không phải lười: bật hiệu ứng MẶC ĐỊNH sẽ đổi hình
         * của MỌI video đã có, kể cả các kênh đang bán trên bản Việt — người
         * dùng render lại một dự án cũ và nhận về một video khác. Cái giá của
         * opt-in là kịch bản cũ không có hiệu ứng; cái giá của mặc định là
         * phá đồ của khách. Chọn cái thứ nhất.
         *
         * `o.vao` chọn kiểu vào: 'len' (mặc định, trôi lên) · 'trai' · 'phai'
         * · 'mo' (chỉ mờ dần) · 'phong' (phóng nhẹ). Nhiều sprite trong một
         * step thì code AI tự so le `e` (vd `Math.min(1, Math.max(0, e*1.8 -
         * i*0.55))`) → chúng hiện LẦN LƯỢT thay vì chen nhau cùng lúc.
         */
        /* `o.ra` = tiến độ RA, 0..1 (0 còn nguyên · 1 biến mất hẳn). Dùng khi
         * một sprite MỚI vào ĐÈ LÊN CHỖ sprite cũ: không nhường chỗ thì hai
         * nhân vật chồng nhau và bong bóng thoại đè chéo — nhìn như lỗi vẽ.
         * Mờ dần KÈM lùi nhẹ ra sau (co lại còn 0.94) để mắt đọc được là "cái
         * này đang rời đi", chứ không phải "cái này bị mất nét".
         * Không truyền → không chạy → đường cũ nguyên vẹn. */
        const _ra = (o.ra === undefined || o.ra === null)
            ? 0 : Math.max(0, Math.min(1, o.ra));
        if (_ra > 0) {
            const rz = _ra * _ra;               // ease-in: giữ lâu rồi biến nhanh
            ctx.globalAlpha *= (1 - rz);
            const k = 1 - 0.06 * rz;
            ctx.translate(cx, cy); ctx.scale(k, k); ctx.translate(-cx, -cy);
        }
        const _e = (o.e === undefined || o.e === null)
            ? 1 : Math.max(0, Math.min(1, o.e));
        if (_e < 1) {
            const ez = 1 - Math.pow(1 - _e, 3);   // cubic-out, cùng lối các kit khác
            const vao = o.vao || 'len';
            const xa = size * 0.22;               // quãng trôi, tỉ lệ theo cỡ sprite
            let dx = 0, dy = 0;
            if (vao === 'len') dy = (1 - ez) * xa;
            else if (vao === 'trai') dx = -(1 - ez) * xa;
            else if (vao === 'phai') dx = (1 - ez) * xa;
            ctx.globalAlpha *= ez;
            ctx.translate(dx, dy);
            if (vao === 'phong') {
                // Phóng từ 0.88 → 1. Neo quanh (cx,cy) nên phải dịch về gốc,
                // scale, rồi dịch lại — scale thẳng sẽ kéo hình về góc canvas.
                const k = 0.88 + 0.12 * ez;
                ctx.translate(cx, cy); ctx.scale(k, k); ctx.translate(-cx, -cy);
            }
        }
        const bob = Math.sin(time * 2 + (o.seed || 0)) * (o.bob !== undefined ? o.bob : 8);
        const tilt = Math.sin(time * 1.6 + (o.seed || 0)) * (o.tilt !== undefined ? o.tilt : 0.045);
        ctx.translate(cx, cy + bob);
        ctx.rotate(tilt);
        if (img) {
            const s = size / Math.max(img.width, img.height);
            ctx.drawImage(img, -img.width * s / 2, -img.height * s / 2,
                          img.width * s, img.height * s);
        } else {
            // Thiếu sprite (vd chân dung người CHƯA có trong kho: Babbage, Ada…)
            // → BÓNG CHÂN DUNG trung tính (bust đầu+vai), KHÔNG hình que vàng
            //   (hình que trông như lỗi vẽ, lệch tông cạnh chân dung thật).
            ctx.shadowBlur = 0;
            ctx.fillStyle = 'rgba(66,66,74,0.5)';
            ctx.beginPath(); ctx.arc(0, -size * 0.14, size * 0.17, 0, Math.PI * 2); ctx.fill();
            ctx.beginPath(); ctx.ellipse(0, size * 0.44, size * 0.33, size * 0.30, 0, Math.PI, Math.PI * 2); ctx.fill();
        }
        ctx.restore();
    };
    ui.withA = withA; ui.mix = mix; ui.col = col; ui.lite = lite;
    return ui;
}

// ── Dữ liệu ký tự toán VECTOR cho mnk.mathGlyph ──────────────────────────
// Mỗi kind = mảng stroke; stroke = polyline [x,y] CHUẨN HOÁ trong [-0.5,0.5]²
// (y dương xuống). Đường cong xấp xỉ 8-14 đoạn — giữ style polyline như
// mnk.glyph cũ, KHÔNG bezier API. Stroke 1 điểm = chấm tô tròn (dots).
// Độ dài chuẩn hoá từng stroke tính SẴN một lần (tỉ lệ bất biến theo s).
const MN_MATH_GLYPHS = (function () {
    const D = Math.PI / 180;
    function arc(cx, cy, r, a0, a1, n) {
        const p = [];
        for (let i = 0; i <= n; i++) {
            const a = (a0 + (a1 - a0) * i / n) * D;
            p.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
        }
        return p;
    }
    function wave(y0, amp, n) {
        const p = [];
        for (let i = 0; i <= n; i++) {
            const u = i / n;
            p.push([-0.4 + 0.8 * u, y0 - amp * Math.sin(u * Math.PI * 2)]);
        }
        return p;
    }
    // ∫ — S-cong dọc mảnh (đối xứng tâm); tái dùng cho ∮
    const INT = [
        [0.20, -0.36], [0.17, -0.44], [0.10, -0.49], [0.03, -0.47],
        [0.00, -0.40], [-0.01, -0.25], [-0.01, 0.00], [-0.01, 0.25],
        [0.00, 0.40], [-0.03, 0.47], [-0.10, 0.49], [-0.17, 0.44],
        [-0.20, 0.36],
    ];
    // C hở (mở về phải) — dùng cho ∈ ∉ ⊂
    const CEE = arc(0, 0, 0.40, -60, -300, 12);
    const RAW = {
        // ∑ zigzag E-form 4 đoạn
        sum: [[[0.35, -0.42], [-0.35, -0.42], [0.02, 0.00], [-0.35, 0.42], [0.35, 0.42]]],
        integral: [INT],
        // ∮ = ∫ + vòng tròn nhỏ giữa
        ointegral: [INT, arc(0, 0, 0.14, -90, 270, 12)],
        // ∂ — móc hở trên (mở về trái) đổ xuống sườn phải + bụng tròn KHÉP kín
        partial: [[
            [-0.16, -0.38], [-0.07, -0.46], [0.04, -0.48], [0.13, -0.44],
            [0.19, -0.34], [0.22, -0.20], [0.22, -0.02], [0.19, 0.14],
        ].concat(arc(-0.01, 0.25, 0.235, -28, 332, 10).slice(1))],
        // ∇ tam giác ngược
        nabla: [[[-0.40, -0.38], [0.40, -0.38], [0.00, 0.42], [-0.40, -0.38]]],
        // ∞ — 2 vòng số 8 nằm, bút đi vòng trái rồi vòng phải ngược chiều
        infinity: [arc(-0.20, 0, 0.20, 0, 360, 12), arc(0.20, 0, 0.20, 180, -180, 12)],
        // ∈ = C hở + gạch ngang giữa
        'in': [CEE, [[-0.40, 0.00], [0.32, 0.00]]],
        // ∉ = ∈ + gạch chéo
        notin: [CEE, [[-0.40, 0.00], [0.32, 0.00]], [[0.20, -0.48], [-0.20, 0.48]]],
        subset: [CEE],
        // ⊆ = ⊂ (nâng nhẹ) + gạch dưới
        subseteq: [arc(0, -0.08, 0.34, -60, -300, 12), [[-0.34, 0.42], [0.34, 0.42]]],
        // ⊕ tròn + dấu cộng trong
        oplus: [arc(0, 0, 0.42, -90, 270, 12), [[-0.42, 0.00], [0.42, 0.00]], [[0.00, -0.42], [0.00, 0.42]]],
        // ⊗ tròn + X trong
        otimes: [arc(0, 0, 0.42, -90, 270, 12), [[-0.29, -0.29], [0.29, 0.29]], [[0.29, -0.29], [-0.29, 0.29]]],
        // ⋂ U úp: chân trái lên → vòm → chân phải xuống
        bigcap: [[[-0.32, 0.45]].concat(arc(0, -0.13, 0.32, 180, 360, 8)).concat([[0.32, 0.45]])],
        // ⋃ U ngửa
        bigcup: [[[-0.32, -0.45]].concat(arc(0, 0.13, 0.32, 180, 0, 8)).concat([[0.32, -0.45]])],
        // ≈ 2 sóng ngang
        approx: [wave(-0.13, 0.09, 10), wave(0.13, 0.09, 10)],
        // ≠ = 2 gạch + chéo
        neq: [[[-0.40, -0.13], [0.40, -0.13]], [[-0.40, 0.13], [0.40, 0.13]], [[0.20, -0.45], [-0.20, 0.45]]],
        // ≤ = < + gạch dưới
        leq: [[[0.28, -0.46], [-0.30, -0.09], [0.28, 0.28]], [[-0.30, 0.46], [0.28, 0.46]]],
        // ≥ = > + gạch dưới
        geq: [[[-0.28, -0.46], [0.30, -0.09], [-0.28, 0.28]], [[-0.28, 0.46], [0.30, 0.46]]],
        // ⌈⌉ 2 móc trên (vẽ từ chân lên rồi bẻ vào trong)
        ceil: [[[-0.30, 0.45], [-0.30, -0.45], [-0.12, -0.45]], [[0.30, 0.45], [0.30, -0.45], [0.12, -0.45]]],
        // ⌊⌋ 2 móc dưới
        floor: [[[-0.30, -0.45], [-0.30, 0.45], [-0.12, 0.45]], [[0.30, -0.45], [0.30, 0.45], [0.12, 0.45]]],
        // … 3 chấm tô tròn nhỏ
        dots: [[[-0.30, 0.00]], [[0.00, 0.00]], [[0.30, 0.00]]],
        // ── nhóm VẬT LÝ (08/08 — physics-lab dùng chung kit mnk nhưng thiếu
        // đúng các ký hiệu vật lý gọi nhiều nhất: T=2π√(L/g), F∝1/r², ±A...) ──
        // √ — đuôi trái, sụp đáy, vút lên đỉnh, gạch ngang phủ
        sqrt: [[[-0.44, 0.06], [-0.30, 0.00], [-0.12, 0.42], [0.10, -0.42], [0.46, -0.42]]],
        // ∝ — vòng trái khép + 2 cánh mở về phải (một nét liền)
        propto: [[[0.42, -0.34]].concat(arc(-0.06, 0, 0.27, -52, -308, 12)).concat([[0.42, 0.34]])],
        // ± = dấu cộng + gạch dưới
        pm: [[[0.00, -0.44], [0.00, 0.14]], [[-0.30, -0.15], [0.30, -0.15]], [[-0.34, 0.40], [0.34, 0.40]]],
        // × chéo kép (tích có hướng)
        times: [[[-0.32, -0.32], [0.32, 0.32]], [[0.32, -0.32], [-0.32, 0.32]]],
        // ∠ hai tia + cung đánh dấu góc
        angle: [[[0.40, -0.38], [-0.38, 0.38], [0.42, 0.38]], arc(-0.38, 0.38, 0.30, -44, 0, 6)],
        // ⊥ trụ đứng chạm sàn ngang
        perp: [[[0.00, -0.42], [0.00, 0.38]], [[-0.36, 0.38], [0.36, 0.38]]],
        // ∥ hai trụ song song
        parallel: [[[-0.11, -0.42], [-0.11, 0.42]], [[0.11, -0.42], [0.11, 0.42]]],
    };
    const out = {};
    for (const k in RAW) {
        out[k] = RAW[k].map(function (pts) {
            if (pts.length < 2) return { p: pts, len: 0.15, dot: true };
            let L = 0;
            for (let i = 1; i < pts.length; i++) {
                L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
            }
            return { p: pts, len: Math.max(L, 0.0001), dot: false };
        });
    }
    return out;
})();

// ── Bộ dựng cảnh MATH NOIR cho custom_js (mnk.*) ─────────────────────────
// Ngôn ngữ manim/3Blue1Bồ: đen tuyền + nét trắng MẢNH + đúng MỘT accent
// vàng. Mọi hàm vẽ nhận progress e (0..1, mặc định 1) và TỰ VẼ NÉT
// (clip/dash-offset/path cắt) — ease cubic-out bên trong, code AI chỉ đưa
// tiến độ thô (thường qua mnk.seq để so le). Kit không phụ thuộc artStyle
// về mặt code — dùng được ở mọi style, nhưng tông màu tune cho mathnoir.
function makeMnKit(ctx, time) {
    const INK = '#e8e8ea', MUTED = '#9a9aa0', FAINT = 'rgba(232,232,234,0.45)', ACCENT = '#facc15';
    const BLUE = '#60a5fa', GREEN = '#2f9e44';  // cặp màu ngữ nghĩa (2 vùng diện tích/so sánh)
    const FONT = "'Segoe UI', sans-serif";
    const CL = v => Math.max(0, Math.min(1, v));
    const EZ = t => 1 - Math.pow(1 - CL(t), 3); // cubic-out
    // sub-progress: đoạn [a..b] của e — để 1 hàm tự chia pha vẽ
    const seg = (e, a, b) => CL((e - a) / Math.max(b - a, 0.0001));
    function pen(color, lw) {
        ctx.strokeStyle = color || INK;
        ctx.lineWidth = lw || 2;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.setLineDash([]);
        ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
        ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
    }
    function rrPath(x, y, w, h, r) {
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
        else ctx.rect(x, y, w, h);
    }
    // đầu mũi tên nhỏ tại (x,y) theo hướng ang
    function head(x, y, ang, color, a) {
        const L = 13;
        ctx.save();
        ctx.globalAlpha *= CL(a);
        pen(color, 2);
        ctx.beginPath();
        ctx.moveTo(x - L * Math.cos(ang - 0.42), y - L * Math.sin(ang - 0.42));
        ctx.lineTo(x, y);
        ctx.lineTo(x - L * Math.cos(ang + 0.42), y - L * Math.sin(ang + 0.42));
        ctx.stroke();
        ctx.restore();
    }

    // hex #rrggbb → chuỗi rgba(...) với alpha a; màu dạng khác trả nguyên văn
    function rgba(c, a) {
        const m = /^#([0-9a-fA-F]{6})$/.exec(String(c));
        if (!m) return c;
        const n = parseInt(m[1], 16);
        return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' +
               (n & 255) + ',' + a + ')';
    }
    // token màu → hex thật: AI chỉ cần nhớ tên; mã màu thô đi thẳng qua
    function tone(name, dflt) {
        if (name === undefined || name === null || name === '') return dflt;
        const s = String(name).toLowerCase();
        if (s === 'blue') return BLUE;
        if (s === 'green') return GREEN;
        if (s === 'ink' || s === 'white') return INK;
        if (s === 'accent' || s === 'yellow' || s === 'gold') return ACCENT;
        if (s === 'muted') return MUTED;
        return String(name);
    }
    // Dựng path polyline tới tỉ lệ t theo CHIỀU DÀI tích luỹ (không theo số
    // đoạn — đoạn dài vẽ lâu hơn, tốc độ bút đều). Trả [x,y] đầu nét để đặt
    // orb. KHÔNG stroke — caller tự pen() + stroke().
    function pathTo(pts, t) {
        const L = [];
        let total = 0;
        for (let i = 1; i < pts.length; i++) {
            const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
            L.push(d); total += d;
        }
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        if (total <= 0) return [pts[0][0], pts[0][1]];
        const lim = total * CL(t) + 0.0001;  // +eps: t=1 không rơi nhánh cắt vì float
        let run = 0, hx = pts[0][0], hy = pts[0][1];
        for (let i = 1; i < pts.length; i++) {
            const d = L[i - 1];
            if (run + d <= lim) {
                hx = pts[i][0]; hy = pts[i][1];
                ctx.lineTo(hx, hy);
                run += d;
            } else {
                const u = d > 0 ? (lim - run) / d : 0;
                hx = pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * u;
                hy = pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * u;
                ctx.lineTo(hx, hy);
                break;
            }
        }
        return [hx, hy];
    }

    const mnk = {};
    // tokens lộ ra ngoài — code lắp ráp dùng lại đúng bảng màu
    mnk.INK = INK; mnk.MUTED = MUTED; mnk.FAINT = FAINT; mnk.ACCENT = ACCENT;
    mnk.BLUE = BLUE; mnk.GREEN = GREEN;

    // Tiến độ so le cho item i trong n item: item i bắt đầu sau
    // i*(1-overlap)/n (chuẩn hoá), mọi item cùng kết thúc tại P=1.
    mnk.seq = function (P, i, n, overlap) {
        overlap = overlap === undefined ? 0.35 : overlap;
        n = Math.max(1, n || 1);
        const start = i * (1 - overlap) / n;
        const dur = Math.max(1 - (n - 1) * (1 - overlap) / n, 0.0001);
        return CL((P - start) / dur);
    };

    // Hộp bo góc nét mảnh: viền tự vẽ vòng quanh, dash tuỳ chọn, label
    // nhỏ MUTED bên TRONG mép trên (kiểu "danh sách hữu hạn").
    mnk.box = function (x, y, w, h, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        const r = o.r === undefined ? 10 : o.r;
        const col = o.accent ? ACCENT : INK;
        ctx.save();
        if (o.fill) {
            ctx.save();
            ctx.globalAlpha *= seg(t, 0.25, 1);
            ctx.fillStyle = 'rgba(255,255,255,0.04)';
            rrPath(x, y, w, h, r); ctx.fill();
            ctx.restore();
        }
        pen(col, 2);
        if (o.dash) {
            // dash: lộ dần bằng clip quét ngang (giữ nhịp dash đều)
            ctx.save();
            ctx.beginPath();
            ctx.rect(x - 6, y - 6, (w + 12) * t, h + 12);
            ctx.clip();
            ctx.setLineDash([10, 8]);
            rrPath(x, y, w, h, r); ctx.stroke();
            ctx.restore();
        } else {
            // nét liền: tự vẽ vòng quanh chu vi bằng dash-offset
            const per = 2 * (w + h) + 2 * Math.PI * r - 8 * r + 4;
            ctx.setLineDash([per * t, per]);
            rrPath(x, y, w, h, r); ctx.stroke();
            ctx.setLineDash([]);
        }
        if (o.label) {
            ctx.save();
            ctx.globalAlpha *= seg(t, 0.45, 1);
            ctx.font = `500 24px ${FONT}`;
            ctx.fillStyle = MUTED;
            ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
            ctx.fillText(o.label, x + w / 2, y + 34);
            ctx.restore();
        }
        ctx.restore();
    };

    // MỘT gạch chéo phủ nhận (trên-trái → dưới-phải), tự vẽ theo e.
    mnk.cross = function (x, y, w, h, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        ctx.save();
        pen(o.color || FAINT, 2.5);
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + w * t, y + h * t);
        ctx.stroke();
        ctx.restore();
    };

    // Nhãn chữ: fade theo e + lún nhẹ 8px từ dưới lên.
    mnk.label = function (x, y, text, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        const size = o.size || 26;
        const muted = o.muted === undefined ? true : o.muted;
        ctx.save();
        ctx.globalAlpha *= t;
        ctx.font = `${o.bold ? 'bold ' : ''}${size}px ${FONT}`;
        ctx.fillStyle = o.accent ? ACCENT : (muted ? MUTED : INK);
        ctx.textAlign = o.align || 'center';
        ctx.textBaseline = 'alphabetic';
        ctx.shadowBlur = 0;
        ctx.fillText(text, x, y + 8 * (1 - t));
        ctx.restore();
    };

    // Mũi tên mảnh: thân mọc từ (x1,y1), đầu chỉ hiện khi e>0.85.
    mnk.arrow = function (x1, y1, x2, y2, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        const col = o.accent ? ACCENT : INK;
        const cx2 = x1 + (x2 - x1) * t, cy2 = y1 + (y2 - y1) * t;
        ctx.save();
        pen(col, 2);
        if (o.dash) ctx.setLineDash([10, 8]);
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(cx2, cy2); ctx.stroke();
        ctx.setLineDash([]);
        if (e > 0.85) head(cx2, cy2, Math.atan2(y2 - y1, x2 - x1), col, (e - 0.85) / 0.15);
        ctx.restore();
    };

    // Leader line ĐỨT cong nhẹ (quadratic, control lệch vuông góc ~40px),
    // màu FAINT — kiểu đường dẫn chú thích trong reference.
    mnk.connect = function (x1, y1, x2, y2, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        const dx = x2 - x1, dy = y2 - y1;
        const len = Math.max(Math.hypot(dx, dy), 0.0001);
        const cx = mx - dy / len * 40, cy = my + dx / len * 40;
        ctx.save();
        pen(FAINT, 2);
        ctx.setLineDash([8, 8]);
        ctx.beginPath();
        const N = 26;
        for (let i = 0; i <= Math.ceil(N * t); i++) {
            const u = Math.min(i / N, t);
            const a = 1 - u;
            const px = a * a * x1 + 2 * a * u * cx + u * u * x2;
            const py = a * a * y1 + 2 * a * u * cy + u * u * y2;
            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.stroke();
        ctx.restore();
    };

    // Công thức lớn bold INK, phần accent (substring) tô vàng; lộ dần bằng
    // clip ngang theo e; tự thu nhỏ khi tràn W-160.
    mnk.formula = function (x, y, text, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        let size = o.size || 52;
        const align = o.align || 'center';
        ctx.save();
        ctx.font = `bold ${size}px ${FONT}`;
        let tw = ctx.measureText(text).width;
        while (tw > W - 160 && size > 18) {
            size -= 2;
            ctx.font = `bold ${size}px ${FONT}`;
            tw = ctx.measureText(text).width;
        }
        let left = align === 'center' ? x - tw / 2 : (align === 'right' ? x - tw : x);
        ctx.beginPath();
        ctx.rect(left - 6, y - size * 1.25, (tw + 12) * t, size * 1.7);
        ctx.clip();
        ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
        const acc = o.accent || '';
        const idx = acc ? text.indexOf(acc) : -1;
        if (idx >= 0) {
            const pre = text.slice(0, idx), suf = text.slice(idx + acc.length);
            const wPre = ctx.measureText(pre).width;
            const wAcc = ctx.measureText(acc).width;
            ctx.fillStyle = INK;
            if (pre) ctx.fillText(pre, left, y);
            ctx.fillStyle = ACCENT;
            ctx.fillText(acc, left + wPre, y);
            ctx.fillStyle = INK;
            if (suf) ctx.fillText(suf, left + wPre + wAcc, y);
        } else {
            ctx.fillStyle = INK;
            ctx.fillText(text, left, y);
        }
        ctx.restore();
    };

    // Gạch ngang phủ định (đỏ dịu) mọc từ trái.
    mnk.strike = function (x, y, w, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        ctx.save();
        pen('rgba(248,113,113,0.9)', 3);
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w * t, y); ctx.stroke();
        ctx.restore();
    };

    // So sánh hai cột: hairline FAINT dọc giữa W/2 vẽ xuống + 2 tiêu đề
    // cột 30px MUTED fade ở đỉnh mỗi nửa.
    mnk.split = function (o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        const y0 = o.y0 || 0, h = o.h || 300;
        ctx.save();
        pen(FAINT, 1);
        ctx.beginPath();
        ctx.moveTo(W / 2, y0);
        ctx.lineTo(W / 2, y0 + h * t);
        ctx.stroke();
        const ta = seg(t, 0.3, 1);
        if (ta > 0) {
            ctx.globalAlpha *= ta;
            ctx.font = `600 30px ${FONT}`;
            ctx.fillStyle = MUTED;
            ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
            if (o.left) ctx.fillText(o.left, W / 4, y0 + 40);
            if (o.right) ctx.fillText(o.right, W * 0.75, y0 + 40);
        }
        ctx.restore();
    };

    // Mini-diagram nét mảnh, tâm (x,y), khung ~s×s, tự vẽ theo e.
    mnk.glyph = function (kind, x, y, s, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        const col = o.accent ? ACCENT : INK;
        const dot = (dx, dy, r, a) => {
            ctx.save(); ctx.globalAlpha *= CL(a);
            ctx.fillStyle = col;
            ctx.beginPath(); ctx.arc(dx, dy, r, 0, Math.PI * 2); ctx.fill();
            ctx.restore();
        };
        const line = (ax, ay, bx, by, u) => {
            if (u <= 0) return;
            ctx.beginPath(); ctx.moveTo(ax, ay);
            ctx.lineTo(ax + (bx - ax) * u, ay + (by - ay) * u); ctx.stroke();
        };
        ctx.save();
        ctx.translate(x, y);
        pen(col, 2);
        if (kind === 'line_pts') {
            line(-s * 0.4, s * 0.28, s * 0.4, -s * 0.28, seg(t, 0, 0.7));
            dot(-s * 0.4, s * 0.28, 4, seg(t, 0.6, 0.8));
            dot(s * 0.4, -s * 0.28, 4, seg(t, 0.8, 1));
        } else if (kind === 'segment') {
            const u = seg(t, 0, 0.8);
            line(-s * 0.45, 0, s * 0.45, 0, u);
            const ha = seg(t, 0.8, 1);
            head(s * 0.45, 0, 0, col, ha);
            head(-s * 0.45, 0, Math.PI, col, ha);
        } else if (kind === 'circle_r') {
            const r = s * 0.42;
            ctx.beginPath();
            ctx.arc(0, 0, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * seg(t, 0, 0.7));
            ctx.stroke();
            line(0, 0, r * 0.94, 0, seg(t, 0.65, 1));
            dot(0, 0, 3.5, seg(t, 0.6, 0.85));
        } else if (kind === 'right_angle') {
            const a = s * 0.38;
            line(-a, -a, -a, a, seg(t, 0, 0.5));            // cạnh đứng
            line(-a, a, a, a, seg(t, 0.4, 0.9));            // cạnh ngang
            const q = s * 0.16, qa = seg(t, 0.85, 1);
            if (qa > 0) {
                ctx.save(); ctx.globalAlpha *= qa;
                ctx.beginPath();
                ctx.moveTo(-a + q, a); ctx.lineTo(-a + q, a - q); ctx.lineTo(-a, a - q);
                ctx.stroke(); ctx.restore();
            }
        } else if (kind === 'axes') {
            const a = s * 0.4;
            line(-a, a * 0.8, a, a * 0.8, seg(t, 0, 0.5));   // trục x
            line(-a * 0.8, a, -a * 0.8, -a, seg(t, 0.35, 0.85));  // trục y
            const ha = seg(t, 0.85, 1);
            head(a, a * 0.8, 0, col, ha);
            head(-a * 0.8, -a, -Math.PI / 2, col, ha);
        } else if (kind === 'dots_curve') {
            const pts = [
                [-0.42, 0.30], [-0.25, 0.05], [-0.08, 0.22],
                [0.10, -0.12], [0.27, 0.02], [0.42, -0.30],
            ].map(p => [p[0] * s, p[1] * s]);
            for (let i = 0; i < pts.length; i++) {
                dot(pts[i][0], pts[i][1], 3.5, seg(t, i * 0.08, i * 0.08 + 0.15));
            }
            const cu = seg(t, 0.5, 1);
            if (cu > 0) {
                ctx.save();
                ctx.beginPath();
                ctx.rect(-s * 0.5, -s * 0.55, s * cu, s * 1.1);
                ctx.clip();
                ctx.beginPath();
                ctx.moveTo(pts[0][0], pts[0][1]);
                for (let i = 1; i < pts.length - 1; i++) {
                    const mx = (pts[i][0] + pts[i + 1][0]) / 2;
                    const my = (pts[i][1] + pts[i + 1][1]) / 2;
                    ctx.quadraticCurveTo(pts[i][0], pts[i][1], mx, my);
                }
                ctx.quadraticCurveTo(
                    pts[pts.length - 1][0], pts[pts.length - 1][1],
                    pts[pts.length - 1][0], pts[pts.length - 1][1]);
                ctx.stroke();
                ctx.restore();
            }
        } else if (kind === 'wave') {
            ctx.beginPath();
            const wN = 40, span = s * 0.9;
            const lim = Math.ceil(wN * t);
            for (let i = 0; i <= lim; i++) {
                const u = Math.min(i / wN, t);
                const px = -span / 2 + span * u;
                const py = -Math.sin(u * Math.PI * 2) * s * 0.28;
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            }
            ctx.stroke();
        } else if (kind === 'infinity') {
            ctx.globalAlpha *= t;
            ctx.font = `bold ${Math.round(s * 0.5)}px ${FONT}`;
            ctx.fillStyle = col;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText('∞', 0, 0);
        } else if (kind === 'parallel') {
            line(-s * 0.42, -s * 0.18, s * 0.42, -s * 0.18, seg(t, 0, 0.5));
            line(-s * 0.42, s * 0.18, s * 0.42, s * 0.18, seg(t, 0.3, 0.8));
            dot(s * 0.1, -s * 0.18, 4.5, seg(t, 0.75, 1));
        } else if (kind === 'bars') {
            // cột equalizer (nén nhạc / dữ liệu / thống kê)
            const hs = [0.55, 0.28, 0.14, 0.22, 0.34, 0.24, 0.46];
            const bw = s * 0.07, gap = s * 0.13, x0 = -gap * 3;
            for (let i = 0; i < hs.length; i++) {
                const u = seg(t, i * 0.09, i * 0.09 + 0.35);
                if (u <= 0) continue;
                const bh = s * hs[i] * u;
                ctx.fillStyle = col;
                ctx.fillRect(x0 + i * gap - bw / 2, s * 0.3 - bh, bw, bh);
            }
        } else if (kind === 'ecg') {
            // nhịp tim / tín hiệu (y tế, sóng xung)
            const span = s * 0.95, x0 = -span / 2;
            const beat = u => {
                const p = (u * 3) % 1;   // 3 nhịp trên chiều ngang
                if (p < 0.62 || p > 0.86) return 0;
                const q = (p - 0.62) / 0.24;
                return q < 0.35 ? -q / 0.35 * 0.32
                    : q < 0.7 ? (-0.32 + (q - 0.35) / 0.35 * 0.42)
                        : (0.1 - (q - 0.7) / 0.3 * 0.1);
            };
            ctx.beginPath();
            const N = 90, lim = Math.ceil(N * t);
            for (let i = 0; i <= lim; i++) {
                const u = Math.min(i / N, t);
                const px = x0 + span * u, py = beat(u) * s;
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            }
            ctx.stroke();
        } else if (kind === 'network') {
            // mạng: nút giữa + vệ tinh nối tia (di động, đồ thị, liên kết)
            const R = s * 0.42;
            const sats = [[-0.9, -0.35], [-0.55, 0.55], [0.5, -0.6],
                          [0.95, 0.1], [0.55, 0.62], [-1.0, 0.15]];
            for (let i = 0; i < sats.length; i++) {
                const sx = sats[i][0] * R, sy = sats[i][1] * R;
                line(0, 0, sx, sy, seg(t, 0.15 + i * 0.06, 0.5 + i * 0.06));
                dot(sx, sy, 3.5, seg(t, 0.45 + i * 0.06, 0.7 + i * 0.06));
            }
            dot(0, 0, 6, seg(t, 0, 0.3));
        } else if (kind === 'check') {
            // dấu ✓ nét vẽ dần (đạt / đúng / đã kiểm)
            line(-s * 0.3, s * 0.02, -s * 0.08, s * 0.24, seg(t, 0, 0.45));
            line(-s * 0.08, s * 0.24, s * 0.32, -s * 0.22, seg(t, 0.4, 1));
        } else if (kind === 'clock') {
            // đồng hồ: vòng + 2 kim (thời gian, chu kỳ, lịch sử)
            const r = s * 0.4;
            ctx.beginPath();
            ctx.arc(0, 0, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * seg(t, 0, 0.65));
            ctx.stroke();
            line(0, 0, 0, -r * 0.62, seg(t, 0.6, 0.85));
            line(0, 0, r * 0.42, r * 0.1, seg(t, 0.75, 1));
            dot(0, 0, 3, seg(t, 0.55, 0.75));
        }
        ctx.restore();
    };

    // Quầng ACCENT thở liên tục theo time — giữ cảnh đã vẽ xong "còn sống".
    mnk.pulse = function (x, y, r) {
        const a = 0.095 + 0.045 * Math.sin(time * 1.6);
        ctx.save();
        const g = ctx.createRadialGradient(x, y, 0, x, y, Math.max(r, 1));
        g.addColorStop(0, `rgba(250,204,21,${a.toFixed(3)})`);
        g.addColorStop(1, 'rgba(250,204,21,0)');
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, Math.max(r, 1), 0, Math.PI * 2); ctx.fill();
        ctx.restore();
    };

    // ── Primitive đợt 3: TỪ VỰNG chuyển động (trace/arcSweep/shape/ghost/
    // ring/orb) — AI ghép tự do theo TỪNG bài, không nhân bản layout cứng. ──

    // Hạt sáng: quầng radial-gradient (color→trong suốt, bán kính halo)
    // + lõi trắng r. Linh kiện chung: các primitive khác dùng làm "đầu bút"
    // khi đang vẽ (qua tuỳ chọn orb).
    mnk.orb = function (x, y, o) {
        o = o || {};
        const a = o.a === undefined ? 1 : CL(o.a);
        if (a <= 0) return;
        const r = o.r === undefined ? 5 : o.r;
        const halo = Math.max(o.halo === undefined ? 16 : o.halo, 1);
        const col = tone(o.color, ACCENT);
        ctx.save();
        ctx.globalAlpha *= a;
        const g = ctx.createRadialGradient(x, y, 0, x, y, halo);
        g.addColorStop(0, rgba(col, 0.85));
        g.addColorStop(0.55, rgba(col, 0.28));
        g.addColorStop(1, rgba(col, 0));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, halo, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.beginPath(); ctx.arc(x, y, Math.max(r, 0.5), 0, Math.PI * 2); ctx.fill();
        ctx.restore();
    };

    // Polyline vẽ dần theo chiều dài tích luỹ — nhận mảng [x,y] BẤT KỲ
    // (thẳng/gãy/cong xấp xỉ); orb đầu nét khi đang vẽ.
    mnk.trace = function (pts, o) {
        o = o || {};
        if (!pts || pts.length < 2) return;
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        ctx.save();
        pen(tone(o.color, INK), o.w === undefined ? 2.5 : o.w);
        if (o.dash) ctx.setLineDash([10, 8]);
        const hp = pathTo(pts, t);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();
        if ((o.orb === undefined ? true : o.orb) && t > 0 && t < 1) {
            mnk.orb(hp[0], hp[1], { r: 4, halo: 14 });
        }
    };

    // Cung vẽ dần a0→a0+(a1−a0)*e (radian, a1<a0 = ngược chiều) — tổng quát
    // MỌI "xoay/nhân −1/quét góc". sector:true → quạt mờ quét theo; label
    // đặt giữa cung, lộ khi e>0.5; orb đầu cung khi đang quét.
    mnk.arcSweep = function (cx, cy, r, a0, a1, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        const col = tone(o.color, ACCENT);
        const ccw = a1 < a0;
        const a2 = a0 + (a1 - a0) * t;
        ctx.save();
        if (o.sector) {
            ctx.save();
            ctx.fillStyle = 'rgba(232,232,234,0.08)';
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, r, a0, a2, ccw);
            ctx.closePath(); ctx.fill();
            ctx.restore();
        }
        pen(col, 2.5);
        if (o.dash === undefined ? true : o.dash) ctx.setLineDash([10, 8]);
        ctx.beginPath(); ctx.arc(cx, cy, r, a0, a2, ccw); ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();
        if (o.label) {
            const la = seg(e, 0.5, 0.9);
            if (la > 0) {
                const am = (a0 + a1) / 2;
                mnk.label(cx + Math.cos(am) * (r + 34),
                          cy + Math.sin(am) * (r + 34) + 9,
                          o.label, { e: la, size: 24 });
            }
        }
        if ((o.orb === undefined ? true : o.orb) && t > 0 && t < 1) {
            mnk.orb(cx + Math.cos(a2) * r, cy + Math.sin(a2) * r,
                    { r: 4, halo: 14, color: col });
        }
    };

    // Đa giác: NÉT chạy dần theo chu vi (orb đầu bút, xong ở 78% e); fill mờ
    // + label lộ SAU khi nét xong. fill nhận 'blue'|'green'|'ink'|'accent'
    // hoặc mã màu; glowLine → viền shadow thở theo time.
    mnk.shape = function (pts, o) {
        o = o || {};
        if (!pts || pts.length < 2) return;
        const e = o.e === undefined ? 1 : o.e;
        if (e <= 0) return;
        const col = tone(o.stroke, INK);
        const ts = EZ(seg(e, 0, 0.78));   // pha 1: nét chạy chu vi
        const fa = seg(e, 0.78, 1);       // pha 2: fill + label fade
        const closed = pts.concat([[pts[0][0], pts[0][1]]]);
        if (o.fill && fa > 0) {
            ctx.save();
            ctx.globalAlpha *= fa * 0.2;  // tô mờ ~0.2
            ctx.fillStyle = tone(o.fill, INK);
            ctx.beginPath();
            ctx.moveTo(pts[0][0], pts[0][1]);
            for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
            ctx.closePath(); ctx.fill();
            ctx.restore();
        }
        ctx.save();
        pen(col, o.w === undefined ? 2.5 : o.w);
        if (o.glowLine) {
            ctx.shadowColor = rgba(col, 0.55);
            ctx.shadowBlur = 10 + 4 * Math.sin(time * 1.6);
        }
        const hp = pathTo(closed, ts);
        ctx.stroke();
        ctx.restore();
        if (ts > 0 && ts < 1) mnk.orb(hp[0], hp[1], { r: 4, halo: 14 });
        if (o.label && fa > 0) {
            let cx0 = 0, cy0 = 0, top = Infinity, bot = -Infinity;
            for (let i = 0; i < pts.length; i++) {
                cx0 += pts[i][0]; cy0 += pts[i][1];
                if (pts[i][1] < top) top = pts[i][1];
                if (pts[i][1] > bot) bot = pts[i][1];
            }
            cx0 /= pts.length; cy0 /= pts.length;
            const at = o.labelAt || 'center';
            const ly = at === 'top' ? top - 18
                     : (at === 'bottom' ? bot + 40 : cy0 + 9);
            mnk.label(cx0, ly, o.label, { e: fa, muted: false });
        }
    };

    // BẢN SAO TRƯỢT: vẽ đa giác pts tịnh tiến (tx*e, ty*e) + xoay rot*e
    // quanh tâm hình, alpha dim→1 theo e — tổng quát MỌI mảnh ghép/đối
    // xứng/tịnh tiến. e=0 vẫn thấy bản mờ ở vị trí gốc (điểm xuất phát).
    mnk.ghost = function (pts, o) {
        o = o || {};
        if (!pts || pts.length < 2) return;
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        const dim = o.dim === undefined ? 0.55 : o.dim;
        let cx0 = 0, cy0 = 0;
        for (let i = 0; i < pts.length; i++) { cx0 += pts[i][0]; cy0 += pts[i][1]; }
        cx0 /= pts.length; cy0 /= pts.length;
        ctx.save();
        ctx.globalAlpha *= dim + (1 - dim) * t;
        ctx.translate(cx0 + (o.tx || 0) * t, cy0 + (o.ty || 0) * t);
        ctx.rotate((o.rot || 0) * t);
        ctx.translate(-cx0, -cy0);
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        ctx.closePath();
        if (o.fill) {
            ctx.save();
            ctx.globalAlpha *= 0.2;
            ctx.fillStyle = tone(o.fill, INK);
            ctx.fill();
            ctx.restore();
        }
        pen(tone(o.stroke, INK), o.w === undefined ? 2.5 : o.w);
        ctx.stroke();
        ctx.restore();
    };

    // Elip chú thích KHOANH TRÒN vùng bất kỳ — vẽ dần theo góc từ chếch
    // trên-trái (kiểu khoanh tay), nghiêng tilt, orb đầu bút khi đang vẽ.
    mnk.ring = function (cx, cy, rx, ry, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        rx = Math.max(rx || 0, 1);
        ry = Math.max(ry === undefined || ry === null ? rx : ry, 1);
        const col = tone(o.color, ACCENT);
        const tilt = o.tilt === undefined ? -0.06 : o.tilt;
        const a0 = -Math.PI * 0.72;
        const a2 = a0 + Math.PI * 2 * t;
        ctx.save();
        ctx.translate(cx, cy); ctx.rotate(tilt);
        pen(col, 2.5);
        ctx.beginPath();
        ctx.ellipse(0, 0, rx, ry, 0, a0, a2);
        ctx.stroke();
        ctx.restore();
        if (t > 0 && t < 1) {
            const px = Math.cos(a2) * rx, py = Math.sin(a2) * ry;
            mnk.orb(cx + px * Math.cos(tilt) - py * Math.sin(tilt),
                    cy + px * Math.sin(tilt) + py * Math.cos(tilt),
                    { r: 4, halo: 14, color: col });
        }
    };

    // Ký tự toán VECTOR vẽ-nét-dần (draw-on): data chuẩn hoá [-0.5,0.5]²
    // trong MN_MATH_GLYPHS (module scope). Tổng chiều dài mọi stroke →
    // bút chạy stroke này NỐI stroke kia như người viết phấn; orb đầu bút
    // khi 0<e<1 (tắt bằng o.orb:false). Tâm (x,y), cao s.
    mnk.mathGlyph = function (kind, x, y, s, o) {
        o = o || {};
        const e = o.e === undefined ? 1 : o.e, t = EZ(e);
        if (t <= 0) return;
        const strokes = MN_MATH_GLYPHS[String(kind)];
        const col = tone(o.color, INK);
        if (!strokes) {
            // Kind lạ TRƯỚC ĐÂY im lặng biến mất (cùng họ bệnh vl_duong cảnh
            // đen) — giờ fallback FONT: tên Hy Lạp/ký hiệu quen map unicode,
            // kind ≤2 ký tự vẽ thẳng chính nó; fade theo e, không orb.
            const FB = {
                theta: 'θ', omega: 'ω', lambda: 'λ', alpha: 'α', beta: 'β',
                gamma: 'γ', delta: 'Δ', pi: 'π', mu: 'μ', phi: 'φ',
                tau: 'τ', rho: 'ρ', sigma: 'σ', epsilon: 'ε', hbar: 'ℏ',
                deg: '°', cdot: '·', arrow: '→', to: '→', implies: '⇒',
            };
            const ch = FB[String(kind)]
                || (String(kind).length <= 2 ? String(kind) : null);
            if (!ch) return;
            ctx.save();
            ctx.globalAlpha = t;
            ctx.fillStyle = col;
            ctx.font = '400 ' + Math.max(8, Math.round(s)) + 'px ' + FONT;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(ch, x, y);
            ctx.restore();
            return;
        }
        let total = 0;
        for (let i = 0; i < strokes.length; i++) total += strokes[i].len;
        const lim = total * t + 0.0001;   // +eps: t=1 vẽ trọn stroke cuối
        const dotR = Math.max(s * 0.045, 2);
        let run = 0, hx = null, hy = null;
        ctx.save();
        pen(col, o.w === undefined ? 2.5 : o.w);
        for (let i = 0; i < strokes.length; i++) {
            const st = strokes[i];
            if (run >= lim) break;
            const u = Math.min(1, (lim - run) / st.len);
            if (st.dot) {
                hx = x + st.p[0][0] * s; hy = y + st.p[0][1] * s;
                ctx.save();
                ctx.fillStyle = col;
                ctx.beginPath();
                ctx.arc(hx, hy, dotR * u, 0, Math.PI * 2);
                ctx.fill();
                ctx.restore();
            } else {
                const ap = [];
                for (let j = 0; j < st.p.length; j++) {
                    ap.push([x + st.p[j][0] * s, y + st.p[j][1] * s]);
                }
                const hp = pathTo(ap, u);
                ctx.stroke();
                hx = hp[0]; hy = hp[1];
            }
            run += st.len;
        }
        ctx.restore();
        if ((o.orb === undefined ? true : o.orb) && t < 1 && hx !== null) {
            mnk.orb(hx, hy, { r: 4, halo: 14, color: col });
        }
    };

    // CHỐNG BỊA HÀM: model hay gọi nhầm hàm của bộ ui.* (mnk.glass, mnk.chip,
    // mnk.kpi...) — TypeError một phát là chết cả sơ đồ. Alias về hàm gần
    // nghĩa nhất; tên hoàn toàn lạ → no-op có cảnh báo, phần còn lại vẫn vẽ.
    const MNK_ALIAS = {
        glass: 'box', card: 'box', panel: 'box',
        chip: 'label', badge: 'label', text: 'label', title: 'label',
        kpi: 'formula', big: 'formula',
        divider: 'strike', line: 'arrow', bar: 'arrow',
        // dot GIỮ trỏ pulse (alias có trước đợt 3 — không đổi nghĩa);
        // ring giờ là hàm THẬT nên Proxy ưu tiên target, alias cũ ring→pulse bỏ.
        icon: 'glyph', dot: 'pulse',
        circle: 'ring', oval: 'ring',
        glyphMath: 'mathGlyph',
    };
    return new Proxy(mnk, {
        get(target, prop) {
            if (prop in target) return target[prop];
            const alias = MNK_ALIAS[prop];
            if (alias && alias in target) return target[alias];
            if (typeof prop === 'string') {
                process.stderr.write(`[mnk] unknown fn '${prop}' -> no-op\n`);
                return function () {};
            }
            return undefined;
        },
    });
}

// ── Bộ dựng cảnh EDITORIAL CREAM cho custom_js (eck.*) ───────────────────
// Mô hình "kit + AI tự lắp" (giống mnk.*): kit cấp LINH KIỆN, AI chỉ quyết
// bố cục. Ngôn ngữ hình bám video mẫu Editorial Cream: nền cream, mực đen,
// đúng MỘT accent cam, nét MẢNH 2–3px, KHÔNG card/khối nền tối, tối giản
// kiểu tạp chí. Mọi hàm vẽ nhận progress e (0..1, mặc định 1) và TỰ VẼ DẦN
// (dash-offset / clip quét / cắt path) — ease cubic-out nằm trong kit, code
// AI chỉ đưa tiến độ thô (thường qua eck.seq để so le).
// Màu KHÔNG hardcode: đọc T.* runtime MỘT LẦN ở đây → đổi theme là đổi theo.
// Kit KHÔNG tự vẽ nền (nền cream do engine lo).
function makeEckKit(ctx, time, T) {
    T = T || {};
    const INK = T.textColor || '#1A1A1A';
    const ORANGE = T.hlColor || '#E8440A';
    const MUTED = T.mutedColor || '#888580';
    const CREAM = T.whiteColor || '#ECEAE4';
    // Font: KHÔNG family cụ thể. T.font là stack của theme/người dùng (đã có
    // đuôi SYSTEM_FONT_STACK đủ dấu Việt/CJK). Kit nhận ctx THẬT chứ không
    // phải customCtx nên KHÔNG đi qua proxy rewrite 'sans-serif'→T.font —
    // đọc thẳng T.font là đường duy nhất ăn được font người dùng chọn.
    const FONT = T.font || 'sans-serif';
    const CL = v => Math.max(0, Math.min(1, v));
    const EZ = t => 1 - Math.pow(1 - CL(t), 3);           // cubic-out
    const seg = (e, a, b) => CL((e - a) / Math.max(b - a, 0.0001));

    // token màu → hex thật. Nhận cả hex/rgb() thô để AI không bị chặn.
    function col(name, dflt) {
        if (name === undefined || name === null || name === '') return dflt;
        const s = String(name).toLowerCase();
        if (s === 'orange' || s === 'accent' || s === 'hl' || s === 'red') return ORANGE;
        if (s === 'ink' || s === 'text' || s === 'black' || s === 'dark') return INK;
        if (s === 'muted' || s === 'gray' || s === 'grey' || s === 'faint') return MUTED;
        if (s === 'cream' || s === 'white' || s === 'bg' || s === 'paper') return CREAM;
        if (s === 'none' || s === 'transparent') return null;
        if (s.charAt(0) === '#' || s.indexOf('rgb') === 0 || s.indexOf('hsl') === 0) return name;
        return dflt;
    }
    // pha alpha cho MỘT token màu (vùng tô nhạt / track) — vẫn không hardcode
    // hex: màu vào là màu đã lấy từ T.
    function fade(c, a) {
        const m = String(c).match(/^#([0-9a-fA-F]{6})$/);
        if (m) {
            const n = parseInt(m[1], 16);
            return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
        }
        const r = String(c).match(/rgba?\(([^)]+)\)/);
        if (r) {
            const p = r[1].split(',');
            return 'rgba(' + (p[0] || 0).trim() + ',' + (p[1] || 0).trim() + ',' + (p[2] || 0).trim() + ',' + a + ')';
        }
        return c;
    }
    function pen(c, lw, dash) {
        ctx.strokeStyle = c || INK;
        ctx.lineWidth = lw || 2.5;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.setLineDash(dash ? [9, 8] : []);
        ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
        ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
    }
    function rrPath(x, y, w, h, r) {
        r = Math.max(0, Math.min(r || 0, Math.min(Math.abs(w), Math.abs(h)) / 2));
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
        else ctx.rect(x, y, w, h);
    }
    function fnt(size, weight) {
        return (weight ? weight + ' ' : '') + Math.max(8, Math.round(size)) + 'px ' + FONT;
    }
    // đầu mũi tên nhỏ, mảnh — hai nét chứ không phải tam giác đặc
    function tip(x, y, ang, c, a, lw) {
        const L = 15;
        ctx.save();
        ctx.globalAlpha *= CL(a);
        pen(c, lw || 2.5);
        ctx.beginPath();
        ctx.moveTo(x - L * Math.cos(ang - 0.4), y - L * Math.sin(ang - 0.4));
        ctx.lineTo(x, y);
        ctx.lineTo(x - L * Math.cos(ang + 0.4), y - L * Math.sin(ang + 0.4));
        ctx.stroke();
        ctx.restore();
    }

    const eck = {};
    // tokens lộ ra ngoài — code lắp ráp dùng lại đúng bảng màu
    eck.INK = INK; eck.ORANGE = ORANGE; eck.MUTED = MUTED; eck.CREAM = CREAM;

    // Tiến độ so le cho item i trong n item (giống mnk.seq): item i bắt đầu
    // sau i*(1-overlap)/n, mọi item cùng kết thúc tại P=1.
    eck.seq = function (P, i, n, overlap) {
        overlap = overlap === undefined ? 0.35 : overlap;
        n = Math.max(1, n || 1);
        const start = i * (1 - overlap) / n;
        const dur = Math.max(1 - (n - 1) * (1 - overlap) / n, 0.0001);
        return CL((P - start) / dur);
    };

    // Khung/khối. fill:'orange'|'ink' → khối đặc (lộ dần bằng clip quét ngang);
    // fill:'none' (mặc định) → chỉ VIỀN, tự vẽ vòng quanh chu vi bằng dash-offset.
    eck.box = function (x, y, w, h, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        const r = o.r === undefined ? 8 : o.r;
        const lw = o.lw === undefined ? 2.5 : o.lw;
        const f = col(o.fill, null);
        ctx.save();
        if (f) {
            ctx.save();
            ctx.beginPath(); ctx.rect(x - 1, y - 1, w * t + 2, h + 2); ctx.clip();
            ctx.fillStyle = f;
            rrPath(x, y, w, h, r); ctx.fill();
            ctx.restore();
        } else if (o.dash) {
            // dash: lộ dần bằng clip quét ngang (giữ nhịp dash đều, không "bò")
            ctx.save();
            pen(col(o.color, INK) || INK, lw, true);
            ctx.beginPath(); ctx.rect(x - lw - 2, y - lw - 2, (w + 2 * lw + 4) * t, h + 2 * lw + 4); ctx.clip();
            rrPath(x, y, w, h, r); ctx.stroke();
            ctx.restore();
        } else {
            pen(col(o.color, INK) || INK, lw, false);
            const per = 2 * (w + h) + 2 * Math.PI * r - 8 * r + 4;
            ctx.setLineDash([per * t, per + 10]);
            rrPath(x, y, w, h, r); ctx.stroke();
            ctx.setLineDash([]);
        }
        ctx.restore();
    };

    // Ô cam bo góc nhỏ chứa số/nhãn ngắn (ô đánh số của video mẫu). Chữ luôn
    // tô CREAM để đọc được trên nền cam/mực.
    eck.chip = function (cx, cy, text, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        const s = (text === undefined || text === null) ? '' : String(text);
        const size = o.size || 26;
        const bg = col(o.fill, ORANGE) || ORANGE;
        ctx.save();
        ctx.font = fnt(size, 'bold');
        const tw = ctx.measureText(s).width;
        const padX = Math.round(size * 0.60), padY = Math.round(size * 0.40);
        const h = size + padY * 2;
        const w = Math.max(tw + padX * 2, h);
        ctx.globalAlpha *= t;
        ctx.translate(cx, cy);
        const k = 0.86 + 0.14 * t;
        ctx.scale(k, k);
        ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
        ctx.fillStyle = bg;
        rrPath(-w / 2, -h / 2, w, h, Math.round(size * 0.26)); ctx.fill();
        ctx.fillStyle = col(o.textColor, CREAM) || CREAM;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(s, 0, Math.round(size * 0.04));
        ctx.restore();
    };

    // Chữ. maxW>0 → TỰ THU font cho vừa (bài học title tràn khung).
    // Fade theo e + lún nhẹ 8px từ dưới lên.
    eck.label = function (x, y, text, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        const s = (text === undefined || text === null) ? '' : String(text);
        let size = o.size || 26;
        const wg = o.weight || '';
        ctx.save();
        ctx.font = fnt(size, wg);
        const maxW = o.maxW || 0;
        if (maxW > 0) {
            let tw = ctx.measureText(s).width;
            while (tw > maxW && size > 10) {
                size -= 1;
                ctx.font = fnt(size, wg);
                tw = ctx.measureText(s).width;
            }
        }
        ctx.globalAlpha *= t;
        ctx.fillStyle = col(o.color, INK) || INK;
        ctx.textAlign = o.align || 'left';
        ctx.textBaseline = o.baseline || 'alphabetic';
        ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
        ctx.fillText(s, x, y + 8 * (1 - t));
        ctx.restore();
    };

    // Kẻ ngang mảnh — mọc từ x1 sang x2 theo e.
    eck.rule = function (x1, x2, y, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        ctx.save();
        pen(col(o.color, MUTED) || MUTED, o.lw === undefined ? 1.5 : o.lw, !!o.dash);
        ctx.beginPath();
        ctx.moveTo(x1, y); ctx.lineTo(x1 + (x2 - x1) * t, y);
        ctx.stroke();
        ctx.restore();
    };

    // Mũi tên / đường nối. curve>0 → cong (control lệch vuông góc `curve` px).
    // Đầu mũi tên chỉ hiện ở cuối (e>0.8) để không "trôi" theo thân.
    eck.arrow = function (x1, y1, x2, y2, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        const c = col(o.color, ORANGE) || ORANGE;
        const lw = o.lw === undefined ? 2.5 : o.lw;
        const curve = o.curve || 0;
        const wantTip = o.head === undefined ? true : !!o.head;
        let ex = x2, ey = y2, ang = Math.atan2(y2 - y1, x2 - x1);
        ctx.save();
        pen(c, lw, !!o.dash);
        if (curve) {
            const dx = x2 - x1, dy = y2 - y1;
            const len = Math.max(Math.hypot(dx, dy), 0.0001);
            const kx = (x1 + x2) / 2 - dy / len * curve;
            const ky = (y1 + y2) / 2 + dx / len * curve;
            const N = 44, lim = Math.max(1, Math.ceil(N * t));
            let px0 = x1, py0 = y1;
            ctx.beginPath();
            for (let i = 0; i <= lim; i++) {
                const u = Math.min(i / N, t), a = 1 - u;
                const px = a * a * x1 + 2 * a * u * kx + u * u * x2;
                const py = a * a * y1 + 2 * a * u * ky + u * u * y2;
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
                if (i === lim) { ang = Math.atan2(py - py0, px - px0); ex = px; ey = py; }
                px0 = px; py0 = py;
            }
            ctx.stroke();
        } else {
            ex = x1 + (x2 - x1) * t; ey = y1 + (y2 - y1) * t;
            ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(ex, ey); ctx.stroke();
        }
        ctx.setLineDash([]);
        if (wantTip && t > 0.8) tip(ex, ey, ang, c, (t - 0.8) / 0.2, lw);
        ctx.restore();
    };

    // Chấm. ring:true → vòng rỗng nét mảnh thay vì chấm đặc.
    eck.dot = function (cx, cy, r, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        const c = col(o.color, ORANGE) || ORANGE;
        const rr = Math.max((r === undefined ? 7 : r) * t, 0.5);
        ctx.save();
        ctx.globalAlpha *= t;
        ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
        if (o.ring) {
            pen(c, o.lw === undefined ? 2.5 : o.lw);
            ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.stroke();
        } else {
            ctx.fillStyle = c;
            ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.fill();
        }
        ctx.restore();
    };

    // Thanh tỉ lệ p(0..1). track:true → rãnh xám rất nhạt phía sau.
    eck.bar = function (x, y, w, h, p, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        const q = CL(p === undefined ? 1 : p) * t;
        const c = col(o.color, ORANGE) || ORANGE;
        const track = o.track === undefined ? true : !!o.track;
        const rBase = o.r === undefined ? Math.min(Math.abs(w), Math.abs(h)) / 2 : o.r;
        ctx.save();
        ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
        if (track) {
            ctx.save();
            ctx.globalAlpha *= t;
            ctx.fillStyle = fade(MUTED, 0.22);
            rrPath(x, y, w, h, rBase); ctx.fill();
            ctx.restore();
        }
        if (q > 0.002) {
            ctx.fillStyle = c;
            if (o.vertical) rrPath(x, y + h * (1 - q), w, h * q, Math.min(rBase, Math.abs(w) / 2));
            else rrPath(x, y, w * q, h, Math.min(rBase, Math.abs(h) / 2));
            ctx.fill();
        }
        ctx.restore();
    };

    // Hàng n ô vuông, `filled` ô ĐẦU tô cam, phần còn lại chỉ viền mực
    // (mẫu "5 ô" của video gốc). labels[] = nhãn xám nhỏ dưới từng ô.
    eck.blocks = function (x, y, n, filled, o) {
        o = o || {};
        const E = o.e === undefined ? 1 : o.e;
        n = Math.max(0, Math.round(n || 0));
        filled = Math.max(0, Math.min(n, Math.round(filled || 0)));
        const size = o.size || 52;
        const gap = o.gap === undefined ? 14 : o.gap;
        const labels = o.labels || [];
        const rad = Math.round(size * 0.16);
        for (let i = 0; i < n; i++) {
            const q = eck.seq(E, i, n, 0.55);
            if (q <= 0) continue;
            const bx = x + i * (size + gap);
            if (i < filled) {
                const t = EZ(q);
                ctx.save();
                ctx.globalAlpha *= t;
                ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
                ctx.fillStyle = ORANGE;
                rrPath(bx, y, size, size, rad); ctx.fill();
                ctx.restore();
            } else {
                eck.box(bx, y, size, size, { r: rad, lw: o.lw === undefined ? 2.5 : o.lw, color: 'ink', e: q });
            }
            const lb = labels[i];
            if (lb !== undefined && lb !== null && lb !== '') {
                // CAP 30px: ô 130px mà nhân 0.34 ra chữ 44px — to ngang tiêu đề,
                // phá tôn ti editorial. Nhãn dưới ô luôn là chú thích phụ.
                eck.label(bx + size / 2, y + size + Math.round(size * 0.46), String(lb),
                    { size: Math.min(Math.round(size * 0.34), 30), align: 'center',
                      color: 'muted', maxW: size + gap, e: q });
            }
        }
    };

    // Trục đồ thị mảnh (chữ L): trục dọc mọc xuống trước, trục ngang mọc phải
    // sau. (x,y) = GÓC TRÊN-TRÁI vùng vẽ, w/h = kích thước vùng vẽ.
    eck.axis = function (x, y, w, h, o) {
        o = o || {};
        const E = o.e === undefined ? 1 : o.e;
        const t = EZ(E);
        if (t <= 0) return;
        const c = col(o.color, MUTED) || MUTED;
        const a = seg(t, 0, 0.5), b = seg(t, 0.35, 1);
        ctx.save();
        pen(c, o.lw === undefined ? 1.5 : o.lw);
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y + h * a); ctx.stroke();
        if (b > 0) { ctx.beginPath(); ctx.moveTo(x, y + h); ctx.lineTo(x + w * b, y + h); ctx.stroke(); }
        ctx.restore();
        const size = o.size || 22;
        const xl = o.xLabels || [];
        for (let i = 0; i < xl.length; i++) {
            const px = xl.length === 1 ? x + w / 2 : x + w * i / (xl.length - 1);
            eck.label(px, y + h + size + 12, String(xl[i]),
                { size: size, align: 'center', color: 'muted', maxW: o.maxW || 0,
                  e: seg(E, 0.5 + i * 0.04, 0.85 + i * 0.04) });
        }
        if (o.yHint) {
            eck.label(x - 2, y - 14, String(o.yHint),
                { size: size, align: 'left', color: 'muted', e: seg(E, 0.55, 0.9) });
        }
    };

    // Đường dữ liệu VẼ DẦN + vùng tô nhạt dưới đường. `points` nhận 2 dạng:
    // [0.2, 0.5, 0.9] (y chuẩn hoá 0..1, x chia đều) hoặc [[x,y],...] (cả hai
    // chuẩn hoá 0..1). (x,y,w,h) trùng vùng vẽ của eck.axis.
    eck.plot = function (x, y, w, h, points, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        const src = points || [];
        const pts = [];
        for (let i = 0; i < src.length; i++) {
            const p = src[i];
            let u, v;
            if (Array.isArray(p)) { u = +p[0]; v = +p[1]; }
            else { u = src.length === 1 ? 0.5 : i / (src.length - 1); v = +p; }
            if (!isFinite(u) || !isFinite(v)) continue;
            pts.push([x + w * CL(u), y + h * (1 - CL(v))]);
        }
        if (pts.length < 2) return;
        const c = col(o.color, ORANGE) || ORANGE;
        const total = pts.length - 1;
        const cut = total * t;
        const kLast = Math.min(total, Math.floor(cut));
        const frac = cut - kLast;
        const path = pts.slice(0, kLast + 1);
        if (kLast < total && frac > 0) {
            const A = pts[kLast], B = pts[kLast + 1];
            path.push([A[0] + (B[0] - A[0]) * frac, A[1] + (B[1] - A[1]) * frac]);
        }
        if (path.length < 2) return;
        ctx.save();
        ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
        if (o.fill !== false) {
            ctx.save();
            ctx.fillStyle = fade(c, 0.13);
            ctx.beginPath();
            ctx.moveTo(path[0][0], y + h);
            for (let i = 0; i < path.length; i++) ctx.lineTo(path[i][0], path[i][1]);
            ctx.lineTo(path[path.length - 1][0], y + h);
            ctx.closePath(); ctx.fill();
            ctx.restore();
        }
        pen(c, o.lw === undefined ? 3 : o.lw, !!o.dash);
        ctx.beginPath();
        for (let i = 0; i < path.length; i++) {
            if (i === 0) ctx.moveTo(path[i][0], path[i][1]);
            else ctx.lineTo(path[i][0], path[i][1]);
        }
        ctx.stroke();
        ctx.setLineDash([]);
        if (o.marks !== false) {
            ctx.fillStyle = c;
            for (let i = 0; i <= kLast; i++) {
                ctx.beginPath(); ctx.arc(pts[i][0], pts[i][1], o.markR || 5, 0, Math.PI * 2); ctx.fill();
            }
        }
        ctx.restore();
    };

    // Cột dọc các dòng, đầu dòng là chấm cam (style:'dot') hoặc ô số cam
    // (style:'num'). cx = TÂM của cả khối (marker + chữ) → truyền W/2 là cân.
    eck.stack = function (cx, y, items, o) {
        o = o || {};
        const E = o.e === undefined ? 1 : o.e;
        const list = items || [];
        if (!list.length) return;
        const size = o.size || 26;
        const gap = o.gap === undefined ? 44 : o.gap;
        const num = (o.style || 'dot') === 'num';
        const wg = o.weight || '';
        const indent = Math.round(size * (num ? 2.0 : 1.5));
        ctx.save();
        ctx.font = fnt(size, wg);
        let tw = 0;
        for (let i = 0; i < list.length; i++) tw = Math.max(tw, ctx.measureText(String(list[i])).width);
        ctx.restore();
        const cap = o.maxW ? Math.max(o.maxW - indent, 40) : 0;
        if (cap > 0) tw = Math.min(tw, cap);
        const left = cx - (indent + tw) / 2;
        const dy = Math.round(size * 0.34);
        for (let i = 0; i < list.length; i++) {
            const q = eck.seq(E, i, list.length, 0.5);
            if (q <= 0) continue;
            const ly = y + i * gap;
            if (num) eck.chip(left + Math.round(size * 0.62), ly - dy, String(i + 1), { size: Math.round(size * 0.70), e: q });
            else eck.dot(left + Math.round(size * 0.40), ly - dy, Math.round(size * 0.22), { e: q });
            eck.label(left + indent, ly, String(list[i]),
                { size: size, align: 'left', color: o.color || 'ink', weight: wg, maxW: cap, e: q });
        }
    };

    // Nhịp thở cam rất nhẹ theo `time` — giữ cảnh đã vẽ xong "còn sống".
    // Trên nền cream phải NHẠT, đậm một chút là thành vệt bẩn.
    // o.e KHÔNG bắt buộc (chữ ký gốc là 3 tham số) nhưng NÊN truyền: không có
    // nó thì quầng hiện ngay từ e=0 → đốm cam lơ lửng giữa nền trống, trước cả
    // cái nó định nhấn. Đo được ở frame sớm, không phải suy luận.
    eck.pulse = function (cx, cy, r, o) {
        o = o || {};
        const t = EZ(o.e === undefined ? 1 : o.e);
        if (t <= 0) return;
        const R = Math.max(r || 40, 1);
        const a = (0.075 + 0.04 * Math.sin((time || 0) * 1.8)) * t;
        ctx.save();
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
        g.addColorStop(0, fade(ORANGE, Math.max(a, 0.01).toFixed(3)));
        g.addColorStop(1, fade(ORANGE, 0));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
    };

    // CHỐNG BỊA HÀM (bài học mnk): model SẼ gọi hàm không tồn tại — hàm của
    // bộ ui.* (eck.glass/eck.kpi), hoặc tên tự nghĩ ra. TypeError một phát là
    // chết cả sơ đồ. Alias về hàm gần nghĩa nhất; tên hoàn toàn lạ → no-op có
    // cảnh báo, phần còn lại của cảnh VẪN VẼ.
    const ECK_ALIAS = {
        glass: 'box', card: 'box', panel: 'box', frame: 'box', rect: 'box', square: 'box',
        badge: 'chip', pill: 'chip', tag: 'chip', num: 'chip', number: 'chip', step: 'chip',
        text: 'label', title: 'label', heading: 'label', caption: 'label', kpi: 'label',
        big: 'label', stat: 'label', value: 'label', note: 'label',
        divider: 'rule', line: 'rule', hr: 'rule', sep: 'rule', separator: 'rule', underline: 'rule',
        connect: 'arrow', link: 'arrow', pointer: 'arrow', leader: 'arrow', curve: 'arrow',
        circle: 'dot', point: 'dot', marker: 'dot', bullet: 'dot',
        progress: 'bar', meter: 'bar', gauge: 'bar', track: 'bar', column: 'bar',
        grid: 'blocks', cells: 'blocks', squares: 'blocks', row: 'blocks', boxes: 'blocks',
        axes: 'axis', chart: 'plot', graph: 'plot', curveLine: 'plot', trend: 'plot', sparkline: 'plot',
        list: 'stack', bullets: 'stack', items: 'stack', steps: 'stack',
        glow: 'pulse', halo: 'pulse', ring: 'pulse', breathe: 'pulse',
    };
    return new Proxy(eck, {
        get(target, prop) {
            if (prop in target) return target[prop];
            const alias = ECK_ALIAS[prop];
            if (alias && alias in target) return target[alias];
            if (typeof prop === 'string') {
                process.stderr.write('[eck] unknown fn \'' + prop + '\' -> no-op\n');
                return function () {};
            }
            return undefined;
        },
    });
}

function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

function easeOutBack(x) {

    const c1 = 1.70158;

    const c3 = c1 + 1;

    return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);

}

// ── Word Highlight Helpers ───────────────────────────────────────

function normalizeWord(w) {

    return String(w).toLowerCase().replace(/[.,;:!?"'()«»]/g, '').replace(/[.,]/g, '');

}

/** Find the word currently being spoken at currentTime across all visible steps */

function getActiveWord(currentTime) {

    for (const ts of timing.steps) {

        if (!ts.words || !ts.words.length) continue;

        for (const wb of ts.words) {

            if (currentTime >= wb.start && currentTime < wb.end) {

                return { norm: wb.norm, word: wb.word, stepId: ts.id };

            }

        }

    }

    return null;

}

/**

 * Draw a highlight glow box around a canvas region.

 * type: 'box' (rounded rect glow) | 'underline'

 */

function drawHighlightBox(x, y, w, h, color) {

    ctx.save();

    ctx.globalAlpha = 0.35;

    ctx.fillStyle = color || 'rgba(255,215,0,0.4)';

    ctx.shadowColor = color || '#FFD700';

    ctx.shadowBlur = 18;

    roundRect(x - 8, y - 4, w + 16, h + 8, 10);

    ctx.fill();

    ctx.globalAlpha = 1;

    ctx.strokeStyle = color || '#FFD700';

    ctx.lineWidth = 2.5;

    ctx.shadowBlur = 0;

    roundRect(x - 8, y - 4, w + 16, h + 8, 10);

    ctx.stroke();

    ctx.restore();

}

// ── Color & Style resolvers ─────────────────────────────────────

const COLORS = {

    title: () => T.titleColor,

    text: () => T.textColor,

    highlight: () => T.hlColor,

    muted: () => T.mutedColor,

    green: () => (artStyle !== 'default' && STYLE_PALETTES[artStyle]?.greenColor) ? STYLE_PALETTES[artStyle].greenColor : '#00FF88',

    red: () => (artStyle !== 'default' && STYLE_PALETTES[artStyle]?.redColor) ? STYLE_PALETTES[artStyle].redColor : '#FF6B6B',

    blue: () => (artStyle !== 'default' && STYLE_PALETTES[artStyle]?.cyanColor) ? STYLE_PALETTES[artStyle].cyanColor : '#64B5F6',

    yellow: () => (artStyle !== 'default' && STYLE_PALETTES[artStyle]?.yellowColor) ? STYLE_PALETTES[artStyle].yellowColor : '#FFD700',

    white: () => (artStyle !== 'default' && STYLE_PALETTES[artStyle]?.whiteColor) ? STYLE_PALETTES[artStyle].whiteColor : '#F0F0F0',

    cyan: () => (artStyle !== 'default' && STYLE_PALETTES[artStyle]?.cyanColor) ? STYLE_PALETTES[artStyle].cyanColor : '#22D3EE',

    orange: () => '#FFA726',

};

// rc: resolve màu theo tên palette; CHO PHÉP mã hex/rgb đi thẳng — cần cho
// video tông sáng (chữ phải mực tối #0f172a, palette không có màu tối).
function rc(name) {
    if (typeof name === 'string' && (/^#([0-9a-fA-F]{3,8})$/.test(name) || name.startsWith('rgb'))) return name;
    return (COLORS[name] || COLORS.text)();
}

const BOX_STYLES = {

    equation: () => ({ bg: T.eqBg, border: T.eqBorder, glow: false }),

    result:   () => ({ bg: T.resultBg, border: T.resultBorder, glow: false }), // removed glow to fix glare

    tip:      () => ({ bg: T.tipBg, border: T.tipBorder, glow: false }),

    subtle:   () => ({ bg: T.cardBg, border: T.cardBorder, glow: false }),

};

// ── Measure text height (for dynamic box) ───────────────────────

function measureTextHeight(el) {

    if (el.type === 'math_calc') {

        const fs = el.fontSize || 48;

        if (el.op === ':') {

            const leftLines = 1 + (el.intermediates ? el.intermediates.length : 0);

            return Math.max(leftLines, 2) * (fs * 1.3) + 40;

        } else {

            let lines = (el.operands || []).length;

            if (el.intermediates) lines += el.intermediates.length;

            if (el.result || el.result_partial !== undefined) lines += 1;

            let extraPad = 40; // 1 separator

            if (el.intermediates && el.intermediates.length > 0 && (el.result || el.result_partial !== undefined)) {

                extraPad += 28; // 2 separators

            }

            return lines * (fs * 1.3) + extraPad;

        }

    }

    const fs = el.fontSize || 40;

    const font = `${el.bold ? 'bold ' : ''}${fs}px ${T.font}`;

    const contentWFixed = W - MX * 2 - 60;

    if (el.type === 'list') {

        const bullet = el.bullet || '•';

        ctx.font = font;

        const bw = ctx.measureText(bullet + ' ').width;

        let totalH = 0;

        for (const item of (el.items || [])) {

            const wrapped = wrapText(item, contentWFixed - bw, font);

            totalH += wrapped.length * fs * 1.4 + 10;

        }

        return totalH;

    }

    if (el.type === 'timeline') {

        const items = el.items || [];

        const isHoriz = true; // render timeline ngang cho mọi tỷ lệ màn hình

        if (isHoriz) {

            const itemW = (W - MX * 2 - 60) / Math.max(1, items.length);

            let maxH = 0;

            ctx.font = font;

            for (const item of items) {

                let lineH = wrapText(item.event || '', itemW - 20, font).length * fs * 1.4;

                maxH = Math.max(maxH, lineH);

            }

            return maxH + fs + 80;

        } else {

            const lineX = MX + 40;

            let totalH = 0;

            ctx.font = font;

            for (const item of items) {

                totalH += fs * 1.4 + 10;

                totalH += wrapText(item.event || '', W - lineX - 30 - MX - 60, font).length * fs * 1.4;

                totalH += 30;

            }

            return totalH;

        }

    }

    const rawLines = (el.text || '').split('\n');

    let totalH = 0;

    for (const raw of rawLines) {

        const wrapped = wrapText(raw, contentWFixed, font);

        totalH += wrapped.length * fs * 1.4;

    }

    return totalH;

}

// ── Auto-layout element renderer ────────────────────────────────

// Returns height consumed

// stepProgress: 0.0–1.0, how far through this step's duration we are

// ── Cache HÀM custom_js ĐÃ BIÊN DỊCH — khớp theo NỘI DUNG mã nguồn ──────
// `new Function(...)` PHẢI PARSE lại toàn bộ mã JS mỗi lần gọi — TRƯỚC ĐÂY
// renderElementAtY() gọi lại nó ở MỖI KHUNG HÌNH cho MỌI element custom_js,
// dù `el.code` không đổi giữa các khung (chỉ P/P2/time đổi — code tự đọc lại
// khi HÀM chạy, không phải lúc BIÊN DỊCH). Đo thực tế 29/07: CPU đã 81% (gần
// trần worker) mà mỗi worker chỉ ra ~1.2 khung/giây — quá thấp cho vẽ 2D đơn
// giản, đúng dấu hiệu tốn ở BIÊN DỊCH LẶP LẠI chứ không phải ở PHẦN VẼ. Cache
// theo NỘI DUNG chuỗi `el.code` (không phải theo object `el`) — an toàn tuyệt
// đối: cùng mã nguồn luôn biên dịch ra hàm tương đương, fixInlineComments()
// thuần (không side-effect). KHÔNG dọn cache — 1 tiến trình node chỉ sống hết
// 1 lượt render/chunk (vài chục mã duy nhất, vài KB, không đáng lo rò rỉ).
const _customJsFnCache = new Map();
// MEMO biến đổi ctx.font của proxy custom_js: cảnh small-caps (cx_/mn_) đặt
// font TỪNG KÝ TỰ × mỗi khung → hai lượt regex (font_scale + thay family theo
// T.font + scale theo artStyle) chạy hàng trăm nghìn lần/lượt xuất — nặng rõ
// trên WebView mobile. Biến đổi là hàm thuần của (font_scale, chuỗi font)
// trong một lượt render (T.font/artStyle cố định cả lượt) → tra Map trước.
const _fontXformCache = new Map();

function renderElementAtY(el, cursorY, stepProgress) {

    stepProgress = stepProgress ?? 1.0;  // default fully revealed

    const contentW = W - MX * 2;

    switch (el.type) {

        case 'text': {

            const fs = el.fontSize || 40;

            const font = `${el.bold ? 'bold ' : ''}${fs}px ${T.font}`;

            ctx.font = font;

            ctx.fillStyle = rc(el.color);

            const align = el.align || 'left';

            ctx.textAlign = align; ctx.textBaseline = 'top';

            const coords = getElementCoords(el, cursorY);

            let rawText = el.text || '';

            let anim = el.animation;

            if (!anim || anim === 'typewriter') {

                anim = (rawText.length % 2 === 0) ? 'slide_in_left' : 'slide_up';

            }

            const fastP = Math.min(stepProgress * 4.0, 1.0);

            let offsetX = 0, offsetY = 0;

            if (anim === 'slide_in_left' && stepProgress < 1.0) {

                offsetX = -40 * (1 - easeOutBack(fastP));

            } else if (anim === 'slide_up' && stepProgress < 1.0) {

                offsetY = 30 * (1 - easeOutBack(fastP));

            }

            ctx.save();

            if (offsetX !== 0 || offsetY !== 0) {

                ctx.translate(offsetX, offsetY);

            }

            const rawLines = rawText.split('\n');

            let totalH = 0;

            const contentWFixed = W - MX * 2 - 60;

            for (const raw of rawLines) {

                const wrapped = wrapText(raw, contentWFixed, font);

                for (const line of wrapped) {

                    const tx = coords.isAbsolute ? coords.x : (align === 'center' ? W / 2 : align === 'right' ? W - MX : MX);

                    drawRichMathText(ctx, line, tx, coords.y + totalH, fs, rc(el.color), align, el.bold, 'top');

                    totalH += fs * 1.4;

                }

            }

            ctx.restore();

            ctx.textAlign = 'left';

            if (T2_EDIT_ELS) { // bbox chế độ sửa: đo bề ngang thật của khối chữ đã wrap
                let bw = 0;
                for (const raw of rawLines) for (const line of wrapText(raw, contentWFixed, font)) bw = Math.max(bw, measureMathAwareText(line, font));
                const ax = coords.isAbsolute ? coords.x : (align === 'center' ? W / 2 : align === 'right' ? W - MX : MX);
                const bx = align === 'center' ? ax - bw / 2 : align === 'right' ? ax - bw : ax;
                t2EditBox(el, bx + offsetX, coords.y + offsetY, bw, totalH);
            }

            return coords.isAbsolute ? 0 : totalH + 6;

        }

        case 'list': {

            const fs = el.fontSize || 40;

            const bold = el.bold !== false; // default bold

            const font = `${bold ? 'bold ' : ''}${fs}px ${T.font}`;

            ctx.font = font;

            const bullet = el.bullet || '•';

            const align = el.align || 'center';

            const items = el.items || [];

            const n = items.length;

            const lineGap = Math.round(fs * 0.42);   // vertical gap between pills

            const padX = Math.round(fs * 0.6);        // horizontal padding inside pill

            const padY = Math.round(fs * 0.42);       // vertical padding — taller pills

            // Cap max pill width at 65% of canvas to avoid full-width stretch

            const maxPillW = Math.min(W - MX * 2, Math.round(W * 0.65));

            // Pre-measure all items → use UNIFORM width = widest item (aligned stack)

            const measuredW = items.map(item => measureMathAwareText(bullet + '  ' + item, font));

            const uniformW = Math.min(Math.max(...measuredW, 0) + padX * 2, maxPillW);

            const pillData = items.map(item => ({ item, pillW: uniformW }));

            const coords = getElementCoords(el, cursorY);

            let pillX = coords.x - uniformW / 2;

            if (!coords.isAbsolute) {

                pillX = (align === 'center') ? (W / 2 - uniformW / 2) : MX;

            }

            let totalH = 0;

            for (let j = 0; j < n; j++) {

                const itemStart = j / Math.max(n, 1);

                const itemProg = Math.max(0, Math.min((stepProgress - itemStart) * n * 2, 1.0));

                const { item, pillW } = pillData[j];

                const pillH = fs + padY * 2;

                const pillY = coords.y + totalH;

                if (itemProg > 0) {

                    ctx.save();

                    const alpha = easeOut(itemProg);

                    const slideY = 18 * (1 - easeOutBack(itemProg));

                    ctx.globalAlpha = alpha;

                    ctx.translate(0, slideY);

                    // Pill background

                    if (global.glassEffect) {
                        ctx.fillStyle = 'rgba(255,255,255,0.06)';
                        ctx.strokeStyle = 'rgba(255,255,255,0.22)';
                    } else {
                        ctx.fillStyle = rc(el.color) === rc('text') ? 'rgba(99,102,241,0.18)' : 'rgba(99,102,241,0.12)';
                        ctx.strokeStyle = rc(el.color || 'highlight');
                    }

                    ctx.lineWidth = 2;

                    if (global.glassEffect) {
                        ctx.shadowColor = 'rgba(0, 0, 0, 0.25)';
                        ctx.shadowBlur = 12;
                        ctx.shadowOffsetY = 4;
                    }

                    ctx.beginPath();

                    if (ctx.roundRect) ctx.roundRect(pillX, pillY, pillW, pillH, Math.min(pillH / 2, 18));

                    else ctx.rect(pillX, pillY, pillW, pillH);

                    ctx.fill();

                    // Clear shadow for stroke and text
                    ctx.shadowColor = 'rgba(0,0,0,0)';
                    ctx.shadowBlur = 0;
                    ctx.shadowOffsetY = 0;

                    ctx.stroke();

                    // Glassmorphism: frosted top sheen on pill

                    if (global.glassEffect) {

                        ctx.save();

                        ctx.beginPath();

                        if (ctx.roundRect) ctx.roundRect(pillX, pillY, pillW, pillH, Math.min(pillH / 2, 18));

                        else ctx.rect(pillX, pillY, pillW, pillH);

                        ctx.clip();

                        const gs = ctx.createLinearGradient(0, pillY, 0, pillY + pillH);

                        gs.addColorStop(0, 'rgba(255,255,255,0.20)');

                        gs.addColorStop(0.45, 'rgba(255,255,255,0.04)');

                        gs.addColorStop(1, 'rgba(255,255,255,0.0)');

                        ctx.fillStyle = gs;

                        ctx.fillRect(pillX, pillY, pillW, pillH);

                        ctx.strokeStyle = 'rgba(255,255,255,0.45)';

                        ctx.lineWidth = 1.2;

                        ctx.beginPath();

                        ctx.moveTo(pillX + pillH / 2, pillY + 1.2);

                        ctx.lineTo(pillX + pillW - pillH / 2, pillY + 1.2);

                        ctx.stroke();

                        ctx.restore();

                    }

                    // Text inside pill

                    ctx.fillStyle = rc(el.color || 'text');

                    ctx.font = font;

                    ctx.textAlign = 'left';

                    ctx.textBaseline = 'middle';

                    drawRichMathText(ctx, bullet + '  ' + item, pillX + padX, pillY + pillH / 2, fs, rc(el.color || 'text'), 'left', bold, 'middle');

                    ctx.restore();

                }

                totalH += pillH + lineGap;

            }

            t2EditBox(el, pillX, coords.y, uniformW, n ? totalH - lineGap : 0); // bbox chế độ sửa

            return coords.isAbsolute ? 0 : totalH + 4;

        }

        case 'timeline': {

            const fs = el.fontSize || 32, font = `${fs}px ${T.font}`, boldFont = `bold ${fs+4}px ${T.font}`;

            ctx.fillStyle = rc(el.color);

            ctx.strokeStyle = rc(el.color);

            ctx.lineWidth = 4;

            const items = el.items || [];

            const isHoriz = true; // render timeline ngang cho mọi tỷ lệ màn hình

            const n = items.length;

            if (isHoriz) {

                const lineY = cursorY + fs + 20;

                // Draw growing horizontal line

                const lineProg = Math.min(stepProgress * 2.0, 1.0); // line draws first 50%

                if (lineProg > 0) {

                    ctx.save(); ctx.globalAlpha = easeOut(lineProg);

                    const lineW = (W - MX * 2) * lineProg;

                    ctx.beginPath(); ctx.moveTo(MX, lineY); ctx.lineTo(MX + lineW, lineY); ctx.stroke();

                    ctx.restore();

                }

                const itemW = (W - MX * 2) / Math.max(1, n);

                let maxH = 0;

                ctx.textAlign = 'center'; ctx.textBaseline = 'top';

                for (let i = 0; i < n; i++) {

                    const item = items[i];

                    const itemStart = i / Math.max(n, 1);

                    const itemProg = Math.max(0, Math.min((stepProgress - itemStart) * n * 2, 1.0));

                    const x = n === 1 ? W/2 : MX + itemW/2 + i * itemW;

                    let lineH = 0;

                    ctx.font = font;

                    const lines = wrapText(item.event || '', itemW - 20, font);

                    lineH = lines.length * fs * 1.4;

                    maxH = Math.max(maxH, lineY + 20 + lineH - cursorY);

                    if (itemProg > 0) {

                        ctx.save();

                        ctx.globalAlpha = easeOut(itemProg);

                        const offsetY = 20 * (1 - easeOutBack(itemProg));

                        ctx.translate(0, offsetY);

                        ctx.beginPath(); ctx.arc(x, lineY, 8, 0, Math.PI*2); ctx.fill();

                        ctx.font = boldFont;

                        ctx.fillText(item.year || '', x, cursorY);

                        ctx.font = font;

                        let textY = lineY + 20;

                        for (const line of lines) {

                            ctx.fillText(line, x, textY);

                            textY += fs * 1.4;

                        }

                        ctx.restore();

                    }

                }

                return maxH + 40;

            } else {

                const lineX = MX + 40;

                let curY = cursorY;

                ctx.textAlign = 'left'; ctx.textBaseline = 'top';

                // For vertical, measure total height to draw the line

                let totalH = 0;

                const itemHeights = [];

                for (let i = 0; i < n; i++) {

                    const item = items[i];

                    ctx.font = font;

                    const lines = wrapText(item.event || '', W - lineX - 30 - MX, font);

                    const h = (fs * 1.4 + 10) + (lines.length * fs * 1.4) + 30;

                    itemHeights.push(h);

                    totalH += h;

                }

                // Draw vertical line growing

                const lineProg = Math.min(stepProgress * 2.0, 1.0);

                if (lineProg > 0 && n > 0) {

                    ctx.save(); ctx.globalAlpha = easeOut(lineProg);

                    const drawH = (totalH - 30 - fs * 1.4) * lineProg;

                    ctx.beginPath(); ctx.moveTo(lineX, cursorY + 20); ctx.lineTo(lineX, cursorY + 20 + drawH); ctx.stroke();

                    ctx.restore();

                }

                for (let i = 0; i < n; i++) {

                    const item = items[i];

                    const itemStart = i / Math.max(n, 1);

                    const itemProg = Math.max(0, Math.min((stepProgress - itemStart) * n * 2, 1.0));

                    ctx.font = font;

                    const lines = wrapText(item.event || '', W - lineX - 30 - MX, font);

                    if (itemProg > 0) {

                        ctx.save();

                        ctx.globalAlpha = easeOut(itemProg);

                        const offsetX = -20 * (1 - easeOutBack(itemProg)); // slide in left

                        ctx.translate(offsetX, 0);

                        ctx.beginPath(); ctx.arc(lineX, curY + 20, 8, 0, Math.PI*2); ctx.fill();

                        ctx.font = boldFont;

                        ctx.fillText(item.year || '', lineX + 30, curY);

                        let textY = curY + fs * 1.4 + 10;

                        ctx.font = font;

                        for (const line of lines) {

                            ctx.fillText(line, lineX + 30, textY);

                            textY += fs * 1.4;

                        }

                        ctx.restore();

                    }

                    curY += itemHeights[i];

                }

                return totalH;

            }

        }

        case 'custom_js': {

            let h = el.height || 100;

            const coords = getElementCoords(el, cursorY);

            const scaleFactor = (el.fontSize || 40) / 40;

            const scaledH = h * scaleFactor;

            if (el.code) {

                try {

                    // Provide the actual video timeline frame time to the custom_js code block

                    const timeSecs = currentFrameTime;

                    // Create a smart Proxy for ctx to remap colors and soften shadows for light styles

                    const isLightStyle = ['watercolor', 'inkwash', 'pastel', 'sketch', 'sketchnote', 'aurora'].includes(artStyle);

                    const customCtx = new Proxy(ctx, {

                        get(target, prop) {
                            if (prop === 'drawImage') {
                                return function(img, ...args) {
                                    if (isLightStyle && img && typeof img.src === 'string' && img.src.toLowerCase().includes('logo') && !img.src.toLowerCase().includes('logo_tubecreate') && !img.src.toLowerCase().includes('tubecreate')) {
                                        target.save();
                                        target.fillStyle = 'rgba(15, 23, 42, 0.95)';
                                        target.strokeStyle = 'rgba(255, 255, 255, 0.1)';
                                        target.lineWidth = 2;
                                        target.beginPath();
                                        let dx = args[0], dy = args[1], dw = img.width || 120, dh = img.height || 120;
                                        if (args.length === 4 || args.length === 5) {
                                            dw = args[2];
                                            dh = args[3];
                                        } else if (args.length >= 8) {
                                            dx = args[4];
                                            dy = args[5];
                                            dw = args[6];
                                            dh = args[7];
                                        }
                                        let cx = dx + dw/2;
                                        let cy = dy + dh/2;
                                        let r = Math.max(dw, dh) * 0.65;
                                        target.arc(cx, cy, r, 0, Math.PI * 2);
                                        target.fill();
                                        target.stroke();
                                        target.restore();
                                    }
                                    return target.drawImage.apply(target, [img, ...args]);
                                };
                            }
                            if (prop === 'fill') {
                                return function(...args) {
                                    // Light styles: suppress neon glow on fill (looks harsh on light bg)
                                    // liquidglass: keep shadow glow for neon circle effect
                                    if (isLightStyle) {
                                        const oldBlur = target.shadowBlur;
                                        const oldColor = target.shadowColor;
                                        const oldOffsetX = target.shadowOffsetX;
                                        const oldOffsetY = target.shadowOffsetY;
                                        target.shadowBlur = 0;
                                        target.shadowColor = 'rgba(0,0,0,0)';
                                        target.shadowOffsetX = 0;
                                        target.shadowOffsetY = 0;
                                        const res = target.fill.apply(target, args);
                                        target.shadowBlur = oldBlur;
                                        target.shadowColor = oldColor;
                                        target.shadowOffsetX = oldOffsetX;
                                        target.shadowOffsetY = oldOffsetY;
                                        return res;
                                    }
                                    return target.fill.apply(target, args);
                                };
                            }
                            const val = target[prop];
                            if (typeof val === 'function') {
                                return val.bind(target);
                            }
                            return val;
                        },

                        set(target, prop, value) {

                            // HỆ SỐ CỠ CHỮ RIÊNG của element (editor bố cục, user 24/07):
                            // el.font_scale nhân mọi 'Npx' khi code cảnh đặt ctx.font —
                            // chữa "chữ đè/sít nhau" mà KHÔNG teo cả cảnh (đó là việc của
                            // fontSize/scale quanh tâm bên dưới). measureText/lưới chống
                            // tràn tự nhất quán vì cùng đọc ctx.font đã scale. Lưu ý:
                            // mnk.*/ui.* vẽ trên ctx gốc nên không chịu hệ số này.
                            var _fkey;   // key memo font — var để block family-swap dưới cùng thấy
                            if (prop === 'font' && typeof value === 'string') {
                                const _fsc = parseFloat(el && el.font_scale);
                                _fkey = (_fsc || 0) + '|' + value;
                                const _fhit = _fontXformCache.get(_fkey);
                                if (_fhit !== undefined) {
                                    target[prop] = _fhit;   // đã biến đổi y hệt lần trước
                                    return true;
                                }
                                if (_fsc && _fsc > 0.3 && _fsc < 3 && _fsc !== 1) {
                                    value = value.replace(/(\d+(?:\.\d+)?)px/g,
                                        (_m, n) => (Math.round(parseFloat(n) * _fsc * 10) / 10) + 'px');
                                }
                            }

                            const toGrayscale = (colorStr) => {
                                if (typeof colorStr !== 'string') return colorStr;
                                const trimmed = colorStr.trim();
                                const lower = trimmed.toLowerCase();
                                if (lower.startsWith('hsl')) {
                                    return trimmed.replace(/hsl(a?)\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)%?\s*,/i, 'hsl$1($2, 0%,');
                                }
                                const rgbMatch = trimmed.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)/i);
                                if (rgbMatch) {
                                    const r = parseInt(rgbMatch[1]);
                                    const g = parseInt(rgbMatch[2]);
                                    const b = parseInt(rgbMatch[3]);
                                    const gray = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
                                    if (rgbMatch[4] !== undefined) {
                                        return `rgba(${gray}, ${gray}, ${gray}, ${rgbMatch[4]})`;
                                    } else {
                                        return `rgb(${gray}, ${gray}, ${gray})`;
                                    }
                                }
                                if (trimmed.startsWith('#')) {
                                    const hex = trimmed.slice(1);
                                    let r = 255, g = 255, b = 255, a = '';
                                    if (hex.length === 3 || hex.length === 4) {
                                        r = parseInt(hex[0] + hex[0], 16);
                                        g = parseInt(hex[1] + hex[1], 16);
                                        b = parseInt(hex[2] + hex[2], 16);
                                        if (hex.length === 4) a = hex[3] + hex[3];
                                    } else if (hex.length === 6 || hex.length === 8) {
                                        r = parseInt(hex.slice(0, 2), 16);
                                        g = parseInt(hex.slice(2, 4), 16);
                                        b = parseInt(hex.slice(4, 6), 16);
                                        if (hex.length === 8) a = hex.slice(6, 8);
                                    }
                                    const gray = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
                                    const grayHex = gray.toString(16).padStart(2, '0');
                                    return `#${grayHex}${grayHex}${grayHex}${a}`;
                                }
                                const namedColors = {
                                    'red': '#111827', 'green': '#374151', 'blue': '#1f2937', 'yellow': '#4b5563',
                                    'cyan': '#1f2937', 'magenta': '#4b5563', 'white': '#ffffff', 'black': '#000000',
                                    'gray': '#808080', 'grey': '#808080', 'orange': '#4b5563', 'purple': '#374151',
                                    'pink': '#9ca3af', 'brown': '#374151'
                                };
                                if (namedColors[lower]) {
                                    return namedColors[lower];
                                }
                                return colorStr;
                            };

                            let newVal = value;

                            // Intercept font styling to dynamically inject our premium font family

                            if (prop === 'font' && typeof value === 'string') {
                                newVal = value.replace(/sans-serif|monospace|serif/gi, (match) => {
                                    const lower = match.toLowerCase();
                                    if (lower === 'sans-serif') return T.font;
                                    if (lower === 'monospace') return T.font;
                                    if (lower === 'serif') return T.font;
                                    return match;
                                });

                                let scaleFactor = 1.0;
                                if (artStyle === 'pixel') scaleFactor = 0.85;
                                else if (artStyle === 'cyberpunk') scaleFactor = 0.78;
                                else if (artStyle === 'cartoon') scaleFactor = 0.85;
                                else if (artStyle === 'sketch') scaleFactor = 0.85;
                                else if (artStyle === 'inkwash') scaleFactor = 0.85;
                                else if (artStyle === 'sketchnote') scaleFactor = 0.92;
                                else if (artStyle === 'watercolor') scaleFactor = 0.95;
                                else if (artStyle === 'pastel') scaleFactor = 0.95;
                                else if (artStyle === 'aurora') scaleFactor = 0.95;

                                if (scaleFactor !== 1.0) {
                                    newVal = newVal.replace(/(\d+)px/gi, (match, size) => {
                                        const scaled = Math.round(parseInt(size) * scaleFactor);
                                        return `${Math.max(9, scaled)}px`;
                                    });
                                }

                                if (typeof _fkey === 'string') {
                                    if (_fontXformCache.size > 20000) _fontXformCache.clear();
                                    _fontXformCache.set(_fkey, newVal);
                                }
                            }

                            if (typeof value === 'string') {

                                const lowerVal = value.toLowerCase().trim();

                                // Intercept and map fill/stroke colors

                                if (prop === 'fillStyle' || prop === 'strokeStyle') {

                                    if (isLightStyle || artStyle === 'liquidglass') {

                                        // Intercept dark-slate box background and make it translucent/light

                                          const isLightColor = (val) => {
                                         if (!val) return false;
                                         const lower = val.toLowerCase().trim();
                                         if (lower === 'transparent' || lower === 'none' || lower === 'inherit' || lower === 'initial') return false;
                                         if (lower === 'text' || lower === 'title' || lower === 'muted' || lower === 'highlight' || lower === 'cyan' || lower === 'green' || lower === 'red' || lower === 'yellow' || lower === 'orange' || lower === 'blue') {
                                             return false;
                                         }
                                         let r = 255, g = 255, b = 255;
                                         if (lower.startsWith('#')) {
                                             const hex = lower.slice(1);
                                             if (hex.length === 3 || hex.length === 4) {
                                                 r = parseInt(hex[0] + hex[0], 16);
                                                 g = parseInt(hex[1] + hex[1], 16);
                                                 b = parseInt(hex[2] + hex[2], 16);
                                             } else if (hex.length === 6 || hex.length === 8) {
                                                 r = parseInt(hex.slice(0, 2), 16);
                                                 g = parseInt(hex.slice(2, 4), 16);
                                                 b = parseInt(hex.slice(4, 6), 16);
                                             } else {
                                                 return false;
                                             }
                                         } else if (lower.startsWith('rgba') || lower.startsWith('rgb')) {
                                             const match = lower.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
                                             if (match) {
                                                 r = parseInt(match[1]);
                                                 g = parseInt(match[2]);
                                                 b = parseInt(match[3]);
                                             } else {
                                                 return false;
                                             }
                                         } else {
                                             const namedWhites = ['white', 'whitesmoke', 'aliceblue', 'azure', 'ghostwhite', 'honeydew', 'ivory', 'lavender', 'linen', 'snow', 'seashell', 'lightgray', 'lightgrey', 'gainsboro', 'silver'];
                                             if (namedWhites.includes(lower)) return true;
                                             return false;
                                         }
                                         return (r + g + b) / 3 > 195;
                                     };

                                     const isDarkColor = (val) => {

                                        if (!val) return false;

                                        const lower = val.toLowerCase().trim();

                                        if (lower === '#0f172a' || lower === '#0b0f19' || lower === '#1a1a2e' || lower === '#202035' || lower === '#1a1a35' || lower === '#141423' || lower === '#1a3528' || lower === '#0e1111') {

                                            return true;

                                        }

                                        if (lower.startsWith('rgba') || lower.startsWith('rgb')) {

                                            const match = lower.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);

                                            if (match) {

                                                const r = parseInt(match[1]), g = parseInt(match[2]), b = parseInt(match[3]);

                                                return r < 85 && g < 85 && b < 85;

                                            }

                                        }

                                        return false;

                                    };

                                    if (isDarkColor(lowerVal)) {

                                        if (artStyle === 'watercolor') newVal = 'rgba(44, 76, 56, 0.08)'; // sage green tint

                                        else if (artStyle === 'inkwash') newVal = 'rgba(0, 0, 0, 0.05)'; // gray sumi wash

                                        else if (artStyle === 'pastel') newVal = 'rgba(92, 103, 125, 0.06)'; // soft lavender tint
                                        else if (artStyle === 'aurora') newVal = 'rgba(255, 255, 255, 0.78)'; // white glass card

                                        else if (artStyle === 'sketch') newVal = 'rgba(255, 255, 255, 0.9)'; // white paper fill

                                        else if (artStyle === 'sketchnote') newVal = 'rgba(255, 255, 255, 0.95)'; // clean white notebook paper fill

                                        else if (artStyle === 'liquidglass') {
                                             // Deep dark-glass fill: preserve circle/node backgrounds as visible
                                             // dark surfaces so icons render clearly against them.
                                             // High-opacity fills (circle backgrounds) keep dark glass base.
                                             // Low-opacity fills (overlays) get subtle white glass tint.
                                             const ma = lowerVal.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\)/);
                                             const origAlpha = ma && ma[4] !== undefined ? parseFloat(ma[4]) : 1.0;
                                             if (origAlpha > 0.5) {
                                                 // Solid node/circle background — keep dark + glass readable
                                                 newVal = 'rgba(8,14,32,0.72)';
                                             } else {
                                                 // Overlay/tint — use subtle frosted white
                                                 const a = Math.min(0.18, origAlpha);
                                                 newVal = `rgba(255,255,255,${a})`;
                                             }

                                         }

                                    }

                                        // Intercept white text inside nodes and make it dark text

                                        else if (lowerVal === '#ccc' || lowerVal === '#bbb' || lowerVal === '#aaa' || lowerVal === '#999' || lowerVal === '#888' || lowerVal === '#d0d0ff' || lowerVal === '#e0e0ff' || lowerVal === '#c0c0c0' || lowerVal === '#d3d3d3' || lowerVal.includes('rgba(204,204,204') || lowerVal.includes('rgba(187,187,187') || lowerVal.includes('rgba(170,170,170') || lowerVal.includes('rgba(204, 204, 204') || lowerVal.includes('rgba(187, 187, 187') || lowerVal.includes('rgba(170, 170, 170')) {
                                            newVal = rc('muted');
                                        }
                                        else if (isLightStyle && isLightColor(lowerVal)) {
                                            let alpha = 1.0;
                                            const rgbaMatch = lowerVal.match(/rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\)/);
                                            if (rgbaMatch) {
                                                alpha = parseFloat(rgbaMatch[4]);
                                            } else if (lowerVal.startsWith('#')) {
                                                const hex = lowerVal.slice(1);
                                                if (hex.length === 8) {
                                                    alpha = parseInt(hex.slice(6, 8), 16) / 255;
                                                } else if (hex.length === 4) {
                                                    alpha = (parseInt(hex.slice(3, 4), 16) * 17) / 255;
                                                }
                                            }
                                            alpha = Math.round(alpha * 1000) / 1000;

                                            let r = 255, g = 255, b = 255;
                                            if (lowerVal.startsWith('#')) {
                                                const hex = lowerVal.slice(1);
                                                if (hex.length >= 6) {
                                                    r = parseInt(hex.slice(0, 2), 16);
                                                    g = parseInt(hex.slice(2, 4), 16);
                                                    b = parseInt(hex.slice(4, 6), 16);
                                                } else if (hex.length >= 3) {
                                                    r = parseInt(hex[0]+hex[0], 16);
                                                    g = parseInt(hex[1]+hex[1], 16);
                                                    b = parseInt(hex[2]+hex[2], 16);
                                                }
                                            } else if (lowerVal.startsWith('rgba') || lowerVal.startsWith('rgb')) {
                                                const match = lowerVal.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
                                                if (match) {
                                                    r = parseInt(match[1]);
                                                    g = parseInt(match[2]);
                                                    b = parseInt(match[3]);
                                                }
                                            }
                                            const avg = (r + g + b) / 3;

                                            if (alpha < 1.0) {
                                                newVal = `rgba(30, 41, 59, ${alpha})`;
                                            } else {
                                                newVal = avg > 245 ? rc('text') : rc('muted');
                                            }
                                        }

                                    }// Make sure neon standard names mapped properly

                                    if (lowerVal === 'cyan' || lowerVal === '#22d3ee' || lowerVal === '#00ffff') newVal = rc('cyan');

                                    else if (lowerVal === 'yellow' || lowerVal === '#ffd700' || lowerVal === '#efff14') newVal = rc('yellow');

                                    else if (lowerVal === 'green' || lowerVal === '#22c55e' || lowerVal === '#39ff14') newVal = rc('green');

                                    else if (lowerVal === 'red' || lowerVal === '#ef4444' || lowerVal === '#ff073a') newVal = rc('red');

                                    if (artStyle === 'sketch') {
                                        newVal = toGrayscale(newVal);
                                    }

                                }

                                // Intercept shadowColor and disable/soften glow on light backgrounds

                                if (prop === 'shadowColor') {

                                    if (isLightStyle) {

                                        newVal = 'rgba(0, 0, 0, 0.08)'; // soft warm gray shadow instead of neon glow

                                    } else {

                                        // On dark cyberpunk, use proper neon colors

                                        if (lowerVal === 'cyan' || lowerVal === '#22d3ee' || lowerVal === '#00ffff') newVal = rc('cyan');

                                        else if (lowerVal === 'yellow' || lowerVal === '#ffd700' || lowerVal === '#efff14') newVal = rc('yellow');

                                        else if (lowerVal === 'green' || lowerVal === '#22c55e' || lowerVal === '#39ff14') newVal = rc('green');

                                        else if (lowerVal === '#ff007f' || lowerVal === 'magenta' || lowerVal === '#ff00ff') newVal = rc('highlight');

                                    }

                                }

                            }

                            // Intercept shadowBlur to soften it on light styles

                            if (prop === 'shadowBlur') {

                                if (isLightStyle) {

                                    newVal = Math.min(newVal, 4);

                                }

                            }

                            target[prop] = newVal;

                            return true;

                        }

                    });

                    const uiKit = makeUiKit(ctx, artStyle, timeSecs, rc, global.drawEmoji);
                    const mnKit = makeMnKit(ctx, timeSecs);
                    // eck.* — kit linh kiện Editorial Cream (đọc T runtime cho màu + font).
                    const eckKit = makeEckKit(ctx, timeSecs, T);
                    // Bọc code AI trong IIFE: nếu AI lỡ khai lại tham số (const W=.. / var H=..)
                    // thì bên trong IIFE nó chỉ SHADOW hợp lệ, không còn "Identifier 'W' already
                    // declared" (SyntaxError) làm TRẮNG cả cảnh. `return <height>` của code chảy ra
                    // ngoài qua IIFE. W/H luôn = 1080/1920 nên shadow không đổi ngữ nghĩa.
                    let fn = _customJsFnCache.get(el.code);
                    if (!fn) {
                        fn = new Function('ctx', 'W', 'H', 'MX', 'cursorY', 'stepProgress', 'time', 'el', 'T', 'rc', 'wrapText', 'drawEmoji', 'ui', 'mnk', 'eck', CUSTOM_JS_PRE + 'return (function(){\n' + fixInlineComments(el.code) + '\n})();');
                        _customJsFnCache.set(el.code, fn);
                    }

                    // ── LƯỚI ĐỠ CHỐNG TRÀN CHỮ (chỉ cho ctx mà code AI cầm) ─────────
                    // Code custom_js do AI sinh hay gọi fillText() với chuỗi dài hơn
                    // khung → chữ chạy quá mép canvas và bị cắt cụt (tiêu đề Editorial
                    // Cream, nhãn Neon Doodle, caption template Nhật…). Vá từng template
                    // bằng prompt đã thất bại nhiều lần nên chặn cứng ở đây: đo bề rộng
                    // THẬT, vượt biên an toàn thì thu nhỏ cỡ font (giữ weight/family),
                    // có sàn; chạm sàn mà vẫn tràn thì cắt chuỗi + '…'.
                    //
                    // BẤT BIẾN SỐNG CÒN: chữ KHÔNG tràn ⇒ không đổi một pixel nào (bài
                    // cũ của khách phải render y hệt). Nên mọi tình huống không chắc
                    // chắn đều BỎ QUA, không đoán: không đọc được cỡ px, có xoay/nghiêng,
                    // AI tự setTransform/restore lệch, AI đã tự truyền maxWidth, hoặc neo
                    // chữ nằm ngoài vùng an toàn (hoạt cảnh trượt-vào-từ-ngoài-mép).
                    //
                    // Chỉ áp cho proxy này. ui.* / mnk.* / eck.* và mọi đường vẽ của
                    // engine dùng ctx GỐC nên không đi qua đây — chúng đã tự lo wrap.
                    // Lề an toàn tính từ BIÊN CANVAS — đây là chốt chống CẮT, KHÔNG phải
                    // lề bố cục (MX=60). Phải để nhỏ: 20px từng làm nhãn "Receive prompt"
                    // của tech_explainer (mép trái ở 18.1px, KHÔNG hề bị cắt) kích hoạt
                    // lưới đỡ → đổi pixel 6 khung golden. 8px chỉ đủ bù phần measureText
                    // báo thiếu (side bearing / khử răng cưa), không đụng vào khoảng
                    // trống mà người thiết kế cố ý dùng.
                    const OF_MARGIN = 8;
                    // Sàn thu nhỏ. 0.55 hấp thụ được dòng dài hơn khung tới ~82% — đủ cho
                    // ca hỏng thật (AI viết nguyên câu vào chỗ đáng lẽ là tiêu đề: caption
                    // 79 ký tự @46px cần co xuống ≤58% mới vừa khung 1080). Thấp hơn 55%
                    // thì cỡ chữ lệch hẳn phần còn lại của thiết kế, lúc đó '…' thật thà hơn.
                    // Cắt chữ LÀM MẤT NGHĨA nên co được thì luôn ưu tiên co.
                    const OF_FLOOR_RATIO = 0.55;
                    // Sàn tuyệt đối. min(size0,…) để chữ vốn đã nhỏ hơn sàn thì không bị
                    // co tiếp — cắt thẳng.
                    //
                    // 16px (1.5% bề ngang) là con số CŨ và nó SAI trong thực tế: người
                    // dùng gửi ảnh chú thích trên nhân vật "font chữ nhỏ khó đọc" — đó
                    // đúng là chữ đã bị co chạm sàn. Video này xem trên điện thoại, phần
                    // lớn là 9:16 cao 1920, và 16px ở đó mảnh hơn cả phụ đề hệ thống.
                    // 22px ≈ 2% bề ngang: vẫn nhỏ hơn hẳn thân bài nên không phá thiết kế,
                    // nhưng đọc được ở khoảng cách cầm tay. Chữ nào không vừa ở 22px thì
                    // '…' thật thà hơn — người đọc thấy mình bị cắt, còn chữ 16px thì họ
                    // tưởng mắt mình có vấn đề.
                    const OF_FLOOR_PX = 22;
                    const OF_SIZE_RE = /(\d+(?:\.\d+)?)px/;

                    // Theo vết ma trận biến hình [a,b,c,d,e,f] để biết toạ độ THẬT của
                    // chữ. Bắt buộc: engine đã translate/scale trước khi gọi code AI
                    // (scaleFactor = fontSize/40, __centerDY), và code AI cũng hay
                    // translate. Không theo vết thì fillText(s, 0, y) sau translate(W/2)
                    // bị hiểu là sát mép trái → thu nhỏ OAN → đổi pixel bài cũ.
                    let _tm = [1, 0, 0, 1, 0, 0];
                    let _tmLost = false;              // mất mốc → tắt lưới đỡ
                    const _tmStack = [];
                    const _tTranslate = (m, dx, dy) => { m[4] += m[0] * dx + m[2] * dy; m[5] += m[1] * dx + m[3] * dy; };
                    const _tScale = (m, sx, sy) => { m[0] *= sx; m[1] *= sx; m[2] *= sy; m[3] *= sy; };
                    const _tRotate = (m, r) => {
                        const co = Math.cos(r), si = Math.sin(r);
                        const a = m[0], b = m[1], c = m[2], d = m[3];
                        m[0] = a * co + c * si; m[1] = b * co + d * si;
                        m[2] = c * co - a * si; m[3] = d * co - b * si;
                    };
                    const _tMul = (m, a2, b2, c2, d2, e2, f2) => {
                        const a = m[0], b = m[1], c = m[2], d = m[3];
                        m[0] = a * a2 + c * b2; m[1] = b * a2 + d * b2;
                        m[2] = a * c2 + c * d2; m[3] = b * c2 + d * d2;
                        m[4] += a * e2 + c * f2; m[5] += b * e2 + d * f2;
                    };
                    // Nạp biến hình mà engine áp ở dưới TRƯỚC khi gọi code AI (xem khối
                    // ctx.save() ngay sau proxy này). CỐ Ý bỏ qua el.__centerDY: nó chỉ
                    // dịch DỌC, mà lưới đỡ chỉ xét trục NGANG — vả lại lúc này nó còn
                    // chưa được tính (khối đo nằm sau proxy), đọc vào chỉ tổ sai.
                    if (scaleFactor !== 1.0) {
                        const _sx0 = W / 2, _sy0 = coords.y + scaledH / 2;
                        _tTranslate(_tm, _sx0, _sy0);
                        _tScale(_tm, scaleFactor, scaleFactor);
                        _tTranslate(_tm, -_sx0, -_sy0);
                    }

                    // ── NỀN LÓT KHI CHỮ ĐÈ NHÂN VẬT (sprite) ────────────────────────
                    // Cùng bệnh với tràn khung: AI đặt chú thích ĐÈ THẲNG lên nhân vật
                    // chibi (japan_social step 5: hai câu thoại đỏ nằm giữa ngực hai
                    // nhân vật) → chữ lẫn vào hình, không đọc nổi. Dặn trong prompt
                    // ("vùng cấm quanh nhân vật") đã thất bại nhiều vòng.
                    //
                    // KHÔNG DỜI CHỮ: dời tự động phá bố cục nhiều hơn là cứu (chữ nhảy
                    // vào chỗ vô nghĩa, hoạt cảnh giật). Thay vào đó lót một tấm nền
                    // MÀU NỀN CẢNH ngay dưới chữ — chữ trở lại đúng tương phản mà bố
                    // cục AI dựng vẫn nguyên.
                    //
                    // BẤT BIẾN: không đè sprite ⇒ không đổi một pixel nào. Cảnh không
                    // gọi ui.sprite ⇒ sổ rỗng ⇒ nhánh này không bao giờ chạy.
                    //
                    // Ngưỡng 15% DIỆN TÍCH chữ: chữ chỉ chạm rìa nhân vật vẫn đọc tốt,
                    // lót nền lúc đó là thêm hộp thừa vào thiết kế. Ca hỏng thật đo
                    // được cao hơn hẳn (~50-70%) nên 15% tách sạch hai nhóm.
                    const PLATE_MIN_RATIO = 0.15;
                    // 0.96: gần đục hẳn. Bản đầu để 0.86 và người dùng báo ngay "text bị
                    // mờ" — 14% nét nhân vật lộ qua nghe thì hay (mảng giấy chứ không
                    // phải hộp dán) nhưng trên nền cream sáng, tóc đen lộ qua 14% đủ để
                    // ăn mất tương phản của chính dòng chữ mà tấm nền sinh ra để cứu.
                    // Tấm nền chỉ xuất hiện khi chữ ĐÃ đè lên nhân vật, tức là lúc thẩm
                    // mỹ đã hỏng rồi — ưu tiên đọc được, không ưu tiên tinh tế.
                    // Nhân vào globalAlpha hiện tại để nền mờ-dần THEO chữ (AI hay fade
                    // chú thích bằng globalAlpha).
                    const PLATE_ALPHA = 0.96;
                    // Màu = NỀN CẢNH thật, lấy ĐÚNG ĐIỂM chữ đang đứng. Không phải
                    // whiteColor: ở phong cách tối whiteColor là màu MỰC sáng, lót
                    // bằng nó thì chữ sáng biến mất. Và không phải bgGrad[0] cứng:
                    // nền là gradient CHÉO (0,0)→(W,H) trong drawBg(), lấy màu đầu
                    // thì tấm lót sáng hơn nền quanh nó và lộ thành hình chữ nhật ở
                    // phần KHÔNG có nhân vật (đo được trên ov_5: nền tại y≈980 đã
                    // ngả về bgGrad[1]). Nội suy theo đúng công thức drawBg() → tấm
                    // lót tàng hình trên nền, chỉ hiện đúng chỗ phải che nhân vật.
                    const PLATE_C0 = (T && T.bgGrad && T.bgGrad[0]) || (T && T.whiteColor) || '#ffffff';
                    const PLATE_C1 = (T && T.bgGrad && T.bgGrad[1]) || PLATE_C0;
                    const _plateHex = (c) => {
                        const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(c || '').trim());
                        if (!m) return null;
                        let hx = m[1];
                        if (hx.length === 3) hx = hx[0] + hx[0] + hx[1] + hx[1] + hx[2] + hx[2];
                        return [parseInt(hx.slice(0, 2), 16), parseInt(hx.slice(2, 4), 16), parseInt(hx.slice(4, 6), 16)];
                    };
                    const _plateColor = (dx, dy) => {
                        const c0 = _plateHex(PLATE_C0), c1 = _plateHex(PLATE_C1);
                        if (!c0 || !c1) return PLATE_C0;   // nền tuỳ biến kiểu lạ → dùng thẳng màu đầu
                        // t của createLinearGradient(0,0,W,H) = chiếu điểm lên trục chéo
                        const t = Math.max(0, Math.min(1, (dx * W + dy * H) / (W * W + H * H)));
                        return 'rgb(' + Math.round(c0[0] + (c1[0] - c0[0]) * t) + ','
                            + Math.round(c0[1] + (c1[1] - c0[1]) * t) + ','
                            + Math.round(c0[2] + (c1[2] - c0[2]) * t) + ')';
                    };
                    // Sổ hộp sprite của KHUNG HÌNH + ELEMENT NÀY. Khai ở đây nên mỗi
                    // element/khung có sổ mới tinh — không thể rò sang cảnh sau.
                    const _spriteBoxes = [];

                    // LƯỚI MỰC của ảnh sprite: mỗi ô ghi ĐỘ PHỦ (bao nhiêu phần đục) và
                    // MÀU TRUNG BÌNH. Đo MỘT LẦN cho mỗi ảnh rồi nhớ ngay trên đối
                    // tượng ảnh (quét ở 96×96 nên rẻ, cả tiến trình chỉ một lần/ảnh).
                    //
                    // Vì sao lưới chứ không phải một hộp-bao: hộp-bao coi cả khoảng
                    // RỖNG bên trong là "nhân vật". Đo được trên japan_social khung 3
                    // — sprite ba quả bóng thoại rời nhau: chữ chỉ chạm mép một quả mà
                    // hộp-bao báo chồng lấn 77% (lưới mực: 25%) → lót nền oan, cắt cụt
                    // nét bóng thoại. Lưới 24×24 (ô ≈26px với sprite 620px, nhỏ hơn nửa
                    // dòng chữ) tính đúng phần chữ nằm trên MỰC THẬT.
                    //
                    // Vì sao cần cả MÀU: đè lên nhân vật chỉ khó đọc khi màu dưới chữ
                    // sát màu chữ. Chữ đỏ nằm trên quả bóng thoại TRẮNG vẫn đọc tốt —
                    // lót nền chỗ đó là phá hình mà chẳng cứu được gì (chính là artefact
                    // khung 3). Nên chỉ ô nào TƯƠNG PHẢN THẤP với màu chữ mới bị tính.
                    const PLATE_GRID = 24;
                    // 3.0 = ngưỡng WCAG cho chữ lớn; chú thích trên sprite luôn ≥28px
                    // đậm nên đúng nhóm "chữ lớn". Trên ngưỡng này chữ đọc được dù nằm
                    // trên hình → để yên.
                    const PLATE_CONTRAST = 3.0;
                    const _spriteInk = (img) => {
                        if (img.__t2ink) return img.__t2ink;
                        let ink = { g: null, G: 0 };   // đo hỏng → quay về dùng cả hộp ảnh
                        try {
                            const N = 96, G = PLATE_GRID, K = N / G;
                            const _c = HOST.createCanvas(N, N);
                            const _g = _c.getContext('2d');
                            _g.drawImage(img, 0, 0, N, N);
                            const _d = _g.getImageData(0, 0, N, N).data;
                            const cov = new Float32Array(G * G);
                            const cr = new Float32Array(G * G), cg = new Float32Array(G * G), cb = new Float32Array(G * G);
                            let any = false;
                            for (let py = 0; py < N; py++) {
                                const gy = (py / K) | 0;
                                for (let px = 0; px < N; px++) {
                                    const q = (py * N + px) * 4;
                                    if (_d[q + 3] > 16) {
                                        const kk = gy * G + ((px / K) | 0);
                                        cov[kk] += 1;
                                        cr[kk] += _d[q]; cg[kk] += _d[q + 1]; cb[kk] += _d[q + 2];
                                        any = true;
                                    }
                                }
                            }
                            if (any) {
                                for (let kk = 0; kk < G * G; kk++) {
                                    const n = cov[kk];
                                    if (n > 0) { cr[kk] /= n; cg[kk] /= n; cb[kk] /= n; }
                                    cov[kk] = n / (K * K);
                                }
                                ink = { g: cov, G: G, r: cr, gg: cg, b: cb };
                            }
                        } catch (_e) { }
                        try { img.__t2ink = ink; } catch (_e) { }
                        return ink;
                    };
                    // Độ sáng tương đối + tỉ số tương phản (WCAG 2.x).
                    const _lumOf = (r, g, b) => {
                        const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
                    };
                    // Đọc màu chữ hiện hành. Gradient/pattern → null (không đoán được).
                    const _rgbOf = (c) => {
                        if (typeof c !== 'string') return null;
                        const h = _plateHex(c);
                        if (h) return h;
                        const m = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(c.trim());
                        return m ? [+m[1], +m[2], +m[3]] : null;
                    };

                    // Ghi hộp THẬT (đã nhân ma trận hiện hành) của một lần ui.sprite.
                    const _noteSprite = (name, cx, cy, size, o) => {
                        if (_tmLost) return;
                        if (Math.abs(_tm[1]) > 1e-6 || Math.abs(_tm[2]) > 1e-6) return;  // xoay → bỏ
                        if (typeof cx !== 'number' || !isFinite(cx)) return;
                        if (typeof cy !== 'number' || !isFinite(cy)) return;
                        const sz = (typeof size === 'number' && size > 0) ? size : 420;
                        let w = sz, h = sz;
                        let ink = null;
                        const img = (typeof global !== 'undefined' && global.getSprite) ? global.getSprite(name) : null;
                        if (img && img.width > 0 && img.height > 0) {
                            const s = sz / Math.max(img.width, img.height);   // y hệt ui.sprite
                            w = img.width * s; h = img.height * s;
                            ink = _spriteInk(img);
                        }
                        // Nhún dọc: tính ĐÚNG độ lệch của khung này bằng chính công thức
                        // ui.sprite dùng (cùng `time`), thay vì nới hộp ra ±biên độ — nới
                        // là đoán, mà đoán thừa thì lót nền oan ở rìa trên/dưới nhân vật.
                        // (Lắc `tilt` ≤0.045 rad thì BỎ QUA: hộp lệch dưới 3° không đổi
                        // được kết luận đè/không-đè, mà xét vào thì phải bỏ cả trục.)
                        const bobA = (o && o.bob !== undefined) ? o.bob : 8;
                        const bob = Math.sin(timeSecs * 2 + ((o && o.seed) || 0)) * bobA;
                        // ui.sprite căn TÂM ảnh tại (cx, cy + bob)
                        const lx0 = cx - w / 2, ly0 = cy + bob - h / 2;
                        const sx = _tm[0], sy = _tm[3];
                        const dx0 = sx * lx0 + _tm[4], dx1 = sx * (lx0 + w) + _tm[4];
                        const dy0 = sy * ly0 + _tm[5], dy1 = sy * (ly0 + h) + _tm[5];
                        _spriteBoxes.push({
                            x0: Math.min(dx0, dx1), x1: Math.max(dx0, dx1),
                            y0: Math.min(dy0, dy1), y1: Math.max(dy0, dy1),
                            g: (ink && ink.g) || null, G: (ink && ink.G) || 0,
                            r: ink && ink.r, gg: ink && ink.gg, b: ink && ink.b
                        });
                    };

                    // ui.sprite là NƠI DUY NHẤT biết nhân vật nằm ở đâu → ghi sổ rồi vẽ
                    // y như cũ. uiKit dựng mới cho từng element/khung nên vá đè an toàn.
                    // Bản kit của lượt ĐO __centerDY là đối tượng khác, không đi qua đây.
                    if (uiKit && typeof uiKit.sprite === 'function') {
                        const _sprite0 = uiKit.sprite;
                        uiKit.sprite = function (name, cx, cy, size, o) {
                            try { _noteSprite(name, cx, cy, size, o); } catch (_e) { }
                            return _sprite0.apply(this, arguments);
                        };
                    }

                    // Chữ vừa vẽ có đè sprite không? Đè thì lót nền TRƯỚC khi vẽ chữ.
                    // Chạy trong CÙNG phép biến hình với chữ nên nền luôn nằm đúng dưới.
                    let _plateKey = '';
                    const _plateUnderText = (text, x, y) => {
                        // Cảnh TỰ lót nền cho chữ của nó (bộ cảnh Edo của Content Studio: dải tiêu đề, nhãn washi) khai
                        // `no_text_plate: true`. Lưới này chỉ biết hộp sprite, không biết cảnh đã vẽ một dải nền xen giữa
                        // chữ và tranh — nên trên tranh SÁNG màu nó lót thêm một tấm màu giấy đè lên chính dải ấy và chữ
                        // sáng biến mất (đo 21/9/2026: tiêu đề mất từ giây 41 của video thử, đúng lúc tranh đổi sang nền sáng).
                        if (el && el.no_text_plate === true) return;
                        if (_tmLost) return;
                        if (Math.abs(_tm[1]) > 1e-6 || Math.abs(_tm[2]) > 1e-6) return;  // xoay → bỏ
                        const s = String(text == null ? '' : text);
                        if (!s.trim()) return;
                        if (typeof x !== 'number' || !isFinite(x)) return;
                        if (typeof y !== 'number' || !isFinite(y)) return;
                        const sx = _tm[0], sy = _tm[3];
                        if (!(sx > 1e-6) || !(sy > 1e-6)) return;
                        const font0 = ctx.font || '';
                        const m0 = font0.match(OF_SIZE_RE);
                        if (!m0) return;
                        const size = parseFloat(m0[1]);
                        if (!(size > 0)) return;
                        const align = ctx.textAlign || 'start';
                        const base = ctx.textBaseline || 'alphabetic';
                        // strokeText + fillText cùng chuỗi/vị trí = một dòng chữ có viền:
                        // lót MỘT lần, nếu không tấm thứ hai sẽ xoá mất nét viền.
                        const key = s + ' ' + x + ' ' + y + ' ' + font0 + ' ' + align + ' ' + base;
                        if (key === _plateKey) return;
                        const mt = ctx.measureText(s);
                        const w = mt.width;
                        if (!(w > 0)) return;
                        let asc = mt.actualBoundingBoxAscent, desc = mt.actualBoundingBoxDescent;
                        if (!(isFinite(asc) && isFinite(desc) && asc + desc > 0)) {
                            // backend không có hộp-bao thật → ước theo cỡ font + textBaseline
                            const top = (base === 'top' || base === 'hanging') ? 0
                                : (base === 'middle') ? -size * 0.5
                                    : (base === 'bottom' || base === 'ideographic') ? -size
                                        : -size * 0.8;
                            asc = -top; desc = size + top;
                        }
                        const lx0 = (align === 'center') ? x - w / 2
                            : (align === 'right' || align === 'end') ? x - w : x;
                        const ly0 = y - asc, ly1 = y + desc;
                        const dx0 = sx * lx0 + _tm[4], dx1 = sx * (lx0 + w) + _tm[4];
                        const dy0 = sy * ly0 + _tm[5], dy1 = sy * ly1 + _tm[5];
                        const area = (dx1 - dx0) * (dy1 - dy0);
                        if (!(area > 0)) return;
                        // Màu chữ để xét tương phản. Đọc không ra (gradient/pattern) thì
                        // KHÔNG suy đoán: tính mọi ô có mực, như trước khi có bước màu.
                        const tRGB = _rgbOf(ctx.fillStyle);
                        const tL = tRGB ? _lumOf(tRGB[0], tRGB[1], tRGB[2]) : null;
                        let hit = 0;
                        for (let i = 0; i < _spriteBoxes.length; i++) {
                            const b = _spriteBoxes[i];
                            const ox = Math.min(dx1, b.x1) - Math.max(dx0, b.x0);
                            const oy = Math.min(dy1, b.y1) - Math.max(dy0, b.y0);
                            if (!(ox > 0 && oy > 0)) continue;        // loại nhanh
                            if (!b.g) { hit += ox * oy; continue; }   // không đo được mực → cả hộp
                            // cộng phần chữ nằm trên ô CÓ MỰC và TƯƠNG PHẢN THẤP,
                            // nhân với độ phủ của ô (rìa nhân vật che ít thì tính ít)
                            const cw = (b.x1 - b.x0) / b.G, ch = (b.y1 - b.y0) / b.G;
                            const i0 = Math.max(0, Math.floor((dx0 - b.x0) / cw));
                            const i1 = Math.min(b.G - 1, Math.floor((dx1 - b.x0) / cw));
                            const j0 = Math.max(0, Math.floor((dy0 - b.y0) / ch));
                            const j1 = Math.min(b.G - 1, Math.floor((dy1 - b.y0) / ch));
                            for (let j = j0; j <= j1; j++) {
                                for (let k = i0; k <= i1; k++) {
                                    const kk = j * b.G + k;
                                    const covK = b.g[kk];
                                    if (!(covK > 0)) continue;
                                    if (tL !== null && b.r) {
                                        const cL = _lumOf(b.r[kk], b.gg[kk], b.b[kk]);
                                        const hi = Math.max(tL, cL), lo = Math.min(tL, cL);
                                        if ((hi + 0.05) / (lo + 0.05) >= PLATE_CONTRAST) continue;  // đọc tốt → bỏ
                                    }
                                    const gx = b.x0 + k * cw, gy = b.y0 + j * ch;
                                    const w2 = Math.min(dx1, gx + cw) - Math.max(dx0, gx);
                                    const h2 = Math.min(dy1, gy + ch) - Math.max(dy0, gy);
                                    if (w2 > 0 && h2 > 0) hit += w2 * h2 * covK;
                                }
                            }
                        }
                        if (hit / area < PLATE_MIN_RATIO) return;   // KHÔNG ĐÈ → KHÔNG ĐỔI PIXEL
                        _plateKey = key;
                        // Đệm theo cỡ chữ (chữ to cần lề to) nhưng có trần, kẻo tấm nền
                        // của tiêu đề 80px nuốt cả nửa khung.
                        const padX = Math.max(6, Math.min(14, size * 0.30));
                        const padY = Math.max(4, Math.min(12, size * 0.22));
                        const rw = w + padX * 2, rh = (ly1 - ly0) + padY * 2;
                        const rr = Math.min(10, rh * 0.35);
                        const fs0 = ctx.fillStyle;
                        ctx.save();
                        // đổ bóng/nét mà code AI đang bật KHÔNG được dính vào tấm nền
                        ctx.shadowBlur = 0; ctx.shadowColor = 'rgba(0,0,0,0)';
                        ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
                        ctx.globalAlpha = ctx.globalAlpha * PLATE_ALPHA;
                        // __centerDY là phép dịch dọc engine áp NGOÀI _tm (xem ghi chú
                        // ở khối nạp ma trận) — nó không đổi kết quả so chồng lấn (chữ
                        // và sprite cùng dịch) nhưng ĐỔI chỗ lấy màu nền, nên cộng vào.
                        ctx.fillStyle = _plateColor((dx0 + dx1) / 2,
                            (dy0 + dy1) / 2 + ((el && el.__centerDY) || 0));
                        ctx.beginPath();
                        if (ctx.roundRect) ctx.roundRect(lx0 - padX, ly0 - padY, rw, rh, rr);
                        else ctx.rect(lx0 - padX, ly0 - padY, rw, rh);
                        ctx.fill();
                        ctx.restore();
                        // node-canvas: restore() không trả fillStyle về CHUỖI (xem ghi chú
                        // bug ở nhánh emoji) → gán lại tay cho chắc, kể cả gradient.
                        ctx.fillStyle = fs0;
                    };

                    // Trả null = KHÔNG ĐỤNG GÌ. Trả {font, text} = vẽ bản đã co/cắt.
                    const _fitOverflow = (text, x, hasMaxWidth) => {
                        if (_tmLost || hasMaxWidth) return null;
                        const s = String(text == null ? '' : text);
                        if (!s.trim()) return null;
                        if (typeof x !== 'number' || !isFinite(x)) return null;
                        // Xoay/nghiêng → bề rộng ngang không suy ra được đơn giản.
                        if (Math.abs(_tm[1]) > 1e-6 || Math.abs(_tm[2]) > 1e-6) return null;
                        const sx = _tm[0];
                        if (!(sx > 1e-6)) return null;
                        const font0 = ctx.font || '';
                        const m0 = font0.match(OF_SIZE_RE);
                        if (!m0) return null;                  // không đọc được cỡ → không dám đụng
                        const size0 = parseFloat(m0[1]);
                        if (!(size0 > 0)) return null;
                        const w0 = ctx.measureText(s).width;
                        if (!(w0 > 0)) return null;

                        const devX = sx * x + _tm[4];
                        const align = ctx.textAlign || 'start';
                        let avail;
                        if (align === 'center') {
                            avail = 2 * Math.min(devX - OF_MARGIN, (W - OF_MARGIN) - devX);
                        } else if (align === 'right' || align === 'end') {
                            avail = devX - OF_MARGIN;
                        } else {
                            avail = (W - OF_MARGIN) - devX;
                        }
                        // Neo ngoài vùng an toàn: chữ đang trượt vào từ ngoài mép (hoặc
                        // cố ý tràn). Co lại chỉ làm giật hoạt cảnh → để nguyên.
                        if (avail <= 0) return null;
                        if (w0 * sx <= avail + 0.5) return null;   // KHÔNG TRÀN → KHÔNG ĐỔI PIXEL

                        const floor = Math.max(
                            Math.floor(size0 * OF_FLOOR_RATIO * 2) / 2,
                            Math.min(size0, OF_FLOOR_PX)
                        );
                        // Ước lượng tuyến tính rồi ĐO LẠI (hinting làm bề rộng không
                        // tuyến tính tuyệt đối), bước 0.5px cho ổn định giữa các khung.
                        let size1 = Math.floor(size0 * (avail / (w0 * sx)) * 2) / 2;
                        if (size1 > size0) size1 = size0;
                        let guard = 0;
                        while (size1 >= floor && guard++ < 40) {
                            ctx.font = font0.replace(OF_SIZE_RE, size1 + 'px');
                            if (ctx.measureText(s).width * sx <= avail) {
                                ctx.font = font0;
                                return { font: font0.replace(OF_SIZE_RE, size1 + 'px'), text: s };
                            }
                            size1 -= 0.5;
                        }
                        // Chạm sàn mà vẫn tràn → giữ cỡ sàn, cắt chuỗi + '…'.
                        const fontF = font0.replace(OF_SIZE_RE, floor + 'px');
                        ctx.font = fontF;
                        let lo = 0, hi = s.length;
                        while (lo < hi) {
                            const mid = Math.ceil((lo + hi) / 2);
                            if (ctx.measureText(s.slice(0, mid) + '…').width * sx <= avail) lo = mid;
                            else hi = mid - 1;
                        }
                        ctx.font = font0;
                        while (lo > 0 && /[\uD800-\uDBFF]/.test(s.charAt(lo - 1))) lo--;  // không cắt đôi cặp surrogate
                        return { font: fontF, text: s.slice(0, lo).replace(/\s+$/, '') + '…' };
                    };

                    const _emitText = (kind, text, x, y, maxWidth) => {
                        let fit = null;
                        try { fit = _fitOverflow(text, x, maxWidth !== undefined); } catch (_e) { fit = null; }
                        if (!fit) {
                            // Sổ rỗng (cảnh không có nhân vật) ⇒ bỏ qua ngay, đường vẽ y hệt cũ.
                            if (_spriteBoxes.length) { try { _plateUnderText(text, x, y); } catch (_e) { } }
                            if (maxWidth !== undefined) ctx[kind](text, x, y, maxWidth);
                            else ctx[kind](text, x, y);
                            return;
                        }
                        const font0 = ctx.font;
                        ctx.font = fit.font;
                        // lót theo cỡ ĐÃ CO — nền phải ôm đúng chữ sắp vẽ, không phải chữ gốc
                        if (_spriteBoxes.length) { try { _plateUnderText(fit.text, x, y); } catch (_e) { } }
                        ctx[kind](fit.text, x, y);
                        ctx.font = font0;   // không rò cỡ đã co sang lời gọi sau
                    };

                    // Bọc customCtx để chặn fillText có emoji → vẽ bằng icon Lucide
                    // of canvas font rendering which can be blurry/invisible after ctx.restore() resets fillStyle.
                    const emojiRegex = /[\u{1F300}-\u{1FFFF}]|[\u{2600}-\u{27BF}]|[\u{2300}-\u{23FF}]/u;
                    const customCtxWithEmoji = new Proxy(customCtx, {
                        get(target, prop) {
                            // Theo vết biến hình — chỉ ghi sổ, hành vi vẽ y hệt cũ.
                            if (prop === 'save') return function () { _tmStack.push([_tm.slice(), _tmLost]); return target.save(); };
                            if (prop === 'restore') return function () {
                                if (_tmStack.length) { const st = _tmStack.pop(); _tm = st[0]; _tmLost = st[1]; }
                                else _tmLost = true;   // restore lệch save → mất mốc, tắt lưới đỡ
                                return target.restore();
                            };
                            if (prop === 'translate') return function (dx, dy) { _tTranslate(_tm, dx || 0, dy || 0); return target.translate(dx, dy); };
                            if (prop === 'scale') return function (sx, sy) { _tScale(_tm, sx == null ? 1 : sx, sy == null ? 1 : sy); return target.scale(sx, sy); };
                            if (prop === 'rotate') return function (r) { _tRotate(_tm, r || 0); return target.rotate(r); };
                            if (prop === 'transform') return function (a, b, c, d, e, f) { _tMul(_tm, a, b, c, d, e, f); return target.transform(a, b, c, d, e, f); };
                            if (prop === 'setTransform' || prop === 'resetTransform') return function (...args) { _tmLost = true; return target[prop](...args); };
                            if (prop === 'strokeText') {
                                return function (text, x, y, maxWidth) { _emitText('strokeText', text, x, y, maxWidth); };
                            }
                            if (prop === 'fillText') {
                                return function(text, x, y, maxWidth) {
                                    // Check if text is a single emoji character
                                    const trimmed = String(text || '').trim();
                                    if (trimmed.length <= 4 && emojiRegex.test(trimmed)) {
                                        // Determine font size from current ctx font (read from real ctx)
                                        const fontStr = ctx.font || '';
                                        const sizeMatch = fontStr.match(/(\d+)px/);
                                        const size = sizeMatch ? parseInt(sizeMatch[1]) : 36;
                                        // Icon Lucide premium trước (nét mảnh, ăn fillStyle hiện
                                        // tại) — không có icon thì vẽ ký tự đơn sắc.
                                        const licon = global.EMOJI_TO_LUCIDE && global.EMOJI_TO_LUCIDE[trimmed];
                                        if (licon && global.drawLucide) {
                                            // Màu icon = fillStyle hiện tại. Ý nghĩa này BẮT BUỘC
                                            // phải xác định được từ display list, không được phụ
                                            // thuộc backend: node-canvas có BUG restore() không
                                            // khôi phục fillStyle về chuỗi sau khi gán gradient
                                            // trong phạm vi đó → đọc ra object → rơi về xám. Bộ ghi
                                            // lệnh làm ĐÚNG CHUẨN nên đọc ra chuỗi.
                                            // Xem docs/display-list.md — mục "bug node-canvas".
                                            const fs0 = (typeof ctx.fillStyle === 'string') ? ctx.fillStyle : '';
                                            const baseline0 = ctx.textBaseline || 'alphabetic';
                                            const yOff0 = baseline0 === 'middle' ? 0 : -size * 0.35;
                                            if (global.drawLucide(ctx, licon, x, y + yOff0, size, fs0 || '#64748b')) return;
                                        }
                                        // Use drawEmoji for full-color crisp rendering (pass real ctx, not proxy)
                                        if (global.drawEmoji) {
                                            // textBaseline affects y offset — compensate for 'alphabetic' (default)
                                            const baseline = ctx.textBaseline || 'alphabetic';
                                            const yOffset = baseline === 'middle' ? 0 : (baseline === 'alphabetic' ? -size * 0.15 : 0);
                                            global.drawEmoji(ctx, trimmed, x, y + yOffset, size);
                                            return;
                                        }
                                    }
                                    // For non-emoji text, check if fillStyle has gone dark (e.g. after ctx.restore()).
                                    // Threshold 120: sum of R+G+B < 120 is considered "too dark to render visible text".
                                    // NOTE: gradient/pattern objects are INTENTIONAL (gradient headline text) —
                                    // never clobber them to white; only plain dark color strings get rescued.
                                    const fs = ctx.fillStyle;
                                    const isDarkFill =
                                        (typeof fs === 'string' && /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.test(fs) && (()=>{
                                            const m = fs.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
                                            return m && (parseInt(m[1]) + parseInt(m[2]) + parseInt(m[3])) < 120;
                                        })());
                                    if (isDarkFill) {
                                        ctx.save();
                                        ctx.fillStyle = 'rgba(255,255,255,0.95)';
                                        ctx.textAlign = ctx.textAlign; // preserve alignment
                                        _emitText('fillText', text, x, y, maxWidth);
                                        ctx.restore();
                                        return;
                                    }
                                    _emitText('fillText', text, x, y, maxWidth);
                                };
                            }
                            return target[prop];
                        }
                    });

                    // ── CĂN GIỮA DỌC card AI tự-vẽ (custom_js KHÔNG có template) ──
                    // AI hay neo card ở đỉnh khung (y≈14) dù recipe bảo căn giữa —
                    // few-shot RR() thắng prose. Đo hộp-bao THẬT trên canvas phụ MỘT
                    // LẦN (cache theo el), rồi dịch dọc cho tâm nội dung về giữa khung.
                    // Tự-giới-hạn: cảnh phủ-khung (chrome/mn_/intro) đo ra gần trọn
                    // chiều cao → bỏ qua. drawEmoji/ui.* đều nhận ctx phụ nên không rò
                    // sang canvas chính. Preview tua từng-khung, export offline → rẻ.
                    if (el.__centerDY === undefined) {
                        el.__centerDY = 0;
                        if (!el.template) {
                            try {
                                // CỐ Ý KHÔNG nhân RSCALE: đây là canvas ĐO, không
                                // phải canvas vẽ — ảnh của nó không bao giờ lên
                                // khung hình. Nó đo hộp-bao trong TOẠ ĐỘ LOGIC để
                                // ra __centerDY cũng bằng toạ độ logic. Giữ ở W×H
                                // → số đo (và getImageData) y hệt ở mọi RSCALE,
                                // mà không tốn 4× RAM/thời gian quét pixel ở 4K.
                                const _mc = HOST.createCanvas(W, H);
                                const _mx = _mc.getContext('2d');
                                const _muk = makeUiKit(_mx, artStyle, timeSecs, rc, global.drawEmoji);
                                const _mmk = makeMnKit(_mx, timeSecs);
                                const _mek = makeEckKit(_mx, timeSecs, T);
                                fn(_mx, W, H, MX, coords.y, 0.95, timeSecs, el, T, rc, wrapText, global.drawEmoji, _muk, _mmk, _mek);
                                const _d = _mx.getImageData(0, 0, W, H).data;
                                let _minY = H, _maxY = -1;
                                for (let _y = 0; _y < H; _y += 2) {
                                    const _row = _y * W * 4;
                                    for (let _x = 0; _x < W; _x += 8) {
                                        if (_d[_row + _x * 4 + 3] > 12) { if (_y < _minY) _minY = _y; if (_y > _maxY) _maxY = _y; break; }
                                    }
                                }
                                if (_maxY > _minY && (_maxY - _minY) < H * 0.82) {
                                    let _dy = Math.round(H / 2 - (_minY + _maxY) / 2);
                                    if (_minY + _dy < 40) _dy = 40 - _minY;
                                    if (_maxY + _dy > H - 40) _dy = H - 40 - _maxY;
                                    el.__centerDY = _dy;
                                }
                            } catch (_e) { el.__centerDY = 0; }
                        }
                    }

                    ctx.save();

                    if (el.__centerDY) ctx.translate(0, el.__centerDY);

                    if (scaleFactor !== 1.0) {

                        const centerX = W / 2;

                        const centerY = coords.y + scaledH / 2;

                        ctx.translate(centerX, centerY);

                        ctx.scale(scaleFactor, scaleFactor);

                        ctx.translate(-centerX, -centerY);

                    }

                    // restore trong finally — code AI crash giữa chừng mà bỏ
                    // restore là transform rò rỉ sang element/step sau (chrome
                    // xếp bậc thang).
                    let retH;
                    try {
                        retH = fn(customCtxWithEmoji, W, H, MX, coords.y, stepProgress, timeSecs, el, T, rc, wrapText, global.drawEmoji, uiKit, mnKit, eckKit);
                    } finally {
                        ctx.restore();
                    }

                    if (typeof retH === 'number') h = retH;

                } catch (e) {

                    process.stderr.write(`[custom_js Error] ${e.message}\n`);

                }

            }

            // bbox chế độ sửa — thô như edu: toàn bề ngang MX..W−MX, cao = height
            // sau scale; app tie-break chọn box nhỏ nhất khi chồng lấp.
            t2EditBox(el, MX, coords.y + (el.__centerDY || 0), W - MX * 2, h * scaleFactor);

            return coords.isAbsolute ? 0 : h * scaleFactor;

        }

        case 'box': {

            // Dynamic box: look ahead to measure content inside

            // Box itself is rendered as background; returns 0 height (text inside handles it)

            // We store box info for the render pass

            return 0; // handled by renderBoxWithContent

        }

        case 'line': {

            ctx.beginPath();

            ctx.moveTo(MX, cursorY + 5);

            ctx.lineTo(W - MX, cursorY + 5);

            ctx.strokeStyle = rc(el.color || 'muted');

            ctx.lineWidth = 2;

            if (el.dash) ctx.setLineDash([8, 4]);

            ctx.stroke(); ctx.setLineDash([]);

            return 18;

        }

        case 'image': {

            if (el.hidden) return 0;

            if (el.src && IMAGE_CACHE[el.src]) {

                  const img = IMAGE_CACHE[el.src];

                  // Fit within content width, but also cap height at 50% of canvas H

                  // This prevents 1:1 AI images from scaling too large in 16:9 landscape

                  const availW = W - MX * 2;

                  const maxH = Math.min(Math.round(availW * 0.75), Math.round(H * 0.5));

                  const ratio = Math.min(availW / img.width, maxH / img.height);

                  const iw = Math.round(img.width * ratio);

                  const ih = Math.round(img.height * ratio);

                  const coords = getElementCoords(el, cursorY);

                  let ix = coords.x - iw / 2;

                  if (!coords.isAbsolute) {

                      ix = (W - iw) / 2;

                  }

                const anim = el.animation || 'pop_in';

                let scale = 1.0;

                if (anim === 'pop_in' && stepProgress < 1.0) {

                    const p = Math.min(stepProgress * 4.0, 1.0); // Fast pop in

                    scale = 0.8 + 0.2 * easeOutBack(p);

                }

                // ── Background removal via color-keying ──

                // keep_bg: true → BỎ QUA đục nền, vẽ ảnh nguyên bản. Dành cho ảnh CHỤP
                // người dùng chèn — đục nền theo màu 4 góc sẽ làm thủng ảnh loang lổ.
                // Thiếu cờ / false / undefined → đục nền như cũ (ảnh sprite template).

                const processedImg = el.keep_bg ? img : removeImageBackground(img, el.src);

                ctx.save();

                if (scale !== 1.0) {

                    ctx.translate(ix + iw/2, coords.y + ih/2);

                    ctx.scale(scale, scale);

                    ctx.translate(-(ix + iw/2), -(coords.y + ih/2));

                }

                // No clipping rect — draw transparent image directly

                ctx.drawImage(processedImg, ix, coords.y, iw, ih);

                ctx.restore();

                t2EditBox(el, ix, coords.y, iw, ih); // bbox chế độ sửa

                return coords.isAbsolute ? 0 : ih + 24;

            }

            return 0;

        }

        case 'digit_row': {

            // Renders digits 0-9 in a row with even/odd coloring

            // e.g. {"type":"digit_row","even_color":"cyan","odd_color":"orange","fontSize":52}

            const drFs = el.fontSize || 52;

            const drEven = rc(el.even_color || 'cyan');

            const drOdd  = rc(el.odd_color  || 'orange');

            const digits = ['0','1','2','3','4','5','6','7','8','9'];

            const cellW  = (W - MX * 2) / digits.length;

            const rowH   = drFs + 24;

            const bgEven = drEven + '33'; // 20% alpha

            const bgOdd  = drOdd  + '33';

            ctx.font = `bold ${drFs}px ${T.font}`;

            ctx.textAlign = 'center';

            ctx.textBaseline = 'middle';

            digits.forEach((d, i) => {

                const isEven = i % 2 === 0;

                const x = MX + cellW * i;

                const cy2 = cursorY + rowH / 2;

                // Background pill

                ctx.fillStyle = isEven ? bgEven : bgOdd;

                const r = 8;

                ctx.beginPath();

                ctx.roundRect(x + 2, cursorY + 2, cellW - 4, rowH - 4, r);

                ctx.fill();

                // Border

                ctx.strokeStyle = isEven ? drEven : drOdd;

                ctx.lineWidth = 1.5;

                ctx.stroke();

                // Digit

                ctx.fillStyle = isEven ? drEven : drOdd;

                ctx.fillText(d, x + cellW / 2, cy2);

            });

            ctx.textAlign = 'left';

            return rowH + 12;

        }

        case 'icon': {

            const sz = el.size || 64;

            ctx.font = `${sz}px "Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Segoe UI Symbol", ${T.font}`;

            ctx.fillStyle = rc(el.color || 'yellow');

            ctx.textAlign = 'center'; ctx.textBaseline = 'top';

            const coords = getElementCoords(el, cursorY);

            const ix = coords.isAbsolute ? coords.x : W / 2;

            ctx.fillText(el.emoji || '', ix, coords.y);

            ctx.textAlign = 'left';

            return coords.isAbsolute ? 0 : sz + 10;

        }

        case 'arrow': {

            const col = rc(el.color || 'yellow');

            const ax1 = MX + 20, ax2 = W - MX - 20, ay = cursorY + 12;

            ctx.beginPath(); ctx.moveTo(ax1, ay); ctx.lineTo(ax2, ay);

            ctx.strokeStyle = col; ctx.lineWidth = 3; ctx.stroke();

            const a = Math.atan2(0, ax2 - ax1), hl = 16;

            ctx.beginPath(); ctx.moveTo(ax2, ay);

            ctx.lineTo(ax2 - hl * Math.cos(a - 0.4), ay - hl * Math.sin(a - 0.4));

            ctx.lineTo(ax2 - hl * Math.cos(a + 0.4), ay - hl * Math.sin(a + 0.4));

            ctx.closePath(); ctx.fillStyle = col; ctx.fill();

            return 30;

        }

        // ── VISUAL ELEMENT: number_line ──────────────────────────────

        // {"type":"number_line","min":0,"max":10,"highlight":[3,7],"mark":5,"color":"cyan","fontSize":28}

        // Draws a ruler-style number line with optional highlighted points

        case 'number_line': {

            const nlMin = el.min ?? 0;

            const nlMax = el.max ?? 10;

            const nlH = 80;

            const nlY = cursorY + nlH / 2;

            const nlX1 = MX + 10, nlX2 = W - MX - 10;

            const nlRange = nlMax - nlMin || 1;

            const nlColor = rc(el.color || 'cyan');

            const nlFs = el.fontSize || 24;

            const highlights = Array.isArray(el.highlight) ? el.highlight : [];

            // Main line

            ctx.strokeStyle = nlColor + '99'; ctx.lineWidth = 3;

            ctx.beginPath(); ctx.moveTo(nlX1, nlY); ctx.lineTo(nlX2, nlY); ctx.stroke();

            // Arrow head

            ctx.beginPath(); ctx.moveTo(nlX2, nlY);

            ctx.lineTo(nlX2 - 12, nlY - 6); ctx.lineTo(nlX2 - 12, nlY + 6);

            ctx.closePath(); ctx.fillStyle = nlColor + '99'; ctx.fill();

            // Ticks and labels

            ctx.font = `${nlFs}px ${T.font}`; ctx.textAlign = 'center'; ctx.textBaseline = 'top';

            for (let v = nlMin; v <= nlMax; v++) {

                const px = nlX1 + ((v - nlMin) / nlRange) * (nlX2 - nlX1 - 20);

                const isHighlight = highlights.includes(v);

                const isMark = v === el.mark;

                if (isMark) {

                    // Big circle marker

                    ctx.beginPath(); ctx.arc(px, nlY, 14, 0, Math.PI * 2);

                    ctx.fillStyle = nlColor; ctx.fill();

                    ctx.fillStyle = '#0d0d1a'; ctx.fillText(String(v), px, nlY - nlFs/2 - 2);

                } else if (isHighlight) {

                    ctx.beginPath(); ctx.arc(px, nlY, 8, 0, Math.PI * 2);

                    ctx.fillStyle = nlColor + '99'; ctx.fill();

                } else {

                    // Tick

                    ctx.strokeStyle = nlColor + '66'; ctx.lineWidth = 1.5;

                    ctx.beginPath(); ctx.moveTo(px, nlY - 6); ctx.lineTo(px, nlY + 6); ctx.stroke();

                }

                ctx.fillStyle = isHighlight || isMark ? nlColor : nlColor + '88';

                ctx.fillText(String(v), px, nlY + 12);

            }

            ctx.textAlign = 'left';

            return nlH + nlFs + 16;

        }

        // ── VISUAL ELEMENT: comparison_bar ───────────────────────────

        // {"type":"comparison_bar","left":{"label":"A","value":7,"color":"cyan"},"right":{"label":"B","value":5,"color":"orange"}}

        // Draws two horizontal bars side by side for comparison (lớn hơn/nhỏ hơn)

        case 'comparison_bar': {

            const cb = el;

            const left  = cb.left  || { label: 'A', value: 5, color: 'cyan' };

            const right = cb.right || { label: 'B', value: 3, color: 'orange' };

            const maxVal = Math.max(left.value, right.value, 1);

            const barH = 32, rowGap = 10, labelW = 140, valW = 50;

            const barX = MX + labelW;

            const availW = W - MX * 2 - labelW - valW;

            let rowY = cursorY + 6;

            [left, right].forEach((side) => {

                const barW = Math.max((side.value / maxVal) * availW, 8);

                const col = rc(side.color || 'cyan');

                // Label on the left

                ctx.font = `bold 24px ${T.font}`; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';

                ctx.fillStyle = col;

                ctx.fillText(side.label, barX - 10, rowY + barH / 2);

                // Bar background

                ctx.fillStyle = col + '22';

                roundRect(barX, rowY, availW, barH, 5); ctx.fill();

                // Bar fill

                ctx.fillStyle = col + 'BB';

                roundRect(barX, rowY, barW, barH, 5); ctx.fill();

                // Value on the right

                ctx.textAlign = 'left'; ctx.fillStyle = col;

                ctx.font = `bold 22px ${T.font}`;

                ctx.fillText(String(side.value), barX + availW + 8, rowY + barH / 2);

                rowY += barH + rowGap;

            });

            ctx.textAlign = 'left';

            return (barH + rowGap) * 2 + 12;

        }

        // ── VISUAL ELEMENT: fraction_bar ─────────────────────────────

        // {"type":"fraction_bar","numerator":3,"denominator":4,"color":"cyan","showDecimal":false}

        // Draws a visual fraction as a segmented bar

        case 'fraction_bar': {

            const fn2 = el.numerator ?? 1, fd = el.denominator ?? 4;

            const fbH = 64, fbY = cursorY + 8;

            const fbW = W - MX * 2;

            const segW = fbW / fd;

            const fbCol = rc(el.color || 'cyan');

            for (let i = 0; i < fd; i++) {

                const sx = MX + i * segW;

                const filled = i < fn2;

                ctx.fillStyle = filled ? fbCol + 'CC' : fbCol + '22';

                ctx.beginPath(); ctx.roundRect(sx + 2, fbY, segW - 4, fbH, 4); ctx.fill();

                ctx.strokeStyle = fbCol + '88'; ctx.lineWidth = 1.5;

                ctx.stroke();

            }

            // Fraction label centered

            ctx.font = `bold 36px ${T.font}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';

            ctx.fillStyle = '#fff';

            ctx.fillText(`${fn2}/${fd}`, W / 2, fbY + fbH / 2);

            if (el.showDecimal) {

                ctx.font = `24px ${T.font}`; ctx.fillStyle = fbCol;

                ctx.fillText(`= ${(fn2/fd).toFixed(2)}`, W / 2 + 80, fbY + fbH / 2);

            }

            ctx.textAlign = 'left';

            return fbH + 28;

        }

        case 'math_calc': {

            const fs = el.fontSize || 48;

            ctx.font = `bold ${fs}px 'Courier New', Consolas, monospace`;

            ctx.fillStyle = rc(el.color || 'white');

            ctx.textAlign = 'right'; ctx.textBaseline = 'top';

            const cx = W / 2 + 80;

            let cy = cursorY + 10;

            const ops = el.operands || [];

            const inters = el.intermediates || [];

            const fullResult = String(el.result || '');

            // ── Expression-mode fallback ──────────────────────────────

            // Detect when operands are expression strings (not simple numbers)

            // e.g. ["35 + 5 × 2", "5 × 2 = 10", "35 + 10 = 45"]

            const isExprMode = ops.some(o => /[a-zA-Z×÷=]/.test(String(o)) || String(o).includes('+') || String(o).includes('-'));

            if (isExprMode || (ops.length === 0 && el.expression)) {

                // Render as centered stacked expression lines

                ctx.textAlign = 'center';

                ctx.textBaseline = 'top';

                const lines = ops.length > 0 ? ops : (el.expression ? [el.expression] : []);

                for (let i = 0; i < lines.length; i++) {

                    const line = String(lines[i]);

                    // Last line or line containing '=' with result → highlight green

                    const isResult = i === lines.length - 1 && fullResult && line.includes(fullResult);

                    if (isResult) {

                        ctx.save();

                        ctx.shadowColor = '#00FF88'; ctx.shadowBlur = 18;

                        ctx.fillStyle = '#00FF88';

                    }

                    ctx.fillText(line, W / 2, cy);

                    if (isResult) ctx.restore();

                    cy += fs * 1.45;

                }

                // Separator + result if not already shown in last line

                if (fullResult && ops.length > 0 && !ops[ops.length - 1].toString().includes(fullResult)) {

                    cy += 4;

                    ctx.beginPath(); ctx.moveTo(W / 2 - 200, cy); ctx.lineTo(W / 2 + 200, cy);

                    ctx.strokeStyle = rc(el.color || 'white'); ctx.lineWidth = 3; ctx.stroke();

                    cy += 14;

                    ctx.save();

                    ctx.shadowColor = '#00FF88'; ctx.shadowBlur = 18;

                    ctx.fillStyle = '#00FF88';

                    ctx.fillText(fullResult, W / 2, cy);

                    ctx.restore();

                    cy += fs * 1.45;

                }

                ctx.textAlign = 'left';

                return (cy - cursorY) + 10;

            }

            // ── End expression-mode ───────────────────────────────────

            if (el.op === ':') {

                // Vietnamese Long Division Layout

                // Left side: Dividend and Intermediates (remainders)

                // Right side: Divisor and Quotient

                const cxLeft = W / 2 - 15;

                const cxRight = W / 2 + 15;

                // Left column: right aligned

                ctx.textAlign = 'right';

                ctx.fillText(ops[0] || '', cxLeft, cy);

                let cyLeft = cy + fs * 1.3;

                for (let i = 0; i < inters.length; i++) {

                    ctx.fillText(inters[i], cxLeft, cyLeft);

                    cyLeft += fs * 1.3;

                }

                // Right column: left aligned

                ctx.textAlign = 'left';

                ctx.fillText(ops[1] || '', cxRight, cy);

                // Horizontal line under divisor

                ctx.beginPath(); ctx.moveTo(W / 2, cy + fs * 1.2); ctx.lineTo(W / 2 + 150, cy + fs * 1.2);

                ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 4; ctx.stroke();

                let cyRight = cy + fs * 1.3 + 8;

                // Result

                if (fullResult || el.result_partial !== undefined) {

                    const toDraw = (el.result_partial !== undefined && el.result_partial !== null) ? String(el.result_partial) : fullResult;

                    ctx.save();

                    if (el.result_partial !== undefined && el.result_partial !== null && toDraw.length > 0) {

                        ctx.shadowColor = '#00FF88'; ctx.shadowBlur = 22; ctx.fillStyle = '#00FF88';

                    } else if (el.reveal_result && stepProgress >= (el.reveal_at ?? 0.1)) {

                        ctx.fillStyle = rc('green');

                    } else if (!el.reveal_result) {

                        ctx.fillStyle = rc('green');

                    } else {

                        // Not revealed yet

                        ctx.globalAlpha = 0;

                    }

                    if (ctx.globalAlpha > 0) ctx.fillText(toDraw, cxRight, cyRight);

                    ctx.restore();

                    cyRight += fs * 1.3;

                }

                // Vertical line separating left and right

                const totalHLeft = Math.max(cyLeft - cy, cyRight - cy);

                ctx.beginPath(); ctx.moveTo(W / 2, cy - 5); ctx.lineTo(W / 2, cy + totalHLeft + 10);

                ctx.stroke();

                return Math.max(cyLeft, cyRight) - cursorY + 10;

            }

            // Standard Vertical Layout (+, -, x)

            // Calculate max length to position the operator

            const allStrs = [...ops.map(String), ...inters.map(String), fullResult];

            const totalLen = Math.max(...allStrs.map(s => s.length));

            for (let i = 0; i < ops.length; i++) {

                ctx.fillText(ops[i], cx, cy);

                if (i === ops.length - 1 && el.op) {

                    ctx.textAlign = 'left';

                    const opOffset = totalLen * (fs * 0.6) + 30;

                    ctx.fillText(el.op, cx - opOffset, cy);

                    ctx.textAlign = 'right';

                }

                cy += fs * 1.3;

            }

            // Horizontal separator line 1

            cy += 8;

            ctx.beginPath(); ctx.moveTo(cx - 240, cy); ctx.lineTo(cx + 20, cy);

            ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 4; ctx.stroke();

            cy += 20;

            // Intermediates

            for (let i = 0; i < inters.length; i++) {

                ctx.fillText(inters[i], cx, cy);

                cy += fs * 1.3;

            }

            // Horizontal separator line 2 (if we had intermediates and a final result)

            if (inters.length > 0 && (fullResult || el.result_partial !== undefined)) {

                cy += 8;

                ctx.beginPath(); ctx.moveTo(cx - 240, cy); ctx.lineTo(cx + 20, cy);

                ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 4; ctx.stroke();

                cy += 20;

            }

            // ── Result display (3 modes) ──────────────────────────

            if (fullResult) {

                const charW = ctx.measureText('0').width; // monospace char width

                if (el.result_partial !== undefined && el.result_partial !== null) {

                    // MODE 1: Partial reveal — digits appear one by one from right

                    const partial = String(el.result_partial);

                    const totalDigits = fullResult.length;

                    ctx.save();

                    // Draw dim placeholder slots for unwritten digits (left side)

                    const unwrittenCount = totalDigits - partial.length;

                    for (let d = 0; d < unwrittenCount; d++) {

                        const slotX = cx - (totalDigits - d - 1) * charW * 1.1;

                        ctx.fillStyle = 'rgba(255,255,255,0.12)';

                        ctx.fillText('_', slotX, cy);

                    }

                    // Draw the partial result (right-aligned)

                    if (partial.length > 0) {

                        // Glow on the newest digit (leftmost of partial)

                        ctx.shadowColor = '#00FF88';

                        ctx.shadowBlur = 22;

                        ctx.fillStyle = '#00FF88';

                        ctx.fillText(partial, cx, cy);

                    }

                    ctx.restore();

                    cy += fs * 1.3;

                } else if (el.reveal_result) {

                    // MODE 2: Classic reveal — shows '?' then flips to result

                    const REVEAL_AT = el.reveal_at ?? 0.1;

                    const revealed = stepProgress >= REVEAL_AT;

                    if (revealed) {

                        const rp = Math.min((stepProgress - REVEAL_AT) / 0.2, 1.0);

                        ctx.save();

                        ctx.globalAlpha = 0.9 + rp * 0.1;

                        if (rp < 1) { ctx.shadowColor = '#00FF88'; ctx.shadowBlur = 30 * (1 - rp); }

                        ctx.fillStyle = rc('green');

                        ctx.fillText(fullResult, cx, cy);

                        ctx.restore();

                    } else {

                        // Nhịp đập bám THỜI GIAN VIDEO, không phải đồng hồ máy. Date.now()
                        // làm mỗi worker chunk có pha khác nhau → nhịp NHẢY ở
                        // chỗ nối chunk, và cùng một khung render 2 lần ra 2 ảnh.
                        const pulse = 0.6 + 0.4 * Math.sin(currentFrameTime * 2.5);

                        const tw = ctx.measureText('?').width;

                        ctx.save();

                        ctx.strokeStyle = `rgba(255,215,0,${pulse})`;

                        ctx.lineWidth = 2.5;

                        roundRect(cx - tw - 14, cy - 4, tw + 28, fs + 8, 8);

                        ctx.stroke();

                        ctx.fillStyle = `rgba(255,215,0,${0.5 + 0.3 * pulse})`;

                        ctx.fillText('?', cx, cy);

                        ctx.restore();

                    }

                    cy += fs * 1.3;

                } else {

                    // MODE 3: Always visible

                    ctx.fillStyle = rc('green');

                    ctx.fillText(fullResult, cx, cy);

                }

                cy += fs * 1.3;

            }

            ctx.textAlign = 'left';

            return (cy - cursorY) + 10;

        }

        case 'reveal': {

            // {"type":"reveal", "value":"319", "label":"a + b = b + ?", "fontSize":44, "color":"highlight", "align":"center", "reveal_at":0.4}

            const fs = el.fontSize || 44;

            const REVEAL_AT = el.reveal_at ?? 0.45;

            const revealed = stepProgress >= REVEAL_AT;

            const font = `bold ${fs}px ${T.font}`;

            ctx.font = font; ctx.textBaseline = 'top';

            const align = el.align || 'center';

            ctx.textAlign = align;

            const tx = align === 'center' ? W/2 : align === 'right' ? W - MX : MX;

            // Draw label with placeholder if any

            let displayText = el.label || '';

            if (displayText.includes('?') && revealed) {

                displayText = displayText.replace('?', el.value || '?');

            }

            let lineH = 0;

            if (displayText) {

                ctx.fillStyle = rc(el.color || 'highlight');

                const wrapped = wrapText(displayText, W - MX*2, font);

                for (const line of wrapped) {

                    drawRichMathText(ctx, line, tx, cursorY + lineH, fs, rc(el.color || 'highlight'), align, true, 'top');

                    lineH += fs * 1.4;

                }

            } else {

                // Standalone value (no label)

                const revealProg = revealed ? Math.min((stepProgress - REVEAL_AT) / 0.2, 1) : 0;

                if (revealed) {

                    ctx.save();

                    if (revealProg < 1) { ctx.shadowColor = T.hlColor; ctx.shadowBlur = 25 * (1 - revealProg); }

                    drawRichMathText(ctx, el.value || '', tx, cursorY, fs, rc(el.color || 'highlight'), align, true, 'top');

                    ctx.restore();

                } else {

                    // Nhịp đập bám THỜI GIAN VIDEO, không phải đồng hồ máy. Date.now()
                        // làm mỗi worker chunk có pha khác nhau → nhịp NHẢY ở
                        // chỗ nối chunk, và cùng một khung render 2 lần ra 2 ảnh.
                        const pulse = 0.6 + 0.4 * Math.sin(currentFrameTime * 2.5);

                    const tw = ctx.measureText('?').width;

                    const bx = align==='center' ? W/2-tw/2-14 : tx-14;

                    ctx.save();

                    ctx.strokeStyle = `rgba(255,215,0,${pulse})`; ctx.lineWidth = 2.5;

                    roundRect(bx, cursorY-4, tw+28, fs+8, 8); ctx.stroke();

                    ctx.fillStyle = `rgba(255,215,0,${0.5+0.3*pulse})`;

                    ctx.fillText('?', tx, cursorY);

                    ctx.restore();

                }

                lineH = fs + 12;

            }

            ctx.textAlign = 'left';

            return lineH + 6;

        }

        default:

            return 0;

    }

}

// ── Unified Layout Builder ────────────────────────────────────────

function buildUnifiedLayout(currentTime, renderFrom, steps, tSteps) {

    const nonGeoEls = [];

    const geoEls = [];

    let hasImageGen = false; // only allow first image_generation placeholder

    for (let i = renderFrom; i < steps.length; i++) {

        const step = steps[i], ts = tSteps[i];

        if (!ts || currentTime < ts.start) continue;

        const rawP = Math.min((currentTime - ts.start) / Math.max(ts.end - ts.start, 0.1), 1);

        let addedAny = false;

        for (const el of (step.elements || [])) {

            if (el.type === 'point' || el.type === 'segment' || el.type === 'right_angle') {

                geoEls.push({ el, rawP });

                continue;

            }

            // Deduplicate image_generation: only render the first placeholder per screen

            if (el.type === 'image_generation') {

                if (hasImageGen) continue; // skip duplicates

                hasImageGen = true;

            }

            let replaced = false;

            // Deduplicate math_calc by operands and operator

            if (el.type === 'math_calc') {

                const sig = el.op + '|' + (el.operands||[]).join('|');

                for (let j = nonGeoEls.length - 1; j >= 0; j--) {

                    const u = nonGeoEls[j];

                    if (u.el.type === 'math_calc' && u.el.op + '|' + (u.el.operands||[]).join('|') === sig) {

                        nonGeoEls[j] = { el: el, rawP: u.rawP };

                        replaced = true;

                        break;

                    }

                }

            }

            if (!replaced) {

                nonGeoEls.push({ el, rawP });

                addedAny = true;

            }

        }

        if (addedAny) {

            nonGeoEls.push({ el: { type: 'gap' }, rawP: 1 });

        }

    }

    return { nonGeoEls, geoEls };

}

// Ken Burns cho mathnoir: zoom pha liên tục THUẦN time (1.02 ± 0.018,
// chu kỳ ~114s — không snap khi sang step mới) + drift nhẹ theo time —
// trừ mn_chrome (ghim cứng). Gọi SAU ctx.save() của element; caller tự
// restore. rawP giữ trong chữ ký cho call-site cũ, không dùng nữa.
function applyMnKenBurns(rawP) {
    const t = currentFrameTime;
    const s = 1.02 + 0.018 * Math.sin(t * 0.055);
    const dx = 6 * Math.sin(t * 0.13), dy = 4 * Math.sin(t * 0.09);
    ctx.translate(W / 2 + dx, H / 2 + dy);
    ctx.scale(s, s);
    ctx.translate(-W / 2, -H / 2);
}

function renderUnifiedElements(unifiedEls, startY) {

    let cursorY = startY;

    let i = 0;

    while (i < unifiedEls.length) {

        const u = unifiedEls[i];

        const el = u.el;

        if (el.type === 'gap') {

            cursorY += 18; // STEP_GAP

            i++;

            continue;

        }

        // Fast fade in — riêng mathnoir + custom_js thì BỎ fade (alpha 1):
        // cảnh mn tự lo entrance, fade engine chồng lên chỉ gây chớp đúp.
        const alpha = (artStyle === 'mathnoir' && el.type === 'custom_js')
            ? 1.0
            : easeOut(Math.min(u.rawP * 4.0, 1.0));

        if (el.type === 'box') {

            const style = (BOX_STYLES[el.style] || BOX_STYLES.subtle)();

            const inner = [];

            let j = i + 1;

            while (j < unifiedEls.length && (unifiedEls[j].el.type === 'text' || unifiedEls[j].el.type === 'list' || unifiedEls[j].el.type === 'math_calc' || unifiedEls[j].el.type === 'reveal')) {

                inner.push(unifiedEls[j]);

                j++;

            }

            // Skip rendering if the box is completely empty (happens when AI duplicates box elements)

            if (inner.length === 0) {

                i++; // MUST increment to avoid infinite loop

                continue;

            }

            const anim = el.animation || 'slide_up';

            let offsetY = 0;

            if (anim === 'slide_up' && u.rawP < 1.0) {

                const p = Math.min(u.rawP * 4.0, 1.0); // Fast slide up

                offsetY = 30 * (1 - easeOutBack(p)); // Use easeOutBack for a little bounce

            }

            let innerH = 0;

            for (const iu of inner) innerH += measureTextHeight(iu.el) + 6;

            const boxPadding = 20;

            const boxH = innerH + boxPadding * 2;

            const boxInset = 30; // extra inset from margins for narrower box

            const bx = MX + boxInset - 10, bw = W - MX * 2 - boxInset * 2 + 20;

            const mnKB = (artStyle === 'mathnoir' && el.template !== 'mn_chrome');

            if (mnKB) { ctx.save(); applyMnKenBurns(u.rawP); }

            ctx.save();

            ctx.globalAlpha = alpha;

            ctx.translate(0, offsetY);

            if (style.glow) { ctx.shadowColor = style.border; ctx.shadowBlur = 20; }
            else if (global.glassEffect) {
                ctx.shadowColor = 'rgba(0, 0, 0, 0.35)';
                ctx.shadowBlur = 24;
                ctx.shadowOffsetY = 6;
            }

            roundRect(bx, cursorY, bw, boxH, 16);

            ctx.fillStyle = style.bg; ctx.fill();

            // Clear shadow for borders and sheen
            ctx.shadowBlur = 0;
            ctx.shadowOffsetY = 0;

            if (style.border) { ctx.strokeStyle = style.border; ctx.lineWidth = 2; ctx.stroke(); }

            // Glassmorphism: frosted top-light sheen + soft inner highlight

            if (global.glassEffect) {

                ctx.save();

                roundRect(bx, cursorY, bw, boxH, 16);

                ctx.clip();

                const sheen = ctx.createLinearGradient(0, cursorY, 0, cursorY + boxH);

                sheen.addColorStop(0, 'rgba(255,255,255,0.16)');

                sheen.addColorStop(0.35, 'rgba(255,255,255,0.04)');

                sheen.addColorStop(1, 'rgba(255,255,255,0.0)');

                ctx.fillStyle = sheen;

                ctx.fillRect(bx, cursorY, bw, boxH);

                // bright top edge highlight

                ctx.strokeStyle = 'rgba(255,255,255,0.45)';

                ctx.lineWidth = 1.5;

                ctx.beginPath();

                ctx.moveTo(bx + 16, cursorY + 1.5);

                ctx.lineTo(bx + bw - 16, cursorY + 1.5);

                ctx.stroke();

                ctx.restore();

            }

            ctx.restore();

            t2EditBox(el, bx, cursorY + offsetY, bw, boxH); // bbox chế độ sửa (box vẽ ở đây, không qua renderElementAtY)

            let innerY = cursorY + boxPadding + offsetY;

            for (const iu of inner) {

                ctx.save();

                ctx.globalAlpha = easeOut(Math.min(iu.rawP * 4.0, 1.0));

                innerY += renderElementAtY(iu.el, innerY, iu.rawP);

                ctx.restore();

            }

            if (mnKB) ctx.restore();

            cursorY += boxH + 8;

            i = j;

            continue;

        }

        ctx.save();

        ctx.globalAlpha = alpha;

        if (artStyle === 'mathnoir' && el.template !== 'mn_chrome') applyMnKenBurns(u.rawP);

        cursorY += renderElementAtY(el, cursorY, u.rawP);

        ctx.restore();

        i++;

    }

    return cursorY;

}

// ── Offscreen Canvas Caches for Fast Artistic Rendering ─────────
/**
 * CANVAS PHỤ CỠ KHUNG cho các lớp phủ nghệ thuật (vân giấy, halftone, scanline…).
 *
 * Dựng ở ĐỘ PHÂN GIẢI THẬT (CW×CH) rồi pre-scale ctx về không gian logic: code
 * vẽ bên dưới vẫn dùng W/H/MX/spacing y như cũ, nhưng hoa văn được rasterize ở
 * RSCALE× = nét thật.
 *
 * Vì sao pre-scale chứ không sửa hằng: mật độ hoa văn (spacing 20, gridDist 60,
 * 3000 hạt bụi) là THIẾT KẾ THỊ GIÁC tính theo toạ độ logic. Nếu dựng canvas to
 * mà vẫn vẽ spacing=20 pixel THẬT thì ở RSCALE=2 hoa văn dày gấp đôi → ẢNH KHÁC,
 * không phải ảnh nét hơn. Pre-scale giữ hình y hệt, chỉ nét hơn. Chuỗi rand()
 * cũng không đổi → tất định.
 *
 * ⚠️ Blit BẮT BUỘC drawImage(c, 0, 0, W, H) — bản 2 tham số sẽ đặt ảnh ở cỡ tự
 * nhiên CW×CH rồi bị transform nhân thêm RSCALE nữa = tràn khung RSCALE lần.
 */
function mkFrameLayer() {
    const c = HOST.createCanvas(CW, CH);
    const cx = c.getContext('2d');
    cx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);   // RSCALE=1 → đồng nhất, no-op
    return { c: c, cx: cx };
}

let watercolorOverlayCanvas = null;
function getWatercolorOverlayCanvas() {
    if (watercolorOverlayCanvas) return watercolorOverlayCanvas;
    const _L = mkFrameLayer(), c = _L.c, cx = _L.cx;
    cx.fillStyle = 'rgba(215, 205, 185, 0.12)';
    cx.fillRect(0, 0, W, H);
    const vignette = cx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.3, W / 2, H / 2, Math.max(W, H) * 0.7);
    vignette.addColorStop(0, 'rgba(255, 255, 255, 0)');
    vignette.addColorStop(1, 'rgba(190, 175, 150, 0.25)');
    cx.fillStyle = vignette;
    cx.fillRect(0, 0, W, H);
    cx.fillStyle = 'rgba(0, 0, 0, 0.03)';
    for (let j = 0; j < 3000; j++) {
        const rx = rand() * W;
        const ry = rand() * H;
        const rw = rand() * 3 + 1;
        const rh = rand() * 3 + 1;
        cx.fillRect(rx, ry, rw, rh);
    }
    watercolorOverlayCanvas = c;
    return watercolorOverlayCanvas;
}

let cartoonHalftoneCanvas = null;
function getCartoonHalftoneCanvas() {
    if (cartoonHalftoneCanvas) return cartoonHalftoneCanvas;
    const _L = mkFrameLayer(), c = _L.c, cx = _L.cx;
    cx.fillStyle = 'rgba(0, 0, 0, 0.08)';
    const spacing = 20;
    for (let x = spacing / 2; x < W; x += spacing) {
        for (let y = spacing / 2; y < H; y += spacing) {
            const dx = x - W / 2;
            const dy = y - H / 2;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist > Math.min(W, H) * 0.36) {
                const size = Math.min(7, (dist - Math.min(W, H) * 0.36) / 45);
                if (size > 0.6) {
                    cx.beginPath(); cx.arc(x, y, size, 0, Math.PI * 2); cx.fill();
                }
            }
        }
    }
    cartoonHalftoneCanvas = c;
    return cartoonHalftoneCanvas;
}

let sketchOverlayCanvas = null;
function getSketchOverlayCanvas() {
    if (sketchOverlayCanvas) return sketchOverlayCanvas;
    const _L = mkFrameLayer(), c = _L.c, cx = _L.cx;
    cx.fillStyle = 'rgba(0, 0, 0, 0.05)';
    cx.fillRect(0, 0, W, H);
    const vignette = cx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.4, W / 2, H / 2, Math.max(W, H) * 0.7);
    vignette.addColorStop(0, 'rgba(255, 255, 255, 0)');
    vignette.addColorStop(1, 'rgba(0, 0, 0, 0.12)');
    cx.fillStyle = vignette;
    cx.fillRect(0, 0, W, H);
    cx.strokeStyle = 'rgba(0, 0, 0, 0.02)';
    cx.lineWidth = 1;
    const gridDist = 60;
    for (let x = 0; x < W; x += gridDist) {
        cx.beginPath(); cx.moveTo(x, 0); cx.lineTo(x, H); cx.stroke();
    }
    for (let y = 0; y < H; y += gridDist) {
        cx.beginPath(); cx.moveTo(0, y); cx.lineTo(W, y); cx.stroke();
    }
    cx.strokeStyle = 'rgba(0, 0, 0, 0.16)';
    cx.lineWidth = 1.8;
    cx.beginPath(); cx.moveTo(MX - 15, 38); cx.lineTo(W - MX + 20, 36); cx.stroke();
    cx.beginPath(); cx.moveTo(MX - 10, 42); cx.lineTo(W - MX + 15, 40); cx.stroke();
    cx.beginPath(); cx.moveTo(MX - 8, 25); cx.lineTo(MX - 10, H - 30); cx.stroke();
    cx.beginPath(); cx.moveTo(W - MX + 8, 28); cx.lineTo(W - MX + 6, H - 35); cx.stroke();
    cx.beginPath(); cx.moveTo(MX - 20, H - 38); cx.lineTo(W - MX + 20, H - 40); cx.stroke();
    cx.strokeStyle = 'rgba(0, 0, 0, 0.05)'; cx.lineWidth = 1;
    for (let j = 0; j < 40; j++) {
        const rx = rand() * W;
        const ry = rand() * H;
        cx.beginPath(); cx.moveTo(rx, ry);
        cx.lineTo(rx + rand() * 50 - 25, ry + rand() * 50 - 25);
        cx.stroke();
    }
    sketchOverlayCanvas = c;
    return sketchOverlayCanvas;
}

let pixelScanlinesCanvas = null;
function getPixelScanlinesCanvas() {
    if (pixelScanlinesCanvas) return pixelScanlinesCanvas;
    const _L = mkFrameLayer(), c = _L.c, cx = _L.cx;
    cx.fillStyle = 'rgba(0, 0, 0, 0.08)';
    for (let y = 0; y < H; y += 4) {
        cx.fillRect(0, y, W, 1);
    }
    pixelScanlinesCanvas = c;
    return pixelScanlinesCanvas;
}

// ── Mathnoir: grain phấn + vignette nền — pre-render MỘT LẦN ────────────
// 1) Tile grain 256×256: hash tất định theo (x,y) — TUYỆT ĐỐI không
//    Math.random: v = frac(sin(x*12.9898 + y*78.233)*43758.5453). Chấm phấn
//    xám sáng 200–232, alpha 0.05–0.09, phủ khung ở globalAlpha 0.5.
// 2) Vignette radial (trong suốt → rgba(0,0,0,0.34) ở mép) vẽ SAU grain.
// Cả hai bake vào MỘT layer khung hình cache module-level → chi phí mỗi
// frame đúng 1 drawImage trong drawBg(). Grain TĨNH (đúng chất giấy than,
// deterministic cho worker chunk — không nhấp nháy giữa frame).
let mathnoirBgFxCanvas = null;
function getMathnoirBgFxCanvas() {
    if (mathnoirBgFxCanvas) return mathnoirBgFxCanvas;
    const N = 256;
    const tile = HOST.createCanvas(N, N);
    const tcx = tile.getContext('2d');
    const fr = function (v) { return v - Math.floor(v); };
    for (let gy = 0; gy < N; gy++) {
        for (let gx = 0; gx < N; gx++) {
            const v = fr(Math.sin(gx * 12.9898 + gy * 78.233) * 43758.5453);
            if (v <= 0.74) continue;                        // ~26% pixel có chấm
            const a = 0.05 + 0.04 * fr(v * 7.13);           // 0.05–0.09
            const g = Math.round(200 + 32 * fr(v * 13.7));  // xám 200–232
            tcx.fillStyle = 'rgba(' + g + ',' + g + ',' + g + ',' + a.toFixed(3) + ')';
            tcx.fillRect(gx, gy, 1, 1);
        }
    }
    const _L = mkFrameLayer(), c = _L.c, cx = _L.cx;
    cx.globalAlpha = 0.5;
    for (let ty = 0; ty < H; ty += N) {
        for (let tx = 0; tx < W; tx += N) cx.drawImage(tile, tx, ty);
    }
    cx.globalAlpha = 1;
    const vg = cx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.42,
                                       W / 2, H / 2, Math.max(W, H) * 0.75);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(1, 'rgba(0,0,0,0.34)');
    cx.fillStyle = vg;
    cx.fillRect(0, 0, W, H);
    mathnoirBgFxCanvas = c;
    return mathnoirBgFxCanvas;
}

let crtScanlinesCanvas = null;
function getCrtScanlinesCanvas() {
    if (crtScanlinesCanvas) return crtScanlinesCanvas;
    const _L = mkFrameLayer(), c = _L.c, cx = _L.cx;
    cx.fillStyle = 'rgba(0, 0, 0, 0.07)';
    for (let y = 0; y < H; y += 4) {
        cx.fillRect(0, y, W, 2);
    }
    crtScanlinesCanvas = c;
    return crtScanlinesCanvas;
}

// ── PHỤ ĐỀ: khởi tạo engine + gộp dữ liệu step ──────────────────
// subtitle_engine.js là hàm THUẦN theo thời gian (không tích luỹ giữa frame)
// nên worker chunk khởi động lạnh ở frame 900 vẫn vẽ y hệt → không "nhảy" ở
// chỗ nối chunk. Bố cục cụm chữ được cache theo step.id, không tính lại/frame.
let SUB_ENGINE = null;
let SUB_STEPS = null;

if (SUB_CFG) {
    try {
        const { makeSubtitle, loadPresets, getPreset } = require('./subtitle_engine.js');
        // Preset phụ đề: Node đọc từ file; trình duyệt/QuickJS không có hệ
        // thống file nên BƠM SẴN qua BOOT (fetch JSON trước rồi truyền vào).
        const presets = (BOOT && BOOT.subtitlePresets)
            ? BOOT.subtitlePresets
            : loadPresets(path.join(__dirname, 'subtitle_presets.json'));
        const preset = getPreset(presets, SUB_CFG.preset);
        if (!preset) {
            process.stderr.write('[Subtitle] subtitle_presets.json rỗng → bỏ qua phụ đề\n');
        } else {
            if (SUB_CFG.preset && preset.id !== SUB_CFG.preset) {
                process.stderr.write(`[Subtitle] không có preset "${SUB_CFG.preset}" → dùng "${preset.id}"\n`);
            }
            if (SUB_CFG.accent && /^#[0-9a-fA-F]{6}$/.test(SUB_CFG.accent)) {
                // Màu nhấn theo template (def "subtitle_accent"): từ-đang-đọc
                // + quầng glow (chỉ preset kiểu glow, blur lớn) ăn theo accent.
                const r = parseInt(SUB_CFG.accent.slice(1, 3), 16),
                    g = parseInt(SUB_CFG.accent.slice(3, 5), 16),
                    b = parseInt(SUB_CFG.accent.slice(5, 7), 16);
                preset.color = preset.color || {};
                preset.color.active = SUB_CFG.accent;
                const sh = preset.color.shadow;
                if (sh && Number(sh.blur) >= 18) {
                    const m = /rgba?\([^)]*,\s*([\d.]+)\s*\)/.exec(String(sh.color || ''));
                    sh.color = `rgba(${r},${g},${b},${m ? m[1] : '0.7'})`;
                }
            }
            // Font PHỤ ĐỀ theo TEMPLATE — dùng khi user KHÔNG tự chọn font phụ
            // đề. T.font = font của phong cách/template (hoặc font user chọn ở
            // tab Phong cách, đi qua --font). Chỉ lấy phần font ĐẶC TRƯNG: bỏ
            // mọi family nằm trong SYSTEM_FONT_STACK — cái đuôi fallback đa ngôn
            // ngữ mà MỌI palette đều phải nối vào. Nhờ vậy palette KHÔNG khai
            // font riêng (editcream/aibrief: font = SYSTEM_FONT_STACK; mathnoir/
            // techdark/warmpaper: 'Segoe UI' vốn ĐÃ nằm trong stack) cho ra
            // chuỗi RỖNG → preset giữ nguyên → pixel-identical với HEAD.
            // Family không có trong máy sẽ bị familyAvailable() loại ở
            // subtitle_engine.js/resolveFamily → rơi về preset, KHÔNG ra ô vuông.
            const _sysFams = new Set(SYSTEM_FONT_STACK.split(',').map(function (s) {
                return s.trim().replace(/^["']|["']$/g, '').toLowerCase();
            }));
            const _tplSubFont = String((T && T.font) || '').split(',')
                .map(function (s) { return s.trim().replace(/^["']|["']$/g, ''); })
                .filter(function (f) { return f && !_sysFams.has(f.toLowerCase()); })
                .map(function (f) { return '"' + f + '"'; })
                .join(', ');
            SUB_ENGINE = makeSubtitle(preset, {
                fontScale: SUB_CFG.fontScale,
                yPct: (SUB_CFG.yPct === undefined ? null : SUB_CFG.yPct),
                maxLines: (SUB_CFG.maxLines === undefined ? null : SUB_CFG.maxLines),
                // Thứ tự ưu tiên font phụ đề:
                //   1. Người dùng CHỦ ĐỘNG chọn font phụ đề → `SUB_CFG.fontFamily`
                //      (app bơm vào object --subtitle khi user chọn).
                //   2. Font ĐẶC TRƯNG của template/phong cách (_tplSubFont, lọc
                //      từ T.font) — để phụ đề mang bản sắc kênh thay vì luôn là
                //      một kiểu chữ cho mọi template.
                //   3. Rỗng → preset.font.family như cũ.
                // LƯU Ý (lịch sử): trước đây CỐ Ý không nối `_ovFont` thô vào đây
                // vì `_ovFont` chứa CẢ đuôi SYSTEM_FONT_STACK, nên nó nuốt font
                // preset ở MỌI render (golden 55/59 sub-frame lệch). _tplSubFont
                // đã LỌC SẠCH đuôi đó nên chỉ template có font THẬT SỰ riêng mới
                // đổi pixel. Xem subtitle_engine.js/resolveFamily.
                fontFamily: (SUB_CFG.fontFamily && String(SUB_CFG.fontFamily).trim())
                    ? SUB_CFG.fontFamily
                    : _tplSubFont,
                // Trần mép dưới tuỳ chọn (app mobile nới để kéo phụ đề thấp
                // tới 0.95); vắng khoá = BOTTOM_LIMIT 0.90 như cũ.
                bottomLimitPct: (SUB_CFG.bottomLimitPct === undefined ? null : SUB_CFG.bottomLimitPct),
                fallbackFamily: SYSTEM_FONT_STACK,   // Be Vietnam Pro: đủ dấu tiếng Việt
                // Canvas phụ (bóng, quầng sáng, ảnh chữ đúc sẵn) phải xin từ HOST.
                // Đoán lớp Canvas từ ctx.canvas.constructor thì trên trình duyệt
                // ra HTMLCanvasElement → new HTMLCanvasElement() ném lỗi → bóng
                // biến mất im lặng. Xem subtitle_engine.js/mkCanvas.
                createCanvas: HOST.createCanvas,
                // Engine phụ đề vẫn BỐ CỤC bằng toạ độ logic (draw nhận W/H
                // logic) — RS chỉ để nó đúc CANVAS PHỤ (lớp bóng, ảnh chữ) ở
                // đúng độ phân giải thật. Thiếu khoá này = chữ phụ đề mờ ở 2K/4K.
                renderScale: RSCALE,
                warn: function (m) { HOST.warn('[Subtitle] ' + m); }
            });
            process.stderr.write(`[Subtitle] preset=${preset.id} fontScale=${SUB_CFG.fontScale || 1}\n`);
        }
    } catch (e) {
        process.stderr.write(`[Subtitle] tắt phụ đề (lỗi khởi tạo): ${e.message}\n`);
        SUB_ENGINE = null;
    }
}

/** Gộp timing.steps + script.steps.voice_text → dữ liệu đầu vào của engine. */
function buildSubSteps() {
    const ts = (timing && timing.steps) || [];
    const ss = (script && script.steps) || [];
    const out = [];
    for (let i = 0; i < ts.length; i++) {
        const t = ts[i] || {};
        const s = ss[i] || {};
        const start = Number(t.start) || 0;
        const end = (t.end !== undefined && t.end !== null) ? Number(t.end)
            : start + (Number(t.duration) || 0);
        out.push({
            id: (t.id !== undefined && t.id !== null) ? t.id : (i + 1),
            start: start,
            end: end,
            duration: Number(t.duration) || Math.max(0, end - start),
            words: Array.isArray(t.words) ? t.words : [],
            voice_text: s.voice_text || '',        // dự phòng khi words rỗng
            // Ghi đè theo từng step (schema.py bỏ qua key lạ nên script vẫn hợp lệ):
            //   "subtitle": false        → step này không có phụ đề (thẻ tiêu đề…)
            //   "subtitle_pos": "top"    → đẩy phụ đề lên trên (step chật ở dưới)
            subtitle: s.subtitle,
            no_subtitle: s.no_subtitle,
            subtitle_pos: s.subtitle_pos,
            subtitle_y_pct: s.subtitle_y_pct,
            //   "subtitle_y_pct_9_16" → né cảnh cao, CHỈ áp cho khung dọc
            //   (script_generator._center_layout tính từ y_9_16 × 1920)
            subtitle_y_pct_9_16: s.subtitle_y_pct_9_16
        });
    }
    return out;
}

function drawSubtitle(t) {
    if (!SUB_ENGINE) return;
    if (!SUB_STEPS) SUB_STEPS = buildSubSteps();
    if (!SUB_STEPS.length) return;
    // T2_EDIT (app sửa bố cục): app mutate script.steps SỐNG (kéo phụ đề) mà
    // SUB_STEPS là bản chép lúc boot → làm tươi các khoá ghi đè per-step trước
    // khi vẽ. Cờ tắt = không dòng nào chạy (zero-diff với export/thumbnail).
    if (globalThis.T2_EDIT === true) {
        const ss = (script && script.steps) || [];
        for (let i = 0; i < SUB_STEPS.length; i++) {
            const s = ss[i] || {};
            SUB_STEPS[i].subtitle = s.subtitle;
            SUB_STEPS[i].no_subtitle = s.no_subtitle;
            SUB_STEPS[i].subtitle_pos = s.subtitle_pos;
            SUB_STEPS[i].subtitle_y_pct = s.subtitle_y_pct;
            SUB_STEPS[i].subtitle_y_pct_9_16 = s.subtitle_y_pct_9_16;
        }
    }
    // Step đang chạy = step cuối cùng đã bắt đầu (totalFrames = ceil(dur*fps) nên
    // frame cuối có thể vượt total_duration một chút → kẹp vào step cuối).
    let cur = null;
    for (let i = 0; i < SUB_STEPS.length; i++) {
        if (t >= SUB_STEPS[i].start - 0.0005) cur = SUB_STEPS[i]; else break;
    }
    if (!cur) return;
    SUB_ENGINE.draw(ctx, W, H, cur, t, FPS);
}

// ── Main render ─────────────────────────────────────────────────

let currentFrameTime = 0;

// ── Ngẫu nhiên TÁI LẬP ĐƯỢC (bụi, nhiễu, nét vẽ tay) ─────────────
// Math.random() làm CÙNG MỘT KHUNG HÌNH render hai lần ra hai ảnh khác nhau:
// không thể kiểm hồi quy renderer, không thể chứng minh hai backend vẽ giống
// nhau (node-canvas vs Flutter Canvas), và mỗi worker chunk có dãy số riêng.
// mulberry32 gieo mầm theo SỐ KHUNG HÌNH: hạt bụi vẫn nhảy múa từng khung như
// cũ, nhưng render lại lần nữa ra y hệt.
let _rngState = 0;
function rand() {
    _rngState = (_rngState + 0x6D2B79F5) | 0;
    let t = _rngState;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
/** Gieo lại đầu mỗi khung → khung thứ N luôn cho cùng một dãy số. */
function seedFrameRandom(timeSec) {
    _rngState = (Math.round(timeSec * (FPS || 30)) * 2654435761) | 0;
}

// ── Sổ bbox chế độ SỬA (kéo-thả trên mobile) ─────────────────────
// Chỉ hoạt động khi globalThis.T2_EDIT === true (app bật trước khi vẽ).
// Mặc định T2_EDIT undefined → T2_EDIT_ELS = null → mọi lời gọi t2EditBox
// là no-op: đường render/export Node/QuickJS KHÔNG đổi một byte hành vi.
// Bắt chước sổ _renderedElements của edu preview_renderer.js, nhưng chỉ ghi
// element của STEP đang vẽ (activeIdx) — element step cũ không sửa được.
// globalThis.T2_BOXES = [{i, type, x, y, w, h}] — i = index element trong
// step, toạ độ CANVAS (W×H, vd 1080×1920), reset đầu mỗi renderFrame.
let T2_EDIT_ELS = null; // Map element → index trong step đang vẽ; null = tắt
function t2EditBegin(steps, activeIdx) {
    if (globalThis.T2_EDIT !== true) { T2_EDIT_ELS = null; return; }
    globalThis.T2_BOXES = [];
    T2_EDIT_ELS = new Map();
    const els = (steps && steps[activeIdx] && steps[activeIdx].elements) || [];
    for (let j = 0; j < els.length; j++) T2_EDIT_ELS.set(els[j], j);
}
function t2EditBox(el, x, y, w, h) {
    if (!T2_EDIT_ELS) return;
    const idx = T2_EDIT_ELS.get(el);
    if (idx === undefined) return; // element của step trước → bỏ qua
    globalThis.T2_BOXES.push({
        i: idx, type: el.type,
        x: Math.round(x), y: Math.round(y),
        w: Math.round(Math.max(0, w)), h: Math.round(Math.max(0, h))
    });
}

function renderFrame(currentTime) {

    // Reset canvas state to prevent state leaks / singular matrix corruption from previous frames

    ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

    ctx.globalAlpha = 1.0;

    ctx.shadowBlur = 0;

    ctx.shadowColor = 'rgba(0,0,0,0)';

    ctx.fillStyle = '#000000';

    ctx.strokeStyle = '#000000';

    ctx.lineWidth = 1;

    ctx.lineCap = 'butt';

    ctx.lineJoin = 'miter';

    ctx.setLineDash([]);

    currentFrameTime = currentTime;

    seedFrameRandom(currentTime);   // bụi/nhiễu tái lập được — xem rand()

    drawBg();

    const steps = script.steps, tSteps = timing.steps;

    const totalDur = timing.total_duration || 30;

    let activeIdx = -1;

    for (let i = 0; i < tSteps.length; i++) if (currentTime >= tSteps[i].start) activeIdx = i;

    t2EditBegin(steps, activeIdx); // no-op trừ khi globalThis.T2_EDIT === true

    // (dots header removed)

    let cursorY = 80;

    let renderFrom = 0;

    for (let i = steps.length - 1; i >= 0; i--) {

        const ts = tSteps[i];

        if (ts && currentTime >= ts.start && steps[i].clear) {

            renderFrom = i;

            break;

        }

    }

    if (renderFrom > 0) {

        drawBg();

    }

    const { nonGeoEls, geoEls } = buildUnifiedLayout(currentTime, renderFrom, steps, tSteps);

    if (geoEls.length > 0) {

        // ── Split layout: text in top portion, geo in fixed bottom zone ──

        const GEO_ZONE_START = Math.round(H * 0.52);

        const GEO_ZONE_H     = H - GEO_ZONE_START - 80;

        ctx.save();

        ctx.beginPath();

        ctx.rect(0, 0, W, GEO_ZONE_START - 10);

        ctx.clip();

        const textStartY = calcCenteredStartY(nonGeoEls, 80, GEO_ZONE_START - 10);

        renderUnifiedElements(nonGeoEls, textStartY);

        ctx.restore();

        ctx.save();

        ctx.strokeStyle = T.geoBorder || '#3a3a5a';

        ctx.lineWidth = 1;

        ctx.setLineDash([8, 6]);

        ctx.beginPath();

        ctx.moveTo(MX, GEO_ZONE_START - 5);

        ctx.lineTo(W - MX, GEO_ZONE_START - 5);

        ctx.stroke();

        ctx.setLineDash([]);

        ctx.restore();

        renderGeometryZone(geoEls, GEO_ZONE_START, GEO_ZONE_H);

    } else {

        const startY = calcCenteredStartY(nonGeoEls, 80, H - 80);

        renderUnifiedElements(nonGeoEls, startY);

    }

    drawHighlights(currentTime);

    // drawProgress removed

    // ── Apply Artistic Post-processing Filters ─────────────────────

    if (artStyle === 'pixel') {
        ctx.save();
        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        // CRT Curved Screen Glass Reflection

        const glassGrad = ctx.createLinearGradient(0, 0, W, H);

        glassGrad.addColorStop(0, 'rgba(255, 255, 255, 0.08)');

        glassGrad.addColorStop(0.3, 'rgba(255, 255, 255, 0.03)');

        glassGrad.addColorStop(0.31, 'rgba(255, 255, 255, 0)');

        glassGrad.addColorStop(1, 'rgba(255, 255, 255, 0)');

        ctx.fillStyle = glassGrad;

        ctx.fillRect(0, 0, W, H);

        // Retro arcade green status text

        ctx.fillStyle = 'rgba(0, 255, 0, 0.5)';

        ctx.font = 'bold 20px "JetBrains Mono", monospace';

        ctx.fillText('CYBER SCAN: ACTIVE', MX, H - 40);

        ctx.fillText('READY PLAYER 1', W - MX - 180, H - 40);

        // CRT Scanline filter (Optimized with Offscreen Canvas)
        ctx.drawImage(getCrtScanlinesCanvas(), 0, 0, W, H);

        ctx.restore();

    } else if (artStyle === 'watercolor') {

        ctx.save();

        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        ctx.globalCompositeOperation = 'multiply';

        ctx.drawImage(getWatercolorOverlayCanvas(), 0, 0, W, H);

        ctx.restore();

    } else if (artStyle === 'inkwash') {

        ctx.save();

        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        ctx.globalCompositeOperation = 'multiply';

        ctx.fillStyle = 'rgba(139, 90, 43, 0.08)';

        ctx.fillRect(0, 0, W, H);

        // Sumi smoke vignette

        const vignette = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.3, W / 2, H / 2, Math.max(W, H) * 0.75);

        vignette.addColorStop(0, 'rgba(255, 255, 255, 0)');

        vignette.addColorStop(1, 'rgba(40, 40, 40, 0.3)');

        ctx.fillStyle = vignette;

        ctx.fillRect(0, 0, W, H);

        // Soft sumi wash fiber strokes

        ctx.fillStyle = 'rgba(0, 0, 0, 0.01)';

        for (let j = 0; j < 10; j++) {

            const ry = rand() * H;

            ctx.fillRect(0, ry, W, rand() * 20 + 5);

        }

        // 1. Beautiful Sumi ink smoke cloud washes in the background

        const inkClouds = [

            {x: 80, y: 120, r: 350, o: 0.08},

            {x: W - 120, y: H - 200, r: 450, o: 0.07},

            {x: W / 2, y: H * 0.45, r: 500, o: 0.04}

        ];

        inkClouds.forEach(cloud => {

            const grad = ctx.createRadialGradient(cloud.x, cloud.y, 0, cloud.x, cloud.y, cloud.r);

            grad.addColorStop(0, `rgba(47, 62, 70, ${cloud.o})`);

            grad.addColorStop(0.6, `rgba(47, 62, 70, ${cloud.o * 0.4})`);

            grad.addColorStop(1, 'rgba(255,255,255,0)');

            ctx.fillStyle = grad;

            ctx.beginPath(); ctx.arc(cloud.x, cloud.y, cloud.r, 0, Math.PI*2); ctx.fill();

        });

        // 2. Roll parchment border vignette

        const vignette2 = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.3, W / 2, H / 2, Math.max(W, H) * 0.72);

        vignette2.addColorStop(0, 'rgba(255, 255, 255, 0)');

        vignette2.addColorStop(1, 'rgba(125, 95, 60, 0.2)');

        ctx.fillStyle = vignette2; ctx.fillRect(0, 0, W, H);

        // 3. Ancient Chinese Calligraphy Red Square Seal in top-right corner

        ctx.globalCompositeOperation = 'source-over';

        ctx.fillStyle = '#b22222'; // Traditional Vermilion seal red

        ctx.fillRect(W - MX - 40, 45, 45, 45);

        ctx.strokeStyle = '#efe9db'; ctx.lineWidth = 2.5;

        ctx.strokeRect(W - MX - 37, 48, 39, 39);

        // Calligraphy squiggles in seal

        ctx.beginPath();

        ctx.moveTo(W - MX - 28, 54); ctx.lineTo(W - MX - 28, 80);

        ctx.moveTo(W - MX - 18, 52); ctx.lineTo(W - MX - 18, 78);

        ctx.stroke();

        // 4. Wooden scroll borders (Hanging roll wrapper - Kakemono)

        ctx.fillStyle = '#2b1c12'; // Dark polished mahogany scroll bars

        ctx.fillRect(0, 0, W, 22);

        ctx.fillRect(0, H - 22, W, 22);

        ctx.restore();

    } else if (artStyle === 'sketch') {

        ctx.save();

        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        ctx.globalCompositeOperation = 'multiply';

        ctx.drawImage(getSketchOverlayCanvas(), 0, 0, W, H);

        ctx.restore();

    } else if (artStyle === 'cartoon') {

        ctx.save();

        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        // Draw pre-rendered halftone shading dots (Optimized)
        ctx.drawImage(getCartoonHalftoneCanvas(), 0, 0, W, H);

        // 2. Thick 8px comic book border outline

        ctx.strokeStyle = '#000000'; ctx.lineWidth = 10;

        ctx.strokeRect(MX - 10, 40, W - MX * 2 + 20, H - 80);

        // 3. Exclamation Pop Starburst Badge in bottom corner!

        ctx.fillStyle = '#ffdf00'; ctx.strokeStyle = '#000000'; ctx.lineWidth = 4;

        const bx = W - MX - 50, by = H - 120, r = 35;

        ctx.beginPath();

        for (let i = 0; i < 16; i++) {

            const angle = (i / 16) * Math.PI * 2;

            const dist = i % 2 === 0 ? r : r * 0.65;

            const px = bx + Math.cos(angle) * dist;

            const py = by + Math.sin(angle) * dist;

            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);

        }

        ctx.closePath(); ctx.fill(); ctx.stroke();

        ctx.fillStyle = '#000'; ctx.font = '900 18px "Impact", sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';

        ctx.fillText('POP!', bx, by);

        ctx.restore();

    } else if (artStyle === 'cyberpunk') {

        ctx.save();

        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        // 1. Retro-future perspective glowing wireframe grid at the bottom

        ctx.strokeStyle = 'rgba(0, 255, 255, 0.12)'; ctx.lineWidth = 1.5;

        const gridY = H - 280;

        for (let x = MX; x <= W - MX; x += 60) {

            ctx.beginPath();

            ctx.moveTo(x, H - 30);

            ctx.lineTo(W / 2 + (x - W / 2) * 0.18, gridY);

            ctx.stroke();

        }

        for (let y = gridY; y < H; y += 35) {

            ctx.beginPath();

            const ratio = (y - gridY) / (H - gridY);

            const wDiff = (W - MX * 2) * (1 - ratio * 0.8);

            ctx.moveTo(W / 2 - wDiff / 2, y);

            ctx.lineTo(W / 2 + wDiff / 2, y);

            ctx.stroke();

        }

        // 2. High-tech HUD Corner Brackets

        ctx.strokeStyle = '#00ffff'; ctx.lineWidth = 3.5;

        const gap = 20; const len = 35;

        // Top-Left

        ctx.beginPath(); ctx.moveTo(MX - gap + len, 50); ctx.lineTo(MX - gap, 50); ctx.lineTo(MX - gap, 50 + len); ctx.stroke();

        // Top-Right

        ctx.beginPath(); ctx.moveTo(W - MX + gap - len, 50); ctx.lineTo(W - MX + gap, 50); ctx.lineTo(W - MX + gap, 50 + len); ctx.stroke();

        // Bottom-Left

        ctx.beginPath(); ctx.moveTo(MX - gap + len, H - 50); ctx.lineTo(MX - gap, H - 50); ctx.lineTo(MX - gap, H - 50 - len); ctx.stroke();

        // Bottom-Right

        ctx.beginPath(); ctx.moveTo(W - MX + gap - len, H - 50); ctx.lineTo(W - MX + gap, H - 50); ctx.lineTo(W - MX + gap, H - 50 - len); ctx.stroke();

        // 3. Digital neon chromatic overlay scanlines

        const vignette = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.4, W / 2, H / 2, Math.max(W, H) * 0.85);

        vignette.addColorStop(0, 'rgba(0, 255, 255, 0)');

        vignette.addColorStop(1, 'rgba(255, 0, 127, 0.14)');

        ctx.fillStyle = vignette; ctx.fillRect(0, 0, W, H);

        ctx.fillStyle = 'rgba(0, 255, 255, 0.05)';

        for (let y = 0; y < H; y += 8) {

            ctx.fillRect(0, y, W, 1);

        }

        ctx.restore();

    } else if (artStyle === 'pastel') {

        ctx.save();

        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        // 1. Organic, beautiful fluid pastel blobs

        const blobs = [

            {x: W * 0.15, y: H * 0.22, r: 500, c1: 'rgba(255, 181, 167, 0.28)', c2: 'rgba(255, 202, 212, 0)'},

            {x: W * 0.85, y: H * 0.65, r: 550, c1: 'rgba(181, 226, 250, 0.28)', c2: 'rgba(181, 242, 234, 0)'},

            {x: W * 0.35, y: H * 0.88, r: 450, c1: 'rgba(240, 230, 255, 0.25)', c2: 'rgba(255, 255, 255, 0)'}

        ];

        blobs.forEach(b => {

            const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r);

            g.addColorStop(0, b.c1);

            g.addColorStop(1, b.c2);

            ctx.fillStyle = g;

            ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, Math.PI*2); ctx.fill();

        });

        // 2. Soft pastel borders

        ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)'; ctx.lineWidth = 12;

        ctx.strokeRect(6, 6, W - 12, H - 12);

        ctx.restore();

    } else if (artStyle === 'aurora') {

        // Nền SÁNG premium: mesh blobs pastel trôi chậm + bokeh + vệt sáng chéo.
        ctx.save();
        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);
        const t = (typeof currentFrameTime === 'number' ? currentFrameTime : 0);
        const AB = [
            {x: 0.15, y: 0.12, r: 430, c: '191,219,254', a: 0.55},
            {x: 0.85, y: 0.24, r: 390, c: '221,214,254', a: 0.50},
            {x: 0.50, y: 0.55, r: 540, c: '251,207,232', a: 0.34},
            {x: 0.18, y: 0.85, r: 410, c: '187,247,208', a: 0.40},
            {x: 0.88, y: 0.80, r: 370, c: '254,215,170', a: 0.34},
        ];
        AB.forEach((b, i) => {
            const wob = Math.sin(t * 0.2 + i * 2.1);
            const bx = b.x * W + wob * 30, by = b.y * H + Math.cos(t * 0.16 + i) * 24;
            const g = ctx.createRadialGradient(bx, by, 0, bx, by, b.r);
            g.addColorStop(0, 'rgba(' + b.c + ',' + b.a + ')');
            g.addColorStop(1, 'rgba(' + b.c + ',0)');
            ctx.fillStyle = g;
            ctx.beginPath(); ctx.arc(bx, by, b.r, 0, Math.PI * 2); ctx.fill();
        });
        // bokeh nổi nhẹ
        for (let i = 0; i < 24; i++) {
            const bx = ((i * 233) % W);
            const by = (((i * 541) % H) + t * 10) % H;
            const fl = 0.05 + 0.09 * Math.abs(Math.sin(t * 0.7 + i * 1.3));
            const r = (i % 5 === 0) ? 24 : (i % 3 === 0 ? 13 : 7);
            ctx.fillStyle = 'rgba(255,255,255,' + fl + ')';
            ctx.beginPath(); ctx.arc(bx, by, r, 0, Math.PI * 2); ctx.fill();
            ctx.strokeStyle = 'rgba(148,163,216,' + (fl * 0.9) + ')'; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.arc(bx, by, r, 0, Math.PI * 2); ctx.stroke();
        }
        // vệt sáng chéo quét chậm
        const swp = ((t * 0.06) % 1.4) - 0.2;
        const g2 = ctx.createLinearGradient(W * (swp - 0.18), 0, W * (swp + 0.18), H * 0.5);
        g2.addColorStop(0, 'rgba(255,255,255,0)');
        g2.addColorStop(0.5, 'rgba(255,255,255,0.33)');
        g2.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.save(); ctx.rotate(-0.18); ctx.fillStyle = g2;
        ctx.fillRect(-W * 0.3, -H * 0.2, W * 1.8, H * 1.6); ctx.restore();
        ctx.restore();

    } else if (artStyle === 'mathnoir') {

        // Đen tuyền manim: chỉ 1 quầng sáng rất nhẹ giữa khung + vignette —
        // sạch tuyệt đối, để nét trắng mảnh tự toả sáng.
        ctx.save();
        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);
        const t = (typeof currentFrameTime === 'number' ? currentFrameTime : 0);
        const mg = ctx.createRadialGradient(
            W / 2, H * 0.42, 0,
            W / 2, H * 0.42, Math.max(W, H) * 0.55);
        mg.addColorStop(0, 'rgba(255,255,255,' + (0.028 + 0.006 * Math.sin(t * 0.4)) + ')');
        mg.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = mg;
        ctx.fillRect(0, 0, W, H);
        const mv = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.45, W / 2, H / 2, Math.max(W, H) * 0.85);
        mv.addColorStop(0, 'rgba(0,0,0,0)');
        mv.addColorStop(1, 'rgba(0,0,0,0.5)');
        ctx.fillStyle = mv; ctx.fillRect(0, 0, W, H);
        // Bụi li ti trôi chậm lên-phải: vị trí deterministic theo index
        // (fract(sin(i)*43758)), wrap quanh mép — mờ đến mức gần vô thức.
        const mnFract = v => v - Math.floor(v);
        for (let i = 0; i < 14; i++) {
            const r1 = mnFract(Math.sin(i * 127.3) * 43758.5453);
            const r2 = mnFract(Math.sin(i * 311.7) * 43758.5453);
            const r3 = mnFract(Math.sin(i * 74.7) * 43758.5453);
            const spd = 6 + 4 * r3;                                    // 6-10 px/s
            const px = mnFract(r1 + t * spd * 0.6 / W) * W;            // dạt phải
            const py = mnFract(r2 - t * spd / H) * H;                  // trôi lên
            ctx.fillStyle = 'rgba(232,232,234,' + (0.04 + 0.06 * r2).toFixed(3) + ')';
            ctx.beginPath();
            ctx.arc(px, py, 1 + 1.2 * r3, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.restore();

    } else if (artStyle === 'warmpaper') {

        // Giấy ấm: lưới kem nhạt + 2 mảng glow cam/hồng đào + vignette rất nhẹ.
        ctx.save();
        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);
        const t = (typeof currentFrameTime === 'number' ? currentFrameTime : 0);
        const wg = [
            { x: 0.8, y: 0.16, r: 560, c: '250,176,105', a: 0.16 },
            { x: 0.15, y: 0.78, r: 620, c: '255,205,150', a: 0.13 },
            { x: 0.55, y: 0.5, r: 700, c: '255,230,200', a: 0.10 },
        ];
        wg.forEach((b, i) => {
            const bx = b.x * W + Math.sin(t * 0.1 + i * 2) * 24;
            const by = b.y * H + Math.cos(t * 0.08 + i) * 20;
            const g = ctx.createRadialGradient(bx, by, 0, bx, by, b.r);
            g.addColorStop(0, 'rgba(' + b.c + ',' + b.a + ')');
            g.addColorStop(1, 'rgba(' + b.c + ',0)');
            ctx.fillStyle = g;
            ctx.beginPath(); ctx.arc(bx, by, b.r, 0, Math.PI * 2); ctx.fill();
        });
        ctx.strokeStyle = 'rgba(180,140,90,0.07)';
        ctx.lineWidth = 1;
        const wgs = 96;
        for (let x = 0; x < W; x += wgs) {
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
        }
        for (let y = 0; y < H; y += wgs) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
        }
        const wv = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.5, W / 2, H / 2, Math.max(W, H) * 0.85);
        wv.addColorStop(0, 'rgba(120,80,40,0)');
        wv.addColorStop(1, 'rgba(120,80,40,0.10)');
        ctx.fillStyle = wv; ctx.fillRect(0, 0, W, H);
        ctx.restore();

    } else if (artStyle === 'techdark') {

        // Than chì editorial: lưới chéo mờ + 2 mảng glow màu ấm/lạnh + vignette.
        ctx.save();
        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);
        const t = (typeof currentFrameTime === 'number' ? currentFrameTime : 0);
        const glows = [
            { x: 0.82, y: 0.18, r: 620, c: '251,146,60', a: 0.07 },
            { x: 0.12, y: 0.62, r: 560, c: '52,211,153', a: 0.05 },
            { x: 0.55, y: 0.92, r: 520, c: '34,211,238', a: 0.045 },
        ];
        glows.forEach((b, i) => {
            const bx = b.x * W + Math.sin(t * 0.12 + i * 2) * 30;
            const by = b.y * H + Math.cos(t * 0.1 + i) * 24;
            const g = ctx.createRadialGradient(bx, by, 0, bx, by, b.r);
            g.addColorStop(0, 'rgba(' + b.c + ',' + b.a + ')');
            g.addColorStop(1, 'rgba(' + b.c + ',0)');
            ctx.fillStyle = g;
            ctx.beginPath(); ctx.arc(bx, by, b.r, 0, Math.PI * 2); ctx.fill();
        });
        // lưới chéo mờ (xoay nhẹ quanh tâm)
        ctx.save();
        ctx.translate(W / 2, H / 2);
        ctx.rotate(-0.18);
        ctx.strokeStyle = 'rgba(255,255,255,0.035)';
        ctx.lineWidth = 1;
        const span = Math.max(W, H) * 1.5, gsz = 120;
        for (let x = -span; x < span; x += gsz) {
            ctx.beginPath(); ctx.moveTo(x, -span); ctx.lineTo(x, span); ctx.stroke();
        }
        for (let y = -span; y < span; y += gsz) {
            ctx.beginPath(); ctx.moveTo(-span, y); ctx.lineTo(span, y); ctx.stroke();
        }
        ctx.restore();
        // vignette đậm mép
        const vg = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.4, W / 2, H / 2, Math.max(W, H) * 0.82);
        vg.addColorStop(0, 'rgba(0,0,0,0)');
        vg.addColorStop(1, 'rgba(0,0,0,0.42)');
        ctx.fillStyle = vg; ctx.fillRect(0, 0, W, H);
        ctx.restore();

    } else if (artStyle === 'neonsketch') {

        // Blueprint neon: lưới xanh rêu + mảng glow olive trôi chậm + vạch
        // neon mảnh trên/dưới — nền cho nhân vật que neon vẽ tay.
        ctx.save();
        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);
        const t = (typeof currentFrameTime === 'number' ? currentFrameTime : 0);
        // mảng glow olive
        const GB = [
            { x: 0.5, y: 0.3, r: 620, a: 0.10 },
            { x: 0.2, y: 0.75, r: 480, a: 0.07 },
            { x: 0.85, y: 0.6, r: 430, a: 0.06 },
        ];
        GB.forEach((b, i) => {
            const bx = b.x * W + Math.sin(t * 0.15 + i * 2) * 26;
            const by = b.y * H + Math.cos(t * 0.12 + i) * 20;
            const g = ctx.createRadialGradient(bx, by, 0, bx, by, b.r);
            g.addColorStop(0, 'rgba(140,170,50,' + b.a + ')');
            g.addColorStop(1, 'rgba(140,170,50,0)');
            ctx.fillStyle = g;
            ctx.beginPath(); ctx.arc(bx, by, b.r, 0, Math.PI * 2); ctx.fill();
        });
        // lưới blueprint
        ctx.strokeStyle = 'rgba(163,230,53,0.075)';
        ctx.lineWidth = 1;
        const gs = 64;
        for (let x = 0; x < W; x += gs) {
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
        }
        for (let y = 0; y < H; y += gs) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
        }
        // vạch neon mảnh: trên (vàng→xanh) + dưới trái (cyan)
        const tl = ctx.createLinearGradient(MX, 0, W * 0.7, 0);
        tl.addColorStop(0, '#fde047'); tl.addColorStop(1, 'rgba(163,230,53,0.15)');
        ctx.fillStyle = tl;
        ctx.shadowColor = '#fde047'; ctx.shadowBlur = 10;
        ctx.fillRect(MX, 64, W * 0.62 - MX, 4);
        ctx.shadowColor = '#38bdf8';
        ctx.fillStyle = 'rgba(56,189,248,0.9)';
        ctx.fillRect(MX, H - 68, 190, 4);
        ctx.shadowBlur = 0;
        // vignette tối mép
        const vg = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.45, W / 2, H / 2, Math.max(W, H) * 0.8);
        vg.addColorStop(0, 'rgba(0,0,0,0)');
        vg.addColorStop(1, 'rgba(0,0,0,0.34)');
        ctx.fillStyle = vg; ctx.fillRect(0, 0, W, H);
        ctx.restore();

    } else if (artStyle === 'sketchnote') {

        ctx.save();

        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        // 1. Grid pattern representing school notebook

        ctx.strokeStyle = 'rgba(30, 41, 59, 0.04)';

        ctx.lineWidth = 1.2;

        const gridS = 40;

        for (let x = 0; x < W; x += gridS) {

            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();

        }

        for (let y = 0; y < H; y += gridS) {

            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();

        }

        // 2. High-quality paper grain noise textures

        ctx.fillStyle = 'rgba(0, 0, 0, 0.015)';

        for (let j = 0; j < 2500; j++) {

            const rx = rand() * W;

            const ry = rand() * H;

            ctx.fillRect(rx, ry, rand() * 2 + 1, rand() * 2 + 1);

        }

        // 3. Cute hand-drawn margin separator line on the left side

        ctx.strokeStyle = 'rgba(220, 38, 38, 0.15)';

        ctx.lineWidth = 2.5;

        ctx.beginPath();

        ctx.moveTo(MX - 18, 0);

        ctx.bezierCurveTo(MX - 22, H * 0.3, MX - 14, H * 0.7, MX - 20, H);

        ctx.stroke();

        ctx.restore();

    }

    // ── PHỤ ĐỀ — vẽ SAU CÙNG: sau elements, sau mọi lớp wash của phong cách.
    // Nhờ vậy phụ đề KHÔNG bị vignette của mathnoir làm tối, không bị lớp
    // watercolor/sketch nhân màu, và KHÔNG dính Ken Burns (applyMnKenBurns chỉ
    // sống trong save/restore của renderUnifiedElements).
    // Trạng thái đặt TƯỜNG MINH chứ không tin vào restore(): custom_js do AI
    // sinh có thể để lệch ngăn xếp save/restore → transform/alpha rò rỉ sang đây.
    if (SUB_ENGINE) {

        ctx.setTransform(RSCALE, 0, 0, RSCALE, 0, 0);

        ctx.globalAlpha = 1;

        ctx.globalCompositeOperation = 'source-over';

        ctx.shadowBlur = 0;

        ctx.shadowColor = 'rgba(0,0,0,0)';

        ctx.shadowOffsetX = 0;

        ctx.shadowOffsetY = 0;

        ctx.setLineDash([]);

        ctx.filter = 'none';

        ctx.save();

        try { drawSubtitle(currentTime); } finally { ctx.restore(); }

    }

    if (DL_REC) {
        const _dl = DL_REC.finish();
        if (process.env.T2_DL_DUMP) {
            try {
                require('fs').writeFileSync(process.env.T2_DL_DUMP, JSON.stringify({
                    nOps: _dl.ops.length, nRes: _dl.res.length, nGrads: _dl.grads.length,
                    ops: _dl.ops.map(function (o) {
                        return o.map(function (x) {
                            if (x && typeof x === 'object' && x.__res === undefined && x.__grad === undefined) {
                                return '<' + (x.constructor ? x.constructor.name : '?') + '>';
                            }
                            return x;
                        });
                    })
                }));
            } catch (e) { }
        }
        // Danh sách lệnh của khung VỪA vẽ. Bộ vẽ của nền tảng khác (Flutter trên
        // mobile) đọc chỗ này thay vì tự vẽ. clearOps() bên dưới sẽ xoá bản
        // trong DL_REC, nên phải giữ tham chiếu ra ngoài trước.
        globalThis.T2_LAST_DL = _dl;

        DL_REC._play(_ctx0, _dl);
        DL_REC.clearOps();   // giữ trạng thái, chỉ xoá lệnh
    }

}

/**

 * Estimate total height of a unified element list (pre-render pass).

 * Used to vertically center content when it doesn't fill the screen.

 */

function estimateTotalHeight(els) {

    let h = 0;

    let i = 0;

    while (i < els.length) {

        const el = els[i].el;

        if (el.type === 'gap') { h += 18; i++; continue; }

        if (el.type === 'box') {

            let j = i + 1;

            let innerH = 0;

            while (j < els.length && ['text','math_calc','reveal'].includes(els[j].el.type)) {

                innerH += estimateElementHeight(els[j].el);

                j++;

            }

            h += innerH + 40 + 8; // padding + gap

            i = j;

            continue;

        }

        h += estimateElementHeight(el);

        i++;

    }

    return h;

}

function estimateElementHeight(el) {

    if (!el) return 0;

    switch (el.type) {

        case 'text':    return measureTextHeight(el) + 6;

        case 'list':    return measureTextHeight(el) + 8;

        case 'timeline': return measureTextHeight(el) + 8;

        case 'math_calc': return measureTextHeight(el) + 10;

        case 'reveal':  return (el.fontSize || 44) * 1.4 + 6;

        case 'line':    return 18;

        case 'icon':    return (el.size || 64) + 10;

        case 'arrow':   return 30;

        case 'image': {

          if (el.src && IMAGE_CACHE[el.src]) {

              const img = IMAGE_CACHE[el.src];

              const availW = W - MX * 2;

              const maxH = Math.min(Math.round(availW * 0.75), Math.round(H * 0.5));

              const ratio = Math.min(availW / img.width, maxH / img.height);

              return Math.round(img.height * ratio) + 24;

          }

          return Math.min(Math.round((W - MX * 2) * 0.75), Math.round(H * 0.5)) + 24;

        }

        case 'image_generation': return 380 + 24; // placeholder height

        case 'gap':     return 18;

        case 'custom_js': {

          const baseH = (el.height !== undefined && el.height !== null) ? el.height : (() => {

              const isPortrait = H > W;

              const sc = isPortrait ? (W / 360) : (H / 600);

              const frameH = isPortrait ? (340 * sc) : (200 * sc);

              return frameH + 20 + 6;

          })();

          const scaleFactor = (el.fontSize || 40) / 40;

          return baseH * scaleFactor;

        }

        default:        return 0;

    }

}

/**

 * Calculate the optimal startY to vertically center content.

 * Keeps a minimum top margin of minY.

 * Only centers if content height < 60% of available height (otherwise top-align).

 */

function calcCenteredStartY(els, minY, maxY) {

    const available = maxY - minY;

    const totalH = estimateTotalHeight(els);

    const topAlignThreshold = (H > W) ? 0.90 : 0.75;

    if (totalH >= available * topAlignThreshold) return minY; // content fills enough space — top align

    // Center in available space, with minimum top margin

    const centered = minY + (available - totalH) / 2;

    const maxClampFactor = (H > W) ? 0.32 : 0.18;

    return Math.max(minY, Math.min(centered, minY + available * maxClampFactor)); // clamp: allow vertical layouts to go down to 32% for balanced centering

}

function renderGeometryZone(geoElsObj, startY, zoneH) {

    if (geoElsObj.length === 0) return 0;

    zoneH = zoneH || 400;

    // geoElsObj is array of {el, rawP}

    const pad = 40;

    const boxW = W - MX * 2;

    ctx.save();

    // Draw zone background

    roundRect(MX, startY, boxW, zoneH, 16);

    ctx.fillStyle = T.geoBg || '#1a1a2e'; 

    ctx.fill();

    ctx.strokeStyle = T.geoBorder || '#3a3a5a';

    ctx.lineWidth = 2;

    ctx.stroke();

    // Mapping normalized (0.0 - 1.0) coords to zone coords

    // Use the inner area with padding

    const innerW = boxW - pad * 2;

    const innerH = zoneH - pad * 2;

    const mapX = (x) => MX + pad + x * innerW;

    const mapY = (y) => startY + pad + y * innerH;

    // Build point lookup

    const pts = {};

    for (const g of geoElsObj) {

        if (g.el.type === 'point') {

            pts[g.el.id] = { x: mapX(g.el.x), y: mapY(g.el.y), el: g.el, rawP: g.rawP };

        }

    }

    // 1. Draw segments

    for (const g of geoElsObj) {

        if (g.el.type === 'segment') {

            const p1 = pts[g.el.from], p2 = pts[g.el.to];

            if (p1 && p2) {

                ctx.globalAlpha = easeOut(Math.min(g.rawP * 2, 1));

                ctx.beginPath();

                ctx.moveTo(p1.x, p1.y);

                ctx.lineTo(p2.x, p2.y);

                ctx.strokeStyle = g.el.color === 'highlight' ? T.highlight

                                : g.el.color === 'red'       ? '#ef4444'

                                : g.el.color === 'green'     ? '#22c55e'

                                : (g.el.color || '#ffffff');

                ctx.lineWidth = 5;

                ctx.lineCap = 'round';

                ctx.stroke();

            }

        }

    }

    // 2. Draw right angles

    for (const g of geoElsObj) {

        if (g.el.type === 'right_angle') {

            const v = pts[g.el.vertex], p1 = pts[g.el.from], p2 = pts[g.el.to];

            if (v && p1 && p2) {

                ctx.globalAlpha = easeOut(Math.min(g.rawP * 2, 1));

                // Unit vectors

                const dx1 = p1.x - v.x, dy1 = p1.y - v.y;

                const len1 = Math.hypot(dx1, dy1);

                const u1x = dx1 / len1, u1y = dy1 / len1;

                const dx2 = p2.x - v.x, dy2 = p2.y - v.y;

                const len2 = Math.hypot(dx2, dy2);

                const u2x = dx2 / len2, u2y = dy2 / len2;

                const size = Math.min(innerW, innerH) * 0.06; // proportional

                ctx.beginPath();

                ctx.moveTo(v.x + u1x * size, v.y + u1y * size);

                ctx.lineTo(v.x + u1x * size + u2x * size, v.y + u1y * size + u2y * size);

                ctx.lineTo(v.x + u2x * size, v.y + u2y * size);

                ctx.strokeStyle = T.highlight || '#eab308';

                ctx.lineWidth = 4;

                ctx.lineJoin = 'round';

                ctx.stroke();

            }

        }

    }

    // 3. Draw points & labels

    for (const id in pts) {

        const p = pts[id];

        ctx.globalAlpha = easeOut(Math.min(p.rawP * 2, 1));

        const pColor = p.el.color === 'highlight' ? T.highlight

                     : p.el.color === 'red'       ? '#ef4444'

                     : p.el.color === 'green'      ? '#22c55e'

                     : '#ffffff';

        // Outer glow

        ctx.beginPath();

        ctx.arc(p.x, p.y, 10, 0, Math.PI * 2);

        ctx.fillStyle = pColor + '40';

        ctx.fill();

        ctx.beginPath();

        ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);

        ctx.fillStyle = pColor;

        ctx.fill();

        if (p.el.label) {

            ctx.fillStyle = pColor;

            ctx.font = 'bold 28px ' + T.font;

            ctx.textAlign = 'center';

            ctx.textBaseline = 'bottom';

            ctx.fillText(p.el.label, p.x, p.y - 14);

        }

    }

    ctx.restore();

    return zoneH + 20;

}

function drawHighlights(currentTime) {

    const activeWord = getActiveWord(currentTime);

    if (!activeWord) return;

    const steps = script.steps, tSteps = timing.steps;

    let renderFrom = 0;

    for (let i = steps.length - 1; i >= 0; i--) {

        const ts = tSteps[i];

        if (ts && currentTime >= ts.start && steps[i].clear) { renderFrom = i; break; }

    }

    const { nonGeoEls } = buildUnifiedLayout(currentTime, renderFrom, steps, tSteps);

    let cursorY = 80;

    _measureAndHighlightUnified(nonGeoEls, cursorY, activeWord);

}

function _measureAndHighlightUnified(unifiedEls, startY, activeWord) {

    let cursorY = startY;

    let i = 0;

    while (i < unifiedEls.length) {

        const u = unifiedEls[i];

        const el = u.el;

        if (el.type === 'gap') {

            cursorY += 18;

            i++;

            continue;

        }

        if (el.type === 'box') {

            const inner = [];

            let j = i + 1;

            while (j < unifiedEls.length && (unifiedEls[j].el.type === 'text' || unifiedEls[j].el.type === 'list' || unifiedEls[j].el.type === 'math_calc' || unifiedEls[j].el.type === 'reveal')) {

                inner.push(unifiedEls[j]);

                j++;

            }

            const pad = 20;

            let iy = cursorY + pad;

            let boxH = pad * 2;

            for (const iu of inner) boxH += _measureElH(iu.el) + 6;

            for (const iu of inner) {

                const consumed = _highlightEl(iu.el, iy, activeWord);

                iy += consumed;

            }

            cursorY += boxH + 8;

            i = j;

            continue;

        }

        const consumed = _highlightEl(el, cursorY, activeWord);

        cursorY += consumed || _measureElH(el) + 6;

        i++;

    }

    return cursorY;

}

function _measureElH(el) {

    const contentW = W - MX * 2;

    if (el.type === 'math_calc') {

        const fs = el.fontSize || 48;

        const lines = (el.operands || []).length + (el.result ? 1 : 0);

        return lines * (fs * 1.3) + 40 + 6;

    }

    if (el.type === 'text') {

        const fs = el.fontSize || 40;

        const font = `${el.bold ? 'bold ' : ''}${fs}px ${T.font}`;

        const contentWFixed = W - MX * 2 - 60;

        let h = 0;

        for (const raw of (el.text || '').split('\n')) {

            h += wrapText(raw, contentWFixed, font).length * fs * 1.4;

        }

        return h + 6;

    }

    if (el.type === 'list') {

        const fs = el.fontSize || 36;

        const font = `${el.bold ? 'bold ' : ''}${fs}px ${T.font}`;

        ctx.font = font;

        const bullet = el.bullet || '•';

        const bw = ctx.measureText(bullet + ' ').width;

        const contentWFixed = W - MX * 2 - 60;

        let h = 0;

        for (const item of (el.items || [])) {

            h += wrapText(item, contentWFixed - bw, font).length * fs * 1.4 + 10;

        }

        return h + 6;

    }

    if (el.type === 'timeline') {

        const fs = el.fontSize || 32, font = `${fs}px ${T.font}`;

        const items = el.items || [];

        const isHoriz = true; // render timeline ngang cho mọi tỷ lệ màn hình

        if (isHoriz) {

            const itemW = (W - MX * 2) / Math.max(1, items.length);

            let maxH = 0;

            ctx.font = font;

            for (const item of items) {

                let lineH = wrapText(item.event || '', itemW - 20, font).length * fs * 1.4;

                maxH = Math.max(maxH, lineH);

            }

            return maxH + fs + 80;

        } else {

            const lineX = MX + 40;

            let totalH = 0;

            ctx.font = font;

            for (const item of items) {

                totalH += fs * 1.4 + 10;

                totalH += wrapText(item.event || '', W - lineX - 30 - MX, font).length * fs * 1.4;

                totalH += 30;

            }

            return totalH;

        }

    }

    if (el.type === 'custom_js') {

        const isPortrait = H > W;

        const sc = isPortrait ? (W / 360) : (H / 600);

        const frameH = isPortrait ? (340 * sc) : (200 * sc);

        return frameH + 20 + 6;

    }

    if (el.type === 'icon') return (el.size || 64) + 10;

    if (el.type === 'line') return 18;

    if (el.type === 'arrow') return 30;

    if (el.type === 'image') {

        if (el.src && IMAGE_CACHE[el.src]) {

            const img = IMAGE_CACHE[el.src];

            const maxW = el.width || (W - MX * 2);

            const maxH = Math.min(el.height || 600, 600);

            const ratio = Math.min(maxW / img.width, maxH / img.height);

            return Math.round(img.height * ratio) + 24;

        }

        return (el.height || 600) + 24;

    }

    return 0;

}

/** Try to find & highlight active word inside a single element. Returns height consumed. */

function _highlightEl(el, y, activeWord) {

    const h = _measureElH(el);

    if (el.type === 'math_calc') {

        const fs = el.fontSize || 48;

        const cx = W / 2 + 80;

        let cy = y + 10;

        const ops = el.operands || [];

        for (let k = 0; k < ops.length; k++) {

            const opNorm = normalizeWord(ops[k]);

            if (opNorm === activeWord.norm || activeWord.norm.includes(opNorm) || opNorm.includes(activeWord.norm)) {

                // Measure text width with monospace font

                ctx.font = `bold ${fs}px 'Courier New', Consolas, monospace`;

                const tw = ctx.measureText(ops[k]).width;

                drawHighlightBox(cx - tw, cy, tw, fs, '#FFD700');

            }

            cy += fs * 1.3;

        }

        // Result highlight

        cy += 28; // separator line

        if (el.result) {

            const resNorm = normalizeWord(el.result);

            if (resNorm === activeWord.norm || activeWord.norm.includes(resNorm) || resNorm.includes(activeWord.norm)) {

                ctx.font = `bold ${fs}px 'Courier New', Consolas, monospace`;

                const tw = ctx.measureText(el.result).width;

                drawHighlightBox(cx - tw, cy, tw, fs, '#00FF88');

            }

        }

        return h;

    }

    if (el.type === 'text') {

        const fs = el.fontSize || 40;

        const font = `${el.bold ? 'bold ' : ''}${fs}px ${T.font}`;

        const align = el.align || 'left';

        ctx.font = font;

        const contentWFixed = W - MX * 2 - 60;

        let lineY = y;

        for (const raw of (el.text || '').split('\n')) {

            const wrapped = wrapText(raw, contentWFixed, font);

            for (const line of wrapped) {

                // Check if active word appears in this line

                const lineNorm = normalizeWord(line);

                const wordsInLine = line.split(' ');

                let xOff = align === 'center' ? W/2 - measureMathAwareText(line, font)/2

                         : align === 'right'  ? W - MX - measureMathAwareText(line, font)

                         : MX;

                for (const w of wordsInLine) {

                    const wNorm = normalizeWord(w);

                    const ww = measureMathAwareText(w, font);

                    if (wNorm && wNorm === activeWord.norm) {

                        drawHighlightBox(xOff, lineY, ww, fs * 0.9, T.hlColor);

                    }

                    xOff += ww + measureMathAwareText(' ', font);

                }

                lineY += fs * 1.4;

            }

        }

        return h;

    }

    if (el.type === 'list') {

        const fs = el.fontSize || 36;

        const font = `${el.bold ? 'bold ' : ''}${fs}px ${T.font}`;

        const align = el.align || 'center';

        ctx.font = font;

        const bullet = el.bullet || '•';

        const bulletW = ctx.measureText(bullet + ' ').width;

        const contentWFixed = W - MX * 2 - 60;

        let maxW = 0;

        for (const item of (el.items || [])) {

            for (const line of wrapText(item, contentWFixed - bulletW, font)) {

                maxW = Math.max(maxW, ctx.measureText(line).width);

            }

        }

        const startX = (align === 'center') ? (W / 2 - (bulletW + maxW) / 2) : MX;

        let lineY = y;

        for (const item of (el.items || [])) {

            for (const line of wrapText(item, contentWFixed - bulletW, font)) {

                const wordsInLine = line.split(' ');

                let xOff = startX + bulletW;

                for (const w of wordsInLine) {

                    const wNorm = normalizeWord(w);

                    const ww = ctx.measureText(w).width;

                    if (wNorm && wNorm === activeWord.norm) {

                        drawHighlightBox(xOff, lineY, ww, fs * 0.9, T.hlColor);

                    }

                    xOff += ww + ctx.measureText(' ').width;

                }

                lineY += fs * 1.4;

            }

            lineY += 10;

        }

        return h;

    }

    if (el.type === 'timeline') {

        const fs = el.fontSize || 32, font = `${fs}px ${T.font}`;

        const items = el.items || [];

        const isHoriz = true; // render timeline ngang cho mọi tỷ lệ màn hình

        if (isHoriz) {

            const lineY = y + fs + 20;

            const itemW = (W - MX * 2) / Math.max(1, items.length);

            ctx.font = font;

            for (let i = 0; i < items.length; i++) {

                const item = items[i];

                const x = items.length === 1 ? W/2 : MX + itemW/2 + i * itemW;

                let textY = lineY + 20;

                const lines = wrapText(item.event || '', itemW - 20, font);

                for (const line of lines) {

                    const wordsInLine = line.split(' ');

                    let xOff = x - ctx.measureText(line).width / 2;

                    for (const w of wordsInLine) {

                        const wNorm = normalizeWord(w);

                        const ww = ctx.measureText(w).width;

                        if (wNorm && wNorm === activeWord.norm) {

                            drawHighlightBox(xOff, textY, ww, fs * 0.9, T.hlColor);

                        }

                        xOff += ww + ctx.measureText(' ').width;

                    }

                    textY += fs * 1.4;

                }

            }

        } else {

            const lineX = MX + 40;

            let curY = y;

            ctx.font = font;

            for (let i = 0; i < items.length; i++) {

                const item = items[i];

                let textY = curY + fs * 1.4 + 10;

                const lines = wrapText(item.event || '', W - lineX - 30 - MX, font);

                for (const line of lines) {

                    const wordsInLine = line.split(' ');

                    let xOff = lineX + 30;

                    for (const w of wordsInLine) {

                        const wNorm = normalizeWord(w);

                        const ww = ctx.measureText(w).width;

                        if (wNorm && wNorm === activeWord.norm) {

                            drawHighlightBox(xOff, textY, ww, fs * 0.9, T.hlColor);

                        }

                        xOff += ww + ctx.measureText(' ').width;

                    }

                    textY += fs * 1.4;

                }

                curY += (fs * 1.4 + 10) + (lines.length * fs * 1.4) + 30;

            }

        }

        return h;

    }

    return h;

}

// ── Main loop ───────────────────────────────────────────────────

const MODE = args.mode || 'pipe'; // 'pipe' (fast, direct to ffmpeg) or 'frames' (PNG files)

const IMAGE_CACHE = {};

global.IMAGE_CACHE = IMAGE_CACHE;

try { global.Image = require('canvas').Image; } catch(e) {}

(async () => {

    async function preloadOne(src) {

        if (!src || IMAGE_CACHE[src]) return;

        try {

            HOST.warn(`[Renderer] Loading image: ${src}`);

            // Nền tảng không có hệ thống file (trình duyệt, QuickJS) tự quyết
            // ảnh này lấy ở đâu — thường là URL do máy chủ xem trước phục vụ.
            // Không có cửa này thì đoạn dưới đổi src thành ĐƯỜNG DẪN FILE Windows
            // và ảnh người dùng chèn vào KHÔNG BAO GIỜ hiện trong xem trước web
            // (hỏng im lặng vì catch nuốt lỗi).
            if (BOOT && typeof BOOT.imageUrl === 'function') {
                IMAGE_CACHE[src] = await HOST.loadImage(BOOT.imageUrl(src));
                return;
            }

            let localPath = src;

            // Handle both /api/v1/edu_video/gallery/file/ and old /api/v1/edu_video_studio/gallery/file/

            if (localPath.includes('/gallery/file/')) {

                const rel = localPath.split('/gallery/file/')[1]; // e.g. 'items/xxx.png'

                // gallery dir: edu_video_studio/gallery/ relative to DATA_DIR

                const dataDir = path.resolve(__dirname, '..', '..', '..');

                const galleryDir = path.join(dataDir, 'edu_video_studio', 'gallery');

                // Try direct path first (includes subfolder like items/)

                let resolved = path.join(galleryDir, rel);

                if (!require('fs').existsSync(resolved)) {

                    // Try bare filename in items/ as fallback

                    resolved = path.join(galleryDir, 'items', path.basename(rel));

                }

                localPath = resolved;

            }

            const img = await HOST.loadImage(localPath);

            IMAGE_CACHE[src] = img;

            process.stderr.write(`[Renderer] Image loaded OK: ${localPath}\n`);

        } catch (e) {

            process.stderr.write(`[Renderer] Failed to load image ${src}: ${e.message}\n`);

        }

    }

    // Preload all image elements and custom_js gallery references in script

    for (const step of script.steps || []) {

        for (const el of step.elements || []) {

            if (el.type === 'image' && el.src) {

                await preloadOne(el.src);

            } else if (el.type === 'custom_js' && el.code) {

                const matches = el.code.match(/["'](\/api\/v1\/edu_video\/gallery\/file\/[^"']+)["']/g);

                if (matches) {

                    for (const m of matches) {

                        const url = m.slice(1, -1);

                        await preloadOne(url);

                    }

                }

            }

        }

    }

    // (Không còn khâu nạp emoji — emoji được vẽ bằng icon Lucide, không tải
    //  PNG từ CDN nữa. Xem 'Icon thay cho emoji' phía trên.)

    // ── Kho sprite của template (ui.sprite) ──────────────────────────────
    // Nhân vật/hình vẽ sẵn dạng PNG trong gói template — AI chỉ gọi tên,
    // không phải vẽ. Quét: <T2_TEMPLATE_CACHE>/<pack>/sprites/*.png (kho
    // online) + <app>/assets/sprites/<bộ>/*.png (đóng gói kèm app).
    global.SPRITES = {};
    global.SPRITE_PATHS = {};
    // Nạp tranh KHI CẦN, giữ tối đa một ngân sách RAM (LRU). Nạp hết ngay từ đầu thì job 188 shot (194 tranh phủ
    // khung, ~1,3 GB sau giải mã) nhân 12 tiến trình song song là ~16 GB: máy 32 GB tràn RAM, đứng ở 81% (19/9/2026).
    // Cảnh nào cũng chỉ dùng vài tranh liên tiếp (một tranh phủ khung, hoặc phông + tối đa 3 con rối) nên 256 MB dư.
    const SPRITE_BUDGET = Math.max(64, parseInt(process.env.T2_SPRITE_BUDGET_MB || '256', 10)) * 1048576;
    const _spriteLRU = new Map();
    let _spriteBytes = 0;
    global.getSprite = function (name) {
        if (!name) return null;
        if (global.SPRITES[name]) return global.SPRITES[name];          // BOOT.sprites (trình duyệt) nạp sẵn
        const hit = _spriteLRU.get(name);
        if (hit) { _spriteLRU.delete(name); _spriteLRU.set(name, hit); return hit; }
        const p = global.SPRITE_PATHS[name];
        if (!p || typeof NodeImage !== 'function') return null;
        let img = null;
        try { img = new NodeImage(); img.src = fs.readFileSync(p); } catch (e) { img = null; }   // Buffer → giải mã ĐỒNG BỘ
        if (!img || !(img.width > 0)) { global.SPRITE_PATHS[name] = ''; return null; }
        _spriteLRU.set(name, img);
        _spriteBytes += img.width * img.height * 4;
        for (const [k, v] of _spriteLRU) {
            if (_spriteBytes <= SPRITE_BUDGET || k === name) break;
            _spriteLRU.delete(k);
            _spriteBytes -= v.width * v.height * 4;
        }
        return img;
    };
    // Trình duyệt/QuickJS không quét được thư mục → nhận sẵn bản đồ {tên: URL}.
    // Thiếu bước này thì xem trước vẽ nhân vật DỰ PHÒNG thay vì sprite thật —
    // tức là lại nói dối, đúng thứ ta đang diệt.
    if (BOOT && BOOT.sprites) {
        for (const key of Object.keys(BOOT.sprites)) {
            try { global.SPRITES[key] = await HOST.loadImage(BOOT.sprites[key]); }
            catch (e) { HOST.warn('[Sprite] không nạp được ' + key + ': ' + e.message); }
        }
    } else try {
        const spriteRoots = [];
        if (process.env.T2_TEMPLATE_CACHE) spriteRoots.push(process.env.T2_TEMPLATE_CACHE);
        spriteRoots.push(path.join(__dirname, '..', 'assets', 'sprites'));
        for (const root of spriteRoots) {
            if (!fs.existsSync(root)) continue;
            for (const sub of fs.readdirSync(root)) {
                for (const dir of [path.join(root, sub, 'sprites'), path.join(root, sub)]) {
                    let files = [];
                    try { files = fs.readdirSync(dir); } catch (e) { continue; }
                    for (const f of files) {
                        if (!f.endsWith('.png')) continue;
                        const key = f.slice(0, -4);
                        if (global.SPRITE_PATHS[key]) continue;
                        global.SPRITE_PATHS[key] = path.join(dir, f);
                    }
                }
            }
        }
        const nSpr = Object.keys(global.SPRITE_PATHS).length;
        if (nSpr) process.stderr.write(`[Sprites] loaded ${nSpr}\n`);
    } catch (e) {
        process.stderr.write(`[Sprites] scan failed: ${e.message}\n`);
    }

    // ══ ĐIỂM CẮT: nạp xong tài nguyên thì TRAO QUYỀN cho nền tảng ══════
    // Node đi tiếp xuống dưới để tự xuất file / bơm vào ffmpeg.
    // Trình duyệt và QuickJS thì KHÔNG — chúng chỉ cần gọi T2_RENDER(t) để vẽ
    // một khung tại thời điểm bất kỳ (tua xem trước!), rồi tự lo phần sau.
    // Nhờ điểm cắt này, cùng một file chạy được ở cả ba nơi.
    if (BOOT) {
        globalThis.T2_RENDER = renderFrame;          // vẽ khung tại thời điểm t
        globalThis.T2_CANVAS = canvas;
        globalThis.T2_DL_REC = DL_REC;               // null nếu không bật display list
        if (typeof BOOT.onReady === 'function') BOOT.onReady();
        return;
    }

    const totalDur = timing.total_duration || 30;

    const totalFrames = Math.ceil(totalDur * FPS);

    const startF = parseInt(args.startFrame || '0');

    const endF = parseInt(args.endFrame || String(totalFrames));

    process.stderr.write(`[Renderer v5] rendering range: ${startF} to ${endF} (total: ${totalFrames} frames), ${FPS}fps, ${totalDur}s, mode=${MODE}\n`);

    // ── PREVIEW MODE: render MỘT frame PNG tại previewTime rồi thoát ──
    if (MODE === 'preview') {
        const t = parseFloat(args.previewTime || String(totalDur * 0.9));
        renderFrame(t);
        const outFile = args.outputFile || path.join(outputDir, 'preview.png');
        fs.writeFileSync(outFile, canvas.toBuffer('image/png'));
        console.log(JSON.stringify({ type: 'done', status: 'success', preview: outFile, time: t }));
        return;
    }

    if (MODE === 'pipe') {

        // ── PIPE MODE: spawn ffmpeg, pipe raw RGBA pixels directly ──

        const audioPath = args.audio || '';

        const outputFile = args.outputFile || path.join(outputDir, 'output.mp4');

        const { spawn } = require('child_process');

        // Build ffmpeg command

        const ffArgs = [

            '-y',

            '-f', 'rawvideo',

            '-pix_fmt', 'bgra',

            // CW×CH, KHÔNG phải W×H: đây là cỡ THẬT của buffer canvas.toBuffer
            // ('raw') bơm xuống. Khai sai một pixel là ffmpeg đọc lệch hàng →
            // video ra xiên/nhiễu chứ không báo lỗi. (RSCALE=1 → CW×CH = W×H.)
            '-s', `${CW}x${CH}`,

            '-r', String(FPS),

            '-i', 'pipe:0',           // video from stdin

        ];

        // Add audio if available

        if (audioPath && fs.existsSync(audioPath)) {

            ffArgs.push('-i', audioPath);

            ffArgs.push('-c:a', 'aac', '-b:a', '128k');

        }

        const codec = args.codec || 'libx264';

        const preset = args.preset || 'medium';

        const extraArgs = args.ffmpegExtra ? args.ffmpegExtra.split(' ') : [];

        ffArgs.push(

            '-c:v', codec,

            '-preset', preset,

            ...extraArgs,

            '-pix_fmt', 'yuv420p',

            '-shortest',

            outputFile

        );

        // -nostats: dong thong ke tung khung cua ffmpeg ket bang CR (khong LF), chuyen tiep len
        // stderr lam driver Python doc theo dong bi nghen sau ~15 phut (xem video_encoder._drain_stderr).
        if (!ffArgs.includes('-nostats')) ffArgs.unshift('-hide_banner', '-nostats', '-loglevel', 'warning');
        const ffmpeg = spawn('ffmpeg', ffArgs, { stdio: ['pipe', 'pipe', 'pipe'] });

        ffmpeg.stderr.on('data', (d) => {

            process.stderr.write(`[FFmpeg] ${d.toString()}`);

        });

        let ffmpegDone = new Promise((resolve, reject) => {

            ffmpeg.on('close', (code) => {

                if (code === 0) resolve();

                else reject(new Error(`FFmpeg exited with code ${code}`));

            });

            ffmpeg.on('error', reject);

        });

        // Write with backpressure: wait for drain if buffer is full

        function writeFrame(buf) {

            return new Promise((resolve) => {

                const ok = ffmpeg.stdin.write(buf);

                if (ok) resolve();

                else ffmpeg.stdin.once('drain', resolve);

            });

        }

        // Render frames and pipe raw pixel data

        let pipeError = null;

        ffmpeg.stdin.on('error', (err) => { pipeError = err; });

        for (let f = startF; f < endF; f++) {

            if (pipeError) {

                process.stderr.write(`[Renderer] Pipe broken at frame ${f}: ${pipeError.message}\n`);

                break;

            }

            renderFrame(f / FPS);

            // node-canvas 'raw' outputs BGRA natively — ffmpeg now expects bgra, no swap needed

            const buf = canvas.toBuffer('raw');

            try { await writeFrame(buf); } catch(e) { pipeError = e; break; }

            if (f % 30 === 0 || f === endF - 1) {

                const chunkTotal = endF - startF;

                const chunkCurrent = f - startF;

                const pct = Math.round((chunkCurrent / chunkTotal) * 100);

                console.log(JSON.stringify({

                    type: 'progress',

                    percent: pct,

                    frame: f,

                    startFrame: startF,

                    endFrame: endF,

                    total: totalFrames,

                    message: `Pipe ${f}/${totalFrames} (${pct}%)`

                }));

            }

        }

        ffmpeg.stdin.end();

        try { await ffmpegDone; } catch(e) {

            process.stderr.write(`[Renderer] FFmpeg error: ${e.message}\n`);

            // Report error so Python can fallback to CPU

            console.log(JSON.stringify({ type: 'error', message: `FFmpeg pipe failed: ${e.message}` }));

            process.exit(1);

        }

        console.log(JSON.stringify({ type: 'done', status: 'success', totalFrames, outputFile }));

    } else {

        // ── FRAMES MODE: write JPEG files (much faster than PNG) ──

        for (let f = startF; f < endF; f++) {

            renderFrame(f / FPS);

            const num = String(f).padStart(6, '0');

            // Use JPEG instead of PNG: ~3x faster to write, GPU encoder reads equally fast

            fs.writeFileSync(path.join(outputDir, `frame_${num}.jpg`), canvas.toBuffer('image/jpeg', { quality: 0.92 }));

            if (f % 30 === 0 || f === endF - 1) {

                const chunkTotal = endF - startF;

                const chunkCurrent = f - startF;

                const pct = Math.round((chunkCurrent / chunkTotal) * 100);

                console.log(JSON.stringify({
                    type: 'progress',
                    percent: pct,
                    frame: f,
                    startFrame: startF,
                    endFrame: endF,
                    total: totalFrames,
                    message: `Frame ${f}/${totalFrames} (${pct}%)`
                }));

            }

        }

        console.log(JSON.stringify({ type: 'done', status: 'success', totalFrames }));

    }

})();
