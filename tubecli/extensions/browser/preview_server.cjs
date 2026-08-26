#!/usr/bin/env node
/**
 * preview_server.cjs — Browser preview + element picker for Browser Extension.
 * Launches a visible browser and provides WebSocket API for element picking and canvas interaction.
 * 
 * Usage: node preview_server.cjs --profile <name> --url <url> --port <port> --profiles-dir <dir>
 */

const ASSET_HASH = "250ef35b8f5ff703706a2a787ecf6d55"; // build asset hash

const fs = require('fs');
const path = require('path');
const net = require('net');
const http = require('http');
const minimist = require('minimist');
// Optional. playwright-with-fingerprints is the BAS binding, and BAS ships Windows
// binaries only — its npm package declares os=win32 and is not installed on Linux
// or macOS. Requiring it at the top made this file impossible to load there, so
// the preview server exited before it could listen and the viewer waited forever.
// ShardX does its own fingerprinting through --fingerprint-profile and needs none
// of this.
let plugin = null;
try {
    ({ plugin } = require('playwright-with-fingerprints'));
} catch (e) {
    console.log('[Preview] BAS fingerprint plugin unavailable on this platform; using ShardX only.');
}
const crypto = require('crypto');
const { Server: WebSocketServer } = require('ws');

const args = minimist(process.argv.slice(2));
const profileName = args.profile || 'default';
const startUrl = args.url || 'about:blank';
const port = parseInt(args.port) || 9222;
const profilesDir = args['profiles-dir'] || '';

function log(msg) {
    console.log(JSON.stringify({ type: 'log', message: msg, time: new Date().toISOString() }));
    if (typeof broadcast === 'function') {
        broadcast({ type: 'status_log', message: msg });
    }
}

const clients = new Set();
const wss = new WebSocketServer({ noServer: true });

function broadcast(data) {
    const msg = JSON.stringify(data);
    for (const ws of clients) {
        try {
            if (ws.readyState === 1) { // 1 means OPEN
                ws.send(msg);
            }
        } catch (e) {
            clients.delete(ws);
        }
    }
}

// Frames go out as raw bytes, not as base64 inside JSON.
//
// Base64 costs 33% on every byte, and on the receiving side each frame became a
// `data:` URI — a fresh image resource per frame, 5 times a second. Measured on
// a live session: 177 frames, 19.2 MB, about 108 KB per frame.
//
// The dropped-frame rule is the part that matters when things get slow.
// bufferedAmount is what the socket has accepted but not yet put on the wire; if
// that is climbing, the viewer is already behind and adding another frame only
// makes the backlog longer and the picture older. A live view wants the NEWEST
// frame, never a queue of stale ones — so when the buffer is over a frame or two
// deep, this one is skipped entirely.
const MAX_BUFFERED_BYTES = 512 * 1024;

function broadcastFrame(buffer) {
    let sent = 0, skipped = 0;
    for (const ws of clients) {
        try {
            if (ws.readyState !== 1) continue;
            if (ws.bufferedAmount > MAX_BUFFERED_BYTES) { skipped++; continue; }
            ws.send(buffer, { binary: true });
            sent++;
        } catch (e) {
            clients.delete(ws);
        }
    }
    return { sent, skipped };
}

