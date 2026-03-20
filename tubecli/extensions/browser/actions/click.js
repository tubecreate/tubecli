import { humanMove } from './mouse_helper.js';

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
