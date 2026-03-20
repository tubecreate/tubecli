import { waitForCaptcha, detectCaptcha } from './captcha_helper.js';
import { humanMove } from './mouse_helper.js';

import fs from 'fs';
import path from 'path';

/**
 * Fetch a live TOTP code from the 2FA API.
 * API: https://ffmpeg.eztub-tk.com/2fa.php?2fa=<secret>
 * Returns the 6-digit code, or null on failure.
 * @param {string} twoFactorCodes - the secret string (space-separated or raw)
 * @returns {Promise<string|null>}
 */
async function fetchTotpCode(twoFactorCodes) {
  try {
    const fetch = (await import('node-fetch')).default;
    // Remove spaces from the base32 secret code as standard TOTP libraries expect contiguous strings
    const cleanSecret = twoFactorCodes.replace(/\s+/g, '').toUpperCase();
    const encoded = encodeURIComponent(cleanSecret);
    
    // Load config if exists
    let apiUrl = 'http://localhost:5295/api/v1/2fa?secret=';
    try {
      // Navigate up from browser-laucher/actions/login.js to python-video-studio/.cache/browser_config.json
      const configPath = path.join(process.cwd(), '..', '.cache', 'browser_config.json');
      if (fs.existsSync(configPath)) {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
        if (config.fallback_2fa_api) {
          apiUrl = config.fallback_2fa_api;
        }
      }
    } catch (err) {
      console.warn('[2FA] Could not read custom API config, using default.');
    }

    const url = `${apiUrl}${encoded}`;
    console.log(`[2FA] Fetching live TOTP code from API...`);
    const resp = await fetch(url, { timeout: 10000 });
    const data = await resp.json();
    if (data && data.code) {
      console.log(`[2FA] Got TOTP code: ${data.code} (valid for ~${30 - (data.time % 30)}s)`);
      return String(data.code);
    }
    console.warn('[2FA] API returned no code:', data);
    return null;
  } catch (e) {
    console.warn('[2FA] Failed to fetch TOTP code:', e.message);
    return null;
  }
}

async function handleCaptcha(page, isRetry) {
  if (await detectCaptcha(page)) {
    if (isRetry) {
      await waitForCaptcha(page);
    } else {
      throw new Error('CAPTCHA_DETECTED');
    }
  }
}

async function humanClick(page, selector) {
  const element = page.locator(selector).first();
  if (await element.isVisible()) {
    const box = await element.boundingBox();
    if (box) {
      await humanMove(page, box.x + box.width / 2, box.y + box.height / 2);
      await page.waitForTimeout(300 + Math.random() * 500);
      await element.click();
    }
  }
}

/**
 * Detect which platform to use based on current URL
 * @param {string} url
 * @returns {string} platform name
 */
function detectPlatformFromUrl(url) {
  if (!url) return 'google';
  if (url.includes('facebook.com') || url.includes('fb.com')) return 'facebook';
  if (url.includes('tiktok.com')) return 'tiktok';
  if (url.includes('twitter.com') || url.includes('x.com')) return 'x';
  if (url.includes('discord.com')) return 'discord';
  if (url.includes('telegram.org') || url.includes('web.telegram.org')) return 'telegram';
  return 'google'; // Default
}

/**
 * Action: Login — Routes to the correct platform handler
 * @param {import('playwright').Page} page
 * @param {object} params
 * @param {string} params.email      - Username or email (alias: params.username)
 * @param {string} params.password
 * @param {string} [params.platform] - Override platform: google|facebook|tiktok|x|discord|telegram
 * @param {string} [params.recoveryEmail]
 * @param {string} [params.twoFactorCodes] - Space-separated backup 2FA codes
 */
