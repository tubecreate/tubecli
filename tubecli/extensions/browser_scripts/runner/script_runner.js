#!/usr/bin/env node
/**
 * script_runner.js — Execute Script Studio steps using Playwright.
 * 
 * Usage: node script_runner.js --exec-file <path_to_exec.json>
 * 
 * Output: JSON lines on stdout for real-time progress.
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const args = require('minimist')(process.argv.slice(2));
const execFile = args['exec-file'];

if (!execFile || !fs.existsSync(execFile)) {
    console.log(JSON.stringify({ status: 'error', message: 'Missing --exec-file' }));
    process.exit(1);
}

const execData = JSON.parse(fs.readFileSync(execFile, 'utf-8'));
const { script, variables = {}, profile = '', headless = false, engine = 'playwright', exec_id } = execData;
const steps = script.steps || [];

function log(msg) { console.log(JSON.stringify({ status: 'log', exec_id, message: msg, time: new Date().toISOString() })); }
function stepLog(idx, type, msg) { console.log(JSON.stringify({ status: 'step', exec_id, step_index: idx, step_type: type, message: msg })); }

// Variable interpolation: replace {{var_name}} with values
function interpolate(text) {
    if (typeof text !== 'string') return text;
    return text.replace(/\{\{(\w+)\}\}/g, (_, key) => variables[key] !== undefined ? variables[key] : `{{${key}}}`);
}

const sleep = ms => {
    return new Promise((resolve, reject) => {
        const start = Date.now();
        const check = () => {
            if (stopped) return reject(new Error('Script stopped by user.'));
            if (Date.now() - start >= ms) return resolve();
            setTimeout(check, Math.min(100, ms - (Date.now() - start)));
        };
        check();
    });
};
const randBetween = (a, b) => a + Math.random() * (b - a);

// ── Pause/resume state ──
let paused = false;
let stopped = false;

function waitIfPaused() {
    return new Promise(resolve => {
        const check = () => {
            if (stopped) return resolve();
            if (!paused) return resolve();
            setTimeout(check, 500);
        };
        check();
    });
}

// ── Human-like Mouse Movement (Bezier curve) ──
let lastMouseX = 0, lastMouseY = 0;

function bezierPoint(p0, p1, p2, p3, t) {
    const u = 1 - t;
    return {
        x: u*u*u*p0.x + 3*u*u*t*p1.x + 3*u*t*t*p2.x + t*t*t*p3.x,
        y: u*u*u*p0.y + 3*u*u*t*p1.y + 3*u*t*t*p2.y + t*t*t*p3.y,
    };
}

// ── Visual Cursor Overlay (red dot + trail) ──
const CURSOR_INJECT_JS = `
(function() {
    if (document.getElementById('__tubecli_cursor')) return;
    
    // Main cursor dot
    const cursor = document.createElement('div');
    cursor.id = '__tubecli_cursor';
    cursor.style.cssText = 'position:fixed;width:16px;height:16px;border-radius:50%;' +
        'background:radial-gradient(circle, #ff3333 30%, rgba(255,51,51,0.6) 70%);' +
        'box-shadow:0 0 8px 2px rgba(255,0,0,0.5);pointer-events:none;z-index:2147483647;' +
        'transition:left 0.02s linear,top 0.02s linear;transform:translate(-50%,-50%);' +
        'display:none;';
    document.body.appendChild(cursor);
    
    // Trail canvas
    const canvas = document.createElement('canvas');
    canvas.id = '__tubecli_trail';
    canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;' +
        'pointer-events:none;z-index:2147483646;';
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    document.body.appendChild(canvas);
    const ctx = canvas.getContext('2d');
    
    // Resize handler
    window.addEventListener('resize', () => {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    });
    
    // Trail fading
    let trailPoints = [];
    setInterval(() => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const now = Date.now();
        trailPoints = trailPoints.filter(p => now - p.t < 2000);
        if (trailPoints.length < 2) return;
        for (let i = 1; i < trailPoints.length; i++) {
            const age = (now - trailPoints[i].t) / 2000;
            const alpha = Math.max(0, 0.6 - age);
            const width = Math.max(1, 3 * (1 - age));
            ctx.beginPath();
            ctx.moveTo(trailPoints[i-1].x, trailPoints[i-1].y);
            ctx.lineTo(trailPoints[i].x, trailPoints[i].y);
            ctx.strokeStyle = 'rgba(255,51,51,' + alpha + ')';
            ctx.lineWidth = width;
            ctx.lineCap = 'round';
            ctx.stroke();
        }
    }, 50);
    
    // Expose update function
    window.__tubecli_moveCursor = function(x, y) {
        cursor.style.display = 'block';
        cursor.style.left = x + 'px';
        cursor.style.top = y + 'px';
        trailPoints.push({ x, y, t: Date.now() });
        if (trailPoints.length > 500) trailPoints = trailPoints.slice(-300);
    };
    
    window.__tubecli_hideCursor = function() {
        cursor.style.display = 'none';
        trailPoints = [];
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
})();
`;

async function injectCursorOverlay(page) {
    try {
        await page.evaluate(CURSOR_INJECT_JS);
    } catch (e) { /* page might not be ready */ }
}

async function updateCursorPos(page, x, y) {
    try {
        await page.evaluate(({x, y}) => {
            if (window.__tubecli_moveCursor) window.__tubecli_moveCursor(x, y);
        }, {x, y});
    } catch (e) { /* ignore */ }
}

async function humanMove(page, targetX, targetY) {
    const startX = lastMouseX || randBetween(100, 600);
    const startY = lastMouseY || randBetween(100, 400);
    const steps = 25 + Math.floor(Math.random() * 25);

    // Inject cursor overlay if not present
    await injectCursorOverlay(page);

    // Random Bezier control points for curved path
    const ctrl1 = {
        x: startX + (targetX - startX) * randBetween(0.2, 0.5) + randBetween(-80, 80),
        y: startY + (targetY - startY) * randBetween(0.1, 0.4) + randBetween(-60, 60),
    };
    const ctrl2 = {
        x: startX + (targetX - startX) * randBetween(0.5, 0.8) + randBetween(-50, 50),
        y: startY + (targetY - startY) * randBetween(0.6, 0.9) + randBetween(-40, 40),
    };

    for (let i = 1; i <= steps; i++) {
        const t = i / steps;
        // Ease-in-out for natural acceleration
        const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        const pos = bezierPoint(
            { x: startX, y: startY },
            ctrl1, ctrl2,
            { x: targetX, y: targetY },
            eased
        );
        await page.mouse.move(pos.x, pos.y);
        await updateCursorPos(page, pos.x, pos.y);
        // Varying speed — occasional micro-pauses
        if (Math.random() > 0.85) await sleep(randBetween(5, 20));
    }

    lastMouseX = targetX;
    lastMouseY = targetY;
}

// ── Human-like Typing ──
async function humanType(page, text) {
    for (const char of text) {
        await page.keyboard.type(char, { delay: 0 });
        // Variable delay per character (40-120ms, occasional pauses)
        let delay = randBetween(40, 120);
        if (char === ' ') delay += randBetween(20, 60);         // Slightly longer on spaces
        if (Math.random() > 0.92) delay += randBetween(100, 300); // Occasional "thinking" pause
        await sleep(delay);
    }
}

// ── Human-like Scroll ──
async function humanScroll(page, deltaY = 300) {
    const scrollSteps = 5 + Math.floor(Math.random() * 5);
    const stepAmount = deltaY / scrollSteps;
    for (let i = 0; i < scrollSteps; i++) {
        const jitter = stepAmount * randBetween(0.7, 1.3);
        await page.mouse.wheel(0, jitter);
        await sleep(randBetween(30, 80));
    }
}

// ── Human-like random pause between steps ──
async function humanPause(page) {
    await sleep(randBetween(300, 800));
    // 15% chance of random idle mouse movement (looks natural)
    if (page && Math.random() > 0.85) {
        const rx = randBetween(200, 1000);
        const ry = randBetween(100, 600);
        await humanMove(page, rx, ry);
    }
}

// ── Helper to wait for locator with stopped flag checks ──
async function waitForLocator(locator, options = {}) {
    if (stopped) throw new Error('Script stopped by user.');
    let stopInterval;
    const stopPromise = new Promise((_, reject) => {
        stopInterval = setInterval(() => {
            if (stopped) {
                clearInterval(stopInterval);
                reject(new Error('Script stopped by user.'));
            }
        }, 100);
    });
    
    const waitPromise = locator.waitFor(options).then(() => {
        clearInterval(stopInterval);
    });
    
    await Promise.race([waitPromise, stopPromise]);
}

// ── Find first visible matching element to bypass hidden autofill inputs/buttons ──
async function resolveVisibleLocator(page, locatorOrSelector, timeout = 10000) {
    if (stopped) throw new Error('Script stopped by user.');
    let loc;
    if (typeof locatorOrSelector === 'string') {
        loc = page.locator(locatorOrSelector);
    } else {
        loc = locatorOrSelector;
    }
    
    // Wait up to timeout for at least one matching element to be attached to DOM
    try {
        await waitForLocator(loc.first(), { state: 'attached', timeout });
    } catch (e) {
        if (e.message === 'Script stopped by user.') throw e;
        // If not even attached, return first (which will fail/timeout as normal)
        return loc.first();
    }
    
    if (stopped) throw new Error('Script stopped by user.');
    const count = await loc.count().catch(() => 0);
    if (count > 1) {
        // Scan for the first visible element
        for (let i = 0; i < count; i++) {
            if (stopped) throw new Error('Script stopped by user.');
            const item = loc.nth(i);
            const isVis = await item.isVisible().catch(() => false);
            if (isVis) {
                return item;
            }
        }
    }
    // Default fallback to first element
    return loc.first();
}

// ── Page State Checker (detect CAPTCHA, errors, unexpected states) ──
class PageBlockedError extends Error {
    constructor(reason, details) {
        super(`🚫 PAGE BLOCKED: ${reason}`);
        this.reason = reason;
        this.details = details;
        this.isPageBlocked = true;
    }
}

