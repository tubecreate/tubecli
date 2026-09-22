/**
 * engines/host.js — Tầng HOST: mọi thứ renderer cần từ NỀN TẢNG.
 *
 * Đây là ĐƯỜNG NỐI thứ hai (đường thứ nhất là display_list.js).
 *
 *   display_list.js  tách "VẼ GÌ"      khỏi "VẼ BẰNG GÌ"   (canvas API)
 *   host.js          tách "CẦN GÌ"     khỏi "LẤY Ở ĐÂU"    (nền tảng)
 *
 * canvas_renderer.js hiện gọi thẳng require('canvas'), fs, https, path — nên
 * chỉ chạy được trong Node. Mà nó phải chạy được ở BA chỗ:
 *   • Node      — render video (desktop)
 *   • trình duyệt — xem trước trực tiếp, THAY renderer thứ hai đang lệch
 *                  (engines/web/preview_renderer.js không truyền ui/mnk nên
 *                   template premium xem trước ra màn hình TRỐNG)
 *   • QuickJS   — render trên điện thoại (mobile)
 *
 * Ba nơi đó khác nhau ở đúng những thứ dưới đây, KHÔNG khác ở code vẽ.
 * Xem docs/display-list.md và t2mobile/docs/02-kien-truc.md.
 *
 * ⚠️ Đừng thêm gì vào đây trừ khi nó THẬT SỰ khác nhau giữa ba nền tảng. Host
 * càng mỏng thì càng dễ cắm nền tảng mới.
 */

'use strict';

/**
 * @typedef {object} Host
 * @property {boolean}  isNode
 * @property {Function} createCanvas   (w, h) -> Canvas (có .getContext('2d'))
 * @property {Function} loadImage      (src) -> Promise<Image>
 * @property {Function} registerFont   (file, family, weight) -> void
 * @property {Function} readText       (file) -> string | null
 * @property {Function} readDir        (dir) -> string[]
 * @property {Function} exists         (file) -> boolean
 * @property {Function} writeBinary    (file, buf) -> void
 * @property {Function} mkdirp         (dir) -> void
 * @property {Function} fetchBinary    (url) -> Promise<Buffer|Uint8Array>
 * @property {Function} joinPath       (...parts) -> string
 * @property {Function} warn           (msg) -> void
 * @property {Function} env            (name) -> string | undefined
 */

/** Host cho Node — dùng node-canvas. */
function nodeHost(deps) {
    const { createCanvas, loadImage, registerFont } = deps.canvas;
    const fs = deps.fs, path = deps.path, https = deps.https;

    return {
        isNode: true,

        createCanvas,
        loadImage,

        /**
         * Ảnh từ BYTES (không qua đĩa) — BẮT BUỘC có.
         *
         * Bẫy đã cắn: emoji được tải về rồi ghi ra đĩa, rồi nạp lại BẰNG ĐƯỜNG
         * DẪN FILE. Trên trình duyệt writeBinary là no-op và không có hệ thống
         * file → nạp đường dẫn đó luôn hỏng → xem trước web KHÔNG BAO GIỜ có
         * emoji màu, mà lại hỏng im lặng (try/catch → trả null → tụt xuống vẽ
         * emoji bằng font).
         * Đi thẳng từ bytes: Node lẫn trình duyệt lẫn QuickJS đều làm được.
         */
        loadImageBytes(buf) {
            return loadImage(buf);          // node-canvas nhận thẳng Buffer
        },

        registerFont(file, family, weight) {
            if (!registerFont) return;
            const o = { family: family };
            if (weight) o.weight = weight;
            registerFont(file, o);
        },

        readText(file) {
            try { return fs.readFileSync(file, 'utf8'); } catch (e) { return null; }
        },
        readDir(dir) {
            try { return fs.readdirSync(dir); } catch (e) { return []; }
        },
        exists(file) {
            try { return fs.existsSync(file); } catch (e) { return false; }
        },
        writeBinary(file, buf) {
            try { fs.writeFileSync(file, buf); } catch (e) { /* cache lỗi = bỏ qua */ }
        },
        mkdirp(dir) {
            try { fs.mkdirSync(dir, { recursive: true }); } catch (e) { }
        },

        /**
         * Tải nhị phân (emoji Twemoji). Trình duyệt/QuickJS cắm fetch() của chúng.
         *
         * TIMEOUT 8s là BẮT BUỘC, không phải cho đẹp: một socket chết của CDN sẽ
         * treo cả lượt render. Preview chỉ có ngân sách 90 giây — một emoji tải
         * treo là ăn sạch. Mọi host khác cũng PHẢI có giới hạn thời gian.
         */
        fetchBinary(url, timeoutMs) {
            const LIMIT = timeoutMs || 8000;
            return new Promise((resolve, reject) => {
                const req = https.get(url, (res) => {
                    if (res.statusCode !== 200) {
                        res.resume();
                        return reject(new Error('HTTP ' + res.statusCode));
                    }
                    const parts = [];
                    res.on('data', (d) => parts.push(d));
                    res.on('end', () => resolve(Buffer.concat(parts)));
                    res.on('error', reject);
                });
                req.on('error', reject);
                req.setTimeout(LIMIT, function () {
                    this.destroy(new Error('fetchBinary timeout sau ' + LIMIT + 'ms: ' + url));
                });
            });
        },

        joinPath() { return path.join.apply(path, arguments); },
        warn(msg) { try { process.stderr.write(String(msg) + '\n'); } catch (e) { } },
        env(name) { return process.env[name]; },
    };
}

module.exports = { nodeHost };
