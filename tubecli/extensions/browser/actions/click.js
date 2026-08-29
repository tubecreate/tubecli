import { humanMove } from './mouse_helper.js';

/**
 * Tìm một link ĐI SÂU HƠN trong cùng site — dùng cho "click an internal link
 * within the SAME site" của behaviour pattern 2.
 *
 * Đồ đạc điều hướng bị loại theo TỔ TIÊN, không theo vị trí. Bỏ "hai link đầu"
 * từng chỉ là phỏng đoán, và trên trang có mega-menu nó rơi trúng một mục
 * dropdown đang cụp: Playwright báo visible, cuộn tới, rồi từ chối với "Element
 * is outside of the viewport" — vì dropdown chưa mở thì render RA NGOÀI màn
 * hình chứ không phải ẩn đi.
 *
 * Bốn vai ARIA thêm vào đây không nới lỏng gì cả, chúng đóng chặt thêm: chúng
 * đúng là <header>/<footer>/<aside> của một trang dựng bằng custom element.
 * YouTube không có <header> nào hết — thanh trên cùng là custom element mang
 * role="banner", ngăn kéo trái mang role="navigation". Nếu chỉ nới rộng vùng
 * tìm mà không dịch luôn ý định cũ sang thứ tiếng app-shell nói, thì đúng cái
 * mega-menu ngày xưa sẽ quay lại qua cửa mới.
 */
const NOT_NAV = ':not(nav *):not(header *):not(footer *):not(aside *)'
              + ':not([role="navigation"] *):not([role="banner"] *)'
              + ':not([role="complementary"] *):not([role="contentinfo"] *)'
              + ':not([aria-hidden="true"] *)';

// <main> và <article> KHÔNG tồn tại trên YouTube — đo thật: 0 <main>, 0
// <article>, nên hai tầng đầu của bản cũ chết cứng trên MỌI trang YouTube. Vai
// ARIA là thứ app-shell thực sự khai báo (YouTube có đúng 1 [role="main"]), nên
// mở rộng gốc nội dung sang vai chứ không đi đoán tên id/class của từng site.
const CONTENT_ROOTS = ['main', 'article', '[role="main"]', '[role="article"]', '[role="feed"]'];

/**
 * Bốn tầng, hẹp trước rộng sau: trong gốc nội dung trước, rồi cả trang trừ đồ
 * đạc điều hướng.
 */
export function internalLinkSelectors(hostname) {
  const PATH_LINK = `a[href^="/"]:not([href="/"]):not([href^="//"])${NOT_NAV}`;
  const HOST_LINK = `a[href*="${hostname}"]${NOT_NAV}`;
  const inContent = (tail) => CONTENT_ROOTS.map((r) => `${r} ${tail}`).join(', ');
  return [inContent(PATH_LINK), inContent(HOST_LINK), PATH_LINK, HOST_LINK];
}

/**
 * href có thật sự dẫn sâu hơn vào CÙNG site không? Trả về URL tuyệt đối, hoặc
 * null nếu không.
 *
 * Cần lọc bằng URL chứ không bằng chuỗi con: trên trang chủ YouTube, ứng viên
 * DUY NHẤT mà bản cũ tìm được là nút "Sign in", vì href của nó là
 * accounts.google.com/ServiceLogin?...&continue=https://www.youtube.com/...
 * — `a[href*="www.youtube.com"]` khớp vì tên host nằm trong query string. Bản
 * cũ bấm nó và rời hẳn khỏi site đang đọc.
 */