async function checkPageState(page, stepIndex, stepType) {
    try {
        const stateInfo = await page.evaluate(() => {
            const url = window.location.href;
            const title = document.title || '';
            const bodyText = (document.body?.innerText || '').slice(0, 3000).toLowerCase();
            const html = (document.documentElement?.innerHTML || '').slice(0, 5000).toLowerCase();
            
            // ── CAPTCHA Detection ──
            const captchaSignals = [
                // Google reCAPTCHA
                !!document.querySelector('iframe[src*="recaptcha"]'),
                !!document.querySelector('.g-recaptcha'),
                !!document.querySelector('#recaptcha'),
                // hCaptcha  
                !!document.querySelector('iframe[src*="hcaptcha"]'),
                !!document.querySelector('.h-captcha'),
                // Cloudflare Turnstile
                !!document.querySelector('iframe[src*="challenges.cloudflare.com"]'),
                !!document.querySelector('.cf-turnstile'),
                // Generic
                bodyText.includes("i'm not a robot") || bodyText.includes('not a robot'),
                bodyText.includes('verify you are human') || bodyText.includes('xác minh bạn là người'),
                bodyText.includes('captcha') && !bodyText.includes('captcha_solved'),
                bodyText.includes('unusual traffic') || bodyText.includes('lưu lượng truy cập bất thường'),
                bodyText.includes('automated queries') || bodyText.includes('truy vấn tự động'),
                title.toLowerCase().includes('captcha'),
            ];
            const hasCaptcha = captchaSignals.filter(Boolean).length >= 1;
            
            // ── Bot/Block Detection ──
            const blockSignals = [
                url.includes('/sorry/') && url.includes('google'),  // Google block page
                url.includes('challenge') && url.includes('blocked'),
                bodyText.includes('access denied') || bodyText.includes('truy cập bị từ chối'),
                bodyText.includes('forbidden') && bodyText.includes('403'),
                bodyText.includes('your ip has been') || bodyText.includes('ip của bạn'),
                bodyText.includes('rate limit') || bodyText.includes('too many requests'),
                bodyText.includes('temporarily blocked') || bodyText.includes('tạm thời bị chặn'),
                bodyText.includes('suspicious activity') || bodyText.includes('hoạt động đáng ngờ'),
            ];
            const isBlocked = blockSignals.filter(Boolean).length >= 1;
            
            // ── Error Page Detection ──
            const errorSignals = [
                title.includes('404') || bodyText.includes('page not found') || bodyText.includes('không tìm thấy'),
                title.includes('500') || bodyText.includes('internal server error') || bodyText.includes('lỗi máy chủ'),
                title.includes('502') || title.includes('503') || title.includes('504'),
                bodyText.includes('this site can\'t be reached') || bodyText.includes('không thể truy cập'),
                bodyText.includes('err_connection') || bodyText.includes('dns_probe'),
                url.startsWith('chrome-error://'),
            ];
            const hasError = errorSignals.filter(Boolean).length >= 1;
            
            // ── Login Wall Detection ──
            const loginWall = [
                bodyText.includes('please sign in') || bodyText.includes('vui lòng đăng nhập'),
                bodyText.includes('log in to continue') || bodyText.includes('đăng nhập để tiếp tục'),
                bodyText.includes('session expired') || bodyText.includes('phiên đã hết hạn'),
            ];
            const needsLogin = loginWall.filter(Boolean).length >= 1;
            
            return {
                url,
                title,
                hasCaptcha,
                isBlocked,
                hasError,
                needsLogin,
                captchaCount: captchaSignals.filter(Boolean).length,
                blockCount: blockSignals.filter(Boolean).length,
                errorCount: errorSignals.filter(Boolean).length,
            };
        });
        
        // ── React to detected states ──
        if (stateInfo.hasCaptcha) {
            stepLog(stepIndex, stepType, `🚫 CAPTCHA DETECTED on ${stateInfo.url}`);
            stepLog(stepIndex, stepType, `🚫 Page title: "${stateInfo.title}"`);
            stepLog(stepIndex, stepType, `🚫 Script stopped — manual CAPTCHA solving required`);
            throw new PageBlockedError('CAPTCHA detected', stateInfo);
        }
        
        if (stateInfo.isBlocked) {
            stepLog(stepIndex, stepType, `🚫 BLOCKED/BANNED on ${stateInfo.url}`);
            stepLog(stepIndex, stepType, `🚫 Page title: "${stateInfo.title}"`);
            stepLog(stepIndex, stepType, `🚫 Script stopped — IP or account may be blocked`);
            throw new PageBlockedError('Access blocked/banned', stateInfo);
        }
        
        if (stateInfo.hasError) {
            stepLog(stepIndex, stepType, `🚫 ERROR PAGE on ${stateInfo.url}`);
            stepLog(stepIndex, stepType, `🚫 Page title: "${stateInfo.title}"`);
            stepLog(stepIndex, stepType, `🚫 Script stopped — page returned an error`);
            throw new PageBlockedError('Error page detected', stateInfo);
        }
        
        if (stateInfo.needsLogin) {
            stepLog(stepIndex, stepType, `⚠️ LOGIN REQUIRED on ${stateInfo.url}`);
            stepLog(stepIndex, stepType, `⚠️ Page title: "${stateInfo.title}"`);
            // Don't throw for login — might be expected (e.g. Gmail login script)
            // Just warn
        }
        
    } catch (err) {
        if (err.isPageBlocked) throw err; // Re-throw our custom errors
        // Ignore evaluate errors (page might be navigating)
    }
}

