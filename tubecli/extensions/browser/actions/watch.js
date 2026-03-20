import { humanMove } from './mouse_helper.js';

/**
 * Action: Watch a video for a specified duration, handling ads and simulating human behavior.
 * @param {import('playwright').Page} page
 * @param {object} params
 * @param {string|number} [params.duration="60s"] - Duration to watch (e.g. "50-100s", "60", 60).
 * @param {boolean} [params.skipAds=true] - Whether to automatically skip ads.
 */
export async function watch(page, params = {}) {
  const durationParam = params.duration || '60s';
  const skipAds = params.skipAds !== false;

  // 1. Parse Duration
  let durationSeconds = 60;
  
  if (typeof durationParam === 'string') {
    if (durationParam.includes('%')) {
        // Percentage based duration (requires video metadata)
        console.log(`Percentage duration detected: ${durationParam}. Waiting for video metadata...`);
        try {
            await page.waitForSelector('video', { timeout: 5000 }); // Wait 5s
            const videoDuration = await page.evaluate(async () => {
                const v = document.querySelector('video');
                if (!v) return 60; // Default
                return v.duration || 60;
            });
            
            const pct = parseInt(durationParam) / 100;
            durationSeconds = Math.floor(videoDuration * pct);
            console.log(`Video duration: ${videoDuration}s. Calculated watch time (${durationParam}): ${durationSeconds}s`);
        } catch (e) {
            console.warn('Failed to get video duration for percentage calculation (timeout/error). Defaulting to 60s.');
            durationSeconds = 60;
        }
    } else {
        const rangeMatch = durationParam.match(/(\d+)-(\d+)/);
        if (rangeMatch) {
            const min = parseInt(rangeMatch[1]);
            const max = parseInt(rangeMatch[2]);
            durationSeconds = Math.floor(Math.random() * (max - min + 1)) + min;
        } else {
            durationSeconds = parseInt(durationParam) || 60;
        }
    }
  } else if (typeof durationParam === 'number') {
    durationSeconds = durationParam;
  }

  // Cap default duration to a sane value if it's too high on article pages
  if (durationSeconds > 300) {
      console.log(`Capping duration from ${durationSeconds}s to 300s for safety.`);
      durationSeconds = 300;
  }

  // 2. Ensure Video is Playing & Visible
  try {
    const videoLocator = page.locator('video');
    await page.waitForSelector('video', { timeout: 5000, state: 'visible' }).catch(() => null);
    
    const videoState = await page.evaluate(() => {
      const v = document.querySelector('video');
      if (!v) return { found: false };
      const rect = v.getBoundingClientRect();
      const isVisible = rect.width > 100 && rect.height > 100 && v.offsetParent !== null;
      return { found: true, isVisible, isPlaying: !v.paused };
    });

    if (!videoState.found || !videoState.isVisible) {
      console.log('No visible video found. Signalling fallback to browse...');
      throw new Error('NO_VIDEO_FOUND');
    }

    if (!videoState.isPlaying) {
      console.log('Video paused, attempting to play...');
      await page.keyboard.press('k'); // YouTube shortcut
      await page.waitForTimeout(1000);
    }
  } catch (e) {
    if (e.message === 'NO_VIDEO_FOUND') throw e;
    console.warn('Could not confirm video playback, proceeding anyway:', e.message);
  }

  console.log(`Starting 'watch' action. Planning to watch for ~${durationSeconds} seconds.`);

  // 3. Watch Loop
  const startTime = Date.now();
  const endTime = startTime + (durationSeconds * 1000);

  while (Date.now() < endTime) {
    if (page.isClosed()) return;

    // A. Check for Ads
    if (skipAds) {
      await handleAds(page);
    }

    // B. Human Behavior (Randomly)
    if (Math.random() < 0.1) {
      // 10% chance to move mouse per second
      await randomMouseMove(page);
    }
    
    // C. Wait 1 second
    await page.waitForTimeout(1000);
    
    // Log progress every 10s
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    if (elapsed > 0 && elapsed % 10 === 0) {
        console.log(`Watched for ${elapsed}/${durationSeconds}s...`);
    }
  }

  console.log('Watch action completed.');
}

async function handleAds(page) {
    // Common YouTube ad selectors - Updated based on recent UI changes
    const skipBtnSelectors = [
        '.ytp-ad-skip-button',
        '.ytp-ad-skip-button-modern',
        '.videoAdUiSkipButton',
        '.ytp-ad-overlay-close-button',
        '.ytp-skip-ad-button', // New one often seen
        'button[id^="skip-button"]', 
        'div.ad-interrupting .ytp-ad-skip-button-slot' 
    ];

    for (const selector of skipBtnSelectors) {
        try {
            const btn = page.locator(selector).first();
            if (await btn.isVisible({ timeout: 100 })) { // Short timeout check
                console.log(`Ad detected (${selector})! Clicking skip button...`);
                await btn.click({ force: true }); // Force click to bypass overlays
                await page.waitForTimeout(500);
                return; 
            }
        } catch (e) {
            // Ignore visibility check errors
        }
    }
    
    // Also check for "Skip Ads" text content as a fallback
    try {
        const skipTextBtn = page.getByText('Skip Ads', { exact: false }).first();
        if (await skipTextBtn.isVisible({ timeout: 100 })) {
             console.log('Ad detected (Text Match)! Clicking skip button...');
             await skipTextBtn.click({ force: true });
        }
    } catch (e) {}
}

async function randomMouseMove(page) {
    const vp = page.viewportSize();
    if (!vp) return;
    
    const x = Math.floor(Math.random() * (vp.width - 100)) + 50;
    const y = Math.floor(Math.random() * (vp.height - 100)) + 50;
    
    // Use try-catch for mouse moves as they can fail if page context is lost
    try {
        await page.mouse.move(x, y, { steps: 5 });
    } catch (e) {}
}