export function sameSiteHref(href, here) {
  if (!href) return null;
  const raw = String(href).trim();
  if (!raw || raw.startsWith('#')) return null;
  let u;
  try { u = new URL(raw, here.href); } catch (e) { return null; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;  // mailto:, tel:, javascript:
  const strip = (h) => h.replace(/^www\./, '');
  const host = strip(u.hostname), base = strip(here.hostname);
  if (host !== base && !host.endsWith('.' + base)) return null;
  // Link trỏ về đúng trang đang đứng thì bấm xong vẫn ở nguyên đó, và
  // session_manager.isStuckOnSameUrl() sẽ tính đó là bế tắc.
  if (u.href.split('#')[0] === here.href.split('#')[0]) return null;
  return u.href;
}

/**
 * Chỗ bấm được của một link, tính theo toạ độ viewport — hoặc null.
 *
 * Luật cũ đòi phần tử nằm TRỌN VẸN trong viewport. Một thẻ bài / ô video to hơn
 * viewport vẫn bấm được bình thường, mà lưới video thì làm bằng đúng thứ đó;
 * luật cũ vứt sạch. Đổi thành: phần GIAO giữa phần tử và viewport phải đủ to,
 * và điểm bấm là tâm của phần giao đó.
 *
 * Vì sao vẫn chặn được mục dropdown ngày xưa: dropdown đang cụp render RA NGOÀI
 * màn hình, nên phần giao rỗng — nó trượt ngay ở bước đầu, y như trước.
 *
 * Đo bằng innerWidth/innerHeight của chính trang, KHÔNG bằng page.viewportSize().
 * browser_manager.js:1637 và :2164 truyền viewport:null để cửa sổ thật quyết
 * định kích thước, nên viewportSize() trả về null và bản cũ rơi vào hằng số
 * 1280x800 — sai cả hai đầu: cửa sổ mặc định của hồ sơ là 1920x1080
 * (profile_manager.py:151), còn fingerprint di động mở cửa sổ 450x900
 * (open.js:1108).
 *
 * Trả về { x, y, covered, by }: covered=true nghĩa là có thứ khác nằm đè lên
 * điểm đó (banner cookie, quảng cáo dính). Không vứt luôn, vì trên trang bị
 * OneTrust phủ kín thì vứt luôn = không còn ứng viên nào; chỉ xếp xuống hạng nhì.
 */
export async function clickableSpot(page, loc, tally = null) {
  const note = (k) => { if (tally) tally[k] = (tally[k] || 0) + 1; };
  try {
    if (!(await loc.isVisible())) { note('khongHien'); return null; }
    await loc.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
    // Một lượt đi về duy nhất: hình học, viewport thật và hit-test cùng một lúc,
    // để trang không kịp trôi giữa các phép đo.
    const r = await loc.evaluate((el) => {
      const b = el.getBoundingClientRect();
      const vw = window.innerWidth, vh = window.innerHeight;
      const x1 = Math.max(b.left, 0), y1 = Math.max(b.top, 0);
      const x2 = Math.min(b.right, vw), y2 = Math.min(b.bottom, vh);
      if (x2 - x1 < 8 || y2 - y1 < 8) return { off: true, vw, vh };
      const x = (x1 + x2) / 2, y = (y1 + y2) / 2;
      const h = document.elementFromPoint(x, y);
      const ok = !!h && (el === h || el.contains(h) || (h.closest && h.closest('a') === el));
      const by = h ? `${h.tagName}${h.id ? '#' + h.id : ''}`
                     + `${h.className ? '.' + String(h.className).trim().split(/\s+/)[0] : ''}`
                   : 'không có gì';
      return { off: false, x, y, ok, by, vw, vh, w: b.width, h: b.height };
    });
    if (!r || r.off) { note('ngoaiManHinh'); return null; }
    if (!r.ok) { note('biChe'); return { x: r.x, y: r.y, covered: true, by: r.by }; }
    return { x: r.x, y: r.y, covered: false, by: null };
  } catch (e) {
    note('loi');
    return null;
  }
}

/**
 * Generic Click Action
 * @param {import('playwright').Page} page 
 * @param {object} params 
 * @param {string} [params.selector] - CSS selector to click. If not provided, clicks first search result.
 * @param {string} [params.text] - Text to find and click.
 * @param {string} [params.type] - Type of target (e.g. 'video').
 */
export async function click(page, params = {}) {
  if (params.type === 'enter') {
    console.log('[CLICK] Pressing Enter key...');
    await page.keyboard.press('Enter');
    return;
  }

  // Cloudflare / Verification Handling
  if (params.type === 'verify' || params.text?.toLowerCase().includes('check')) {
      console.log('[CLICK] Searching for Verification/Cloudflare buttons...');
      const verifySelectors = [
          'input[type="checkbox"]', 
          '#challenge-stage input', 
          'iframe[src*="cloudflare"]',
          'text="Verify you are human"',
          'text="Click to verify"'
      ];
      for (const sel of verifySelectors) {
          const btn = page.locator(sel).first();
          if (await btn.isVisible({ timeout: 2000 }).catch(() => false)) {
              console.log(`[CLICK] Found verification element: ${sel}`);
              await btn.click({ force: true });
              await page.waitForTimeout(5000); // Wait for challenge to resolve
              return;
          }
      }
  }

  const { selector, text, type } = params;
  let target;
  
  // Ensure results are loaded if on Google
  if (page.url().includes('google.com/search')) {
    await page.waitForSelector('#search', { timeout: 10000 }).catch(() => {});
  }

  if (selector) {
    target = page.locator(selector).first();
  } else if (params.text) {
    // Sanitize AI text: Remove prefixes like "Link:", "Button:"
    let searchText = params.text.replace(/^(Link:|Button:|Click:)\s*/i, '').trim();
    
    // Truncate long text to improve match rate (first 60 chars)
    if (searchText.length > 60) {
        searchText = searchText.substring(0, 60).trim();
    }
    
    console.log(`Searching for element with text: "${searchText}" (Original: "${params.text}")`);
    
    // 1. Playwright getByText (smart fuzzy match)
    target = page.getByText(searchText, { exact: false }).first();
    
    // 2. Fallback: XPath string contains (case-insensitive approximation)
    if (!(await target.isVisible().catch(() => false))) {
       console.log('Standard match failed. Trying deep text search...');
       // XPath 1.0 doesn't support lower-case easily, so we rely on Playwright's pseudo-selectors or simple contains
       // Try a simpler partial match for the first few words
       const shortText = searchText.split(' ').slice(0, 5).join(' ');
       target = page.locator(`text=${shortText}`).first();
    }

    // 3. Fallback: Search in attributes (aria-label, title)
    if (!(await target.isVisible().catch(() => false))) {
       const attrSelector = `[aria-label*="${searchText}" i], [title*="${searchText}" i], [alt*="${searchText}" i]`;
       const attrTarget = page.locator(attrSelector).first();
       if (await attrTarget.isVisible().catch(() => false)) {
          target = attrTarget;
       }
    }
  } else if (params.type === 'video') {
    // Target video results: STRICT YouTube links or video thumbnails
    // Avoid Clicking "AI Overview" or "People also ask"
    const videoSelectors = [
        'a[href*="youtube.com/watch"]', // Direct video links
        'div[data-surl*="youtube.com/watch"] a', // Video type results
        'video-voyager a'
    ];
    target = page.locator(videoSelectors.join(',')).first();
    console.log('Searching for STRICT video results (youtube.com)...');
  } else if (!page.url().includes('google.com/search')) {
    // Not on the results page any more, so "click" cannot mean "click a search
    // result". This is the second click of behaviour pattern 2, whose prompt
    // asks to "click an internal link within the SAME site" — an intent the
    // heuristic parser in open.js drops when it splits the sentence, leaving a
    // bare click. The old code then hunted for #search on a page that is not
    // Google, retried twice, and failed the whole session after the agent had
    // already searched, clicked and read successfully.
    const here = new URL(page.url());
    console.log(`Not on search results — looking for an internal link on ${here.hostname}...`);

    // Đếm luôn lý do trượt của từng ứng viên, để dòng log lúc thất bại nói được
    // sự thật. Lần trước phải mở ảnh chụp ra đọc bằng mắt mới biết YouTube đang
    // chìa ra một feed RỖNG chứ không phải selector hỏng.
    const tally = { xet: 0, ngoaiSite: 0, khongHien: 0, ngoaiManHinh: 0, biChe: 0, loi: 0 };
    let covered = null, coveredWhy = '';

    outer:
    for (const [tier, sel] of internalLinkSelectors(here.hostname).entries()) {
      const candidates = page.locator(sel);
      const n = await candidates.count().catch(() => 0);
      for (let i = 0; i < Math.min(n, 25); i++) {
        const c = candidates.nth(i);
        tally.xet++;
        const dest = sameSiteHref(await c.getAttribute('href').catch(() => null), here);
        if (!dest) { tally.ngoaiSite++; continue; }
        const s = await clickableSpot(page, c, tally);
        if (s && !s.covered) {
          target = c;
          console.log(`Found internal link (tier ${tier}, ứng viên ${i}) -> ${dest}`);
          break outer;
        }
        // Bị che thì vẫn giữ lại làm hạng nhì. Trang tin nào cũng có thể đang
        // đội một banner đồng ý cookie phủ kín (đo thật: apnews.com,
        // theguardian.com); nếu bỏ hẳn thì lượt chạy mất trắng một trang có
        // thừa link đọc được, trong khi banner có thể tự tan lúc bấm.
        if (s && !covered) {
          covered = c;
          coveredWhy = `${dest} (bị ${s.by} che)`;
        }
      }
    }

    if (!target && covered) {
      // Không có ứng viên sạch nào: lấy ứng viên bị che và để chính cú bấm phán
      // xử — Playwright sẽ nói "intercepts pointer events" nếu banner thật sự
      // chắn. Đúng bằng hành vi bản cũ ở tình huống này, không tệ hơn.
      target = covered;
      console.log(`Only covered internal links here — trying anyway: ${coveredWhy}`);
    }

    if (!target) {
      // Nothing to go deeper into is a normal property of many pages, not a
      // failure of the run. Say so and let the caller decide.
      //
      // Trang chủ YouTube lúc chưa đăng nhập là ví dụ chuẩn: nó ghi thẳng "Try
      // searching to get started", không có ô video nào, và mọi link còn lại
      // đều nằm trong masthead hoặc ngăn kéo trái. Đo thật: 8 thẻ <a> trên toàn
      // trang, 0 cái sống sót — con số đó đi kèm lỗi để lần sau khỏi phải đoán.
      const err = new Error(`No internal link found on ${here.hostname}`
        + ` (xét ${tally.xet}: ${tally.ngoaiSite} ngoài site, ${tally.khongHien} không hiện,`
        + ` ${tally.ngoaiManHinh} ngoài màn hình, ${tally.biChe} bị che)`);
      err.softFail = true;
      err.code = 'NO_INTERNAL_LINK';
      throw err;
    }

    // From here the click itself is also optional: this is a "read one more
    // page" bonus, and a page that fights it is not a failed session. Try, and
    // downgrade any refusal to a skip.
    try {
      await target.click({ timeout: 8000 });
      console.log('Click executed.');
      return { clicked: true, internal: true, url: page.url() };
    } catch (e) {
      // Với phần tử CAO/RỘNG HƠN viewport, Playwright tự chọn điểm bấm ở tâm
      // phần tử — cái tâm đó nằm ngoài màn hình — rồi từ chối. Ta đã biết một
      // điểm bấm được rồi; tính lại (trang có thể vừa dịch chuyển) và bấm thẳng
      // vào đó bằng chuột.
      const again = await clickableSpot(page, target);
      if (again && !again.covered) {
        try {
          await humanMove(page, again.x, again.y);
          await page.mouse.click(again.x, again.y);
          console.log('Click executed at a visible spot (element larger than the viewport).');
          return { clicked: true, internal: true, url: page.url() };
        } catch (e2) {
          console.warn(`Coordinate click also refused: ${String(e2.message).split('\n')[0]}`);
        }
      }
      const err = new Error(`Could not open an internal link: ${String(e.message).split('\n')[0]}`);
      err.softFail = true;
      err.code = 'CLICK_REFUSED';
      throw err;
    }
  } else {
    // Default to first Google result if no selector
    // Try multiple strategies to find the first clickable search result
    console.log('Finding first search result using multiple strategies...');

    const strategies = [
      // Strategy 1: Standard search result link (.g is Google's result container)
      '#search .g a[href]:not([href*="google.com"])',
      // Strategy 2: Any link in search results area (broader)
      '#search a[href]:not([href*="google.com"]):not([href*="#"])',
      // Strategy 3: Main region links (fallback for different layouts)
      '[role="main"] a[href]:not([href*="google.com"]):not([href*="#"])',
      // Strategy 4: Any h3 link (headline links)
      'h3 a[href]:not([href*="google.com"])'
    ];
    
    // Try strategies with retry logic
    let maxAttempts = 3;
    let attemptDelay = 2000; // Wait 2 seconds between attempts
    
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      if (attempt > 0) {
        console.log(`Retry attempt ${attempt}/${maxAttempts - 1} - waiting ${attemptDelay}ms for results...`);
        await page.waitForTimeout(attemptDelay);
      }
      
      for (const selector of strategies) {
        const candidate = page.locator(selector).first();
        if (await candidate.isVisible()) {
          target = candidate;
          console.log(`Found target using selector: ${selector}`);
          break;
        }
      }
      
      if (target) {
        break; // Found target, exit retry loop
      }
    }
    
    if (!target) {
      console.warn('No suitable search result found with any strategy after retries. Using first strategy as final attempt.');
      target = page.locator(strategies[0]).first();
      // Wait a bit more for it to appear
      await page.waitForTimeout(3000);
    }
  }

  // Final visibility and click attempt
  let isVisible = await target.isVisible().catch(() => false);
  
  if (!isVisible) {
      console.log('Target not immediately visible. Attempting to scroll into view...');
      await target.scrollIntoViewIfNeeded().catch(() => {});
      await page.waitForTimeout(1000);
      isVisible = await target.isVisible().catch(() => false);
  }

  if (isVisible) {
    console.log('Clicking on target element...');
    const box = await target.boundingBox();
    if (box) {
      await humanMove(page, box.x + box.width / 2, box.y + box.height / 2);
      await page.waitForTimeout(500);
    }
    
    // Try regular click first, then force click if it fails
    try {
        await target.click({ timeout: 10000 });
        console.log('Click executed.');
    } catch (e) {
        console.warn('Regular click failed, trying force click:', e.message);
        await target.click({ force: true });
        console.log('Force click executed.');
    }

      // --- Post-Click Video Handling ---
      if (params.type === 'video') {
        try {
          console.log('Waiting for video page to stabilize...');
          await page.waitForTimeout(5000); // Give it more time to load
          
          if (page.url().includes('youtube.com/watch')) {
            console.log('Detected YouTube page, ensuring video is playing...');
            
            // Multiple attempts to play
            for (let attempt = 0; attempt < 3; attempt++) {
              const isPlaying = await page.evaluate(async () => {
                const video = document.querySelector('video');
                if (video && video.paused) {
                  // Attempt 1: DOM play()
                  video.play().catch(() => {});
                  
                  // Attempt 2: Click the player
                  const moviePlayer = document.querySelector('#movie_player');
                  if (moviePlayer) moviePlayer.click();

                  // Attempt 3: Click large play button
                  const playBtn = document.querySelector('.ytp-large-play-button');
                  if (playBtn && playBtn.offsetParent !== null) {
                    playBtn.click();
                  }
                  return false;
                }
                return !!video && !video.paused;
              });

              if (isPlaying) {
                console.log('Video is confirmed playing.');
                break;
              }
              await page.waitForTimeout(2000);
            }
          }
        } catch (e) {
          console.warn('Video playback check failed:', e.message);
        }
      }
  } else {
    const msg = `Target element '${selector || 'default'}' not visible.`;
    console.warn(msg);
    throw new Error(msg);
  }
}