async function executeStep(page, step, index) {
    const type = step.type;
    const params = step.params || {};
    const selector = interpolate(step.selector || '');
    const timeout = params.timeout || 10000;

    stepLog(index, type, step.label || `Step ${index + 1}`);

    // Human pause between steps
    await humanPause(page);

    switch (type) {
        case 'navigate': {
            let url = interpolate(params.url || script.target_url || '');
            // Auto-add protocol if missing
            if (url && !url.startsWith('http://') && !url.startsWith('https://') && !url.startsWith('about:')) {
                url = 'https://' + url;
            }
            await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
            await injectCursorOverlay(page); // Re-inject cursor after navigation
            stepLog(index, type, `Navigated to ${url}`);
            // ── Page State Check after navigation ──
            await checkPageState(page, index, type);
            break;
        }
        case 'click': {
            const el = await resolveVisibleLocator(page, selector, timeout);
            await waitForLocator(el, { state: 'visible', timeout });
            // Human-like: move mouse to element, then click
            const box = await el.boundingBox();
            if (box) {
                // Click at a slightly randomized position within the element
                const clickX = box.x + box.width * randBetween(0.3, 0.7);
                const clickY = box.y + box.height * randBetween(0.3, 0.7);
                await humanMove(page, clickX, clickY);
                await sleep(randBetween(100, 300)); // Brief pause before clicking
            }
            if (params.force) await el.click({ force: true });
            else await el.click();
            stepLog(index, type, `Clicked: ${selector}`);
            // ── Page State Check after click (wait for potential navigation) ──
            await sleep(1500); // Give page time to start navigating
            await checkPageState(page, index, type);
            break;
        }
        case 'type': {
            const text = interpolate(params.text || '');
            const el = await resolveVisibleLocator(page, selector, timeout);
            await waitForLocator(el, { state: 'visible', timeout });
            // Human-like: move to input, click, then type
            const box = await el.boundingBox();
            if (box) {
                await humanMove(page, box.x + box.width / 2, box.y + box.height / 2);
                await sleep(randBetween(100, 250));
            }
            await el.click();
            if (params.clear_first) { await el.fill(''); await sleep(200); }
            // Use human-like typing with random delays
            await humanType(page, text);
            stepLog(index, type, `Typed ${text.length} chars into ${selector}`);
            break;
        }
        case 'wait': {
            const state = params.state || 'visible';
            if (state === 'hidden') {
                await waitForLocator(page.locator(selector).first(), { state, timeout });
            } else {
                const el = await resolveVisibleLocator(page, selector, timeout);
                await waitForLocator(el, { state, timeout });
            }
            stepLog(index, type, `Element ${state}: ${selector}`);
            break;
        }
        case 'wait_hidden': {
            await waitForLocator(page.locator(selector).first(), { state: 'hidden', timeout });
            stepLog(index, type, `Element hidden: ${selector}`);
            break;
        }
        case 'wait_network_response': {
            const urlPattern = interpolate(params.url_pattern || params.url || '');
            const statusCode = params.status || 200;
            stepLog(index, type, `Waiting for network response matching "${urlPattern}" (status ${statusCode})...`);
            let stopInterval;
            const stopPromise = new Promise((_, reject) => {
                stopInterval = setInterval(() => {
                    if (stopped) {
                        clearInterval(stopInterval);
                        reject(new Error('Script stopped by user.'));
                    }
                }, 100);
            });
            
            const waitPromise = page.waitForResponse(resp => {
                const url = resp.url();
                const status = resp.status();
                return url.includes(urlPattern) && status === statusCode;
            }, { timeout }).then(res => {
                clearInterval(stopInterval);
                return res;
            });
            
            const response = await Promise.race([waitPromise, stopPromise]);
            
            try {
                const text = await response.text();
                let data = text;
                try {
                    data = JSON.parse(text);
                } catch (e) {
                    // Not JSON
                }
                const saveName = params.save_as || '_network_data';
                variables[saveName] = data;
                stepLog(index, type, `Received network response. Saved to {{${saveName}}}`);
            } catch (err) {
                stepLog(index, type, `⚠️ Could not read network response body: ${err.message}`);
            }
            break;
        }
        case 'evaluate': {
            const code = interpolate(params.code || '');
            const result = await page.evaluate(code);
            if (params.save_as) variables[params.save_as] = result;
            stepLog(index, type, `Evaluated, result: ${JSON.stringify(result).slice(0, 200)}`);
            break;
        }
        case 'fetch_otp': {
            // Fetch TOTP code from TubeCLI 2FA API (server-side, not browser)
            const secret = interpolate(params.secret || '');
            if (!secret) {
                stepLog(index, type, '⚠️ No TOTP secret provided — skipping 2FA');
                break;
            }
            const tubecliPort = process.env.TUBECLI_PORT || '5295';
            const otpUrl = `http://localhost:${tubecliPort}/api/v1/browser/2fa?secret=${encodeURIComponent(secret.replace(/\s+/g, '').toUpperCase())}`;
            stepLog(index, type, `🔐 Fetching OTP from API...`);
            try {
                const http = require('http');
                const otpData = await new Promise((resolve, reject) => {
                    const req = http.get(otpUrl, (res) => {
                        let body = '';
                        res.on('data', chunk => body += chunk);
                        res.on('end', () => {
                            try { resolve(JSON.parse(body)); } catch(e) { reject(e); }
                        });
                    });
                    req.on('error', reject);
                    req.setTimeout(10000, () => { req.destroy(); reject(new Error('timeout')); });
                });
                if (otpData && otpData.code) {
                    const saveName = params.save_as || 'otp_code';
                    variables[saveName] = String(otpData.code);
                    stepLog(index, type, `🔐 OTP: ${otpData.code} (valid ~${otpData.remaining}s) → {{${saveName}}}`);
                } else {
                    stepLog(index, type, `⚠️ API returned no code: ${JSON.stringify(otpData)}`);
                }
            } catch (err) {
                stepLog(index, type, `🚫 Failed to fetch OTP: ${err.message}`);
            }
            break;
        }
        case 'extract': {
            const el = await resolveVisibleLocator(page, selector, timeout);
            await waitForLocator(el, { state: 'visible', timeout });
            let value;
            if (params.attribute === 'innerText') value = await el.innerText();
            else if (params.attribute === 'innerHTML') value = await el.innerHTML();
            else if (params.attribute === 'content_with_images') {
                value = await el.evaluate(node => {
                    let text = '';
                    const walk = (n) => {
                        if (['SCRIPT', 'STYLE', 'NAV', 'FOOTER', 'HEADER', 'ASIDE', 'NOSCRIPT', 'SVG'].includes(n.nodeName)) return;
                        if (n.nodeType === Node.TEXT_NODE) {
                            const t = n.textContent.trim();
                            if (t) text += t + ' ';
                        } else if (n.nodeName === 'IMG') {
                            let src = n.getAttribute('data-src') || n.getAttribute('data-original') || n.getAttribute('src');
                            if (src && !src.startsWith('data:image')) {
                                try { src = new URL(src, window.location.href).href; } catch(e) {}
                                let w = n.getAttribute('width');
                                let h = n.getAttribute('height');
                                if (!(w && h && parseInt(w) < 20 && parseInt(h) < 20)) {
                                    text += '\n[IMAGE: ' + src + ']\n';
                                }
                            }
                        } else {
                            for (let child of n.childNodes) walk(child);
                            if (['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI', 'BR'].includes(n.nodeName)) {
                                text += '\n';
                            }
                        }
                    };
                    walk(node);
                    return text.replace(/\\n\\s*\\n/g, '\\n\\n').trim();
                });
            }
            else value = await el.getAttribute(params.attribute || 'href');
            if (params.save_as) variables[params.save_as] = value;
            stepLog(index, type, `Extracted ${params.attribute}: ${String(value).slice(0, 200)}`);
            break;
        }
        case 'extract_all': {
            await page.waitForSelector(selector, { state: 'attached', timeout: 5000 }).catch(() => {});
            const els = await page.locator(selector).all();
            let values = [];
            for (const el of els) {
                if (params.min_width || params.min_height) {
                    try {
                        const dims = await el.evaluate(n => ({ 
                            w: n.naturalWidth || n.clientWidth || n.width || 0, 
                            h: n.naturalHeight || n.clientHeight || n.height || 0 
                        }));
                        if (params.min_width && dims.w > 0 && dims.w < params.min_width) continue;
                        if (params.min_height && dims.h > 0 && dims.h < params.min_height) continue;
                    } catch (e) {}
                }

                let val;
                if (params.attribute === 'innerText') val = await el.innerText();
                else if (params.attribute === 'innerHTML') val = await el.innerHTML();
                else val = await el.getAttribute(params.attribute || 'href');
                
                if (val) {
                    if (params.exclude_patterns && Array.isArray(params.exclude_patterns)) {
                        if (params.exclude_patterns.some(pat => String(val).toLowerCase().includes(pat.toLowerCase()))) continue;
                    }
                    if (params.attribute === 'src' || params.attribute === 'href') {
                        try { val = new URL(val, page.url()).toString(); } catch(e) {}
                    }
                    if (!values.includes(val)) values.push(val);
                }
            }
            if (params.save_as) variables[params.save_as] = values;
            stepLog(index, type, `Extracted ${values.length} items for ${params.attribute}`);
            break;
        }
        case 'screenshot': {
            const savePath = interpolate(params.save_as || `step_${index}.png`);
            await page.screenshot({ path: savePath, fullPage: params.full_page || false });
            stepLog(index, type, `Screenshot saved: ${savePath}`);
            break;
        }
        case 'sleep': {
            const ms = params.ms || 2000;
            await sleep(ms);
            stepLog(index, type, `Slept ${ms}ms`);
            break;
        }
        case 'condition': {
            const checkCode = interpolate(params.check || 'false');
            const result = await page.evaluate(checkCode);
            const branch = result ? (params.then_steps || []) : (params.else_steps || []);
            for (let i = 0; i < branch.length; i++) {
                await executeStepWithRetry(page, branch[i], `${index}.${i}`);
            }
            break;
        }
        case 'loop': {
            const count = params.count || 1;
            const delay = params.delay || 1000;
            const loopSteps = params.steps || [];
            for (let iter = 0; iter < count; iter++) {
                variables['_loop_index'] = iter;
                if (params.break_on) {
                    const shouldBreak = await page.evaluate(interpolate(params.break_on));
                    if (shouldBreak) { stepLog(index, type, `Loop break at iteration ${iter}`); break; }
                }
                for (let i = 0; i < loopSteps.length; i++) {
                    await executeStepWithRetry(page, loopSteps[i], `${index}.loop${iter}.${i}`);
                }
                if (iter < count - 1) await sleep(delay);
            }
            break;
        }
        case 'download': {
            // Wait for download event
            const downloadPromise = page.waitForEvent('download', { timeout });
            if (selector) {
                // Human-like click on download trigger
                const el = await resolveVisibleLocator(page, selector, timeout);
                const box = await el.boundingBox();
                if (box) {
                    await humanMove(page, box.x + box.width / 2, box.y + box.height / 2);
                    await sleep(randBetween(100, 300));
                }
                await el.click();
            }
            const download = await downloadPromise;
            const outputDir = interpolate(params.output_dir || '.');
            const filename = interpolate(params.filename || download.suggestedFilename());
            const savePath = path.join(outputDir, filename);
            await download.saveAs(savePath);
            variables['_last_download'] = savePath;
            stepLog(index, type, `Downloaded: ${savePath}`);
            break;
        }
        case 'keyboard': {
            const key = interpolate(params.key || 'Enter');
            await sleep(randBetween(100, 300));
            await page.keyboard.press(key);
            stepLog(index, type, `Pressed key: ${key}`);
            break;
        }
        case 'scroll': {
            const direction = params.direction || 'down';
            const amount = params.amount || 400;
            const delta = direction === 'up' ? -amount : amount;
            await humanScroll(page, delta);
            stepLog(index, type, `Scrolled ${direction} ${amount}px`);
            break;
        }
        case 'mouse_move': {
            const mx = params.x || randBetween(200, 1000);
            const my = params.y || randBetween(100, 600);
            await humanMove(page, mx, my);
            stepLog(index, type, `Moved mouse to (${Math.round(mx)}, ${Math.round(my)})`);
            break;
        }
        case 'hover': {
            if (selector) {
                const el = await resolveVisibleLocator(page, selector, timeout);
                await waitForLocator(el, { state: 'visible', timeout });
                const box = await el.boundingBox();
                if (box) {
                    await humanMove(page, box.x + box.width / 2, box.y + box.height / 2);
                }
                stepLog(index, type, `Hovered: ${selector}`);
            }
            break;
        }
        case 'ai_generate': {
            // Extract page context if selector provided
            let context = '';
            const extractSel = params.extract_selector || params.context_selector || 'h1';
            try {
                context = await page.locator(extractSel).first().innerText({ timeout: 5000 });
            } catch (e) {
                // Fallback: get page title
                context = await page.title();
            }

            const aiPrompt = interpolate(params.prompt || 'Write a short, friendly comment');
            const saveName = params.save_as || '_ai_text';

            stepLog(index, type, `🤖 AI generating: "${aiPrompt}" (context: ${context.slice(0, 50)}...)`);

            // Call AI via TubeCLI API
            const tubecliPort = process.env.TUBECLI_PORT || '5295';
            try {
                const http = require('http');
                const aiResult = await new Promise((resolve, reject) => {
                    const postData = JSON.stringify({
                        message: `${aiPrompt}\n\nPage context: "${context}"\n\nRespond with ONLY the generated text, no explanations or quotes.`,
                        history: [],
                        script: null,
                    });
                    const req = http.request({
                        hostname: '127.0.0.1', port: tubecliPort,
                        path: '/api/v1/scripts/chat', method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(postData) },
                    }, (res) => {
                        let data = '';
                        res.on('data', c => data += c);
                        res.on('end', () => {
                            try { resolve(JSON.parse(data)); } catch (e) { reject(new Error('Invalid AI response')); }
                        });
                    });
                    req.on('error', reject);
                    req.write(postData);
                    req.end();
                });

                const generatedText = (aiResult.reply || '').trim();
                variables[saveName] = generatedText;
                stepLog(index, type, `🤖 Generated: "${generatedText.slice(0, 80)}..." → {{${saveName}}}`);
            } catch (aiErr) {
                stepLog(index, type, `🤖 AI generation failed: ${aiErr.message}`);
                variables[saveName] = params.fallback || 'Great content! 👍';
            }
            break;
        }
        case 'call_function': {
            const fnSlug = interpolate(params.function_slug || params.slug || '');
            if (!fnSlug) {
                stepLog(index, type, `❌ call_function: missing function_slug`);
                break;
            }

            stepLog(index, type, `📦 Calling function: ${fnSlug}`);

            // Load function script from scripts/ directory
            const scriptsDir = execData.scripts_dir || path.join(__dirname, '..', 'scripts');
            const fnPath = path.join(scriptsDir, `${fnSlug}.json`);

            if (!fs.existsSync(fnPath)) {
                stepLog(index, type, `❌ Function not found: ${fnPath}`);
                break;
            }

            const fnScript = JSON.parse(fs.readFileSync(fnPath, 'utf-8'));
            const fnSteps = fnScript.steps || [];

            if (!fnSteps.length) {
                stepLog(index, type, `⚠️ Function ${fnSlug} has no steps`);
                break;
            }

            // Map caller variables → function inputs (scoped)
            const savedVars = { ...variables };
            const inputMap = params.inputs || {};
            for (const [fnVar, callerExpr] of Object.entries(inputMap)) {
                variables[fnVar] = interpolate(String(callerExpr));
            }

            stepLog(index, type, `📦 Executing ${fnSteps.length} function steps...`);

            // Execute function steps
            for (let i = 0; i < fnSteps.length; i++) {
                await executeStepWithRetry(page, fnSteps[i], `${index}.fn.${i}`);
            }

            // Map function outputs → caller variables
            const outputMap = params.outputs || {};
            for (const [callerVar, fnVar] of Object.entries(outputMap)) {
                savedVars[callerVar] = variables[fnVar];
            }

            // Restore caller scope (but keep outputs)
            Object.keys(variables).forEach(k => delete variables[k]);
            Object.assign(variables, savedVars);

            stepLog(index, type, `✅ Function ${fnSlug} completed`);
            break;
        }
        default:
            stepLog(index, type, `Unknown step type: ${type}`);
    }
}

