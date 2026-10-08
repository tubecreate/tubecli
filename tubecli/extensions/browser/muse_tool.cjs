// Muse (muse.ai — agent AI của Meta) qua phiên trình duyệt ĐÃ ĐĂNG NHẬP của một hồ sơ TubeCLI.
//
// Vì sao lái trình duyệt: Muse không có API. Chat đi qua một WebSocket MÃ HOÁ (giao thức Noise:
// X25519 + HKDF + AES-GCM, token ký Ed25519 trong URL — wss://hatch.metaaivm.com/v1/noise), nên
// cách chắc là để chính ứng dụng web của Muse làm hết phần mật mã, ta chỉ gõ câu hỏi vào ô soạn
// và đọc câu trả lời trên DOM. Cách làm theo github.com/duclm1x1/Muse-Chat-MCP, selector đo lại
// trên phiên thật 2/10/2026 (giao diện tiếng Việt — mọi selector ở đây KHÔNG dựa vào chữ hiển thị).
//
// Mỗi lượt mở MỘT TAB RIÊNG trong phiên đang chạy rồi đóng nó: tab người dùng đang xem không bị
// đổi trang. connectOverCDP: TUYỆT ĐỐI không browser.close() — đóng là giết phiên của người dùng.
//
// Dùng:
//   node muse_tool.cjs --cdp <port> --action status
//   node muse_tool.cjs --cdp <port> --action ask --in <req.json>
// req.json: {prompt, thread: "new"|"<uuid>", timeout_ms, want_images, image_dir, max_images, want_videos, video_dir,
//            max_videos, files: [đường dẫn]}
// In kết quả giữa __MUSE_RESULT__ và __MUSE_END__ để phía Python bóc (tubecli/core/muse.py).
const fs = require('fs');
const path = require('path');

const MUSE = 'https://muse.ai';
const SEL = {
  composer: '[data-hatch-composer-root]',
  textarea: '[data-hatch-composer-root] textarea',
  fileInput: '[data-hatch-composer-root] input[type="file"]',
  actionSlot: '[data-hatch-composer-action-slot]',
  stop: '[data-testid="hatch-composer-stop-button"]',
  streaming: '[data-hatch-markdown-streaming="true"]',
  message: '[data-message-item]',
  error: '[data-testid="assistant-response-error-notice"]',
  approval: '[data-hatch-composer-approval-stack]',
  video: '[data-hatch-video-wrapper] video, video',
};
// Câu trả lời coi là XONG khi không còn nút dừng / chữ đang chạy và đứng yên chừng này.
const QUIET_MS = 1800;
// Xin ảnh mà lượt trả lời đã đứng yên chừng này vẫn không có ảnh → coi như Muse không vẽ.
const IMAGE_GRACE_MS = 60000;
// Ảnh nhỏ hơn cạnh này là avatar / biểu tượng, không phải ảnh Muse vẽ.
const MIN_IMAGE_EDGE = 256;
// Xin video mà ô trả lời đã đứng yên chừng này vẫn chưa có video → coi như Muse không làm. Đo 2/10/2026: ô trả lời
// thường xuất hiện KHI video đã xong (~90 s), nhưng có lượt Muse bày một ô trợ lý RỖNG (nút dừng đã tắt) rồi mới gắn
// video sau hơn 90 s nữa — 90 s ân hạn trả «empty reply» trong khi video vẫn về. Nên 4 phút.
const VIDEO_GRACE_MS = 240000;

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function emit(obj) {
  process.stdout.write('__MUSE_RESULT__' + JSON.stringify(obj) + '__MUSE_END__\n');
}

async function authCheck(page) {
  try {
    return await page.evaluate(async () => {
      try {
        const r = await fetch('/api/auth/check', {
          method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}', credentials: 'same-origin',
        });
        const j = await r.json().catch(() => null);
        return { status: r.status, ok: !!(j && j.ok), viewer: (j && j.viewer_id) || '' };
      } catch (e) { return { status: 0, ok: false, error: String(e) }; }
    });
  } catch (e) {
    return { status: 0, ok: false, error: String((e && e.message) || e) };
  }
}

