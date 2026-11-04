// ui.anim — dải hình động `<tên>_a<khung>x<cột>f<fps>` (clip Muse phông xanh đã tách nền, 4/11/2026).
// Chạy: node tests/anim_strip_test.js   (mã thoát 0 = đạt). Không cần node-canvas: lấy nguyên thân hàm ui.anim
// trong canvas_renderer.js rồi chạy với ctx giả ghi lại lệnh drawImage.
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'engines', 'canvas_renderer.js'), 'utf8');
const m = /ui\.anim = function \(name, cx, cy, size, o = \{\}\) \{[\s\S]*?\n    \};\n/.exec(src);
let fails = 0, checks = 0;
function check(name, ok, detail) {
    checks++;
    console.log((ok ? '  ok   ' : '  FAIL ') + name + (ok ? '' : '  ' + JSON.stringify(detail)));
    if (!ok) fails++;
}
check('canvas_renderer.js có ui.anim', !!m);
if (!m) process.exit(1);

function make(time, img) {
    const calls = [];
    const ctx = {
        globalAlpha: 1, save() {}, restore() {}, translate() {}, rotate() {}, scale(x) { calls.push(['scale', x]); },
        drawImage(...a) { calls.push(['draw', ...a]); },
    };
    const ui = { sprite: (...a) => calls.push(['sprite', ...a]) };
    global.SPRITES = { x: 1 };
    global.getSprite = () => img;
    new Function('ui', 'ctx', 'time', m[0])(ui, ctx, time);
    return { ui, calls };
}
// 8 khung, 4 cột → 2 hàng; ảnh 400×200 → ô 100×100; 10 fps.
const IMG = { width: 400, height: 200 };
const KEY = 'meo_chay_a8x4f10';
function idx(time, o) {
    const { ui, calls } = make(time, IMG);
    ui.anim(KEY, 0, 0, 200, o || {});
    const d = calls.find(c => c[0] === 'draw');
    return d ? (d[3] / 100) * 4 + d[2] / 100 : null;
}
check('t=0 → khung 0', idx(0) === 0, idx(0));
check('t=0.35 s @10 fps → khung 3', idx(0.35) === 3, idx(0.35));
check('t=0.5 → khung 5 (hàng 2)', idx(0.5) === 5, idx(0.5));
check('lặp vòng: t=0.9 → khung 1', idx(0.9) === 1, idx(0.9));
check('loop:false dừng ở khung cuối', idx(5, { loop: false }) === 7, idx(5, { loop: false }));
check('pingpong: khung 8 → 6', idx(0.8, { pingpong: true }) === 6, idx(0.8, { pingpong: true }));
check('frame cố định', idx(3, { frame: 2 }) === 2, idx(3, { frame: 2 }));
check('fps trong o thắng fps của khoá', idx(0.25, { fps: 20 }) === 5, idx(0.25, { fps: 20 }));
{
    const { ui, calls } = make(0, IMG);
    ui.anim(KEY, 0, 0, 200);
    const d = calls.find(c => c[0] === 'draw');
    check('cắt đúng ô 100×100 và phóng về 200', d && d[3] === 0 && d[4] === 100 && d[5] === 100 && d[8] === 200, d);
}
{
    const { ui, calls } = make(0, IMG);
    ui.anim('meo_tinh', 1, 2, 300);
    check('khoá không đúng quy ước → rơi về ui.sprite', calls.length === 1 && calls[0][0] === 'sprite', calls);
}
{
    const { ui, calls } = make(0, null);
    ui.anim(KEY, 1, 2, 300);
    check('thiếu ảnh → rơi về ui.sprite', calls.length === 1 && calls[0][0] === 'sprite', calls);
}
check('Linux: fontconfig ép sans-serif → Be Vietnam Pro', /process\.platform !== 'win32'\) \{[\s\S]{0,1600}Be Vietnam Pro/.test(src));
console.log(`\n${checks - fails}/${checks} PASS`);
process.exit(fails ? 1 : 0);