async function executeStepWithRetry(page, step, index) {
    await waitIfPaused();
    if (stopped) throw new Error('Script stopped by user.');
    if (step.enabled === false) {
        stepLog(index, step.type, 'SKIPPED (disabled)');
        return;
    }
    const retryCount = step.retry_count || 0;
    const retryDelay = step.retry_delay || 1000;
    const onError = step.on_error || 'abort';

    for (let attempt = 0; attempt <= retryCount; attempt++) {
        if (stopped) throw new Error('Script stopped by user.');
        try {
            await executeStep(page, step, index);
            return;
        } catch (err) {
            if (stopped) throw new Error('Script stopped by user.');
            if (paused) {
                stepLog(index, step.type, `⏸ Step paused during execution (error: ${err.message.split('\n')[0]}). Waiting for resume...`);
                await waitIfPaused();
                if (stopped) throw new Error('Script stopped by user.');
                attempt = -1; // Reset attempt counter to retry the step on resume
                continue;
            }

            // ── Page blocked errors bypass all retries — stop immediately ──
            if (err.isPageBlocked) {
                stepLog(index, step.type, `🚫 ${err.message}`);
                throw err; // Propagate up to stop script
            }
            
            const msg = `Step ${index} failed (attempt ${attempt + 1}/${retryCount + 1}): ${err.message}`;
            stepLog(index, step.type, msg);
            
            // If overlay is blocking clicks, skip remaining retries → go straight to popup dismiss
            if (err.message.includes('intercepts pointer events') || err.message.includes('overlay')) {
                stepLog(index, step.type, '🔔 Overlay detected blocking clicks, dismissing...');
                attempt = retryCount; // Skip to post-retry fix phase
            }
            
            if (attempt < retryCount) {
                await sleep(retryDelay);
                if (stopped) throw new Error('Script stopped by user.');
                continue;
            }

            // ── Smart Auto-Fix: try to find correct selector ──
            const isSelectorError = err.message.includes('Timeout') ||
                                    err.message.includes('waiting for') ||
                                    err.message.includes('locator');

            // ── Phase 0: Auto-dismiss popup/overlay (most common blocker) ──
            try {
                const dismissed = await page.evaluate(() => {
                    // ── Step A: Check required checkboxes in modals/dialogs ──
                    const modalContainers = document.querySelectorAll(
                        '[role="dialog"], [class*="modal"], [class*="dialog"], [class*="overlay"], [class*="popup"], ' +
                        '.cdk-overlay-container, .cdk-overlay-pane, [class*="cdk-overlay"]'
                    );
                    for (const container of modalContainers) {
                        const rect = container.getBoundingClientRect();
                        // cdk-overlay-container is full-screen, so skip size check for it
                        const isCDK = container.classList?.contains('cdk-overlay-container');
                        if (!isCDK && rect.width === 0 && rect.height === 0) continue;
                        // Find unchecked checkboxes (native + Angular Material mat-checkbox)
                        const checkboxes = container.querySelectorAll(
                            'input[type="checkbox"]:not(:checked), [role="checkbox"][aria-checked="false"], ' +
                            'mat-checkbox:not(.mat-mdc-checkbox-checked), .mat-checkbox:not(.mat-checkbox-checked)'
                        );
                        for (const cb of checkboxes) {
                            const label = cb.closest('label')?.textContent || cb.closest('mat-checkbox')?.textContent || cb.parentElement?.textContent || '';
                            // Check agreement/terms/acknowledge checkboxes
                            if (label.match(/agree|acknowledge|accept|terms|consent|developer|đồng ý|chấp nhận|xác nhận/i)) {
                                // For mat-checkbox, click the label or the checkbox wrapper
                                const clickTarget = cb.querySelector('input[type="checkbox"]') || cb.querySelector('.mdc-checkbox') || cb;
                                clickTarget.click();
                            }
                        }
                    }

                    // ── Step B: Find and click dismiss/continue buttons ──
                    const closeSelectors = [
                        '[aria-label="Close"]', '[aria-label="Dismiss"]', '[aria-label="Đóng"]',
                        'button.close', 'button[class*="close"]', 'button[class*="dismiss"]',
                        '[class*="modal"] button', '[class*="dialog"] button',
                        '[role="dialog"] button', '[class*="overlay"] button',
                        '.cdk-overlay-pane button', '.cdk-overlay-container button', // Angular CDK
                        'button[id*="accept"]', 'button[id*="agree"]', 'button[id*="consent"]',
                        '[class*="cookie"] button', '[class*="consent"] button',
                        'button[jsname="tWT92d"]', 'button[jsname="b3VHJd"]',
                        '.VfPpkd-LgbsSe.VfPpkd-LgbsSe-OWXEXe-k8QpJ',
                    ];
                    const dismissTexts = /^(ok|close|dismiss|got it|accept|agree|i agree|continue|proceed|confirm|đóng|đồng ý|x|✕|✖|×|tôi đồng ý|skip|bỏ qua|later|để sau|tiếp tục|xác nhận)$/i;
                    
                    let found = false;
                    for (const sel of closeSelectors) {
                        const btns = document.querySelectorAll(sel);
                        for (const btn of btns) {
                            const rect = btn.getBoundingClientRect();
                            const style = window.getComputedStyle(btn);
                            if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                                const text = (btn.textContent || '').trim().toLowerCase();
                                if (dismissTexts.test(text) ||
                                    btn.getAttribute('aria-label')?.match(/close|dismiss|đóng/i) ||
                                    text === '') {
                                    btn.click();
                                    found = true;
                                    break;
                                }
                            }
                        }
                        if (found) break;
                    }
                    
                    // ── Step C: Escape fallback ──
                    if (!found) {
                        const modal = document.querySelector('[role="dialog"]:not([style*="display: none"]), [class*="modal"]:not([style*="display: none"])');
                        if (modal) {
                            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
                            found = true;
                        }
                    }
                    return found;
                }).catch(() => false);

                if (dismissed) {
                    stepLog(index, step.type, '🔔 Auto-dismissed popup/overlay! Retrying step...');
                    await sleep(1000);
                    try {
                        await executeStep(page, step, index);
                        return; // Step succeeded after dismissing popup
                    } catch (retryErr) {
                        stepLog(index, step.type, `Step still failed after popup dismiss, continuing fix...`);
                    }
                }
            } catch (popupErr) {}

            // ── Phase 1: Auto 2FA Handler (only when on 2FA page) ──
            // If step failed and page is on a 2FA challenge, handle it automatically
            try {
                const currentUrl = page.url() || '';
                const is2FAPage = await page.evaluate(() => {
                    const body = (document.body?.innerText || '').toLowerCase();
                    const selectors = [
                        'input#totpPin', 'input[name="totpPin"]', 'input[type="tel"]',
                        'input[autocomplete="one-time-code"]', 'input[name="approvals_code"]',
                        'input[placeholder*="code" i]', 'input[aria-label*="code" i]',
                    ];
                    const hasInput = selectors.some(s => !!document.querySelector(s));
                    const hasText = body.includes('2-step') || body.includes('two-step') ||
                                    body.includes('verification') || body.includes('xác minh') ||
                                    body.includes('authenticator') || body.includes('2fa') ||
                                    body.includes('mã xác minh');
                    return hasInput || hasText;
                }).catch(() => false);

                if (is2FAPage && variables.totp_secret) {
                    stepLog(index, step.type, '🔐 2FA challenge detected! Auto-handling...');
                    
                    // Fetch OTP from API
                    const secret = variables.totp_secret.replace(/\s+/g, '').toUpperCase();
                    const tubecliPort = process.env.TUBECLI_PORT || '5295';
                    const otpUrl = `http://localhost:${tubecliPort}/api/v1/browser/2fa?secret=${encodeURIComponent(secret)}`;
                    
                    const http = require('http');
                    const otpData = await new Promise((resolve, reject) => {
                        const req = http.get(otpUrl, (res) => {
                            let body = '';
                            res.on('data', chunk => body += chunk);
                            res.on('end', () => {
                                try { resolve(JSON.parse(body)); } catch(e) { reject(e); }
                            });
                        });
                        req.on('error', reject);
                        req.setTimeout(10000, () => { req.destroy(); reject(new Error('timeout')); });
                    });

                    if (otpData && otpData.code) {
                        stepLog(index, step.type, `🔐 Got OTP: ${otpData.code} (valid ~${otpData.remaining}s)`);
                        
                        // Find and fill 2FA input
                        const otpSelectors = [
                            'input#totpPin', 'input[name="totpPin"]', 'input[type="tel"]',
                            'input[autocomplete="one-time-code"]', 'input[name="approvals_code"]',
                            'input[placeholder*="code" i]', 'input[aria-label*="code" i]',
                        ];
                        for (const sel of otpSelectors) {
                            const otpInput = await resolveVisibleLocator(page, sel, 1000);
                            if (await otpInput.isVisible().catch(() => false)) {
                                // Move cursor to input
                                const box = await otpInput.boundingBox();
                                if (box) await humanMove(page, box.x + box.width / 2, box.y + box.height / 2);
                                await sleep(randBetween(200, 500));
                                await otpInput.click();
                                await otpInput.fill('');
                                // Type code like a human
                                for (const char of otpData.code) {
                                    await page.keyboard.type(char, { delay: 80 + Math.random() * 120 });
                                }
                                stepLog(index, step.type, `🔐 Entered OTP into ${sel}`);
                                break;
                            }
                        }
                        
                        await sleep(randBetween(500, 1000));
                        
                        // Click submit/next button
                        const submitSelectors = [
                            '#totpNext button', 'button[jsname="LgbsSe"]',
                            'button:has-text("Next")', 'button:has-text("Tiếp theo")',
                            'button:has-text("Verify")', 'button:has-text("Xác minh")',
                            'button:has-text("Submit")', 'button[type="submit"]',
                        ];
                        for (const sel of submitSelectors) {
                            const btn = await resolveVisibleLocator(page, sel, 1000);
                            if (await btn.isVisible().catch(() => false)) {
                                const box = await btn.boundingBox();
                                if (box) await humanMove(page, box.x + box.width / 2, box.y + box.height / 2);
                                await sleep(randBetween(300, 600));
                                await btn.click();
                                stepLog(index, step.type, `🔐 Clicked ${sel}`);
                                break;
                            }
                        }
                        
                        // Wait for 2FA to clear
                        stepLog(index, step.type, '🔐 Waiting for 2FA to clear...');
                        await sleep(5000);
                        await injectCursorOverlay(page);
                        
                        // Retry original step
                        stepLog(index, step.type, '🔐 2FA handled! Retrying original step...');
                        try {
                            await executeStep(page, step, index);
                            return; // Success!
                        } catch (retryErr) {
                            stepLog(index, step.type, `Step still failed after 2FA: ${retryErr.message}`);
                        }
                    } else {
                        stepLog(index, step.type, '⚠️ 2FA detected but API returned no code');
                    }
                } else if (is2FAPage && !variables.totp_secret) {
                    stepLog(index, step.type, '⚠️ 2FA challenge detected but no totp_secret variable set!');
                    stepLog(index, step.type, '⚠️ Add a variable "totp_secret" with your TOTP base32 secret key');
                }
            } catch (twoFaErr) {
                // 2FA handler failed — continue to Smart Fix
                if (twoFaErr.message) stepLog(index, step.type, `2FA auto-handler error: ${twoFaErr.message}`);
            }

            if (isSelectorError && (step.selector || step.type === 'wait' || step.type === 'navigate')) {

                // ─── Phase 2: Smart Selector Finder (no AI, instant) ───
                stepLog(index, step.type, '🔍 Smart fix: probing page for element...');
                const origSelector = step.selector;
                let smartFixed = false;

                // Extract keywords from failed selector for matching
                const selectorKeywords = origSelector.toLowerCase()
                    .replace(/[#.\[\]='":()]/g, ' ').split(/\s+/)
                    .filter(w => w.length > 2 && !['first', 'last', 'nth', 'child', 'type', 'not', 'has', 'text', 'button', 'div', 'span', 'input'].includes(w));
                const labelHint = (step.label || '').toLowerCase();
                const labelWords = labelHint.split(/\s+/).filter(w => w.length > 2);
                
                // ── Intent detection from label ──
                const isButton = labelHint.includes('click') || labelHint.includes('button') || labelHint.includes('submit') || 
                                 labelHint.includes('next') || labelHint.includes('tiếp') || labelHint.includes('đăng') ||
                                 labelHint.includes('gửi') || labelHint.includes('sign') || labelHint.includes('log') ||
                                 step.type === 'click';
                const isInput = labelHint.includes('type') || labelHint.includes('enter') || labelHint.includes('input') ||
                                labelHint.includes('nhập') || labelHint.includes('email') || labelHint.includes('password') ||
                                labelHint.includes('search') || labelHint.includes('tìm') ||
                                origSelector.includes('input') || origSelector.includes('textarea') ||
                                step.type === 'type';
                const isLink = labelHint.includes('link') || labelHint.includes('href') || origSelector.includes('a[');
                const isSearching = labelHint.includes('search') || selectorKeywords.includes('search') || labelHint.includes('tìm');

                // ── Extract text hints from label (multi-language) ──
                // "Click Next after email" → look for button with text "Next"
                // "Hover over Next button" → look for "Next"
                const actionWords = ['click', 'hover', 'wait', 'press', 'tap', 'select', 'check', 'find', 'for', 'on', 'the', 'over',
                                     'after', 'before', 'bấm', 'nhấn', 'chọn', 'đợi', 'tìm', 'vào', 'nút', 'button', 'link', 'input', 'box'];
                const textHints = labelWords.filter(w => !actionWords.includes(w) && w.length > 1);
                
                stepLog(index, step.type, `🔍 Intent: ${isButton ? 'button' : isInput ? 'input' : isLink ? 'link' : 'element'}, hints: [${textHints.join(', ')}]`);

                // ══════════════════════════════════════════════
                // Strategy 0: Well-known site patterns (instant)
                // ══════════════════════════════════════════════
                const wellKnownTrials = [];
                const pageUrl = page.url() || '';
                
                if (pageUrl.includes('accounts.google.com') || pageUrl.includes('google.com/signin')) {
                    // Google Login — language-agnostic selectors
                    if (labelHint.includes('next') || labelHint.includes('tiếp') || labelHint.includes('identifier')) {
                        wellKnownTrials.push({ loc: page.locator('#identifierNext button'), desc: '#identifierNext button' });
                        wellKnownTrials.push({ loc: page.locator('#passwordNext button'), desc: '#passwordNext button' });
                        wellKnownTrials.push({ loc: page.locator('button[jsname="LgbsSe"]'), desc: 'button[jsname="LgbsSe"]' });
                        wellKnownTrials.push({ loc: page.locator('button:has-text("Next")'), desc: 'button:has-text("Next")' });
                        wellKnownTrials.push({ loc: page.locator('button:has-text("Tiếp theo")'), desc: 'button:has-text("Tiếp theo")' });
                        wellKnownTrials.push({ loc: page.locator('button:has-text("Tiếp tục")'), desc: 'button:has-text("Tiếp tục")' });
                        wellKnownTrials.push({ loc: page.locator('#identifierNext'), desc: '#identifierNext' });
                        wellKnownTrials.push({ loc: page.locator('#passwordNext'), desc: '#passwordNext' });
                    }
                    if ((labelHint.includes('email') || labelHint.includes('identifier')) && !isButton) {
                        wellKnownTrials.push({ loc: page.locator('input[type="email"]'), desc: 'input[type="email"]' });
                        wellKnownTrials.push({ loc: page.locator('#identifierId'), desc: '#identifierId' });
                    }
                    if ((labelHint.includes('password') || labelHint.includes('mật khẩu')) && !isButton) {
                        wellKnownTrials.push({ loc: page.locator('input[type="password"]'), desc: 'input[type="password"]' });
                        wellKnownTrials.push({ loc: page.locator('input[name="Passwd"]'), desc: 'input[name="Passwd"]' });
                    }
                }
                if (pageUrl.includes('youtube.com')) {
                    if (isSearching) {
                        wellKnownTrials.push({ loc: page.locator('input#search'), desc: 'input#search' });
                        wellKnownTrials.push({ loc: page.locator('input[name="search_query"]'), desc: 'input[name="search_query"]' });
                    }
                    if (labelHint.includes('comment') || labelHint.includes('bình luận')) {
                        wellKnownTrials.push({ loc: page.locator('#simplebox-placeholder, #contenteditable-root'), desc: '#simplebox-placeholder' });
                        wellKnownTrials.push({ loc: page.locator('div[contenteditable="true"]'), desc: 'div[contenteditable]' });
                    }
                    if (labelHint.includes('submit') || labelHint.includes('gửi')) {
                        wellKnownTrials.push({ loc: page.locator('#submit-button button, tp-yt-paper-button#button[aria-label*="Comment"]'), desc: '#submit-button' });
                    }
                }
                if (pageUrl.includes('facebook.com')) {
                    if (labelHint.includes('email') || labelHint.includes('login')) {
                        wellKnownTrials.push({ loc: page.locator('#email'), desc: '#email' });
                    }
                    if (labelHint.includes('password')) {
                        wellKnownTrials.push({ loc: page.locator('#pass'), desc: '#pass' });
                    }
                    if (labelHint.includes('login') || labelHint.includes('đăng nhập')) {
                        wellKnownTrials.push({ loc: page.locator('button[name="login"], input[value="Log In"]'), desc: 'button[name="login"]' });
                    }
                }

                // ══════════════════════════════════════════════
                // Strategy 1: Playwright Native Locators
                // ══════════════════════════════════════════════
                const nativeTrials = [];

                // Button/Link: match by visible text from label hints
                if (isButton || isLink) {
                    for (const hint of textHints) {
                        // Multi-language: try both original and common translations
                        const textVariants = [hint];
                        const translations = {
                            'next': ['Tiếp theo', 'Tiếp tục', 'Continue', 'Next'],
                            'sign': ['Đăng nhập', 'Đăng ký', 'Sign in', 'Sign up', 'Login'],
                            'login': ['Đăng nhập', 'Log in', 'Sign in'],
                            'submit': ['Gửi', 'Submit', 'Đăng', 'Post'],
                            'search': ['Tìm kiếm', 'Search'],
                            'cancel': ['Hủy', 'Cancel'],
                            'ok': ['OK', 'Đồng ý', 'Agree'],
                            'accept': ['Chấp nhận', 'Accept', 'Đồng ý'],
                            'close': ['Đóng', 'Close'],
                            'save': ['Lưu', 'Save'],
                            'delete': ['Xóa', 'Delete', 'Remove'],
                            'comment': ['Bình luận', 'Comment'],
                            'reply': ['Trả lời', 'Reply'],
                            'send': ['Gửi', 'Send'],
                        };
                        for (const [key, vals] of Object.entries(translations)) {
                            if (hint.includes(key) || key.includes(hint)) {
                                textVariants.push(...vals);
                            }
                        }
                        
                        for (const txt of [...new Set(textVariants)]) {
                            nativeTrials.push({ locator: page.getByRole('button', { name: txt, exact: false }), desc: `getByRole("button", "${txt}")` });
                            nativeTrials.push({ locator: page.getByRole('link', { name: txt, exact: false }), desc: `getByRole("link", "${txt}")` });
                            nativeTrials.push({ locator: page.getByText(txt, { exact: false }), desc: `getByText("${txt}")` });
                        }
                    }
                    // Generic button roles
                    nativeTrials.push({ locator: page.locator('[type="submit"]'), desc: '[type="submit"]' });
                }

                // Input: match by role, placeholder, label
                if (isInput) {
                    for (const hint of textHints) {
                        nativeTrials.push({ locator: page.getByPlaceholder(hint, { exact: false }), desc: `getByPlaceholder("${hint}")` });
                        nativeTrials.push({ locator: page.getByLabel(hint, { exact: false }), desc: `getByLabel("${hint}")` });
                    }
                    nativeTrials.push({ locator: page.getByRole('textbox'), desc: 'getByRole("textbox")' });
                    nativeTrials.push({ locator: page.getByRole('searchbox'), desc: 'getByRole("searchbox")' });
                    nativeTrials.push({ locator: page.getByRole('combobox'), desc: 'getByRole("combobox")' });
                    
                    // Common input types based on label
                    if (labelHint.includes('email')) {
                        nativeTrials.push({ locator: page.locator('input[type="email"]'), desc: 'input[type="email"]' });
                    }
                    if (labelHint.includes('password') || labelHint.includes('mật khẩu')) {
                        nativeTrials.push({ locator: page.locator('input[type="password"]'), desc: 'input[type="password"]' });
                    }
                }

                // Fallback: generic keyword matching via label/placeholder/aria
                for (const kw of selectorKeywords) {
                    nativeTrials.push({ locator: page.getByLabel(kw, { exact: false }), desc: `getByLabel("${kw}")` });
                }

                // ══════════════════════════════════════════════
                // Strategy 2: XPath (deep DOM traversal)
                // ══════════════════════════════════════════════
                const xpathTrials = [];
                
                // Button XPaths
                if (isButton) {
                    for (const hint of textHints) {
                        xpathTrials.push(`//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'${hint}')]`);
                        xpathTrials.push(`//*[@role='button'][contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'${hint}')]`);
                        xpathTrials.push(`//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'${hint}')]`);
                        xpathTrials.push(`//*[contains(@aria-label,'${hint}') or contains(@title,'${hint}')]`);
                    }
                    // Generic submit/next buttons
                    xpathTrials.push(`//button[@type='submit']`);
                    xpathTrials.push(`//input[@type='submit']`);
                    xpathTrials.push(`//*[@role='button' and (@jsname or @data-action)]`);
                }
                
                // Input XPaths
                if (isInput) {
                    for (const hint of textHints) {
                        xpathTrials.push(`//input[contains(@name,'${hint}') or contains(@id,'${hint}') or contains(@placeholder,'${hint}') or contains(@aria-label,'${hint}')]`);
                        xpathTrials.push(`//textarea[contains(@name,'${hint}') or contains(@id,'${hint}') or contains(@placeholder,'${hint}')]`);
                        xpathTrials.push(`//*[@contenteditable='true'][contains(@aria-label,'${hint}')]`);
                    }
                    if (isSearching) {
                        xpathTrials.push(`//input[contains(@name,'search') or contains(@name,'query') or @type='search']`);
                        xpathTrials.push(`//input[contains(@placeholder,'Search') or contains(@placeholder,'search') or contains(@placeholder,'Tìm')]`);
                    }
                }
                
                // Generic: any element matching keywords by id/name/aria
                for (const kw of selectorKeywords) {
                    xpathTrials.push(`//*[contains(@id,'${kw}') or contains(@name,'${kw}') or contains(@aria-label,'${kw}') or contains(@data-testid,'${kw}')]`);
                }

                // ══════════════════════════════════════════════
                // Strategy 3: CSS alternatives
                // ══════════════════════════════════════════════
                const cssTrials = [];
                
                if (isButton) {
                    for (const kw of selectorKeywords) {
                        cssTrials.push(`button[aria-label*="${kw}"], button[title*="${kw}"]`);
                        cssTrials.push(`[role="button"][aria-label*="${kw}"]`);
                        cssTrials.push(`button[data-testid*="${kw}"]`);
                        cssTrials.push(`a[aria-label*="${kw}"]`);
                    }
                }
                if (isInput) {
                    for (const kw of selectorKeywords) {
                        cssTrials.push(`input[name*="${kw}"], input[id*="${kw}"]`);
                        cssTrials.push(`input[placeholder*="${kw}"]`);
                        cssTrials.push(`textarea[name*="${kw}"]`);
                        cssTrials.push(`[contenteditable="true"][aria-label*="${kw}"]`);
                    }
                    cssTrials.push(`input[type="search"]`);
                }
                for (const kw of selectorKeywords) {
                    cssTrials.push(`[data-testid*="${kw}"]`);
                    cssTrials.push(`[aria-label*="${kw}"]`);
                    cssTrials.push(`#${kw}`);
                }

                // ══════════════════════════════════════════════
                // Execute strategies in priority order
                // ══════════════════════════════════════════════
                
                // Helper: try a locator for click/type/wait
                const tryLocator = async (locOrSel, desc) => {
                    const loc = await resolveVisibleLocator(page, locOrSel, 2000);
                    const visible = await loc.isVisible({ timeout: 2000 }).catch(() => false);
                    if (!visible) return false;
                    stepLog(index, step.type, `🔍 Found: ${desc}`);
                    if (step.type === 'wait' || step.type === 'hover') {
                        if (step.type === 'hover') await loc.hover();
                        else await waitForLocator(loc, { state: 'visible', timeout: 5000 });
                    } else if (step.type === 'click') {
                        const box = await loc.boundingBox();
                        if (box) await humanMove(page, box.x + box.width * randBetween(0.3, 0.7), box.y + box.height * randBetween(0.3, 0.7));
                        await sleep(randBetween(100, 300));
                        await loc.click();
                    } else if (step.type === 'type') {
                        const box = await loc.boundingBox();
                        if (box) await humanMove(page, box.x + box.width / 2, box.y + box.height / 2);
                        await sleep(randBetween(100, 250));
                        await loc.click();
                        if (step.params?.clear_first) await loc.fill('');
                        await humanType(page, interpolate(step.params?.text || ''));
                    }
                    stepLog(index, step.type, `✅ Smart fix worked! ${desc}`);
                    return true;
                };

                // 0. Well-known site patterns (highest priority)
                for (const wk of wellKnownTrials) {
                    try { if (await tryLocator(wk.loc, wk.desc)) { smartFixed = true; break; } } catch (e) {}
                }

                // 1. Playwright native locators
                if (!smartFixed) {
                    for (const trial of nativeTrials) {
                        try { if (await tryLocator(trial.locator, trial.desc)) { smartFixed = true; break; } } catch (e) {}
                    }
                }

                // 2. XPath
                if (!smartFixed) {
                    for (const xpath of xpathTrials) {
                        try {
                            const loc = page.locator(xpath);
                            if (await tryLocator(loc, `xpath: ${xpath}`)) { smartFixed = true; break; }
                        } catch (e) {}
                    }
                }

                // 3. CSS alternatives
                if (!smartFixed) {
                    for (const css of cssTrials) {
                        try {
                            const loc = page.locator(css);
                            if (await tryLocator(loc, `css: ${css}`)) { smartFixed = true; break; }
                        } catch (e) {}
                    }
                }

                if (smartFixed) return;
                step.selector = origSelector; // Restore

                // ─── Phase 2: AI Fix (if smart finder failed) ───
                stepLog(index, step.type, '🤖 AI Auto-Fix: analyzing page...');
                try {
                    // Get FULL DOM including shadow roots
                    const pageHtml = await page.evaluate(() => {
                        function getFullDOM(root, depth = 0) {
                            if (depth > 3) return '';
                            let html = '';
                            for (const child of root.children || []) {
                                html += child.outerHTML?.slice(0, 500) || '';
                                if (child.shadowRoot) {
                                    html += '<!-- SHADOW ROOT -->';
                                    html += getFullDOM(child.shadowRoot, depth + 1);
                                }
                            }
                            return html;
                        }
                        return getFullDOM(document.body).slice(0, 15000);
                    }).catch(() => '');

                    const pageUrl = page.url() || '';
                    const visibleText = await page.evaluate(() => {
                        return document.body ? document.body.innerText.slice(0, 3000) : '';
                    }).catch(() => '');

                    // Smart selector hints removed (handled in Phase 1 now)
                    const smartHints = '';

                    const tubecliPort = process.env.TUBECLI_PORT || '5295';
                    const fixRes = await fetch(`http://localhost:${tubecliPort}/api/v1/scripts/ai-fix`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            selector: step.selector,
                            step_type: step.type,
                            label: step.label || `Step ${index}`,
                            error: err.message,
                            page_html: pageHtml,
                            page_url: pageUrl,
                            visible_text: visibleText + '\n\n--- FOUND ELEMENTS ---\n' + smartHints,
                        }),
                    });
                    const fix = await fixRes.json();
                    if (fix.status === 'fixed') {
                        stepLog(index, step.type, `🤖 AI: ${fix.reason}`);

                        // Try pre-action clicks
                        const clicks = fix.pre_action_clicks || [];
                        for (const clickSel of clicks) {
                            try {
                                stepLog(index, step.type, `🤖 Clicking: ${clickSel}`);
                                await page.click(clickSel, { force: true, timeout: 5000 });
                                await sleep(1000);
                            } catch (clickErr) {
                                try {
                                    await page.getByRole('button', { name: clickSel }).first().click({ timeout: 3000 });
                                    await sleep(1000);
                                } catch (e2) {}
                            }
                        }

                        // Execute pre-action JS
                        if (fix.pre_action_js) {
                            stepLog(index, step.type, `🤖 Running JS fix...`);
                            try {
                                await page.evaluate(fix.pre_action_js);
                                await sleep(1000);
                            } catch (preErr) {}
                        }

                        // Unblock page
                        try {
                            await page.evaluate(() => {
                                document.body.style.overflow = '';
                                document.body.style.position = '';
                                document.documentElement.style.overflow = '';
                                document.querySelectorAll('[class*="consent"], [class*="overlay"], [class*="backdrop"], [id*="consent"]')
                                    .forEach(el => { try { el.remove(); } catch(e) {} });
                            });
                        } catch (e) {}

                        await sleep(1500);
                        await page.waitForLoadState('domcontentloaded').catch(() => {});

                        // Retry with AI's selector
                        if (fix.selector) step.selector = fix.selector;
                        try {
                            await executeStep(page, step, index);
                            stepLog(index, step.type, `✅ AI fix worked!`);
                            return;
                        } catch (fixErr) {
                            stepLog(index, step.type, `❌ AI fix also failed: ${fixErr.message}`);
                            step.selector = origSelector;
                        }
                    } else {
                        stepLog(index, step.type, `🤖 AI could not fix: ${fix.reason || 'unknown'}`);
                    }
                } catch (aiErr) {
                    stepLog(index, step.type, `🤖 AI fix error: ${aiErr.message}`);
                }
            }

            if (onError === 'skip') {
                stepLog(index, step.type, 'Error handled: skip');
                return;
            }
            if (onError === 'abort') throw err;
        }
    }
}

