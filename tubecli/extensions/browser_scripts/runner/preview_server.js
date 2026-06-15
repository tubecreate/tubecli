#!/usr/bin/env node
/**
 * preview_server.js — Browser preview + element picker for Script Studio.
 * Launches a visible browser and provides WebSocket API for element picking.
 * 
 * Usage: node preview_server.js --profile <name> --url <url> --port <port>
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const { chromium } = require('playwright');
const minimist = require('minimist');

const args = minimist(process.argv.slice(2));
const profileName = args.profile || 'default';
const startUrl = args.url || 'about:blank';
const port = parseInt(args.port) || 9222;
const profilesDir = args['profiles-dir'] || '';

function log(msg) { console.log(JSON.stringify({ type: 'log', message: msg, time: new Date().toISOString() })); }

// Simple WebSocket implementation using raw HTTP upgrade
const clients = new Set();

function broadcast(data) {
    const msg = JSON.stringify(data);
    for (const ws of clients) {
        try { ws.write(encodeWSFrame(msg)); } catch (e) { clients.delete(ws); }
    }
}

function encodeWSFrame(data) {
    const buf = Buffer.from(data, 'utf-8');
    const frame = [];
    frame.push(0x81); // text frame, FIN
    if (buf.length < 126) { frame.push(buf.length); }
    else if (buf.length < 65536) { frame.push(126, (buf.length >> 8) & 0xFF, buf.length & 0xFF); }
    else {
        frame.push(127);
        for (let i = 7; i >= 0; i--) frame.push((buf.length >> (i * 8)) & 0xFF);
    }
    return Buffer.concat([Buffer.from(frame), buf]);
}

(async () => {
    // Resolve profile — use profilesDir from backend (DATA_DIR/browser_profiles)
    let storageDir = '';
    let rawProxy = null;
    let pwProxy = undefined;
    let normalizedProxy = null;

    if (profilesDir && profileName) {
        const profileDir = path.join(profilesDir, profileName);
        if (fs.existsSync(profileDir)) {
            storageDir = profileDir;
            // Load proxy from config
            try {
                const configPath = path.join(storageDir, 'config.json');
                if (fs.existsSync(configPath)) {
                    const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
                    if (cfg.proxy) {
                        rawProxy = cfg.proxy;
                        log(`Loaded proxy from config: ${rawProxy}`);
                        
                        const simpleFormatRegex = /^(socks5|http|https):\/\/([^:@]+):([^:@]+):([^:@]+):(\d+)$/i;
                        const match = rawProxy.match(simpleFormatRegex);
                        if (match) {
                            normalizedProxy = `${match[1].toLowerCase()}://${match[2]}:${match[3]}@${match[4]}:${match[5]}`;
                        } else {
                            normalizedProxy = rawProxy;
                        }

                        try {
                            const parsed = new URL(normalizedProxy.includes('://') ? normalizedProxy : `http://${normalizedProxy}`);
                            pwProxy = { server: `${parsed.protocol}//${parsed.hostname}:${parsed.port}` };
                            if (parsed.username) pwProxy.username = decodeURIComponent(parsed.username);
                            if (parsed.password) pwProxy.password = decodeURIComponent(parsed.password);
                        } catch (e) {
                            pwProxy = { server: normalizedProxy.includes('://') ? normalizedProxy : `http://${normalizedProxy}` };
                        }
                    }
                }
            } catch (e) {
                log(`⚠️ Failed to parse proxy from config: ${e.message}`);
            }
        }
    }

    // Cleanup stale locks
    if (storageDir && fs.existsSync(storageDir)) {
        for (const lf of ['SingletonLock', 'SingletonSocket', 'SingletonCookie']) {
            try {
                const p = path.join(storageDir, lf);
                if (fs.existsSync(p)) fs.unlinkSync(p);
            } catch (e) {}
        }
    }

    log('Launching preview browser...');
    let context;
    if (storageDir) {
        const ctxOpts = {
            channel: 'chrome', headless: false,
            args: ['--no-sandbox', '--disable-blink-features=AutomationControlled', '--window-size=1280,900'],
            ignoreDefaultArgs: ['--enable-automation'],
            viewport: { width: 1280, height: 800 },
        };
        if (pwProxy) ctxOpts.proxy = pwProxy;
        context = await chromium.launchPersistentContext(storageDir, ctxOpts);
    } else {
        const brOpts = { channel: 'chrome', headless: false };
        if (pwProxy) brOpts.proxy = pwProxy;
        const browser = await chromium.launch(brOpts);
        context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    }

    const page = context.pages()[0] || await context.newPage();
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

    // HTTP + WS server
    const server = http.createServer((req, res) => {
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        if (req.method === 'OPTIONS') { res.writeHead(200); res.end(); return; }

        if (req.url === '/status') {
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ status: 'running', profile: profileName }));
        } else if (req.url === '/screenshot') {
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
                                    const cls = el.className.trim().split(/\\s+/).filter(c => !c.startsWith('sc-')).slice(0, 2);
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
        } else {
            res.writeHead(404);
            res.end('Not found');
        }
    });

    server.listen(port, () => {
        log(`Preview server listening on port ${port}`);
        console.log(JSON.stringify({ type: 'ready', port }));
    });

    // Handle browser close
    context.on('close', () => {
        log('Browser closed');
        server.close();
        process.exit(0);
    });
})();