export async function login(page, params = {}) {
  // Support both 'email' and 'username' keys
  const email = params.email || params.username;
  const { password, recoveryEmail, twoFactorCodes } = params;

  if (!email || !password) {
    console.error('[Login] email/username and password are required. Got:', { email: !!email, password: !!password });
    return;
  }

  // Auto-detect platform from current URL unless override provided
  const platform = params.platform || detectPlatformFromUrl(page.url());
  console.log(`[Login] Platform: ${platform} | Account: ${email}`);

  switch (platform) {
    case 'facebook':
      return loginFacebook(page, { email, password, twoFactorCodes, isRetry: params.isRetry });
    case 'tiktok':
      return loginTiktok(page, { email, password, twoFactorCodes, isRetry: params.isRetry });
    case 'x':
      return loginX(page, { email, password, twoFactorCodes, isRetry: params.isRetry });
    case 'discord':
      return loginDiscord(page, { email, password, twoFactorCodes, isRetry: params.isRetry });
    case 'telegram':
      console.warn('[Login] Telegram login requires phone number — manual action needed.');
      return;
    case 'google':
    default:
      return loginGoogle(page, { email, password, recoveryEmail, twoFactorCodes, isRetry: params.isRetry });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// GOOGLE LOGIN
// ─────────────────────────────────────────────────────────────────────────────
async function loginGoogle(page, params) {
  const { email, password, recoveryEmail, twoFactorCodes, isRetry } = params;

  console.log(`[Google] Checking login status for: ${email}...`);

  try {
    // 0. Ensure we are on a valid domain
    if (page.url() === 'about:blank' || page.url().startsWith('data:')) {
      console.log('[Google] Navigating to Google...');
      await page.goto('https://www.google.com');
    }

    // 1. Check if already logged in
    await page.waitForTimeout(2000);
    let isAlreadyLoggedIn = false;
    if (page.url().includes('youtube.com')) {
      isAlreadyLoggedIn = await page.locator('button#avatar-btn').first().isVisible();
    } else {
      isAlreadyLoggedIn = await page.locator('.gb_A, a[href*="SignOut"]').first().isVisible();
    }
    if (isAlreadyLoggedIn) {
      console.log('[Google] Already logged in. Skipping.');
      return;
    }

    // 2. Navigate/click sign-in
    const signInBtnSelector = [
      'a[href*="accounts.google.com/ServiceLogin"]',
      'a:has-text("Sign in")',
      'a:has-text("Đăng nhập")',
      'ytd-masthead #buttons ytd-button-renderer a',
      'tp-yt-paper-button:has-text("Sign in")',
      'button:has-text("Sign in")'
    ].join(', ');

    const signInBtn = page.locator(signInBtnSelector).first();
    if (await signInBtn.isVisible()) {
      console.log('[Google] Found Sign-in button, clicking...');
      await humanClick(page, signInBtnSelector);
    } else if (!page.url().includes('accounts.google.com')) {
      console.log('[Google] Navigating to Google Login...');
      await page.goto('https://accounts.google.com/signin');
    }

    await handleCaptcha(page, isRetry);

    // 3. Enter Email
    console.log('[Google] Entering email...');
    const emailSelector = 'input[type="email"], input[name="identifier"]';
    const emailInput = page.locator(emailSelector).first();
    await emailInput.waitFor({ state: 'visible', timeout: 20000 });
    await humanClick(page, emailSelector);
    await page.waitForTimeout(1000 + Math.random() * 2000);
    for (const char of email) {
      await page.keyboard.type(char, { delay: 50 + Math.random() * 150 });
    }
    await page.waitForTimeout(800 + Math.random() * 1200);

    // Re-click/focus the email field to ensure it's focused before pressing Enter
    await emailInput.click();
    await page.waitForTimeout(300);

    // Press Enter to submit email
    console.log('[Google] Pressing Enter to submit email...');
    await page.keyboard.press('Enter');
    console.log('[Google] Pressed Enter, waiting for password field...');

    // Error check after Enter
    try {
      const errorMsg = page.locator('div[jsname="B34EJc"], div.o6cuMc').first();
      if (await errorMsg.isVisible({ timeout: 2000 })) {
        const text = await errorMsg.innerText();
        console.error(`[Google] Login Error: ${text}`);
        throw new Error(`LOGIN_ERROR: ${text}`);
      }
    } catch (e) { if (e.message && e.message.startsWith('LOGIN_ERROR')) throw e; }

    await handleCaptcha(page, isRetry);

    // 4. Enter Password — retry if Enter didn't transition to password step
    console.log('[Google] Entering password...');
    const passwordSelector = 'input[type="password"]:not([aria-hidden="true"]):not([name="hiddenPassword"])';
    const passwordInput = page.locator(passwordSelector).first();

    let passwordVisible = false;
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        await passwordInput.waitFor({ state: 'visible', timeout: 10000 });
        passwordVisible = true;
        break;
      } catch (e) {
        console.warn(`[Google] Password field not visible (attempt ${attempt}/3).`);
        if (attempt < 3) {
          const nextBtn = page.locator('#identifierNext, button:has-text("Next"), button:has-text("Tiếp theo")').first();
          if (await nextBtn.isVisible()) {
            console.log('[Google] Clicking Next button (retry)...');
            await nextBtn.click();
          } else {
            console.log('[Google] Pressing Enter again (retry)...');
            await page.keyboard.press('Enter');
          }
          await page.waitForTimeout(3000);
        }
      }
    }
    if (!passwordVisible) {
      console.error('[Google] Password field did not appear after 3 attempts.');
      throw new Error('Password field did not appear.');
    }
    await humanClick(page, passwordSelector);
    await page.waitForTimeout(1000 + Math.random() * 2000);
    for (const char of password) {
      await page.keyboard.type(char, { delay: 60 + Math.random() * 180 });
    }
    await page.waitForTimeout(1000 + Math.random() * 1500);
    await humanClick(page, '#passwordNext, button:has-text("Next"), button:has-text("Tiếp theo")');
    console.log('[Google] Password entered.');

    // 5. Handle Challenges
    await page.waitForTimeout(3000 + Math.random() * 2000);

    // Recovery Email Challenge
    const recoverySelector = 'div[data-challengetype="12"], li:has-text("Confirm your recovery email"), li:has-text("Xác nhận email khôi phục")';
    if (await page.locator(recoverySelector).first().isVisible()) {
      console.log('[Google] Recovery email challenge detected.');
      if (recoveryEmail) {
        await humanClick(page, recoverySelector);
        const recoveryInputSelector = 'input[type="email"], input[name="knowledgePrereqResponse"]';
        await page.locator(recoveryInputSelector).first().waitFor({ state: 'visible', timeout: 10000 });
        await humanClick(page, recoveryInputSelector);
        await page.waitForTimeout(1200 + Math.random() * 1800);
        for (const char of recoveryEmail) {
          await page.keyboard.type(char, { delay: 50 + Math.random() * 120 });
        }
        await page.waitForTimeout(1000 + Math.random() * 1000);
        await humanClick(page, 'button:has-text("Next"), button:has-text("Tiếp theo")');
        console.log('[Google] Recovery email submitted.');
      } else {
        console.warn('[Google] Recovery email challenge but no recoveryEmail provided.');
      }
    }

    // 2FA Challenge — fetch live TOTP code from API, fallback to backup codes
    await page.waitForTimeout(2000);
    const twoFASelector = 'input[type="tel"], input[aria-label*="code" i], input[placeholder*="code" i]';
    if (await page.locator(twoFASelector).first().isVisible({ timeout: 5000 }).catch(() => false)) {
      console.log('[Google] 2FA challenge detected.');
      if (twoFactorCodes) {
        // Try live TOTP first (from API)
        let code = await fetchTotpCode(twoFactorCodes);

        // Fallback: treat twoFactorCodes as space-separated backup codes
        if (!code) {
          const backupCodes = twoFactorCodes.trim().split(/\s+/);
          code = backupCodes[0];
          console.log(`[Google] Using backup code (${backupCodes.length} available): ${code}`);
        }

        if (code) {
          console.log(`[Google] Entering 2FA code: ${code}`);
          await humanClick(page, twoFASelector);
          for (const char of code) {
            await page.keyboard.type(char, { delay: 80 + Math.random() * 120 });
          }
          await page.waitForTimeout(800 + Math.random() * 600);
          await humanClick(page, 'button:has-text("Next"), button:has-text("Tiếp theo"), button:has-text("Submit"), button:has-text("Verify")');
          console.log('[Google] 2FA code submitted.');
        }
      } else {
        console.warn('[Google] 2FA challenge detected but no twoFactorCodes provided.');
      }
    }

    // 6. Wait for success
    console.log('[Google] Waiting for login to stabilize...');
    await page.waitForSelector('#avatar-btn, .gb_A, ytd-topbar-menu-button-renderer img', { timeout: 20000 })
      .catch(() => console.log('[Google] Avatar not found immediately, checking if still in challenge...'));
    await page.waitForTimeout(5000);
    console.log('[Google] Login completed and session stabilized.');

  } catch (error) {
    console.error('[Google] Login failed:', error.message);
    if (page.url().includes('challenge')) {
      console.warn('[Google] Security challenge detected. Manual intervention may be required.');
    }
    if (error.message.includes('CAPTCHA')) throw error;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// FACEBOOK LOGIN
// ─────────────────────────────────────────────────────────────────────────────
async function loginFacebook(page, params) {
  const { email, password, twoFactorCodes, isRetry } = params;
  console.log(`[Facebook] Logging in as: ${email}`);

  try {
    if (!page.url().includes('facebook.com')) {
      await page.goto('https://www.facebook.com/login');
    }

    // Check already logged in
    await page.waitForTimeout(2000);
    if (await page.locator('[aria-label="Your profile"], [data-testid="royal_login_form"]').first().isVisible()) {
      const isForm = await page.locator('[data-testid="royal_login_form"]').first().isVisible();
      if (!isForm) {
        console.log('[Facebook] Already logged in.');
        return;
      }
    }

    // Email
    const emailSel = '#email, input[name="email"], input[type="email"]';
    await page.locator(emailSel).first().waitFor({ state: 'visible', timeout: 15000 });
    await humanClick(page, emailSel);
    await page.waitForTimeout(700 + Math.random() * 800);
    for (const char of email) {
      await page.keyboard.type(char, { delay: 60 + Math.random() * 130 });
    }

    // Password
    const passSel = '#pass, input[name="pass"], input[type="password"]';
    await humanClick(page, passSel);
    await page.waitForTimeout(500 + Math.random() * 700);
    for (const char of password) {
      await page.keyboard.type(char, { delay: 60 + Math.random() * 140 });
    }

    // Submit
    await humanClick(page, 'button[name="login"], button:has-text("Log in"), button:has-text("Đăng nhập")');
    console.log('[Facebook] Submitted login form...');
    await page.waitForTimeout(4000);

    // 2FA if needed
    if (twoFactorCodes && await page.locator('input[name="approvals_code"], input[id*="approvals"]').first().isVisible({ timeout: 5000 }).catch(() => false)) {
      const codes = twoFactorCodes.trim().split(/\s+/);
      const code = codes[0];
      console.log('[Facebook] 2FA challenge detected, entering code...');
      await humanClick(page, 'input[name="approvals_code"], input[id*="approvals"]');
      for (const char of code) {
        await page.keyboard.type(char, { delay: 80 + Math.random() * 120 });
      }
      await humanClick(page, 'button:has-text("Continue"), button:has-text("Submit")');
    }

    await page.waitForTimeout(3000);
    console.log('[Facebook] Login flow completed.');
  } catch (error) {
    console.error('[Facebook] Login failed:', error.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TIKTOK LOGIN
// ─────────────────────────────────────────────────────────────────────────────
async function loginTiktok(page, params) {
  const { email, password, isRetry } = params;
  console.log(`[TikTok] Logging in as: ${email}`);

  try {
    if (!page.url().includes('tiktok.com')) {
      await page.goto('https://www.tiktok.com/login/phone-or-email/email');
    }

    await page.waitForTimeout(2000);

    // Click "Use phone / email / username"
    const emailTabSel = 'a:has-text("Email"), a:has-text("phone / email")';
    if (await page.locator(emailTabSel).first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await humanClick(page, emailTabSel);
      await page.waitForTimeout(1000);
    }

    // Email input
    const emailSel = 'input[name="email"], input[placeholder*="email" i], input[type="email"]';
    await page.locator(emailSel).first().waitFor({ state: 'visible', timeout: 15000 });
    await humanClick(page, emailSel);
    for (const char of email) {
      await page.keyboard.type(char, { delay: 70 + Math.random() * 130 });
    }

    // Password input
    const passSel = 'input[type="password"], input[placeholder*="password" i]';
    await humanClick(page, passSel);
    await page.waitForTimeout(600 + Math.random() * 600);
    for (const char of password) {
      await page.keyboard.type(char, { delay: 70 + Math.random() * 130 });
    }

    // Submit
    await humanClick(page, 'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")');
    await page.waitForTimeout(4000);
    console.log('[TikTok] Login flow completed.');
  } catch (error) {
    console.error('[TikTok] Login failed:', error.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// X (TWITTER) LOGIN
// ─────────────────────────────────────────────────────────────────────────────
async function loginX(page, params) {
  const { email, password, twoFactorCodes, isRetry } = params;
  console.log(`[X] Logging in as: ${email}`);

  try {
    if (!page.url().includes('x.com') && !page.url().includes('twitter.com')) {
      await page.goto('https://x.com/login');
    }

    await page.waitForTimeout(2000);

    // Username/email step
    const userSel = 'input[autocomplete="username"], input[name="text"], input[data-testid="ocfEnterTextTextInput"]';
    await page.locator(userSel).first().waitFor({ state: 'visible', timeout: 15000 });
    await humanClick(page, userSel);
    for (const char of email) {
      await page.keyboard.type(char, { delay: 60 + Math.random() * 130 });
    }
    await humanClick(page, 'div[data-testid="LoginForm_Login_Button"], button:has-text("Next")');
    await page.waitForTimeout(2000);

    // Password step
    const passSel = 'input[name="password"], input[type="password"]';
    await page.locator(passSel).first().waitFor({ state: 'visible', timeout: 15000 });
    await humanClick(page, passSel);
    await page.waitForTimeout(600 + Math.random() * 800);
    for (const char of password) {
      await page.keyboard.type(char, { delay: 70 + Math.random() * 140 });
    }
    await humanClick(page, 'div[data-testid="LoginForm_Login_Button"], button:has-text("Log in")');
    await page.waitForTimeout(4000);

    // 2FA if needed
    if (twoFactorCodes && await page.locator('input[data-testid="ocfEnterTextTextInput"]').first().isVisible({ timeout: 5000 }).catch(() => false)) {
      const codes = twoFactorCodes.trim().split(/\s+/);
      const code = codes[0];
      console.log('[X] 2FA challenge, entering code...');
      await humanClick(page, 'input[data-testid="ocfEnterTextTextInput"]');
      for (const char of code) {
        await page.keyboard.type(char, { delay: 80 + Math.random() * 100 });
      }
      await humanClick(page, 'button:has-text("Next")');
    }

    await page.waitForTimeout(3000);
    console.log('[X] Login flow completed.');
  } catch (error) {
    console.error('[X] Login failed:', error.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// DISCORD LOGIN
// ─────────────────────────────────────────────────────────────────────────────
async function loginDiscord(page, params) {
  const { email, password, twoFactorCodes, isRetry } = params;
  console.log(`[Discord] Logging in as: ${email}`);

  try {
    if (!page.url().includes('discord.com')) {
      await page.goto('https://discord.com/login');
    }

    await page.waitForTimeout(2000);

    // Email
    const emailSel = 'input[name="email"], input[aria-label*="Email" i]';
    await page.locator(emailSel).first().waitFor({ state: 'visible', timeout: 15000 });
    await humanClick(page, emailSel);
    for (const char of email) {
      await page.keyboard.type(char, { delay: 60 + Math.random() * 120 });
    }

    // Password
    const passSel = 'input[name="password"], input[type="password"]';
    await humanClick(page, passSel);
    await page.waitForTimeout(500 + Math.random() * 600);
    for (const char of password) {
      await page.keyboard.type(char, { delay: 70 + Math.random() * 130 });
    }

    // Submit
    await humanClick(page, 'button[type="submit"]:has-text("Log In"), button:has-text("Login")');
    await page.waitForTimeout(4000);

    // 2FA if needed
    if (twoFactorCodes && await page.locator('input[placeholder*="6-digit" i], input[name="code"]').first().isVisible({ timeout: 5000 }).catch(() => false)) {
      const codes = twoFactorCodes.trim().split(/\s+/);
      const code = codes[0];
      console.log('[Discord] 2FA challenge, entering backup code...');
      await humanClick(page, 'input[placeholder*="6-digit" i], input[name="code"]');
      for (const char of code) {
        await page.keyboard.type(char, { delay: 80 + Math.random() * 100 });
      }
      await humanClick(page, 'button:has-text("Log In"), button[type="submit"]');
    }

    await page.waitForTimeout(3000);
    console.log('[Discord] Login flow completed.');
  } catch (error) {
    console.error('[Discord] Login failed:', error.message);
  }
}