async function sessionCookie(ctx) {
  try {
    const now = Date.now() / 1000;
    const cks = await ctx.cookies(MUSE);
    const c = cks.find((x) => x.name === 'hatch_sess');
    return !!(c && (c.expires <= 0 || c.expires > now));
  } catch { return false; }
}

// ── dọn tab (user 8/10/2026: «muse quá tải là quá nhiều tab, xoá bớt tab không cần mỗi lần tạo xong») ────────────
// Tab việc đóng ở finally, nhưng lượt bị Python giết vì quá giờ (clip 600 s) thì finally không chạy → tab mồ côi dồn
// dần; muse.ai cũng tự bật tab phụ. Giữ MỘT tab muse.ai (tab đầu — status() gõ cửa nó), đóng mọi tab muse.ai khác và
// tab trống. KHÔNG đụng tab trang khác: hồ sơ có thể là trình duyệt người dùng đang mở tay. `keep` = tab việc đang dùng.
async function pruneTabs(ctx, keep) {
  let closed = 0;
  const pages = ctx.pages();
  const home = pages.find((p) => p !== keep && p.url().startsWith(MUSE));
  for (const p of pages) {
    if (p === keep || p === home) continue;
    const u = p.url();
    if (u.startsWith(MUSE) || u === 'about:blank' || u === '') {
      await p.close().catch(() => {});
      closed++;
    }
  }
  return closed;
}

// ── status: KHÔNG mở tab mới (bảng chọn model gõ cửa mỗi lần mở) ─────────────────────────────
async function status(ctx) {
  const page = ctx.pages().find((p) => p.url().startsWith(MUSE));
  const cookie = await sessionCookie(ctx);
  if (page) {
    const a = await authCheck(page);
    return { ok: true, logged_in: !!a.ok, verified: true, session_cookie: cookie, tab_open: true };
  }
  // Không có tab Muse nào: cookie phiên còn hạn là dấu hiệu đủ tốt — lượt hỏi thật sẽ kiểm lại.
  return { ok: true, logged_in: cookie, verified: false, session_cookie: cookie, tab_open: false };
}

// Tình trạng lượt trả lời của tin người dùng vừa gửi (tin người dùng cuối cùng không có trong `seen`):
// mọi tin của trợ lý đứng SAU nó trong DOM. Muse tách một lượt thành nhiều ô (chữ, rồi ảnh) cùng data-message-turn-id.
function turnState(page, seen, minEdge) {
  return page.evaluate(({ seen, sel, minEdge }) => {
    const items = [...document.querySelectorAll(sel.message)];
    const mine = items.filter((e) => e.getAttribute('data-message-role') === 'user'
      && !seen.includes(e.getAttribute('data-message-id'))).pop();
    const after = mine ? items.filter((e) => mine.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING) : [];
    const asst = after.filter((e) => e.getAttribute('data-message-role') === 'assistant');
    const imgs = [];
    const vids = [];
    let pending = false;
    for (const e of asst) {
      for (const i of e.querySelectorAll('img')) {
        const src = i.currentSrc || i.src || '';
        if (!/^(blob:|https?:)/.test(src)) continue;
        if (!i.complete) { pending = true; continue; }
        if (Math.max(i.naturalWidth, i.naturalHeight) < minEdge) continue;
        // Poster của video cũng là <img> trong ô — không tính là ảnh vẽ.
        if (i.closest('[data-hatch-video-wrapper]')) continue;
        imgs.push(i.naturalWidth + 'x' + i.naturalHeight);
      }
      for (const v of e.querySelectorAll(sel.video)) {
        const src = v.currentSrc || v.src || (v.closest('[data-hatch-video-wrapper]') || {}).getAttribute?.('data-hatch-video-src') || '';
        if (!/^(blob:|https?:)/.test(src)) continue;
        // readyState < 1: chưa đọc được metadata (độ dài/kích thước) — còn đang tải.
        if (v.readyState < 1 || !(v.duration > 0)) { pending = true; continue; }
        vids.push(v.videoWidth + 'x' + v.videoHeight + '@' + Math.round(v.duration));
      }
    }
    const err = document.querySelector(sel.error);
    return {
      n: asst.length,
      lens: asst.map((e) => (e.innerText || '').length),
      imgs,
      vids,
      pending,
      stop: !!document.querySelector(sel.stop),
      streaming: !!document.querySelector(sel.streaming),
      busy: asst.some((e) => e.querySelector('[aria-busy="true"]')),
      error: err ? (err.innerText || 'assistant error').trim() : '',
      approval: !!document.querySelector(sel.approval),
    };
  }, { seen, sel: SEL, minEdge });
}

