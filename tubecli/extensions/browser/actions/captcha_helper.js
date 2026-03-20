/**
 * Selectors for various Google/YouTube captchas
 */
const CAPTCHA_SELECTORS = [
  'iframe[title*="reCAPTCHA"]',
  '#captcha-form',
  '#captcha-box',
  '.g-recaptcha',
  '#recaptcha',
  '#image-captcha-section',
  'text=Enter the letters you see',
  'text=Nhập ký tự bạn thấy',
  'text=Our systems have detected unusual traffic',
  'text=Hệ thống của chúng tôi đã phát hiện thấy lưu lượng truy cập bất thường'
];

/**
 * Checks if a CAPTCHA is currently visible on the page.
 */
export async function detectCaptcha(page) {
  for (const selector of CAPTCHA_SELECTORS) {
    try {
      if (await page.locator(selector).first().isVisible()) {
        console.log(`Captcha detected via selector: ${selector}`);
        return true;
      }
    } catch (e) {
      // Ignore errors for invalid selectors if any
    }
  }
  return false;
}

/**
 * Detects if a CAPTCHA is present and waits for manual resolution.
 * @param {import('playwright').Page} page
 * @param {number} timeout Total time to wait for manual resolution (default 10 mins)
 */
export async function waitForCaptcha(page, timeout = 600000) {
  if (await detectCaptcha(page)) {
    console.warn('\n--- CAPTCHA DETECTED ---');
    console.warn(`Automation paused for up to ${timeout/60000} mins. PLEASE SOLVE MANUALLY.`);
    console.warn('The process will close if not solved within the timeout.');
    
    try {
      // Wait for the captcha to disappear by checking the detect function periodically
      const startTime = Date.now();
      while (Date.now() - startTime < timeout) {
        if (!(await detectCaptcha(page))) {
          console.log('CAPTCHA cleared. Resuming...');
          await page.waitForTimeout(2000);
          return;
        }
        await page.waitForTimeout(3000); // Check every 3 seconds
      }
      throw new Error('CAPTCHA_TIMEOUT');
    } catch (e) {
      if (e.message === 'CAPTCHA_TIMEOUT') throw e;
      console.error('Error during manual CAPTCHA resolution:', e.message);
      throw new Error('CAPTCHA_ERROR');
    }
  }
}