(async () => {
    log(`Starting execution: ${script.name} (${steps.length} steps)`);

    // Resolve browser profile storage
    const profilesDir = execData.profiles_dir || '';
    let storageDir = '';
    let rawProxy = null;
    let pwProxy = undefined;
    let normalizedProxy = null;

    if (profile && profilesDir) {
        const profileDir = path.join(profilesDir, profile);
        if (fs.existsSync(profileDir)) {
            storageDir = profileDir;
            log(`Profile: ${profile} → ${storageDir}`);
            
            // Load proxy from config
            try {
                const configPath = path.join(storageDir, 'config.json');
                if (fs.existsSync(configPath)) {
                    const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
                    if (cfg.proxy) {
                        rawProxy = cfg.proxy;
                        log(`  Loaded proxy from config: ${rawProxy}`);
                        
                        // Normalize proxy — supports multiple formats:
                        //   protocol://user:pass@host:port  (standard URL)
                        //   protocol://host:port:user:pass  (simple format A)
                        //   protocol://user:pass:host:port  (simple format B)
                        //   host:port:user:pass             (no protocol)
                        const fourPartRegex = /^(?:(socks5|socks4|http|https):\/\/)?([^:@]+):([^:@]+):([^:@]+):([^:@]+)$/i;
                        const urlRegex = /^(?:(socks5|socks4|http|https):\/\/)?([^:@]+):([^:@]+)@([^:@]+):(\d+)$/i;
                        
                        let urlMatch = rawProxy.match(urlRegex);
                        if (urlMatch) {
                            // Already standard format: user:pass@host:port
                            const proto = (urlMatch[1] || 'http').toLowerCase();
                            normalizedProxy = `${proto}://${urlMatch[2]}:${urlMatch[3]}@${urlMatch[4]}:${urlMatch[5]}`;
                        } else {
                            let fourMatch = rawProxy.match(fourPartRegex);
                            if (fourMatch) {
                                const proto = (fourMatch[1] || 'http').toLowerCase();
                                const p1 = fourMatch[2], p2 = fourMatch[3], p3 = fourMatch[4], p4 = fourMatch[5];
                                // Detect format by checking which part is a port number
                                if (/^\d+$/.test(p2)) {
                                    // Format: host:port:user:pass
                                    normalizedProxy = `${proto}://${p3}:${p4}@${p1}:${p2}`;
                                } else if (/^\d+$/.test(p4)) {
                                    // Format: user:pass:host:port
                                    normalizedProxy = `${proto}://${p1}:${p2}@${p3}:${p4}`;
                                } else {
                                    normalizedProxy = rawProxy;
                                }
                            } else {
                                normalizedProxy = rawProxy;
                            }
                        }
                        log(`  Normalized proxy: ${normalizedProxy}`);

                        // Parse for Playwright format
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
                log(`  ⚠️ Failed to parse proxy from config: ${e.message}`);
            }

            // Check if profile has cookies
            const cookiePath = path.join(storageDir, 'Default', 'Network', 'Cookies');
            const loginPath = path.join(storageDir, 'Default', 'Login Data');
            if (fs.existsSync(cookiePath)) log(`  ✅ Cookies found (${Math.round(fs.statSync(cookiePath).size / 1024)}KB)`);
            else log('  ⚠️ No cookies file found in profile');
            if (fs.existsSync(loginPath)) log(`  ✅ Login Data found`);
        } else {
            log(`⚠️ Profile dir not found: ${profileDir}`);
        }
    }

    // Kill Chrome AND BAS worker processes using THIS specific profile (safe: won't touch user's browser)
    if (storageDir && fs.existsSync(storageDir)) {
        try {
            const { execSync } = require('child_process');
            const escaped = storageDir.replace(/\\/g, '\\\\\\\\');
            // Kill chrome.exe using this profile
            const wmicOut = execSync(
                `wmic process where "name='chrome.exe' and CommandLine like '%${escaped}%'" get ProcessId /format:csv`,
                { encoding: 'utf-8', timeout: 5000 }
            ).trim();
            const pids = wmicOut.split('\n')
                .map(l => l.trim().split(',').pop())
                .filter(p => p && /^\d+$/.test(p));
            if (pids.length > 0) {
                log(`Closing ${pids.length} Chrome process(es) using profile "${profile}"...`);
                for (const pid of pids) {
                    try { execSync(`taskkill /PID ${pid} /F`, { timeout: 3000 }); } catch (e) {}
                }
            }
        } catch (e) { /* wmic may not be available */ }

        // Kill BAS worker processes (they hold profile locks and prevent re-launch)
        try {
            const { execSync } = require('child_process');
            const workerOut = execSync(
                `wmic process where "name='worker.exe'" get ProcessId /format:csv`,
                { encoding: 'utf-8', timeout: 5000 }
            ).trim();
            const workerPids = workerOut.split('\n')
                .map(l => l.trim().split(',').pop())
                .filter(p => p && /^\d+$/.test(p));
            if (workerPids.length > 0) {
                log(`Closing ${workerPids.length} BAS worker process(es)...`);
                for (const pid of workerPids) {
                    try { execSync(`taskkill /PID ${pid} /F`, { timeout: 3000 }); } catch (e) {}
                }
            }
        } catch (e) {}
        
        if (true) await sleep(1500);

        // Also clean lock files
        const lockFiles = ['SingletonLock', 'SingletonSocket', 'SingletonCookie'];
        const dirs = [storageDir, path.join(storageDir, 'Default')];
        for (const dir of dirs) {
            for (const lf of [...lockFiles, 'LOCK', 'lockfile']) {
                try {
                    const p = path.join(dir, lf);
                    if (fs.existsSync(p)) fs.unlinkSync(p);
                } catch (e) {}
            }
        }
    }

    // ── Launch Browser ──
    const launchArgs = ['--no-sandbox', '--disable-blink-features=AutomationControlled', '--window-size=1280,900'];
    let context;

    if (engine === 'bablosoft') {
        log('Launching with Security Browser engine (fingerprint)...');
        const originalCwd = process.cwd();
        try {
            const browserExtDir = path.resolve(__dirname, '..', '..', '..', '..', 'tubecli', 'extensions', 'browser');
            process.chdir(browserExtDir);

            const { createRequire } = require('module');
            const extRequire = createRequire(path.join(browserExtDir, 'package.json'));
            const { plugin } = extRequire('playwright-with-fingerprints');

            // ── 1. Service key (REQUIRED for fingerprint injection) ──
            try {
                const https = require('https');
                const http = require('http');
                
                const fetchKey = (urlStr, redirectLimit = 5) => {
                    return new Promise((resolve, reject) => {
                        if (redirectLimit <= 0) {
                            reject(new Error('Too many redirects'));
                            return;
                        }
                        const url = new URL(urlStr);
                        const lib = url.protocol === 'https:' ? https : http;
                        
                        lib.get(urlStr, { timeout: 10000 }, (res) => {
                            const { statusCode } = res;
                            if ([301, 302, 307, 308].includes(statusCode) && res.headers.location) {
                                const redirectUrl = new URL(res.headers.location, urlStr).toString();
                                fetchKey(redirectUrl, redirectLimit - 1).then(resolve).catch(reject);
                                return;
                            }
                            
                            if (statusCode !== 200) {
                                reject(new Error(`HTTP status code ${statusCode}`));
                                return;
                            }
                            
                            let d = '';
                            res.on('data', c => d += c);
                            res.on('end', () => {
                                try {
                                    resolve(JSON.parse(d));
                                } catch (e) {
                                    reject(new Error(`Invalid JSON response: ${e.message}. Response prefix: ${d.substring(0, 100)}`));
                                }
                            });
                        }).on('error', reject);
                    });
                };

                const keyData = await fetchKey('https://api.tubecreate.com/api/fingerprints/key.php');
                if (keyData && keyData.status === 'success' && keyData.key) {
                    plugin.setServiceKey(Buffer.from(keyData.key, 'base64').toString('utf8'));
                    log('  ✅ Service key set.');
                } else {
                    log('  ⚠ Service key format invalid or status not success');
                }
            } catch (keyErr) {
                log('  ⚠ Service key failed: ' + keyErr.message);
            }

            // Set generous timeout for BAS engine requests (premium fingerprints are ~8MB)
            plugin.setRequestTimeout(120000);

            // ── 2. Detect installed engine & hotfix project.xml ──
            const ENGINE_MAP = {
                '30.0.0': '147.0.7727.56',
                '29.9.2': '146.0.7680.80',
                '29.8.1': '145.0.7632.46',
                '29.7.0': '144.0.7559.60',
            };
            let targetBasVer = null;
            let targetChromiumVer = null;
            const scriptDir = path.join(browserExtDir, 'data', 'script');
            if (fs.existsSync(scriptDir)) {
                const dirs = fs.readdirSync(scriptDir)
                    .filter(d => /^\d+\.\d+\.\d+$/.test(d))
                    .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));
                for (const d of dirs) {
                    if (fs.existsSync(path.join(scriptDir, d, 'FastExecuteScript.exe'))) {
                        targetBasVer = d;
                        targetChromiumVer = ENGINE_MAP[d] || null;
                        break;
                    }
                }
            }
            if (targetBasVer) {
                log(`  Engine: ${targetBasVer} (Chrome ${targetChromiumVer || '?'})`);
                if (targetChromiumVer) {
                    try {
                        plugin.useBrowserVersion(targetChromiumVer);
                    } catch (verErr) {
                        log(`  ⚠ plugin.useBrowserVersion failed: ${verErr.message.split('\n')[0]}. Proceeding anyway.`);
                    }
                }
                // Hotfix project.xml
                const projectXml = path.join(browserExtDir, 'node_modules', 'browser-with-fingerprints', 'project.xml');
                if (fs.existsSync(projectXml)) {
                    let xml = fs.readFileSync(projectXml, 'utf8');
                    xml = xml.replace(/<EngineVersion>.*?<\/EngineVersion>/, `<EngineVersion>${targetBasVer}</EngineVersion>`);
                    fs.writeFileSync(projectXml, xml, 'utf8');
                    log('  ✅ project.xml hotfixed.');
                }
            }

            // ── 3. Load fingerprint ──
            const fingerprintPath = path.join(storageDir, 'fingerprint.json');
            let fpData;
            if (fs.existsSync(fingerprintPath)) {
                // IMPORTANT: keep as raw string — plugin.useFingerprint requires typeof === 'string'
                fpData = fs.readFileSync(fingerprintPath, 'utf-8');
                log('  Loaded saved fingerprint.');
            } else {
                log('  No fingerprint. Fetching new...');
                // Build fetch options matching engine configuration
                const fetchOpts = {
                    tags: ['Microsoft Windows', 'Chrome'],
                    minWidth: 1280,
                    minHeight: 900,
                };
                // Set minBrowserVersion to match installed engine's Chromium major version
                if (targetChromiumVer) {
                    const majorVer = parseInt(targetChromiumVer.split('.')[0], 10);
                    if (majorVer > 0) {
                        fetchOpts.minBrowserVersion = majorVer;
                        log(`  Fingerprint filter: Chrome >= ${majorVer}, screen >= 1280x900`);
                    }
                }
                fpData = await plugin.fetch(fetchOpts);
                fs.mkdirSync(storageDir, { recursive: true });
                // fpData from plugin.fetch is already a string
                fs.writeFileSync(fingerprintPath, typeof fpData === 'string' ? fpData : JSON.stringify(fpData));
            }

            // Apply fingerprint — must be a string
            plugin.useFingerprint(typeof fpData === 'string' ? fpData : JSON.stringify(fpData));


            // ── 5. Launch ──
            // Use a separate profile dir for Security Browser to prevent Playwright lock/corruption timeouts
            const launchPath = (storageDir || path.join(execData.profiles_dir || '', profile)) + '_bas';
            
            // Clean ALL lock files recursively in both profile directories
            function cleanLocksRecursive(dir) {
                if (!fs.existsSync(dir)) return;
                let cleaned = 0;
                const lockNames = ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'LOCK', 'lockfile'];
                function walk(d) {
                    try {
                        const entries = fs.readdirSync(d, { withFileTypes: true });
                        for (const e of entries) {
                            const full = path.join(d, e.name);
                            if (e.isDirectory()) {
                                walk(full);
                            } else if (lockNames.includes(e.name)) {
                                try { fs.unlinkSync(full); cleaned++; } catch (err) {}
                            }
                        }
                    } catch (err) {}
                }
                walk(dir);
                if (cleaned > 0) log(`  🔓 Cleaned ${cleaned} lock files in ${path.basename(dir)}`);
            }
            for (const dir of [storageDir, launchPath]) {
                cleanLocksRecursive(dir);
            }

            if (normalizedProxy) {
                plugin.useProxy(normalizedProxy, { changeTimezone: true, changeGeolocation: true });
                log(`  ✅ Security Browser proxy applied: ${normalizedProxy}`);
            } else {
                plugin.proxy = null;
            }

            context = await plugin.launchPersistentContext(launchPath, {
                headless,
                args: ['--start-maximized', '--disable-blink-features=AutomationControlled'],
                timeout: 120000
            });
            log('✅ Security Browser launched with fingerprint.');
            process.chdir(originalCwd);
        } catch (basErr) {
            process.chdir(originalCwd);
            log('Security Browser failed: ' + String(basErr.message).split('\n')[0] + '. Falling back to Playwright...');
            try {
                for (const lf of ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'LOCK', 'lockfile']) {
                    try { fs.unlinkSync(path.join(storageDir, lf)); } catch (e) {}
                    try { fs.unlinkSync(path.join(storageDir, 'Default', lf)); } catch (e) {}
                }
                const ctxOpts = {
                    headless, args: [...launchArgs],
                    ignoreDefaultArgs: ['--enable-automation'], viewport: { width: 1280, height: 800 }
                };
                // SOCKS5 with auth: Chromium doesn't support it via Playwright proxy option
                // Use --proxy-server Chrome arg instead
                if (pwProxy && normalizedProxy && /^socks/i.test(normalizedProxy) && pwProxy.username) {
                    ctxOpts.args.push(`--proxy-server=${pwProxy.server}`);
                    log(`  ⚠️ SOCKS5+auth: using Chrome --proxy-server flag (auth may not work)`);
                } else if (pwProxy) {
                    ctxOpts.proxy = pwProxy;
                }
                context = await chromium.launchPersistentContext(storageDir, ctxOpts);
            } catch (e2) {
                log('Profile also failed: ' + String(e2.message).split('\n')[0]);
                log('Using fresh browser + cookies...');
                try {
                    const brOpts = { headless, args: [...launchArgs], ignoreDefaultArgs: ['--enable-automation'] };
                    if (pwProxy && normalizedProxy && /^socks/i.test(normalizedProxy) && pwProxy.username) {
                        brOpts.args.push(`--proxy-server=${pwProxy.server}`);
                    } else if (pwProxy) {
                        brOpts.proxy = pwProxy;
                    }
                    const browser = await chromium.launch(brOpts);
                    context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
                    const cookieFile = path.join(storageDir, 'cookies.json');
                    if (fs.existsSync(cookieFile)) {
                        try {
                            const cookies = JSON.parse(fs.readFileSync(cookieFile, 'utf-8'));
                            const cleaned = cookies.filter(c => c.name && c.domain).map(c => {
                                const cc = { ...c };
                                if (!['Strict', 'Lax', 'None'].includes(cc.sameSite)) cc.sameSite = 'Lax';
                                return cc;
                            });
                            await context.addCookies(cleaned);
                            log('  Injected ' + cleaned.length + ' cookies.');
                        } catch (ce) {}
                    }
                } catch (e3) {
                    log('❌ All launch methods failed: ' + e3.message);
                    throw e3;
                }
            }
        }
    } else {
    // ── Playwright: use bundled Chromium (NOT system Chrome) for profile compatibility ──
    log(headless ? 'Launching (Playwright headless)...' : 'Launching (Playwright)...');
    if (storageDir) {
        for (const lf of ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'LOCK', 'lockfile']) {
            try { fs.unlinkSync(path.join(storageDir, lf)); } catch (e) {}
            try { fs.unlinkSync(path.join(storageDir, 'Default', lf)); } catch (e) {}
        }
        try {
            const ctxOpts = {
                headless, args: launchArgs,
                ignoreDefaultArgs: ['--enable-automation'],
                viewport: { width: 1280, height: 800 }
            };
            if (pwProxy) ctxOpts.proxy = pwProxy;
            context = await chromium.launchPersistentContext(storageDir, ctxOpts);
            log('Profile loaded with Playwright Chromium.');
        } catch (e) {
            log('PersistentContext failed: ' + String(e.message).split('\n')[0]);
            log('Falling back to fresh browser + cookie injection...');
            const brOpts = { headless, args: launchArgs, ignoreDefaultArgs: ['--enable-automation'] };
            if (pwProxy) brOpts.proxy = pwProxy;
            const browser = await chromium.launch(brOpts);
            context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
            const cookieFile = path.join(storageDir, 'cookies.json');
            if (fs.existsSync(cookieFile)) {
                try {
                    const cookies = JSON.parse(fs.readFileSync(cookieFile, 'utf-8'));
                    if (Array.isArray(cookies) && cookies.length > 0) {
                        const cleaned = cookies.map(c => {
                            const cc = { ...c };
                            if (!['Strict', 'Lax', 'None'].includes(cc.sameSite)) cc.sameSite = 'Lax';
                            return cc;
                        });
                        await context.addCookies(cleaned);
                        log('  Injected ' + cleaned.length + ' cookies from profile.');
                    }
                } catch (ce) { log('  Cookie load failed: ' + ce.message); }
            }
        }
    } else {
        const browser = await chromium.launch({ headless, args: launchArgs, ignoreDefaultArgs: ['--enable-automation'] });
        context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    }
    }
    const page = context.pages()[0] || await context.newPage();
    log('Browser launched.');

    // ── CDP WebSocket Preview: start BEFORE execution so frontend sees it live ──
    const http = require('http');
    const net = require('net');
    const { WebSocketServer } = require('ws');

    const tmpSrv = net.createServer();
    const previewPort = await new Promise(r => { tmpSrv.listen(0, () => { const p = tmpSrv.address().port; tmpSrv.close(() => r(p)); }); });

    let cdp;
    try {
        cdp = await page.context().newCDPSession(page);
    } catch (e) {
        log(`CDP session failed: ${e.message}`);
    }

    const httpServer = http.createServer((req, res) => {
        res.setHeader('Access-Control-Allow-Origin', '*');
        if (req.url === '/status') {
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ status: 'open', profile, ws: true }));
        } else if (req.url.startsWith('/screenshot')) {
            page.screenshot({ type: 'jpeg', quality: 60 }).then(buf => {
                res.writeHead(200, { 'Content-Type': 'image/jpeg' });
                res.end(buf);
            }).catch(() => { res.writeHead(500); res.end(); });
        } else { res.writeHead(404); res.end(); }
    });

    const wss = new WebSocketServer({ server: httpServer });
    let activeClients = new Set();

    // Broadcast current URL to all connected clients
    function broadcastUrl() {
        const url = page.url();
        const msg = JSON.stringify({ type: 'url_changed', url });
        for (const c of activeClients) {
            if (c.readyState === 1) c.send(msg);
        }
    }

    // Listen for page navigations and broadcast URL changes
    page.on('framenavigated', (frame) => {
        if (frame === page.mainFrame()) broadcastUrl();
    });

    wss.on('connection', (ws) => {
        activeClients.add(ws);
        log('Preview client connected (WebSocket)');
        // Send current URL immediately on connect
        ws.send(JSON.stringify({ type: 'url_changed', url: page.url() }));

        if (cdp) {
            cdp.send('Page.startScreencast', {
                format: 'jpeg', quality: 50, maxWidth: 1280, maxHeight: 900,
                everyNthFrame: 2,
            }).catch(() => {});
        }

        ws.on('message', async (raw) => {
            try {
                const msg = JSON.parse(raw.toString());
                if (msg.type === 'mouse') {
                    const { action, x, y, button } = msg;
                    if (action === 'move') await page.mouse.move(x, y);
                    else if (action === 'click') await page.mouse.click(x, y, { button: button || 'left' });
                    else if (action === 'down') await page.mouse.down();
                    else if (action === 'up') await page.mouse.up();
                } else if (msg.type === 'keyboard') {
                    if (msg.action === 'type') await page.keyboard.type(msg.text);
                    else if (msg.action === 'press') await page.keyboard.press(msg.key);
                } else if (msg.type === 'scroll') {
                    await page.mouse.wheel(msg.deltaX || 0, msg.deltaY || 0);
                } else if (msg.type === 'pick_element') {
                    const selector = await page.evaluate(({ x, y }) => {
                        const el = document.elementFromPoint(x, y);
                        if (!el) return null;
                        if (el.id) return `#${el.id}`;
                        if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`;
                        if (el.getAttribute('aria-label')) return `[aria-label="${el.getAttribute('aria-label')}"]`;
                        if (el.placeholder) return `[placeholder="${el.placeholder}"]`;
                        if (el.className && typeof el.className === 'string') {
                            const cls = el.className.trim().split(/\s+/)[0];
                            if (cls) return `${el.tagName.toLowerCase()}.${cls}`;
                        }
                        const path = [];
                        let node = el;
                        while (node && node !== document.body) {
                            let seg = node.tagName.toLowerCase();
                            if (node.id) { path.unshift(`#${node.id}`); break; }
                            const parent = node.parentElement;
                            if (parent) {
                                const siblings = Array.from(parent.children).filter(c => c.tagName === node.tagName);
                                if (siblings.length > 1) seg += `:nth-child(${Array.from(parent.children).indexOf(node) + 1})`;
                            }
                            path.unshift(seg);
                            node = node.parentElement;
                        }
                        return path.join(' > ');
                    }, { x: msg.x, y: msg.y });
                    ws.send(JSON.stringify({ type: 'picked', selector }));
                } else if (msg.type === 'hover_inspect') {
                    const info = await page.evaluate(({ x, y }) => {
                        const el = document.elementFromPoint(x, y);
                        if (!el) return null;
                        const rect = el.getBoundingClientRect();
                        return {
                            tag: el.tagName.toLowerCase(),
                            id: el.id || '',
                            classes: el.className?.toString?.()?.slice(0, 60) || '',
                            text: el.innerText?.slice(0, 40) || '',
                            rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
                        };
                    }, { x: msg.x, y: msg.y }).catch(() => null);
                    if (info) ws.send(JSON.stringify({ type: 'inspect', ...info }));
                } else if (msg.type === 'navigate') {
                    // Navigate to URL
                    try {
                        await page.goto(msg.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
                        broadcastUrl();
                    } catch (e) {}
                } else if (msg.type === 'nav') {
                    // Back / Forward / Reload
                    try {
                        if (msg.action === 'back') await page.goBack({ waitUntil: 'domcontentloaded', timeout: 10000 });
                        else if (msg.action === 'forward') await page.goForward({ waitUntil: 'domcontentloaded', timeout: 10000 });
                        else if (msg.action === 'reload') await page.reload({ waitUntil: 'domcontentloaded', timeout: 15000 });
                        broadcastUrl();
                    } catch (e) {}
                }
            } catch (e) {}
        });

        ws.on('close', () => {
            activeClients.delete(ws);
            if (activeClients.size === 0 && cdp) {
                cdp.send('Page.stopScreencast').catch(() => {});
            }
        });
    });

    if (cdp) {
        cdp.on('Page.screencastFrame', (params) => {
            const vp = page.viewportSize() || { width: 1280, height: 900 };
            const frame = { type: 'frame', data: params.data, metadata: params.metadata, viewport: vp };
            const msg = JSON.stringify(frame);
            for (const ws of activeClients) {
                if (ws.readyState === 1) ws.send(msg);
            }
            cdp.send('Page.screencastFrameAck', { sessionId: params.sessionId }).catch(() => {});
        });
    }

    // Start WS server BEFORE executing steps — emit preview_port immediately
    await new Promise(r => httpServer.listen(previewPort, r));
    console.log(JSON.stringify({
        status: 'log', exec_id,
        preview_port: previewPort,
        preview_ws: true,
        message: `Live preview ready on port ${previewPort}`,
        time: new Date().toISOString(),
    }));

    // ── Pause/resume support ──
    paused = false;
    stopped = false;

    // Listen for pause/resume/stop from WS clients
    wss.on('connection', (ws2) => {
        ws2.on('message', (raw) => {
            try {
                const m = JSON.parse(raw.toString());
                if (m.type === 'pause') { paused = true; log('⏸ Script paused.'); }
                else if (m.type === 'resume') { paused = false; log('▶ Script resumed.'); }
                else if (m.type === 'stop_script') { stopped = true; paused = false; log('⏹ Script stop requested.'); }
            } catch (e) {}
        });
    });

    // ── Now execute steps (frontend is already connected and watching) ──
    let success = false;
    try {
        for (let i = 0; i < steps.length; i++) {
            await waitIfPaused();
            if (stopped) { log('Script stopped by user.'); break; }
            await executeStepWithRetry(page, steps[i], i);
        }
        log('All steps completed successfully.');
        success = true;
    } catch (err) {
        log(`Execution failed: ${err.message}`);
        process.exitCode = 1;
    }

    // Save cookies back to profile (for Playwright mode)
    if (storageDir && engine !== 'bablosoft') {
        try {
            const updatedCookies = await context.cookies();
            if (updatedCookies.length > 0) {
                fs.writeFileSync(path.join(storageDir, 'cookies.json'), JSON.stringify(updatedCookies, null, 2));
                log(`Saved ${updatedCookies.length} cookies back to profile.`);
            }
        } catch (e) {}
    }

    // Write variables output for skill execution
    try {
        const resultFile = path.join(path.dirname(execFile), `result_${exec_id}.json`);
        fs.writeFileSync(resultFile, JSON.stringify({ success, variables }, null, 2), 'utf-8');
    } catch (e) {
        log(`Failed to write result file: ${e.message}`);
    }

    // Signal completion
    console.log(JSON.stringify({
        status: 'done', exec_id, success,
        preview_port: previewPort,
        preview_ws: true,
        message: success ? (headless ? 'Completed!' : 'Completed! Browser kept open for preview.') : (headless ? 'Failed.' : 'Failed. Browser kept open for inspection.')
    }));

    if (headless) {
        try { if (cdp) cdp.send('Page.stopScreencast').catch(() => {}); httpServer.close(); await context.close(); } catch (e) {}
        process.exit(success ? 0 : 1);
    }

    // Close when browser is closed by user
    context.on('close', () => { httpServer.close(); process.exit(0); });

    process.on('SIGTERM', async () => {
        try { if (cdp) cdp.send('Page.stopScreencast').catch(() => {}); httpServer.close(); await context.close(); } catch (e) {}
        process.exit(0);
    });
})();