(async () => {
    // Dynamic import BrowserManager (it's ESM)
    const { BrowserManager } = await import('./browser_manager.js');

    let context = null;
    let page = null;
    let isBrowserReady = false;
    let activeFileChooser = null;

    // Resolve profile — use profilesDir from backend (DATA_DIR/browser_profiles)
    let storageDir = '';
    if (profilesDir && profileName) {
        const profileDir = path.join(profilesDir, profileName);
        if (fs.existsSync(profileDir)) {
            storageDir = profileDir;
        }
    }

    // Cleanup stale locks
    if (storageDir && fs.existsSync(storageDir)) {
        for (const lf of ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'LOCK']) {
            try {
                const p = path.join(storageDir, lf);
                if (fs.existsSync(p)) fs.unlinkSync(p);
            } catch (e) {}
        }
    }

    // Cleanup stale temp uploads
    const tempDir = path.join(__dirname, 'data', 'temp_uploads');
    if (fs.existsSync(tempDir)) {
        try {
            fs.rmSync(tempDir, { recursive: true, force: true });
        } catch (e) {}
    }

    // ── Cổng CDP của phiên live view ────────────────────────────────────────
    // Playwright điều khiển Chromium qua pipe, nên nếu không ép cổng thì KHÔNG có
    // CDP nào để script attach vào, và <profile>/DevToolsActivePort chỉ còn là rác
    // của phiên cũ (đúng cái bẫy làm nút ▶ chạy script báo ECONNREFUSED).
    const cdpFile = storageDir ? path.join(storageDir, 'preview_cdp.json') : '';
    let cdpPort = 0;
    // Dấu vết CỔNG của phiên trước phải chết cùng phiên đó. /preview/stop trên
    // Windows là taskkill /F: handler thoát không chạy, nên preview_cdp.json (và
    // DevToolsActivePort) ở lại, trỏ vào một cổng không còn của ai. Cổng ephemeral
    // thì hệ điều hành cấp lại cho tiến trình sau, nên lần attach sau nối vào
    // browser CỦA PROFILE KHÁC. Khung này đang mở lại chính profile này, nên mọi
    // file cổng còn sót ở đây là rác.
    if (storageDir) {
        for (const stale of ['preview_cdp.json', 'DevToolsActivePort']) {
            try {
                const p = path.join(storageDir, stale);
                if (fs.existsSync(p)) fs.unlinkSync(p);
            } catch (e) {}
        }
    }
    // Cổng Chromium THỰC SỰ mở, do chính nó ghi ra. Ép --remote-debugging-port=N
    // chỉ là phỏng đoán: N lấy được lúc thăm dò rồi nhả ra ngay, tới lúc launch có
    // thể đã bị tiến trình khác chiếm (hay gặp nhất: preview của profile khác khởi
    // động cùng lúc). Khi đó /json/version vẫn trả 200 — của browser NGƯỜI KHÁC —
    // và ta công bố cổng của họ dưới tên profile này. File này (bản cũ đã xoá ở
    // trên) là lời của chính Chromium vừa mở, nên nó là trọng tài.
    const boundCdpPort = () => {
        if (!storageDir) return 0;
        try {
            const raw = fs.readFileSync(path.join(storageDir, 'DevToolsActivePort'), 'utf-8');
            return parseInt(String(raw).split('\n')[0].trim(), 10) || 0;
        } catch (e) { return 0; }
    };
    const freePort = () => new Promise((resolve, reject) => {
        const srv = net.createServer();
        srv.once('error', reject);
        srv.listen(0, '127.0.0.1', () => {
            const p = srv.address().port;
            srv.close(() => resolve(p));
        });
    });
    const cdpAlive = (port) => new Promise((resolve) => {
        const req = http.get({ host: '127.0.0.1', port, path: '/json/version', timeout: 1500 },
            (res) => { res.resume(); resolve(res.statusCode === 200); });
        req.on('error', () => resolve(false));
        req.on('timeout', () => { req.destroy(); resolve(false); });
    });
    const publishCdp = async () => {
        if (!cdpFile || !cdpPort) return;
        for (let i = 0; i < 20; i++) {                 // Chromium mở cổng sau khi khởi động
            const bound = boundCdpPort();
            if (bound && bound !== cdpPort) {
                log(`Cảnh báo: Chromium mở CDP ở cổng ${bound} chứ không phải ${cdpPort} — KHÔNG công bố (cổng kia có thể là của profile khác).`);
                return;
            }
            if (await cdpAlive(cdpPort)) {
                try {
                    fs.writeFileSync(cdpFile, JSON.stringify({
                        cdp_port: cdpPort, preview_port: port, pid: process.pid,
                        profile: profileName, started_at: new Date().toISOString(),
                    }), 'utf-8');
                    log(`CDP sẵn sàng ở cổng ${cdpPort} (đã ghi preview_cdp.json)`);
                } catch (e) { log('Không ghi được preview_cdp.json: ' + e.message); }
                return;
            }
            await new Promise((r) => setTimeout(r, 250));
        }
        log(`Cảnh báo: cổng CDP ${cdpPort} không phản hồi — script sẽ không attach được.`);
    };
    const unpublishCdp = () => {
        // File còn lại sau khi phiên chết = lần attach sau nối vào cổng ma. Xoá ngay.
        try { if (cdpFile && fs.existsSync(cdpFile)) fs.unlinkSync(cdpFile); } catch (e) {}
    };
    // 'exit' chỉ dọn file. Còn SIGINT/SIGTERM: hễ đăng ký listener là Node BỎ hành
    // vi mặc định "nhận tín hiệu thì thoát", nên nếu chỉ dọn file thì tiến trình
    // sống tiếp. Trên Linux/macOS mọi đường dừng preview đều là proc.terminate()
    // (SIGTERM) — /preview/stop, /stop, dọn khi khởi động quá hạn — nên khung đóng
    // xong mà node và Chromium của nó vẫn giữ user-data-dir của profile, lần mở sau
    // chết vì SingletonLock. Windows không lộ ra vì taskkill /F không gửi tín hiệu.
    process.on('exit', unpublishCdp);
    process.once('SIGINT', () => { unpublishCdp(); process.exit(130); });
    process.once('SIGTERM', () => { unpublishCdp(); process.exit(143); });

    log('Launching preview browser using BrowserManager...');
    if (plugin) plugin.setWorkingFolder(path.join(__dirname, 'data'));
    const browserManager = new BrowserManager({ baseDir: profilesDir });

    async function getElementInfo(x, y) {
        if (!page) return null;
        try {
            const info = await page.evaluate(({x, y}) => {
                const el = document.elementFromPoint(x, y);
                if (!el) return null;
                // Generate CSS selector
                function getSelector(el) {
                    if (el.id) return '#' + el.id;
                    let path = '';
                    while (el && el.nodeType === 1) {
                        let sel = el.tagName.toLowerCase();
                        if (el.id) { path = '#' + el.id + (path ? ' > ' + path : ''); break; }
                        if (el.className && typeof el.className === 'string') {
                            const cls = el.className.trim().split(/\s+/).filter(c => !c.startsWith('sc-')).slice(0, 2);
                            if (cls.length) sel += '.' + cls.join('.');
                        }
                        const parent = el.parentElement;
                        if (parent) {
                            const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
                            if (siblings.length > 1) sel += ':nth-child(' + (Array.from(parent.children).indexOf(el) + 1) + ')';
                        }
                        path = sel + (path ? ' > ' + path : '');
                        el = parent;
                    }
                    return path;
                }
                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    classes: el.className || '',
                    text: (el.innerText || '').slice(0, 100),
                    selector: getSelector(el),
                    attributes: Object.fromEntries(
                        Array.from(el.attributes).map(a => [a.name, a.value.slice(0, 200)])
                    ),
                    rect: el.getBoundingClientRect().toJSON(),
                };
            }, { x, y });
            return info;
        } catch (e) {
            return null;
        }
    }

    async function handleWSMessage(msg) {
        if (!msg || !msg.type || !page) return;
        try {
            if (msg.type === 'mouse') {
                const { action, x, y } = msg;
                if (action === 'click') {
                    await page.mouse.click(x, y);
                } else if (action === 'dblclick') {
                    await page.mouse.click(x, y, { clickCount: 2 });
                } else if (action === 'move') {
                    await page.mouse.move(x, y);
                } else if (action === 'down') {
                    await page.mouse.down();
                } else if (action === 'up') {
                    await page.mouse.up();
                }
                await triggerImmediateFrame();
            } 
            else if (msg.type === 'scroll') {
                const { deltaX, deltaY } = msg;
                // page.mouse.wheel gửi wheel event thật tại vị trí con trỏ →
                // cuộn được cả container bên trong (window.scrollBy chỉ cuộn document gốc)
                await page.mouse.wheel(deltaX, deltaY).catch(async () => {
                    await page.evaluate(({ deltaX, deltaY }) => window.scrollBy(deltaX, deltaY), { deltaX, deltaY });
                });
                await triggerImmediateFrame();
            } 
            else if (msg.type === 'keyboard') {
                const { action, text, key } = msg;
                if (action === 'type') {
                    await page.keyboard.type(text);
                } else if (action === 'insert') {
                    // Paste. insertText delivers the whole string in one input
                    // event instead of synthesising a keystroke per character —
                    // faster for a long paste, and it does not trip the input
                    // debouncing some sites apply to rapid keydowns.
                    await page.keyboard.insertText(text || '');
                } else if (action === 'press') {
                    await page.keyboard.press(key);
                }
                await triggerImmediateFrame();
            }
            else if (msg.type === 'get_selection') {
                // Answering a copy from the remote page. Read it after the
                // mouse is released and hold it client-side, because a copy
                // event has to produce its data synchronously.
                const text = await page.evaluate(
                    () => (window.getSelection() || '').toString()
                ).catch(() => '');
                // broadcast, not ws.send: handleWSMessage receives only the
                // message — there is no socket in scope here, which is why this
                // logged "ws is not defined" on every mouse release.
                broadcast({ type: 'selection', text });
            }
            else if (msg.type === 'navigate') {
                const { url } = msg;
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
            } 
            else if (msg.type === 'new_tab') {
                const np = await context.newPage();
                attachPageListeners(np);
                if (msg.url) { try { await np.goto(msg.url, { waitUntil: 'domcontentloaded', timeout: 30000 }); } catch (e) {} }
                await switchToPage(np);
            }
            else if (msg.type === 'switch_tab') {
                const ps = context.pages(); if (ps[msg.index]) await switchToPage(ps[msg.index]);
            }
            else if (msg.type === 'close_tab') {
                const ps = context.pages();
                if (ps[msg.index]) {
                    const wasActive = ps[msg.index] === page;
                    try { await ps[msg.index].close(); } catch (e) {}
                    const rem = context.pages();
                    if (rem.length === 0) return;
                    if (wasActive) await switchToPage(rem[Math.min(msg.index, rem.length - 1)]); else await broadcastTabs();
                }
            }
            else if (msg.type === 'get_tabs') { await broadcastTabs(); }
            else if (msg.type === 'nav') {
                const { action } = msg;
                if (action === 'back') await page.goBack().catch(()=>{});
                else if (action === 'forward') await page.goForward().catch(()=>{});
                else if (action === 'reload') await page.reload().catch(()=>{});
            } 
            else if (msg.type === 'hover_inspect') {
                const { x, y } = msg;
                const info = await getElementInfo(x, y);
                if (info) {
                    broadcast({ type: 'inspect', ...info });
                }
            } 
            else if (msg.type === 'pick_element') {
                const { x, y } = msg;
                const info = await getElementInfo(x, y);
                if (info) {
                    broadcast({ type: 'picked', selector: info.selector });
                }
            }
            else if (msg.type === 'file_cancel') {
                activeFileChooser = null;
            }
        } catch (e) {
            log(`Error executing message action ${msg.type}: ${e.message}`);
        }
    }

    let isStreaming = false;
    let streamInterval = null;

    async function triggerImmediateFrame() {
        if (clients.size === 0 || !page) return;
        try {
            const buffer = await page.screenshot({ type: 'jpeg', quality: 50, caret: 'initial' });
            // Same binary channel as the stream — the two must not disagree
            // about the wire format, or a click would send a frame the client
            // cannot read. This one is never skipped: it exists precisely to
            // show the result of something the user just did.
            const vp = page.viewportSize() || { width: 1280, height: 800 };
            broadcast({ type: 'viewport', viewport: vp });
            broadcastFrame(buffer);
        } catch (e) {}
    }

    function startStreaming() {
        if (isStreaming) return;
        isStreaming = true;
        let capturing = false;
        let lastHash = '';
        let lastViewport = '';
        let idleTicks = 0;

        streamInterval = setInterval(async () => {
            if (capturing || clients.size === 0 || !page) return;
            capturing = true;
            try {
                const buffer = await page.screenshot({ type: 'jpeg', quality: 50, caret: 'initial' });

                // Skip frames identical to the one already on screen. A page
                // sitting still used to cost five full JPEGs a second for a
                // picture that never changed — most of the traffic on a normal
                // session, since most of a session IS the page sitting still.
                // md5 over ~60 KB is far cheaper than sending it.
                const hash = crypto.createHash('md5').update(buffer).digest('hex');
                if (hash === lastHash) {
                    idleTicks++;
                    return;   // finally{} still clears `capturing`
                }
                lastHash = hash;
                idleTicks = 0;

                // Viewport travels only when it changes, on the JSON channel.
                const vp = page.viewportSize() || { width: 1280, height: 800 };
                const vpKey = `${vp.width}x${vp.height}`;
                if (vpKey !== lastViewport) {
                    lastViewport = vpKey;
                    broadcast({ type: 'viewport', viewport: vp });
                }

                broadcastFrame(buffer);
            } catch (e) {
            } finally {
                capturing = false;
            }
        }, 200); // 5 FPS ceiling; an unchanged page sends nothing at all
    }

    function stopStreaming() {
        isStreaming = false;
        if (streamInterval) {
            clearInterval(streamInterval);
            streamInterval = null;
        }
    }

    // HTTP + WS server
    const server = http.createServer((req, res) => {
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        if (req.method === 'OPTIONS') { res.writeHead(200); res.end(); return; }

        if (req.url === '/status') {
            res.writeHead(200, { 'Content-Type': 'application/json' });
            // active_tab: tab ĐANG ĐƯỢC STREAM. Script attach mặc định chạy trên tab
            // "đang hoạt động" của CDP — thường KHÔNG phải tab người dùng đang nhìn,
            // nên nó chạy ở nơi không ai thấy. Ai muốn "trực quan" thì hỏi chỗ này.
            // KHÔNG kèm cổng CDP ở đây: endpoint này trả Access-Control-Allow-Origin:*
            // và không ai cần cổng đó qua HTTP (script_runner đọc preview_cdp.json,
            // phía nhóm hỏi routes.py) — phát ra chỉ là chỉ đường tới cả cái browser.
            let activeTab = -1;
            try { activeTab = context ? context.pages().indexOf(page) : -1; } catch (e) {}
            let activeUrl = '';
            try { activeUrl = page ? page.url() : ''; } catch (e) {}
            res.end(JSON.stringify({ status: isBrowserReady ? 'running' : 'initializing',
                profile: profileName, active_tab: activeTab, active_url: activeUrl }));
            return;
        }

        // For other endpoints, require browser ready
        if (!isBrowserReady || !page) {
            res.writeHead(503, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Browser is still initializing' }));
            return;
        }

        if (req.url === '/screenshot') {
            page.screenshot({ type: 'jpeg', quality: 60 }).then(buf => {
                res.writeHead(200, { 'Content-Type': 'image/jpeg' });
                res.end(buf);
            }).catch(() => { res.writeHead(500); res.end(); });
        } else if (req.url === '/pick/start') {
            page.evaluate(() => window.__scriptStudio.startPicker()).then(() => {
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'picker_started' }));
            });
        } else if (req.url === '/pick/stop') {
            page.evaluate(() => window.__scriptStudio.stopPicker()).then(() => {
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'picker_stopped' }));
            });
        } else if (req.url === '/element' && req.method === 'POST') {
            let body = '';
            req.on('data', chunk => body += chunk);
            req.on('end', async () => {
                try {
                    const { x, y } = JSON.parse(body);
                    const info = await getElementInfo(x, y);
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ element: info }));
                } catch (e) {
                    res.writeHead(500, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: e.message }));
                }
            });
        } else if (req.url === '/navigate' && req.method === 'POST') {
            let body = '';
            req.on('data', chunk => body += chunk);
            req.on('end', async () => {
                try {
                    const { url } = JSON.parse(body);
                    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ status: 'navigated', url: await page.url() }));
                } catch (e) {
                    res.writeHead(500, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: e.message }));
                }
            });
        } else if ((req.url === '/click' || req.url === '/type' || req.url === '/scroll') && req.method === 'POST') {
            // HTTP control cho workspace sharee (không dùng WebSocket). Nhận toạ độ chuẩn
            // hoá pctX/pctY 0..1 rồi nhân viewport server-side → khỏi phụ thuộc client biết
            // kích thước trang. Mirror logic của handleWSMessage (mouse/keyboard/scroll).
            let body = '';
            req.on('data', chunk => body += chunk);
            req.on('end', async () => {
                try {
                    const b = JSON.parse(body || '{}');
                    if (req.url === '/click') {
                        const vp = (page.viewportSize && page.viewportSize()) || { width: 1280, height: 720 };
                        const x = b.x != null ? b.x : (b.pctX || 0) * vp.width;
                        const y = b.y != null ? b.y : (b.pctY || 0) * vp.height;
                        if (b.dblclick) await page.mouse.click(x, y, { clickCount: 2 });
                        else await page.mouse.click(x, y);
                    } else if (req.url === '/type') {
                        if (b.key) await page.keyboard.press(b.key);
                        else await page.keyboard.type(String(b.text || ''));
                    } else { // /scroll
                        const dx = b.deltaX || 0, dy = b.deltaY || 0;
                        // Đưa con trỏ tới đúng vị trí sharee đang trỏ (pctX/pctY) trước khi cuộn,
                        // để cuộn đúng phần tử dưới chuột (không cuộn ở vị trí cũ).
                        if (b.pctX != null || b.pctY != null) {
                            const vp = (page.viewportSize && page.viewportSize()) || { width: 1280, height: 720 };
                            try { await page.mouse.move((b.pctX || 0) * vp.width, (b.pctY || 0) * vp.height); } catch (e) {}
                        }
                        await page.mouse.wheel(dx, dy).catch(async () => {
                            await page.evaluate(({ dx, dy }) => window.scrollBy(dx, dy), { dx, dy });
                        });
                    }
                    await triggerImmediateFrame().catch(() => {});
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ status: 'ok' }));
                } catch (e) {
                    res.writeHead(500, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: e.message }));
                }
            });
        } else if ((req.url === '/back' || req.url === '/forward' || req.url === '/reload') && req.method === 'POST') {
            (async () => {
                try {
                    if (req.url === '/back') await page.goBack().catch(() => {});
                    else if (req.url === '/forward') await page.goForward().catch(() => {});
                    else await page.reload().catch(() => {});
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ status: 'ok', url: await page.url() }));
                } catch (e) {
                    res.writeHead(500, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: e.message }));
                }
            })();
        } else if (req.url === '/set-input-files' && req.method === 'POST') {
            // Gắn file vào ô <input type=file> mà KHÔNG cần filechooser.
            // /upload-files chỉ chạy khi Playwright vừa bắn sự kiện 'filechooser', tức là
            // khi CÓ NGƯỜI bấm nút tải lên trên trang. Một agent chạy một mình không có
            // ai bấm hộ, nên nó cần đường này: setInputFiles thao tác thẳng lên input.
            let body = '';
            req.on('data', chunk => body += chunk);
            req.on('end', async () => {
                try {
                    const { filePaths, selector } = JSON.parse(body || '{}');
                    if (!filePaths || !filePaths.length) {
                        res.writeHead(400, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ error: 'no files' }));
                        return;
                    }
                    const sel = (typeof selector === 'string' && selector.trim()) || 'input[type=file]';
                    // Ô upload hay nằm trong iframe (trình tải video, khung nhúng) và
                    // thường bị ẩn sau nút giả, nên duyệt mọi frame và KHÔNG đòi visible.
                    let done = null;
                    for (const fr of page.frames()) {
                        const h = await fr.$(sel).catch(() => null);
                        if (!h) continue;
                        await h.setInputFiles(filePaths);
                        done = { frame: fr.url() || 'main', count: filePaths.length };
                        break;
                    }
                    if (!done) {
                        res.writeHead(404, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ error: `no element matching ${sel} on this page` }));
                        return;
                    }
                    log(`setInputFiles: ${filePaths.length} file(s) -> ${sel}`);
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ status: 'attached', ...done }));
                } catch (e) {
                    res.writeHead(500, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: e.message }));
                }
            });
        } else if (req.url === '/upload-files' && req.method === 'POST') {
            let body = '';
            req.on('data', chunk => body += chunk);
            req.on('end', async () => {
                try {
                    const { filePaths } = JSON.parse(body);
                    if (activeFileChooser && filePaths && filePaths.length > 0) {
                        await activeFileChooser.setFiles(filePaths);
                        log(`Successfully uploaded ${filePaths.length} file(s).`);
                        activeFileChooser = null;
                        res.writeHead(200, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ status: 'uploaded', count: filePaths.length }));
                    } else {
                        log('Warning: File chooser was not active or no files selected.');
                        res.writeHead(400, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ error: 'File chooser not active or no files' }));
                    }
                } catch (e) {
                    res.writeHead(500, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: e.message }));
                }
            });
        } else {
            res.writeHead(404);
            res.end('Not found');
        }
    });

    // Handle WebSocket upgrade
    server.on('upgrade', (req, socket, head) => {
        if (req.headers['upgrade'] && req.headers['upgrade'].toLowerCase() === 'websocket') {
            wss.handleUpgrade(req, socket, head, (ws) => {
                wss.emit('connection', ws, req);
            });
        }
    });

    wss.on('connection', (ws) => {
        clients.add(ws);
        startStreaming();

        // Send initial state if ready
        if (isBrowserReady && page) {
            try {
                ws.send(JSON.stringify({ type: 'url_changed', url: page.url() }));
                ws.send(JSON.stringify({ type: 'browser_ready', url: page.url() }));
            } catch (e) {}
            triggerImmediateFrame().catch(()=>{});
        }

        ws.on('message', async (message) => {
            try {
                const msg = JSON.parse(message.toString('utf8'));
                await handleWSMessage(msg);
            } catch (e) {
                log(`Error parsing WS data: ${e.message}`);
            }
        });

        ws.on('close', () => {
            clients.delete(ws);
            if (clients.size === 0) stopStreaming();
        });

        ws.on('error', () => {
            clients.delete(ws);
            if (clients.size === 0) stopStreaming();
        });
    });

    server.listen(port, () => {
        log(`Preview server listening on port ${port}`);
        console.log(JSON.stringify({ type: 'ready', port }));
    });

    // Launch Browser background thread / async start
    if (storageDir) {
        let attempt = 1;
        const maxAttempts = 3;
        let success = false;
        let lastError = null;

        while (attempt <= maxAttempts && !success) {
            log(`Launch attempt ${attempt}/${maxAttempts}...`);
            let fingerprint = null;
            try {
                fingerprint = await browserManager.getFingerprint(profileName);
            } catch (e) {
                log(`Warning: Failed to fetch fingerprint: ${e.message}`);
            }

            const launchArgs = [
                '--no-sandbox',
                '--window-size=1280,900'
            ];

            if (fingerprint) {
                let ua = "";
                try {
                    let innerFp = fingerprint;
                    if (typeof fingerprint === 'object' && fingerprint.fingerprint) {
                        innerFp = typeof fingerprint.fingerprint === 'string' ? JSON.parse(fingerprint.fingerprint) : fingerprint.fingerprint;
                    }
                    if (typeof innerFp === 'object' && innerFp.navigator && innerFp.navigator.userAgent) {
                        ua = innerFp.navigator.userAgent.toLowerCase();
                    } else if (typeof fingerprint === 'string') {
                        ua = fingerprint.toLowerCase();
                    }
                } catch(e) {}

                if (ua.includes('android') || ua.includes('iphone') || ua.includes('ipad')) {
                    log('Mobile fingerprint detected. Setting small window size.');
                    launchArgs.push('--window-size=450,900');
                }
            }

            try {
                if (!cdpPort) {
                    try { cdpPort = await freePort(); } catch (e) { log('Không lấy được cổng CDP trống: ' + e.message); }
                }
                if (cdpPort) launchArgs.push(`--remote-debugging-port=${cdpPort}`);
                context = await browserManager.launch(profileName, {
                    headless: true,
                    fingerprint,
                    args: launchArgs
                });
                success = true;
                log(`Launch successful on attempt ${attempt}`);
                publishCdp();                       // không await: khung phải stream ngay
            } catch (e) {
                lastError = e;
                log(`Launch attempt ${attempt} failed: ${e.message}`);
                // Cổng đã ghim có thể chính là lý do hỏng: Chromium không bind được
                // thì không in dòng "DevTools listening on ...", mà Playwright chờ
                // đúng dòng đó khi args có --remote-debugging-port — launch treo tới
                // hết hạn. Giữ nguyên số cũ là ba lần thử cùng một cổng chết, và
                // khung live view không bao giờ mở. Lấy cổng khác.
                cdpPort = 0;
                
                // Clear fingerprint on fatal fingerprint error or incorrect format
                if (e.message === 'FINGERPRINT_FATAL_ERROR' || e.message.toLowerCase().includes('fingerprint') || e.message.toLowerCase().includes('incorrect format')) {
                    log(`Fingerprint error detected. Deleting saved fingerprint for profile ${profileName} and re-fetching...`);
                    try {
                        const fingerprintPath = path.join(storageDir, 'fingerprint_saved.json');
                        const legacyFingerprintPath = path.join(storageDir, 'fingerprint.json');
                        if (fs.existsSync(fingerprintPath)) {
                            fs.unlinkSync(fingerprintPath);
                        }
                        if (fs.existsSync(legacyFingerprintPath)) {
                            fs.unlinkSync(legacyFingerprintPath);
                        }
                    } catch (ex) {
                        log(`Warning: Failed to delete fingerprint file: ${ex.message}`);
                    }
                }

                // Clean locks for retry
                try {
                    for (const lf of ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'LOCK']) {
                        const p = path.join(storageDir, lf);
                        if (fs.existsSync(p)) fs.unlinkSync(p);
                    }
                } catch (ex) {}
                
                attempt++;
                if (attempt <= maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, 2000));
                }
            }
        }

        if (!success) {
            throw new Error(`Failed to launch browser after ${maxAttempts} attempts. Last error: ${lastError?.message}`);
        }
    } else if (plugin) {
        const browser = await plugin.launch({ headless: true });
        context = await browser.newContext();
    } else {
        // No profile storage and no BAS plugin (Linux/macOS). Plain Playwright
        // Chromium is enough for a scratch preview; the fingerprinted path is the
        // profile branch above, which runs on ShardX.
        const { chromium } = require('playwright');
        const args = ['--window-size=1280,900'];
        if (process.platform === 'linux') {
            args.push('--disable-dev-shm-usage');
            if (typeof process.getuid === 'function' && process.getuid() === 0) {
                args.push('--no-sandbox', '--disable-setuid-sandbox');
            }
        }
        const browser = await chromium.launch({ headless: true, args });
        context = await browser.newContext();
    }

    // ── Quản lý nhiều tab ────────────────────────────────────────────
    function attachPageListeners(p) {
        if (p.__ssBound) return; p.__ssBound = true;
        p.setViewportSize({ width: 1280, height: 800 }).catch(() => {});
        p.on('filechooser', async (fc) => { activeFileChooser = fc; broadcast({ type: 'file_chooser_open', multiple: fc.isMultiple() }); });
        p.on('framenavigated', async () => { if (p === page) { broadcast({ type: 'url_changed', url: p.url() }); await triggerImmediateFrame(); } broadcastTabs(); });
        p.on('load', async () => { if (p === page) { broadcast({ type: 'url_changed', url: p.url() }); await triggerImmediateFrame(); } broadcastTabs(); });
        p.on('close', () => { try { broadcastTabs(); } catch (e) {} });
    }
    async function broadcastTabs() {
        try {
            const ps = context.pages();
            const tabs = await Promise.all(ps.map(async (pg, i) => { let t = ''; try { t = await pg.title(); } catch (e) {} return { index: i, title: (t || pg.url() || 'Tab'), url: pg.url(), active: pg === page }; }));
            broadcast({ type: 'tabs', tabs });
        } catch (e) {}
    }
    async function switchToPage(p) {
        if (!p) return; page = p; attachPageListeners(p);
        try { await p.bringToFront(); } catch (e) {}
        broadcast({ type: 'url_changed', url: p.url() });
        await triggerImmediateFrame(); broadcastTabs();
    }

    // ── Nối vào phiên cũ thay vì chất thêm tab ───────────────────────
    // Chromium tự khôi phục các tab của phiên trước (đúng thứ người dùng muốn), NHƯNG
    // mỗi lần khởi động lại kèm một about:blank từ tham số dòng lệnh, và goto(startUrl)
    // đè lên pages()[0] biến tab trắng thành một tab mới nữa → mỗi lần mở là +1 tab,
    // vài hôm sau thành một đống (đã thấy: about:blank ×5, YouTube ×3).
    // Quy tắc: dọn hết tab trắng thừa; đã có tab đúng trang cần mở thì DÙNG LẠI nó;
    // không có gì khôi phục thì mới điều hướng tab trắng còn lại.
    {
        const all = context.pages();
        const real = all.filter((p) => p.url() !== 'about:blank');
        const blanks = all.filter((p) => p.url() === 'about:blank');
        // giữ đúng 1 tab trắng khi không còn tab thật nào — đóng sạch thì context chết
        const keep = real.length ? 0 : 1;
        for (let i = 0; i < blanks.length - keep; i++) {
            try { await blanks[i].close(); } catch (e) {}
        }
        log(`Phiên cũ: ${real.length} tab thật, dọn ${Math.max(0, blanks.length - keep)} tab trắng thừa`);
    }
    page = context.pages()[0] || await context.newPage();

    attachPageListeners(page);
    context.on('page', async (np) => {
        attachPageListeners(np);
        try { await np.waitForLoadState('domcontentloaded', { timeout: 8000 }); } catch (e) {}
        await switchToPage(np);
    });

    try {
        await page.setViewportSize({ width: 1280, height: 800 });
    } catch (e) {
        log(`Warning: Failed to set viewport size: ${e.message}`);
    }

    if (startUrl !== 'about:blank') {
        // So theo origin+path (bỏ query): trang như YouTube Studio tự đổi query liên tục,
        // so cả chuỗi URL thì không bao giờ trúng và lại mở trùng tab.
        const sameDoc = (a, b) => {
            try { const x = new URL(a), y = new URL(b); return x.origin === y.origin && x.pathname === y.pathname; } catch (e) { return false; }
        };
        const pages = context.pages();
        const hit = pages.find((p) => sameDoc(p.url(), startUrl));
        if (hit) {
            await switchToPage(hit);                    // phiên cũ đã có trang này → dùng lại
        } else {
            const blank = pages.find((p) => p.url() === 'about:blank');
            const target = blank || (pages.some((p) => p.url() !== 'about:blank') ? await context.newPage() : page);
            page = target; attachPageListeners(target);
            await target.goto(startUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
        }
    } else {
        // Không yêu cầu URL nào → về đúng tab CUỐI của phiên trước, không mở gì thêm.
        const real = context.pages().filter((p) => p.url() !== 'about:blank');
        if (real.length) await switchToPage(real[real.length - 1]);
    }
    log(`Browser ready at: ${await page.url()}`);

    // Inject element picker overlay
    const pickerScript = `
    window.__scriptStudio = window.__scriptStudio || {};
    window.__scriptStudio.pickerActive = false;
    window.__scriptStudio.startPicker = function() {
        this.pickerActive = true;
        document.body.style.cursor = 'crosshair';
        const overlay = document.createElement('div');
        overlay.id = '__ss_overlay';
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:999999;pointer-events:none;';
        document.body.appendChild(overlay);
        
        const highlight = document.createElement('div');
        highlight.id = '__ss_highlight';
        highlight.style.cssText = 'position:fixed;border:2px solid #4CAF50;background:rgba(76,175,80,0.15);z-index:999998;pointer-events:none;display:none;';
        document.body.appendChild(highlight);
        
        const info = document.createElement('div');
        info.id = '__ss_info';
        info.style.cssText = 'position:fixed;bottom:10px;left:10px;background:#1a1a2e;color:#e0e0e0;padding:8px 12px;border-radius:6px;font:12px monospace;z-index:999999;pointer-events:none;display:none;box-shadow:0 2px 8px rgba(0,0,0,0.5);';
        document.body.appendChild(info);
    };
    window.__scriptStudio.stopPicker = function() {
        this.pickerActive = false;
        document.body.style.cursor = '';
        ['__ss_overlay','__ss_highlight','__ss_info'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.remove();
        });
    };
    `;
    await page.evaluate(pickerScript);

    // Listeners điều hướng đã gắn qua attachPageListeners; phát tab ban đầu
    broadcastTabs();

    isBrowserReady = true;
    log('Browser is now ready and streaming.');
    
    // Broadcast initial state to any already-connected clients
    broadcast({ type: 'url_changed', url: page.url() });
    broadcast({ type: 'browser_ready', url: page.url() });
    triggerImmediateFrame().catch(()=>{});

    // Handle browser close
    context.on('close', () => {
        log('Browser closed');
        server.close();
        process.exit(0);
    });
})();