// Chữ của từng ô trả lời. innerText của thân tin (bộ vẽ markdown «streamdown») giữ đủ xuống dòng, chỉ
// có khối mã là lẫn nhãn ngôn ngữ ("json" rồi mới tới "{…") — thay khối ấy bằng ```lang … ``` để
// JSON/kịch bản bóc được nguyên vẹn. KHÔNG dùng nút «Sao chép phản hồi»: đo 2/10/2026 nó chép textContent, mất hết
// xuống dòng trong khối mã.
async function replyTexts(page, seen) {
  return page.evaluate(({ seen, sel }) => {
    const items = [...document.querySelectorAll(sel.message)];
    const mine = items.filter((e) => e.getAttribute('data-message-role') === 'user'
      && !seen.includes(e.getAttribute('data-message-id'))).pop();
    const asst = items.filter((e) => mine && (mine.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)
      && e.getAttribute('data-message-role') === 'assistant');
    const out = [];
    for (const e of asst) {
      const body = e.querySelector('[data-hatch-assistant-message-body]') || e;
      let text = body.innerText || '';
      for (const cb of body.querySelectorAll('[data-streamdown="code-block"]')) {
        const pre = cb.querySelector('pre');
        if (!pre) continue;
        const lang = cb.getAttribute('data-language') || '';
        const fenced = '```' + lang + '\n' + (pre.innerText || '').replace(/\n+$/, '') + '\n```';
        const shown = cb.innerText || '';
        if (shown && text.includes(shown)) text = text.replace(shown, fenced);
      }
      text = text.trim();
      if (text) out.push(text);
    }
    return out;
  }, { seen, sel: SEL });
}

async function saveImages(page, seen, dir, maxImages) {
  const blobs = await page.evaluate(async ({ seen, sel, minEdge, maxImages }) => {
    const items = [...document.querySelectorAll(sel.message)];
    const mine = items.filter((e) => e.getAttribute('data-message-role') === 'user'
      && !seen.includes(e.getAttribute('data-message-id'))).pop();
    const asst = items.filter((e) => mine && (mine.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)
      && e.getAttribute('data-message-role') === 'assistant');
    const got = new Set();
    const out = [];
    for (const e of asst) {
      for (const i of e.querySelectorAll('img')) {
        const src = i.currentSrc || i.src || '';
        if (!/^(blob:|https?:)/.test(src) || got.has(src)) continue;
        if (Math.max(i.naturalWidth, i.naturalHeight) < minEdge) continue;
        got.add(src);
        if (out.length >= maxImages) break;
        try {
          const res = await fetch(src, { credentials: 'include' });
          const b = new Uint8Array(await res.arrayBuffer());
          let s = '';
          for (let k = 0; k < b.length; k += 0x8000) s += String.fromCharCode.apply(null, b.subarray(k, k + 0x8000));
          out.push({ ok: res.ok, mime: res.headers.get('content-type') || '', b64: btoa(s),
            width: i.naturalWidth, height: i.naturalHeight, alt: i.alt || '' });
        } catch (err) { out.push({ ok: false, error: String(err) }); }
      }
    }
    return out;
  }, { seen, sel: SEL, minEdge: MIN_IMAGE_EDGE, maxImages });
  const saved = [];
  if (!blobs.length) return saved;
  fs.mkdirSync(dir, { recursive: true });
  const stamp = Date.now().toString(36);
  blobs.forEach((b, i) => {
    if (!b.ok || !b.b64) { saved.push({ error: b.error || 'download failed' }); return; }
    const buf = Buffer.from(b.b64, 'base64');
    const ext = /png/.test(b.mime) ? '.png' : /jpe?g/.test(b.mime) ? '.jpg' : /webp/.test(b.mime) ? '.webp' : '.bin';
    const file = path.join(dir, `muse_${stamp}_${i}${ext}`);
    fs.writeFileSync(file, buf);
    saved.push({ path: file, mime: b.mime, bytes: buf.length, width: b.width, height: b.height });
  });
  return saved;
}

