#!/usr/bin/env node
/**
 * preview_server.cjs — Browser preview + element picker for Browser Extension.
 * Launches a visible browser and provides WebSocket API for element picking and canvas interaction.
 * 
 * Usage: node preview_server.cjs --profile <name> --url <url> --port <port> --profiles-dir <dir>
 */

const fs = require('fs');
const path = require('path');
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
                await page.evaluate(({ deltaX, deltaY }) => {
                    window.scrollBy(deltaX, deltaY);
                }, { deltaX, deltaY });
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
                ws.send(JSON.stringify({ type: 'selection', text }));
            }
            else if (msg.type === 'navigate') {
                const { url } = msg;
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
            } 
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
            const base64 = buffer.toString('base64');
            const viewport = page.viewportSize() || { width: 1280, height: 800 };
            broadcast({
                type: 'frame',
                data: base64,
                viewport: { width: viewport.width, height: viewport.height }
            });
        } catch (e) {}
    }

    function startStreaming() {
        if (isStreaming) return;
        isStreaming = true;
        let capturing = false;
        streamInterval = setInterval(async () => {
            if (capturing || clients.size === 0 || !page) return;
            capturing = true;
            try {
                const buffer = await page.screenshot({ type: 'jpeg', quality: 50, caret: 'initial' });
                const base64 = buffer.toString('base64');
                const viewport = page.viewportSize() || { width: 1280, height: 800 };
                broadcast({
                    type: 'frame',
                    data: base64,
                    viewport: { width: viewport.width, height: viewport.height }
                });
            } catch (e) {
            } finally {
                capturing = false;
            }
        }, 200); // 5 FPS
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
            res.end(JSON.stringify({ status: isBrowserReady ? 'running' : 'initializing', profile: profileName }));
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
                context = await browserManager.launch(profileName, {
                    headless: true,
                    fingerprint,
                    args: launchArgs
                });
                success = true;
                log(`Launch successful on attempt ${attempt}`);
            } catch (e) {
                lastError = e;
                log(`Launch attempt ${attempt} failed: ${e.message}`);
                
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

    page = context.pages()[0] || await context.newPage();
    
    // Listen for file selection dialogs requested by pages
    page.on('filechooser', async (fileChooser) => {
        log('File chooser dialog requested by the page.');
        activeFileChooser = fileChooser;
        broadcast({ type: 'file_chooser_open', multiple: fileChooser.isMultiple() });
    });

    try {
        await page.setViewportSize({ width: 1280, height: 800 });
    } catch (e) {
        log(`Warning: Failed to set viewport size: ${e.message}`);
    }

    if (startUrl !== 'about:blank') {
        await page.goto(startUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
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

    // Bind navigation events
    page.on('framenavigated', async () => {
        broadcast({ type: 'url_changed', url: page.url() });
        await triggerImmediateFrame();
    });
    page.on('load', async () => {
        broadcast({ type: 'url_changed', url: page.url() });
        await triggerImmediateFrame();
    });

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