// Video Muse làm (image→video / text→video, ~10 s mỗi clip): tải blob qua fetch trong trang, kèm poster.
async function saveVideos(page, seen, dir, maxVideos) {
  const blobs = await page.evaluate(async ({ seen, sel, maxVideos }) => {
    const items = [...document.querySelectorAll(sel.message)];
    const mine = items.filter((e) => e.getAttribute('data-message-role') === 'user'
      && !seen.includes(e.getAttribute('data-message-id'))).pop();
    const asst = items.filter((e) => mine && (mine.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)
      && e.getAttribute('data-message-role') === 'assistant');
    const got = new Set();
    const out = [];
    const grab = async (src) => {
      const res = await fetch(src, { credentials: 'include' });
      const b = new Uint8Array(await res.arrayBuffer());
      let s = '';
      for (let k = 0; k < b.length; k += 0x8000) s += String.fromCharCode.apply(null, b.subarray(k, k + 0x8000));
      return { ok: res.ok, mime: res.headers.get('content-type') || '', b64: btoa(s) };
    };
    for (const e of asst) {
      for (const v of e.querySelectorAll(sel.video)) {
        const wrap = v.closest('[data-hatch-video-wrapper]');
        const src = v.currentSrc || v.src || (wrap ? wrap.getAttribute('data-hatch-video-src') : '') || '';
        if (!/^(blob:|https?:)/.test(src) || got.has(src)) continue;
        got.add(src);
        if (out.length >= maxVideos) break;
        try {
          const item = { ...(await grab(src)), width: v.videoWidth, height: v.videoHeight, duration: v.duration,
            name: wrap ? (wrap.getAttribute('aria-label') || '').slice(0, 200) : '' };
          const poster = wrap ? wrap.getAttribute('data-hatch-video-poster') : (v.poster || '');
          if (poster && /^(blob:|https?:)/.test(poster)) {
            try { item.poster = await grab(poster); } catch { /* poster không bắt buộc */ }
          }
          out.push(item);
        } catch (err) { out.push({ ok: false, error: String(err) }); }
      }
    }
    return out;
  }, { seen, sel: SEL, maxVideos });
  const saved = [];
  if (!blobs.length) return saved;
  fs.mkdirSync(dir, { recursive: true });
  const stamp = Date.now().toString(36);
  blobs.forEach((b, i) => {
    if (!b.ok || !b.b64) { saved.push({ error: b.error || 'download failed' }); return; }
    const buf = Buffer.from(b.b64, 'base64');
    const ext = /webm/.test(b.mime) ? '.webm' : '.mp4';
    const file = path.join(dir, `muse_${stamp}_${i}${ext}`);
    fs.writeFileSync(file, buf);
    const rec = { path: file, mime: b.mime, bytes: buf.length, width: b.width, height: b.height, duration: b.duration, name: b.name };
    if (b.poster && b.poster.ok && b.poster.b64) {
      const pext = /png/.test(b.poster.mime) ? '.png' : /webp/.test(b.poster.mime) ? '.webp' : '.jpg';
      rec.poster = path.join(dir, `muse_${stamp}_${i}_poster${pext}`);
      fs.writeFileSync(rec.poster, Buffer.from(b.poster.b64, 'base64'));
    }
    saved.push(rec);
  });
  return saved;
}

// ── ask: gõ một câu vào chat (mới hoặc chat phụ đang dùng), chờ trả lời xong, lấy chữ + ảnh/video ────
async function ask(ctx, req) {
  const t0 = Date.now();
  const timeout = Math.max(15000, Number(req.timeout_ms) || 240000);
  const thread = String(req.thread || 'new').trim();
  if (thread !== 'new' && !/^[0-9a-f-]{36}$/i.test(thread)) {
    return { ok: false, kind: 'error', error: `bad thread id: ${thread}` };
  }
  const prompt = String(req.prompt || '');
  const files = (Array.isArray(req.files) ? req.files : []).filter((f) => f && fs.existsSync(f));
  if (!prompt.trim() && !files.length) return { ok: false, kind: 'error', error: 'prompt is empty' };

  const pruned = await pruneTabs(ctx, null).catch(() => 0);
  const page = await ctx.newPage();
  try {
    // Tab làm việc phải "đang hiện": tab nền ngừng vẽ khung, chữ đang chạy của Muse có thể đứng.
    try {
      const cdp = await ctx.newCDPSession(page);
      await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: true });
    } catch { /* bản Chromium không hỗ trợ — vẫn chạy */ }
    page.setDefaultTimeout(30000);
    await page.goto(`${MUSE}/thread/${thread}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const ta = page.locator(SEL.textarea).first();
    try {
      await ta.waitFor({ state: 'visible', timeout: 45000 });
    } catch {
      const a = await authCheck(page);
      if (!a.ok) return { ok: false, kind: 'auth', error: 'Muse is not signed in on this browser profile.', url: page.url() };
      return { ok: false, kind: 'error', error: 'Muse chat box did not appear.', url: page.url() };
    }
    const a = await authCheck(page);
    if (!a.ok) return { ok: false, kind: 'auth', error: 'Muse is not signed in on this browser profile.', url: page.url() };
    // Chat phụ cũ: chờ lịch sử hiện xong (số ô đứng yên) để biết đâu là tin MỚI của mình.
    let lastN = -1;
    for (let i = 0; i < 12; i++) {
      const n = await page.locator(SEL.message).count();
      if (n === lastN) break;
      lastN = n;
      await sleep(400);
    }
    // Id các ô ĐÃ CÓ trước khi gửi. Tin của mình = tin người dùng CUỐI không nằm trong danh sách này — KHÔNG
    // bám theo id: Muse vẽ tin vừa gửi bằng id tạm rồi thay bằng id của máy chủ (đo 2/10/2026).
    let seen = await page.locator(SEL.message).evaluateAll(
      (els) => els.map((e) => e.getAttribute('data-message-id')));

    if (files.length) {
      // Đính QUÁ SỚM (ô soạn vừa hiện, React chưa gắn xong) → Muse LẶNG LẼ bỏ ảnh mà tin vẫn gửi đi: Muse vẽ / dựng từ
      // ảnh CŨ trong chat hoặc tự bịa người (đo 3/10/2026: demo 2 người mất hẳn chàng trai, clip 3 của #165 bắt đầu
      // từ khung cuối clip 1). Đính xong phải THẤY đủ ảnh xem trước (img blob:/data: trong ô soạn); thiếu thì đính
      // lại MỘT lần; vẫn thiếu thì báo lỗi — thà lỗi còn hơn gửi tin thiếu ảnh.
      const previews = () => page.locator(SEL.composer).first().evaluate(
        (e) => [...e.querySelectorAll('img')].filter((i) => /^(blob|data):/.test(i.src || '')).length).catch(() => 0);
      const base = await previews();
      let got = 0;
      for (let round = 0; round < 2 && got < files.length; round++) {
        if (round) {
          if (process.env.MUSE_DEBUG) console.error(`[muse] only ${got}/${files.length} attachment(s) showed — attaching again`);
          await sleep(2500);
        }
        await page.locator(SEL.fileInput).first().setInputFiles(files);
        const until = Date.now() + 12000;
        while (Date.now() < until) {
          got = (await previews()) - base;
          if (got >= files.length) break;
          await sleep(300);
        }
      }
      if (got < files.length) {
        return { ok: false, kind: 'error', error: `Muse did not take the attached image(s): ${Math.max(0, got)}/${files.length} showed in the composer.`, url: page.url() };
      }
      await sleep(800);
    }
    // Ảnh lớn (bảng panorama PNG 2,5 MB — #160, 2/10/2026) tải lên lâu, ô soạn tin bị khoá quá 30 s → có file thì chờ
    // tới 150 s; vẫn kẹt thì Esc (đóng lớp phủ) rồi ép bấm.
    try {
      await ta.click({ timeout: files && files.length ? 150000 : 30000 });
    } catch {
      await page.keyboard.press('Escape').catch(() => {});
      await ta.click({ force: true, timeout: 10000 });
    }
    // Nhận tin CỦA MÌNH theo đuôi nội dung của chính prompt. 5/10/2026: chat phụ dùng lại mà lịch sử hiện CHẬM (sau khi
    // chụp `seen`) thì «tin người dùng cuối chưa thấy» là tin của LƯỢT TRƯỚC ⇒ trả ảnh của lượt trước sau ~10 s (vẽ
    // thật mất 27–60 s): #275 có 11 tấm trùng. Bản đầu (b6667c2) gắn mã «[message id …]» vào cuối tin — Muse hiểu sai cả
    // tin (#276: vẽ lời dặn style thành chữ «white chalk», nhãn tiếng Anh thay nhãn Đức) ⇒ KHÔNG chèn gì vào tin nữa.
    // So chữ-và-số (bỏ dấu câu, khoảng trắng): Muse hiển thị tin có thể đổi ngoặc/xuống dòng. textContent để tin dài
    // bị thu gọn vẫn khớp.
    const alnum = (s) => String(s || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
    const mark = alnum(prompt).slice(-48);
    await ta.fill(prompt);
    await sleep(200);
    await ta.press('Enter');

    // Đã gửi = có tin người dùng MỚI mang đuôi prompt của mình. Enter không ăn (ô soạn chưa sẵn) thì bấm nút gửi.
    let myId = '';
    const findMine = (needMark) => page.locator(`${SEL.message}[data-message-role="user"]`).evaluateAll(
      (els, { seen, mark, needMark }) => {
        const norm = (s) => String(s || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
        const fresh = els.filter((x) => !seen.includes(x.getAttribute('data-message-id'))).reverse();
        const e = needMark && mark ? fresh.find((x) => norm(x.textContent).includes(mark)) : fresh[0];
        return e ? e.getAttribute('data-message-id') : '';
      }, { seen, mark, needMark });
    for (let i = 0; i < 40 && !myId; i++) {
      await sleep(250);
      myId = await findMine(true);
      if (!myId && i === 16) {
        const left = await ta.inputValue().catch(() => '');
        if (left.trim()) await page.locator(`${SEL.actionSlot} button`).last().click({ timeout: 3000 }).catch(() => {});
      }
    }
    if (!myId) {
      // Muse hiện tin mà không có mã (đổi cách hiển thị?) — lùi về cách cũ, có ghi lại để còn biết.
      myId = await findMine(false);
      if (myId && process.env.MUSE_DEBUG) console.error(`[muse] own message found without its mark ${mark}`);
    }
    if (!myId) return { ok: false, kind: 'error', error: 'Muse did not accept the message (nothing was sent).', url: page.url() };
    // Từ đây «tin của mình» = tin người dùng duy nhất KHÔNG nằm trong `seen`: mọi tin người dùng khác đang có (kể cả
    // lịch sử hiện muộn) vào `seen`. Muse đổi id tạm của tin mình sang id máy chủ thì tin ấy vẫn ngoài `seen`.
    seen = await page.locator(`${SEL.message}[data-message-role="user"]`).evaluateAll(
      (els, myId) => els.map((e) => e.getAttribute('data-message-id')).filter((id) => id !== myId), myId);
    const sentMs = Date.now() - t0;

    const deadline = t0 + timeout;
    let sig = '';
    let changedAt = Date.now();
    let st = null;
    let firstMs = 0;
    while (Date.now() < deadline) {
      st = await turnState(page, seen, MIN_IMAGE_EDGE);
      const s = JSON.stringify([st.n, st.lens, st.imgs, st.vids, st.pending, st.stop, st.streaming, st.busy]);
      if (s !== sig) {
        sig = s; changedAt = Date.now();
        if (process.env.MUSE_DEBUG) console.error(`[muse] +${((Date.now() - t0) / 1000).toFixed(1)}s ${s} mine=${myId}`);
      }
      if (!firstMs && st.n > 0) firstMs = Date.now() - t0;
      if (st.error && !st.stop) break;
      if (st.approval && !st.stop) break;
      const idle = Date.now() - changedAt;
      const settled = st.n > 0 && !st.stop && !st.streaming && !st.busy && !st.pending && idle >= QUIET_MS;
      const gotImages = !req.want_images || st.imgs.length > 0 || idle >= IMAGE_GRACE_MS;
      const gotVideos = !req.want_videos || st.vids.length > 0 || idle >= VIDEO_GRACE_MS;
      if (settled && gotImages && gotVideos) break;
      await sleep(400);
    }
    const timedOut = Date.now() >= deadline;
    const threadId = ((page.url().match(/\/thread\/([0-9a-f-]{36})/i) || [])[1]) || '';
    const texts = await replyTexts(page, seen);
    const images = req.want_images
      ? await saveImages(page, seen, req.image_dir || path.join(process.cwd(), 'muse_images'), Math.max(1, Number(req.max_images) || 4))
      : [];
    const videos = req.want_videos
      ? await saveVideos(page, seen, req.video_dir || req.image_dir || path.join(process.cwd(), 'muse_videos'), Math.max(1, Number(req.max_videos) || 1))
      : [];
    const out = {
      ok: true, text: texts.join('\n\n'), messages: texts, images, videos, thread_id: threadId, url: page.url(),
      elapsed_ms: Date.now() - t0, sent_ms: sentMs, first_ms: firstMs, tabs_closed: pruned,
    };
    if (st && st.error) Object.assign(out, { ok: false, kind: 'error', error: st.error });
    else if (st && st.approval) Object.assign(out, { ok: false, kind: 'approval', error: 'Muse is waiting for an approval in its own app.' });
    else if (timedOut) Object.assign(out, { ok: !!(texts.length || images.length || videos.length) && !req.want_images && !req.want_videos, kind: 'timeout', error: `Muse did not finish within ${Math.round(timeout / 1000)} s.` });
    else if (!texts.length && !images.length && !videos.length) Object.assign(out, { ok: false, kind: 'error', error: 'Muse returned an empty reply.' });
    return out;
  } finally {
    if (!req.keep_tab) await page.close().catch(() => {});
    await pruneTabs(ctx, req.keep_tab ? page : null).catch(() => {});
  }
}

module.exports = { pruneTabs };
if (require.main === module) (async () => {
  const port = parseInt(arg('cdp', '0'), 10);
  const action = arg('action', 'status');
  if (!port) { emit({ ok: false, kind: 'error', error: 'missing --cdp' }); process.exit(2); }
  let chromium;
  try { ({ chromium } = require('playwright-core')); } catch { ({ chromium } = require('playwright')); }
  let browser;
  try {
    browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 10000 });
  } catch (e) {
    emit({ ok: false, kind: 'browser', error: `cannot attach to the browser on CDP port ${port}: ${e.message}` });
    process.exit(3);
  }
  const ctx = browser.contexts()[0];
  if (!ctx) { emit({ ok: false, kind: 'browser', error: 'the browser has no context' }); process.exit(4); }
  try {
    if (action === 'status') emit(await status(ctx));
    else if (action === 'ask') {
      const req = JSON.parse(fs.readFileSync(arg('in', ''), 'utf-8'));
      emit(await ask(ctx, req));
    } else emit({ ok: false, kind: 'error', error: `unknown action ${action}` });
  } catch (e) {
    emit({ ok: false, kind: 'error', error: String((e && e.message) || e).slice(0, 500) });
  }
  // Ngắt CDP bằng cách thoát tiến trình — không close() (xem đầu file).
  process.exit(0);
})();
