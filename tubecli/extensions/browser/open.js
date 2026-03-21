import { plugin } from 'playwright-with-fingerprints';
import minimist from 'minimist';
import fs from 'fs-extra';
import path from 'path';
import { fileURLToPath } from 'url';
import { AIEngine } from './ai_engine.js';
import * as searchAction from './actions/search.js';
import * as browseAction from './actions/browse.js';
import * as clickAction from './actions/click.js';
import * as loginAction from './actions/login.js';
import * as commentAction from './actions/comment.js';
import * as visualScanAction from './actions/visual_scan.js';
import * as watchAction from './actions/watch.js';
import * as navigateAction from './actions/navigate.js';
import * as typeAction from './actions/type.js';
import * as saveImageAction from './actions/save_image.js';
import * as searchExtractAction from './actions/search_extract.js';
import * as extractContentAction from './actions/extract_content.js';
import * as readGmailAction from './actions/read_gmail.js';
import { SessionManager } from './session_manager.js';
import { BrowserManager } from './browser_manager.js';
import axios from 'axios';
import { createRequire } from 'module';

// Mission Manager (CommonJS require to load from tasks/)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// CRITICAL: Tell plugin to use data/ directory for engine storage
// Plugin looks for engines at {cwd}/script/{version}/ and {cwd}/engine/{version}/
// Our engines are at data/script/ and data/engine/, so cwd must be data/
plugin.setWorkingFolder(path.join(__dirname, 'data'));
const _require = createRequire(import.meta.url);
let missionManager = null;
try {
  missionManager = _require('./tasks/mission_manager.cjs');
  console.log('[Mission] mission_manager.js loaded ✅');
} catch (e) {
  console.warn('[Mission] mission_manager.js not found — mission mode disabled.', e.message);
}

let agentContext = null;

// Helper: Report Status to Web Manager
async function reportStatus(args, data) {
    if (!args['instance-id']) return;
    try {
        await axios.post('http://localhost:9000/api/browser-status', {
            instanceId: args['instance-id'],
            profile: args.profile,
            agentName: data.agentName || (typeof agentContext !== 'undefined' && agentContext?.agent_name),
            avatarType: data.avatarType || (typeof agentContext !== 'undefined' && agentContext?.avatar_type),
            avatarColor: data.avatarColor || (typeof agentContext !== 'undefined' && agentContext?.avatar_color),
            ...data
        });
    } catch (e) {
        // Ignore connection errors
    }
}

// Helper: Fetch proxy from TMProxy (CURRENT ONLY)
async function fetchProxyFromProvider(provider) {
    if (!provider || !provider.api_key) return null;
    try {
        const apiKey = provider.api_key;
        const endpoint = "https://tmproxy.com/api/proxy/get-current-proxy";
        
        console.log(`[ProxyFetch] Calling TMProxy: get-current-proxy...`);
        const response = await axios.post(endpoint, {
            api_key: apiKey
        }, { timeout: 10000 });

        const data = response.data;
        if (data.code === 0 && data.data) {
            const p = data.data;
            const username = p.username || "";
            const password = p.password || "";
            const auth = username && password ? `${username}:${password}@` : "";
            
            if (p.socks5) return `socks5://${auth}${p.socks5}`;
            if (p.https) return `http://${auth}${p.https}`;
            if (p.http) return `http://${auth}${p.http}`;
        } else {
            console.warn(`[ProxyFetch] TMProxy: ${data.message || "Failed to get current proxy"}`);
        }
    } catch (e) {
        console.error(`[ProxyFetch] Error: ${e.message}`);
    }
    return null;
}

// Action Registry
const ACTION_REGISTRY = {
  navigate: navigateAction.navigate,
  type: typeAction.type,
  save_image: saveImageAction.save_image,
  search: searchAction.search,
  search_extract: searchExtractAction.search_extract,
  browse: browseAction.browse,
  click: clickAction.click,
  login: loginAction.login,
  comment: commentAction.comment,
  watch: watchAction.watch,
  visual_scan: visualScanAction.visual_scan,
  extract_content: extractContentAction.extract_content,
  read_gmail: readGmailAction.read_gmail,
  wait: async (page, params) => {
    const duration = parseInt(params.duration) || 5;
    console.log(`[WAIT] Waiting for ${duration} seconds...`);
    await page.waitForTimeout(duration * 1000);
  }
};

let browserManager = new BrowserManager();

/**
 * Execute a mission's action[] array using the local ACTION_REGISTRY.
 * Mirrors the non-session action loop but wrapped for mission lifecycle.
 * @param {import('playwright').Page} page
 * @param {Array} actions - mission.actions[]
 * @param {string} missionId
 * @param {string} profileName
 * @param {object} agentCtx
 */
async function executeMissionActions(page, actions, missionId, profileName, agentCtx) {
  console.log(`\n╔══════════════════════════════════════════════════╗`);
  console.log(`║  🎯 MISSION START: ${missionId}`);
  console.log(`║  Profile: ${profileName}`);
  console.log(`║  Actions: ${actions.length}`);
  console.log(`╚══════════════════════════════════════════════════╝\n`);

  for (const step of actions) {
    const actionFn = ACTION_REGISTRY[step.action];
    if (!actionFn) {
      console.warn(`[Mission] Unknown action: ${step.action} — skipping`);
      continue;
    }
    try {
      console.log(`[Mission] ▶ ${step.action} ${JSON.stringify(step.params)}`);
      let stepParams = { ...step.params };
      if (step.action === 'login') {
        stepParams = injectAuthCredentials(page, stepParams, agentCtx);
      }
      await actionFn(page, stepParams);
      // Small human-like pause between mission steps
      await page.waitForTimeout(1500 + Math.floor(Math.random() * 2000));
    } catch (err) {
      console.error(`[Mission] ❌ Step '${step.action}' failed: ${err.message}`);
      // Don't abort — attempt remaining steps
    }
  }

  console.log(`\n[Mission] ✅ All steps executed for ${missionId}\n`);
}

/**
 * Auto-inject auth credentials into a login action params.
 * Looks up agentContext.auth for the current page domain.
 * Falls back to manually provided params if already set.
 * @param {import('playwright').Page} page
 * @param {object} params - Action params (may already have email/password)
 * @param {object|null} agentCtx - agentContext loaded from JSON
 * @returns {object} params with credentials injected
 */
/**
 * Check if a browser profile directory already has an active session.
 * A profile is considered "set up" (has session) if it contains browser data files.
 * @param {string} profileName - Profile directory name under ./profiles/
 * @returns {Promise<boolean>}
 */
async function checkProfileHasSession(profileName, profilesDir = './profiles') {
  if (!profileName) return false;
  try {
    const profilesDir = global._profilesDir || './profiles';
    const profilePath = path.resolve(profilesDir, profileName);
    if (!await fs.pathExists(profilePath)) {
      console.log(`[Auth] Profile '${profileName}' not found — will login to set up.`);
      return false;
    }
    // Check for signs of an active browser session:
    // Playwright stores profile data in subdirectories like Default/
    const contents = await fs.readdir(profilePath);
    const hasData = contents.some(f => ['Default', 'Cookies', 'Local Storage', 'fingerprint.json', 'stats.json'].includes(f));
    if (hasData) {
      console.log(`[Auth] Profile '${profileName}' has existing session data — skipping login.`);
      return true;
    }
    console.log(`[Auth] Profile '${profileName}' exists but has no session — will login to set up.`);
    return false;
  } catch (e) {
    console.warn(`[Auth] Could not check profile session: ${e.message}`);
    return false;
  }
}

function injectAuthCredentials(page, params, agentCtx) {
  // If credentials already in params, use them as-is
  if ((params.email || params.username) && params.password) return params;
  if (!agentCtx || !agentCtx.auth) return params;

  const currentUrl = page.url();
  const auth = agentCtx.auth;

  const DOMAIN_MAP = {
    'google.com': 'google', 'accounts.google.com': 'google',
    'gmail.com': 'google', 'mail.google.com': 'google',
    'docs.google.com': 'google', 'sheets.google.com': 'google',
    'drive.google.com': 'google', 'youtube.com': 'google',
    'facebook.com': 'facebook', 'fb.com': 'facebook',
    'tiktok.com': 'tiktok',
    'twitter.com': 'x', 'x.com': 'x',
    'discord.com': 'discord',
    'telegram.org': 'telegram', 'web.telegram.org': 'telegram'
  };

  let platform = params.platform || null;
  if (!platform) {
    try {
      const hostname = new URL(currentUrl).hostname.replace(/^www\./, '');
      platform = DOMAIN_MAP[hostname];
      if (!platform) {
        for (const [domain, p] of Object.entries(DOMAIN_MAP)) {
          if (hostname.endsWith(domain)) { platform = p; break; }
        }
      }
    } catch (e) {}
  }

  if (!platform || !auth[platform] || !Array.isArray(auth[platform])) return params;
  const account = auth[platform].find(a => a.enabled !== false);
  if (!account) return params;

  console.log(`[Auth] Auto-injecting ${platform} credentials for: ${account.username || account.email}`);
  return {
    ...params,
    platform,
    email: account.username || account.email,
    username: account.username || account.email,
    password: account.password,
    recoveryEmail: account.recoveryEmail || params.recoveryEmail || null,
    twoFactorCodes: account.twoFactorCodes || params.twoFactorCodes || null,
    // Pass the account's linked profile so caller can decide to skip login
    authProfile: account.profile || null
  };
}

/**
 * Check if the current Google page shows a logged-in session.
 * Returns true if user appears to be logged in.
 * @param {import('playwright').Page} page
 * @returns {Promise<boolean>}
 */
async function checkGoogleLoginStatus(page) {
  try {
    const url = page.url();
    // If we're on a sign-in page, definitely not logged in
    if (url.includes('accounts.google.com/signin') || url.includes('/ServiceLogin')) {
      return false;
    }
    // Check for avatar/profile button using modern + legacy Google selectors
    const loggedIn = await page.evaluate(() => {
      // Modern Google 2024: account avatar button (top-right)
      const modernAvatar = document.querySelector(
        'a[href*="myaccount.google.com"] img, ' +
        'img[alt*="Google Account"], ' +
        '[data-ogsr-up] img, ' +          // Google Search avatar
        'a[aria-label*="Google Account"], ' +
        '.gb_A img, ' +                    // Legacy
        '[data-gbap], #gbwa'               // Legacy
      );
      // "Sign in" button means NOT logged in
      const signInBtn = document.querySelector(
        'a[href*="ServiceLogin"], a[href*="accounts.google.com/signin"], ' +
        'a[data-is-menu-item][href*="signin"]'
      );
      if (signInBtn) return false;
      if (modernAvatar) return true;
      // Fallback: check for account email in page meta/cookies area
      const accountEl = document.querySelector('[data-email], [data-authuser], #gb a[href*="mail.google"]');
      return !!accountEl;
    });
    return loggedIn;
  } catch (e) {
    console.warn('[Auth] Could not check Google login status:', e.message);
    return false;
  }
}

/**
 * Auto-login: checks google login state, tries login once per profile per run.
 * Failure is tracked PER ACCOUNT USERNAME in a global auth_status.json file.
 * - Next run: skips failed username, picks next non-failed enabled account.
 * - A profile only attempts login ONCE per run (does not retry with another account).
 */
async function autoLoginIfNeeded(page, profileName, agentCtx) {
  if (!agentCtx || !agentCtx.auth) return 'no_credentials';

  // Global status file tracks both FAILED accounts and already-LOGGED-IN profiles
  const statusFile = path.resolve('./auth_status.json');

  // 1. Read global auth status
  let authStatus = {};
  try {
    if (await fs.pathExists(statusFile)) {
      authStatus = await fs.readJson(statusFile);
    }
  } catch (e) {}

  // ✅ FIX 1: If this profile already has a recorded successful login, skip entirely
  const profileKey = `profile:${profileName}`;
  if (authStatus[profileKey] && authStatus[profileKey].loggedIn === true) {
    const since = authStatus[profileKey].loggedInAt || 'unknown';
    console.log(`[Auth] ✅ Profile '${profileName}' already logged in (recorded ${since}) — skipping.`);
    return 'skipped';
  }

  const COOLDOWN_MS = 24 * 60 * 60 * 1000; // 24 hours - only for failed accounts
  const now = Date.now();

  // Helper: is an account on cooldown?
  // An account is blocked ONLY if it has explicitly failed=true
  // lastUsedAt alone does NOT block — an account can login to multiple profiles
  function isOnCooldown(username) {
    const entry = authStatus[username];
    if (!entry) return false;
    if (entry.failed === true) {
      // Check if failed entry has been around for 24h (auto-reset after 24h)
      if (entry.failedAt) {
        const elapsed = now - new Date(entry.failedAt).getTime();
        if (elapsed > COOLDOWN_MS) {
          console.log(`[Auth] Account '${username}' failed >24h ago — auto-reset, will retry.`);
          return false; // Allow retry after 24h
        }
      }
      return true; // Still in failure cooldown
    }
    return false; // lastUsedAt alone does NOT trigger cooldown
  }

  const failedUsernames = new Set(
    Object.entries(authStatus)
      .filter(([k, v]) => !k.startsWith('profile:') && isOnCooldown(k))
      .map(([username]) => username)
  );

  // 2. Pick account: prefer the one linked to this profile, fallback to first non-cooldown enabled
  const googleAccounts = agentCtx.auth?.google || [];

  // Log cooldown status for debugging
  for (const a of googleAccounts) {
    const entry = authStatus[a.username];
    if (entry && entry.lastUsedAt) {
      const elapsed = now - new Date(entry.lastUsedAt).getTime();
      const remaining = Math.max(0, COOLDOWN_MS - elapsed);
      const remH = (remaining / 3600000).toFixed(1);
      console.log(`[Auth] Account '${a.username}': ${isOnCooldown(a.username) ? `⏳ cooldown ${remH}h left` : '✅ available'}`);
    }
  }

  // ✅ FIX 2: Find best matching account
  // 1. Exact match (account.profile === profileName)
  // 2. Wildcard match (account.profile is empty or matches)
  let account = googleAccounts.find(
    a => a.enabled !== false && !failedUsernames.has(a.username) && (a.profile === profileName)
  );
  
  // Fall back to any non-cooldown enabled account (treat empty profile as wildcard)
  if (!account) {
    account = googleAccounts.find(a => a.enabled !== false && !failedUsernames.has(a.username));
    if (account) {
      console.log(`[Auth] Using account '${account.username}' as wildcard for profile '${profileName}'`);
    }
  }

  if (!account) {
    const reasons = googleAccounts.map(a => {
      if (a.enabled === false) return `${a.username}: disabled`;
      if (authStatus[a.username]?.failed) return `${a.username}: failed`;
      if (isOnCooldown(a.username)) {
        const elapsed = now - new Date(authStatus[a.username].lastUsedAt).getTime();
        const remH = ((COOLDOWN_MS - elapsed) / 3600000).toFixed(1);
        return `${a.username}: cooldown (${remH}h left)`;
      }
      return `${a.username}: unknown`;
    });
    console.log('[Auth] No eligible Google account. Reasons:\n  ' + reasons.join('\n  '));
    return 'no_credentials';
  }

  // 3. Navigate to Google and check if already logged in via DOM
  try {
    await page.goto('https://www.google.com', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2000);
  } catch (e) {
    console.warn('[Auth] Could not navigate to Google for login check:', e.message);
    return 'skipped';
  }

  const alreadyLoggedIn = await checkGoogleLoginStatus(page);
  if (alreadyLoggedIn) {
    console.log(`[Auth] ✅ Profile '${profileName}' is indeed logged in to Google (DOM verified).`);
    // Persist so next run skips DOM check entirely
    if (!authStatus[profileKey] || !authStatus[profileKey].loggedIn) {
        authStatus[profileKey] = { loggedIn: true, loggedInAt: new Date().toISOString(), account: account.username };
        await fs.writeJson(statusFile, authStatus, { spaces: 2 });
    }
    return 'skipped';
  } else {
    // If we thought we were logged in but DOM check says no -> clear it!
    if (authStatus[profileKey] && authStatus[profileKey].loggedIn) {
        console.log(`[Auth] ⚠️ Profile '${profileName}' was marked as logged in but DOM check failed. Clearing status...`);
        delete authStatus[profileKey];
        await fs.writeJson(statusFile, authStatus, { spaces: 2 });
    }
  }

  // 4. Mark account as in-use BEFORE attempting (prevents concurrent runs picking same account)
  authStatus[account.username] = {
    ...(authStatus[account.username] || {}),
    lastUsedAt: new Date().toISOString(),
    inUseBy: profileName,
    failed: false
  };
  await fs.writeJson(statusFile, authStatus, { spaces: 2 });

  console.log(`\n[Auth] Profile '${profileName}' not logged in. Trying account: ${account.username}`);
  console.log(`[Auth] (${failedUsernames.size} account(s) on cooldown or failed)`);

  const { login } = await import('./actions/login.js');

  try {
    await page.goto('https://accounts.google.com/signin', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500);

    await login(page, {
      platform: 'google',
      email: account.username,
      username: account.username,
      password: account.password,
      recoveryEmail: account.recoveryEmail || null,
      twoFactorCodes: account.twoFactorCodes || null
    });

    // 5. Verify login success
    await page.waitForTimeout(3000);
    await page.goto('https://www.google.com', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2000);
    const loginSuccess = await checkGoogleLoginStatus(page);

    if (loginSuccess) {
      console.log(`[Auth] ✅ Login SUCCESS: ${account.username} → profile '${profileName}'`);
      // Record profile as logged in
      authStatus[profileKey] = { loggedIn: true, loggedInAt: new Date().toISOString(), account: account.username };
      // Keep lastUsedAt on account (for 24h cooldown), clear inUseBy
      authStatus[account.username] = {
        lastUsedAt: authStatus[account.username]?.lastUsedAt || new Date().toISOString(),
        failed: false
      };
      await fs.writeJson(statusFile, authStatus, { spaces: 2 });
      return 'success';
    } else {
      throw new Error('Google did not show logged-in state after login attempt');
    }

  } catch (e) {
    console.error(`[Auth] ❌ Login FAILED for account '${account.username}': ${e.message}`);
    authStatus[account.username] = {
      failed: true,
      failedAt: new Date().toISOString(),
      profile: profileName,
      reason: e.message.substring(0, 200)
    };
    await fs.writeJson(statusFile, authStatus, { spaces: 2 });
    console.log(`[Auth] Marked '${account.username}' as FAILED in auth_status.json`);
    console.log(`[Auth] Other profiles will skip this account and pick the next one.`);
    return 'failed';
  }
}

/**
 * Main Orchestrator
 */
async function main() {
  const args = minimist(process.argv.slice(2));
  
  // --- ENGINE MANAGEMENT ---
  if (args['list-versions']) {
    try {
      const versions = await plugin.versions('extended');
      process.stdout.write("__VERSIONS_START__\n");
      process.stdout.write(JSON.stringify(versions) + "\n");
      process.stdout.write("__VERSIONS_END__\n");
      process.exit(0);
    } catch (e) {
      console.error(e);
      process.exit(1);
    }
  }

  if (args['download-version']) {
    const v = args['download-version'];
    const extDir = path.dirname(fileURLToPath(import.meta.url));
    const engineBaseDir = path.join(extDir, 'data', 'engine');
    const progressFile = path.join(engineBaseDir, `${v}.progress.json`);
    
    await fs.ensureDir(engineBaseDir);

    async function updateProgress(data) {
        await fs.writeJson(progressFile, { 
            version: v, 
            status: 'downloading', 
            percent: 0, 
            ...data 
        }, { spaces: 2 });
    }

    console.log(`[Download] Starting download for version: ${v}...`);
    try {
        await updateProgress({ status: 'fetching-list', percent: 5 });
        const list = await plugin.versions('extended');
        const verInfo = list.find(x => x.browser_version === v || x.bas_version === v);
        
        if (!verInfo) {
            throw new Error(`Version ${v} not found in available engines list.`);
        }

        const basVer = verInfo.bas_version;
        const targetDir = path.join(engineBaseDir, basVer);
        const zipPath = path.join(targetDir, `FastExecuteScript.x64.zip`);
        
        await fs.ensureDir(targetDir);
        
        // If already installed, skip
        if (await fs.pathExists(path.join(targetDir, 'FastExecuteScript.exe'))) {
            console.log(`[Download] ✅ Version ${v} is already installed.`);
            await updateProgress({ status: 'completed', percent: 100 });
            process.exit(0);
        }

        const ARCH = '64';
        let url = args['download-url'] || `http://distr.bablosoft.com/distr/FastExecuteScript${ARCH}/${basVer}/FastExecuteScript.x${ARCH}.zip`;
        
        console.log(`[Download] Downloading from: ${url}`);
        await updateProgress({ status: 'downloading', percent: 10 });

        const response = await axios({
            url,
            method: 'GET',
            responseType: 'stream'
        });

        const totalLength = response.headers['content-length'];
        let downloadedLength = 0;

        const writer = fs.createWriteStream(zipPath);
        response.data.on('data', (chunk) => {
            downloadedLength += chunk.length;
            const percent = Math.round((downloadedLength / totalLength) * 80) + 10; // 10% to 90%
            updateProgress({ status: 'downloading', percent });
        });

        response.data.pipe(writer);

        await new Promise((resolve, reject) => {
            writer.on('finish', resolve);
            writer.on('error', reject);
        });

        console.log(`[Download] Extracting...`);
        await updateProgress({ status: 'extracting', percent: 95 });
        
        // Use adm-zip or similar if available, or just use plugin.useBrowserVersion(v).fetch()
        // since we already have the ZIP, it might skip download? 
        // Actually, plugin.fetch() is easier if we just let it handle extraction.
        // But since we already downloaded the zip to zipPath, we can just call plugin.fetch()
        // and it should see the file if it checks the same path.
        // The default path for fingerprints plugin is indeed data/engine/BAS_VER/FastExecuteScript.x64.zip
        
        await plugin.useBrowserVersion(v).fetch(); 

        await updateProgress({ status: 'completed', percent: 100 });
        console.log(`[Download] ✅ Version ${v} is ready.`);
        process.exit(0);
    } catch (e) {
        console.error(`[Download] ❌ Failed: ${e.message}`);
        await updateProgress({ status: 'error', error: e.message, percent: 0 });
        process.exit(1);
    }
  }

  console.log('RAW ARGV:', process.argv);
  console.log('PARSED ARGS:', JSON.stringify(args));
  const keyword = args.keyword || '';
  const actionsArg = args.action || '';
  const prompt = args.prompt || '';
  const isNewProfile = args['new-profile'] || false;
  const exportCookies = args['export-cookies'] || false;
  const isManual = args['manual'] || false;
  const isHeadless = args['headless'] || false; // Run browser in headless mode
  const sessionMode = args['session'] || false; // Enable generative session mode
  const minSessionMinutes = parseInt(args['session-duration']) || 10;
  const aiModel = args['ai-model'] || 'deepseek-r1:latest'; // NEW: AI model for browser automation
  const cliTags = args['tags']; // Raw CLI arg for overrides
  const instanceId = args['instance-id'] || null; // Instance ID from BrowserProcessManager
  const proxyArg = args['proxy'] || ''; // CLI override
  const skipProxyCheck = args['skip-proxy-check'] || false;
  const profilesDir = args['profiles-dir'] || './profiles'; // Custom profiles directory from TubeCLI
  global._profilesDir = profilesDir;
  let proxy = proxyArg;

  // Re-initialize BrowserManager with custom profiles directory
  if (args['profiles-dir']) {
    console.log(`[Config] Using custom profiles directory: ${profilesDir}`);
    browserManager = new BrowserManager({ baseDir: profilesDir });
  }

  // --- Load Agent Context EARLY ---
  if (args['context-file']) {
    try {
        agentContext = await fs.readJson(args['context-file']);
        console.log(`[Session] Agent Context loaded: ${agentContext.agent_name}`);
        
        // --- Normalization: support new JSON structure (personality.interests -> interests) ---
        if (agentContext.personality && agentContext.personality.interests && !agentContext.interests) {
          console.log('[Session] Normalizing agent context: personality.interests -> interests');
          agentContext.interests = agentContext.personality.interests;
        }
    } catch (e) {
        console.error('[Session] Failed to load context file:', e.message);
    }
  }
  
  // Log instance ID if provided (for multi-instance tracking)
  if (instanceId) {
    console.log(`[InstanceID] ${instanceId}`);
  }

  // --- Always fetch fresh proxy when Dynamic Mode is configured ---
  if (agentContext && agentContext.proxy_provider && agentContext.proxy_provider.mode === 'dynamic') {
      console.log('[Launch] Dynamic proxy mode detected. Fetching fresh proxy...');
      const fetchedProxy = await fetchProxyFromProvider(agentContext.proxy_provider);
      if (fetchedProxy) {
          console.log(`[Launch] Using fresh proxy: ${fetchedProxy}`);
          proxy = fetchedProxy;
      } else if (!proxy) {
          console.warn('[Launch] Could not fetch proxy and no fallback available.');
      }
  }

  // 1. Determine Action Sequence & Profile Override
  let actionSequence = [];
  let profileName = args.profile || 'default';
  
  if (!exportCookies && !isManual) { // Skip planning if exporting cookies or manual mode
      if (prompt) { 
        // OPTIMIZATION: If prompt looks like a structured command (contains 'then' or starts with 'read gmail'), skip AI planning
        if (prompt.includes(', then ') || prompt.includes(', and then ') || prompt.startsWith('read gmail')) {
            console.log('>>> Detected structured prompt. Skipping AI planning for speed.');
            // Simple heuristic parsing
            actionSequence = prompt.split(/, then |, and then /).map(step => {
                const s = step.trim().toLowerCase();
                let action = 'browse';
                let params = {};
                if (s.startsWith('navigate to ')) {
                    action = 'navigate';
                    params = { url: s.replace('navigate to ', '').trim() };
                } else if (s.startsWith('search for ')) {
                    action = 'search';
                    params = { keyword: s.replace('search for ', '').replace(/'/g, '') };
                } else if (s.includes('click')) {
                    action = 'click';
                    // Support variations: 'click first result', 'click result', 'click [text]'
                    if (s.includes('first result')) {
                        params = { element: 'first result' };
                    } else if (s.includes('result')) {
                        params = { element: 'result' };
                    } else {
                        params = { element: s.replace('click ', '') };
                    }
                } else if (s.includes('extract content') || s.includes('extract page content')) {
                    action = 'extract_content';
                    params = { type: 'text' }; // Assumed text dump
                } else if (s.startsWith('read gmail')) {
                    action = 'read_gmail';
                    const viewMatch = s.replace('read gmail ', '').trim();
                    params = { view: viewMatch || 'all' };
                } else if (s.startsWith('read')) {
                    action = 'browse'; // Map 'read' to 'browse'
                    const match = s.match(/(\d+) seconds/);
                    params = { duration: match ? parseInt(match[1]) : 60 };
                } else if (s.startsWith('watch')) {
                    action = 'watch';
                    const match = s.match(/(\d+) seconds/);
                    params = { duration: match ? parseInt(match[1]) : 60 };
                } else if (s.includes('browse')) {
                    action = 'browse';
                    const match = s.match(/(\d+) seconds/);
                    params = { duration: match ? parseInt(match[1]) : 60 };
                }
                
                return { action, params };
            });
            
            // Default profile if not specified
            if (!profileName || profileName === 'default') {
                // If we skipped AI, we don't get a profile suggestion, so keep current
            }
        } else {
            // Complex/Unstructured prompt -> Use AI
            console.log('>>> Analyzing prompt with AI...');
            const ai = new AIEngine(aiModel);
            const result = await ai.planActions(prompt);
            actionSequence = result.actions;
            
            console.log('\n--- 🤖 AI PLANNED ACTIONS ---');
            actionSequence.forEach((step, idx) => {
                 console.log(`${idx + 1}. [${step.action.toUpperCase()}] ${JSON.stringify(step.params)}`);
            });
            console.log('-----------------------------\n');
    
            if (result.profile && !args.profile) {
              console.log(`\n>>> Profile switch requested via prompt: ${result.profile}`);
              profileName = result.profile;
            } else if (result.profile && args.profile) {
              console.log(`\n>>> AI suggested profile '${result.profile}' but keeping CLI override '${args.profile}'`);
            }
        }
      } else if (actionsArg) {
        actionSequence = actionsArg.split(',').map(name => ({
          action: name.trim(),
          params: { keyword }
        }));
      } else {
        actionSequence = [
          { action: 'search', params: { keyword: 'playwright automation' } },
          { action: 'browse', params: { iterations: 3 } }
        ];
      }
      
      if (args['dry-run']) {
          console.log('Detected --dry-run flag. Exiting after planning.');
          process.exit(0);
      }
  }


  
  const profilePath = path.resolve(profilesDir, profileName);
  console.log(`Target Profile: ${profileName} (${profilePath})`);

  // --- Multi-Attempt Logic ---
  let attempt = 1;
  const maxAttempts = 3;
  let success = false;

  while (attempt <= maxAttempts && !success) {
    let context;
    let page;
    const isRetry = attempt > 1;

    try {
      console.log(`\n=== Execution Attempt ${attempt} (isRetry: ${isRetry}) ===`);

      // Handle profile clearing only if explicitly requested
      if (isNewProfile && fs.existsSync(profilePath) && !exportCookies) {
        console.log(`Cleaning up profile at ${profilePath}...`);
        try {
          // Preserve config.json and stats.json if they exist
          const configPath = path.join(profilePath, 'config.json');
          const statsPath = path.join(profilePath, 'stats.json');
          
          if (await fs.pathExists(configPath)) {
             await fs.copy(configPath, `${configPath}.bak`);
          }
          if (await fs.pathExists(statsPath)) {
             await fs.copy(statsPath, `${statsPath}.bak`);
          }
          
          await fs.remove(profilePath);
          await fs.mkdirp(profilePath);
          
          if (await fs.pathExists(`${configPath}.bak`)) {
             await fs.move(`${configPath}.bak`, configPath, { overwrite: true });
          }
          if (await fs.pathExists(`${statsPath}.bak`)) {
             await fs.move(`${statsPath}.bak`, statsPath, { overwrite: true });
          }
        } catch (e) {
          console.warn(`Could not remove/restore profile directory: ${e.message}`);
        }
      }

      // 2. Browser Initialization
      console.log('Fetching service key...');
      let serviceKey = '';
      try {
        const keyResponse = await axios.get('https://api.tubecreate.com/api/fingerprints/key.php', { timeout: 10000 });
        if (keyResponse.data && keyResponse.data.status === 'success' && keyResponse.data.key) {
          // Decode Base64 key
          serviceKey = Buffer.from(keyResponse.data.key, 'base64').toString('utf8');
          console.log('Service key fetched and decoded.');
        } else {
          throw new Error('Invalid key response format');
        }
      } catch (e) {
        console.error(`Failed to fetch service key: ${e.message}`);
      }
      
      if (serviceKey) {
        plugin.setServiceKey(serviceKey);
      }

      let fingerprint;
      const fingerprintPath = path.join(profilePath, 'fingerprint.json');
      const configPath = path.join(profilePath, 'config.json');

      if (await fs.pathExists(fingerprintPath)) {
          console.log('Loading saved fingerprint...');
          try {
              const fingerprintData = await fs.readFile(fingerprintPath, 'utf8');
              if (fingerprintData && fingerprintData.length > 20) {
                  // Parse fingerprint if it's a JSON string
                  try {
                      fingerprint = typeof fingerprintData === 'string' ? JSON.parse(fingerprintData) : fingerprintData;
                      
                      // Fix for wrapper object (e.g. {"canvas":true, ..., "fingerprint": "..."})
                      if (fingerprint && fingerprint.fingerprint) {
                          console.log('Detected wrapped fingerprint structure. Extracting inner fingerprint...');
                          try {
                              // If separate string, try to parse it, otherwise use as string
                              fingerprint = typeof fingerprint.fingerprint === 'string' ? JSON.parse(fingerprint.fingerprint) : fingerprint.fingerprint;
                          } catch (e) {
                              fingerprint = fingerprint.fingerprint; 
                          }
                      }
                  } catch (e) {
                      fingerprint = fingerprintData; // Use as-is if not JSON
                  }
                  console.log('Fingerprint loaded successfully.');
              } else {
                  console.warn('Fingerprint file too small, will re-fetch');
                  fingerprint = null;
              }
          } catch (e) {
              console.error(`Failed to load fingerprint: ${e.message}`);
              fingerprint = null;
          }
      } 
      
      if (!fingerprint) {
          console.log('Fetching fingerprint via BrowserManager API...');
          try {
              fingerprint = await browserManager.getFingerprint(profileName);
              if (!fingerprint) throw new Error('API returned empty fingerprint');
          } catch (e) {
              console.error(`!!! [Fingerprint] Failed to get fingerprint from API: ${e.message}`);
              console.log('Ensure your internet connection is stable and API key is valid.');
              // Wait a bit so user can see the error before exit
              await new Promise(r => setTimeout(r, 5000));
              process.exit(1);
          }
      }

      console.log('Launching browser...');
      const finalHeadless = isHeadless || !!exportCookies;

      const launchArgs = [
          '--remote-debugging-port=0', // Force random port
      ];

      // Optional: Load specific extensions if provided via CLI
      if (args['load-extension']) {
          const extensionPaths = args['load-extension'].split(',').map(p => path.resolve(p.trim()));
          launchArgs.push(`--load-extension=${extensionPaths.join(',')}`);
          launchArgs.push(`--disable-extensions-except=${extensionPaths.join(',')}`);
          console.log(`[Launch] Loading custom extensions: ${extensionPaths.join(', ')}`);
      }

      // Check for Mobile Fingerprint to resize window
      if (fingerprint) {
          let ua = "";
          if (typeof fingerprint === 'object' && fingerprint.navigator && fingerprint.navigator.userAgent) {
              ua = fingerprint.navigator.userAgent.toLowerCase();
          } else if (typeof fingerprint === 'string') {
              ua = fingerprint.toLowerCase();
          }

          if (ua.includes('android') || ua.includes('iphone') || ua.includes('ipad')) {
              console.log('[Launch] Mobile fingerprint detected. Setting small window size.');
              launchArgs.push('--window-size=450,900');
          }
      }
      
      context = await browserManager.launch(profileName, {
          headless: finalHeadless,
          fingerprint,
          proxy,
          args: launchArgs,
          skipProxyCheck // Pass the flag
      });

      // Ensure a page exists immediately
      page = context.pages()[0] || await context.newPage();

      // --- COOKIE EXPORT ---
      if (exportCookies) {
          const cookies = await context.cookies();
          console.log('__COOKIES_START__');
          console.log(JSON.stringify(cookies));
          console.log('__COOKIES_END__');
          await context.close();
          return process.exit(0);
      }

      // --- BACKGROUND HELPERS (Mouse & IP Check) ---
      // Determine proxy type label for profile indicator
      const profileProxy = agentContext?.proxy || args.proxy || '';
      let proxyLabel = 'Direct';
      if (profileProxy) {
        if (profileProxy.startsWith('socks5')) proxyLabel = 'SOCKS5';
        else if (profileProxy.startsWith('socks4')) proxyLabel = 'SOCKS4';
        else if (profileProxy.startsWith('http')) proxyLabel = 'HTTP';
        else proxyLabel = 'Proxy';
      }

      await context.addInitScript(({ instanceId, profileName, proxyLabel }) => {
        // 1. Mouse Visualization
        window.addEventListener('DOMContentLoaded', () => {
          if (document.getElementById('mouse-pointer-visualization')) return;
          const box = document.createElement('div');
          box.id = 'mouse-pointer-visualization';
          box.style.position = 'fixed';
          box.style.top = '0';
          box.style.left = '0';
          box.style.width = '20px';
          box.style.height = '20px';
          box.style.background = 'rgba(255, 0, 0, 0.7)';
          box.style.borderRadius = '50%';
          box.style.pointerEvents = 'none';
          box.style.zIndex = '9999999';
          box.style.transition = 'transform 0.1s linear';
          document.body.appendChild(box);
          document.addEventListener('mousemove', (e) => {
            box.style.transform = `translate(${e.clientX - 10}px, ${e.clientY - 10}px)`;
          });
        });

        // 2. Profile Name — expose for extension badge (URL bar)
        window.__PROFILE_NAME__ = profileName || '';

        // 3. Tab Title Injection — antidetect style: "[profileName] original title"
        //    Visible in the tab strip and when clicking URL bar
        if (profileName) {
          const prefix = `[${profileName}]`;
          const setTitle = () => {
            if (!document.title.startsWith(prefix)) {
              const originalTitle = document.title || 'New Tab';
              document.title = `${prefix} ${originalTitle}`;
            }
          };

          // Run as soon as possible
          setTitle();
          window.addEventListener('DOMContentLoaded', setTitle);
          window.addEventListener('load', setTitle);

          // MutationObserver: re-apply prefix whenever any script changes the title
          const observer = new MutationObserver(setTitle);
          const titleEl = document.querySelector('title');
          if (titleEl) {
            observer.observe(titleEl, { childList: true });
          } else {
            // title may not exist yet — watch document head
            new MutationObserver((_, obs) => {
              const t = document.querySelector('title');
              if (t) { observer.observe(t, { childList: true }); obs.disconnect(); }
            }).observe(document.documentElement, { childList: true, subtree: true });
          }
        }

        // 4. Profile Name Chip (top-center of every page)
        window.addEventListener('DOMContentLoaded', () => {
          if (document.getElementById('__profile-chip__') || !profileName) return;
          const chip = document.createElement('div');
          chip.id = '__profile-chip__';
          chip.textContent = '\uD83D\uDC64 ' + profileName;
          chip.style.cssText = [
            'position: fixed',
            'top: 8px',
            'left: 50%',
            'transform: translateX(-50%)',
            'z-index: 2147483647',
            'pointer-events: none',
            'background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            'color: #fff',
            'font-size: 12px',
            'font-weight: 700',
            'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
            'padding: 4px 14px 4px 10px',
            'border-radius: 20px',
            'box-shadow: 0 2px 8px rgba(0,0,0,0.35)',
            'letter-spacing: 0.3px',
            'white-space: nowrap',
            'opacity: 0.92',
            'user-select: none',
          ].join(';');
          document.documentElement.appendChild(chip);
        });

        // 2. Background IP Check (Reporting to Node Server)
        if (instanceId) {
            const checkIP = async () => {
                try {
                    // CRITICAL FIX: Fetch IP from the page context so it uses the proxy/WARP!
                    if (!page) return;
                    let ip = await page.evaluate(async () => {
                        try {
                            const res = await fetch('https://checkip.amazonaws.com', { signal: AbortSignal.timeout(10000) });
                            return res.ok ? (await res.text()).trim() : null;
                        } catch(e) { return null; }
                    });

                    if (!ip) {
                        try {
                            const response = await page.context().request.get('https://checkip.amazonaws.com', { timeout: 10000 });
                            if (response.ok()) {
                                const text = await response.text();
                                ip = text.trim();
                            }
                        } catch (e) {}
                    }

                    if (ip) {
                        await fetch('http://localhost:9000/api/browser-status', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                instanceId,
                                profile: profileName,
                                ip: ip,
                                city: 'Unknown',
                                country: 'Unknown'
                            })
                        });
                    }
                } catch (e) {
                    // Fail silently in background
                }
            };
            checkIP();
            // Check every 2 minutes
            setInterval(checkIP, 120000);
        }
      }, { instanceId, profileName, proxyLabel });

      // --- TAB MANAGEMENT ---
      // Listen for new pages (tabs) and switch focus
      context.on('page', async (newPage) => {
        console.log('[TabManager] New tab detected! Switching focus...');
        page = newPage; // Update the main page reference
        console.log(`[TabManager] Now on: ${page.url()}`);
      });

      // --- AUTO-LOGIN TRIGGER ---
      // Check if we need to login before starting actions/session
      if (agentContext && agentContext.auth && agentContext.auth.google && agentContext.auth.google.length > 0) {
          console.log(`\n[Auth] Auto-login check for profile: ${profileName}...`);
          try {
              const loginResult = await autoLoginIfNeeded(page, profileName, agentContext);
              console.log(`[Auth] Auto-login result: ${loginResult}`);
          } catch (e) {
              console.error(`[Auth] Error during auto-login: ${e.message}`);
          }
      }

      // 3. Manual Mode Check
      if (isManual) {
        console.log('>>> MANUAL MODE: Browser launched. Waiting for user to close window...');
        
        // Navigate to profile start page (antidetect-style: shows profile name in URL bar)
        const startUrl = `http://localhost:9000/profile-start/${encodeURIComponent(profileName)}?profile=${encodeURIComponent(profileName)}`;
        try {
            await page.goto(startUrl, { waitUntil: 'domcontentloaded', timeout: 5000 });
            console.log(`[Profile] Start page: ${startUrl}`);
        } catch (e) {
            // web_manager not running — fallback to google
            console.warn('[Profile] web_manager not reachable, falling back to Google.');
            try {
                if (page.url() === 'about:blank') await page.goto('https://www.google.com');
            } catch (fallbackErr) {
                console.warn('[Profile] Fallback navigation also failed: ' + fallbackErr.message);
            }
        }

        // Wait until the browser context is closed by the user
        // Using a Promise-based approach instead of polling pages().length
        await new Promise((resolve) => {
          context.on('close', () => {
            console.log('Browser closed by user.');
            resolve();
          });
          // Fallback: also poll in case 'close' event is missed
          const pollInterval = setInterval(() => {
            try {
              if (context.pages().length === 0) {
                clearInterval(pollInterval);
                console.log('All browser tabs closed by user.');
                resolve();
              }
            } catch (e) {
              // Context already destroyed
              clearInterval(pollInterval);
              resolve();
            }
          }, 2000);
        });
        return process.exit(0);
      }

      // 4. Execute Action Sequence (Only if NOT in session mode)
      if (!sessionMode) {
        let initialActionsSucceeded = true;
        const results = [];
        for (const step of actionSequence) {
          const actionFn = ACTION_REGISTRY[step.action];
          if (actionFn) {
            console.log(`\n--- Executing: ${step.action} ---`);
            try {
              // Auto-inject auth credentials if this is a login action
              let stepParams = { ...step.params, isRetry, aiModel };
              if (step.action === 'login') {
                stepParams = injectAuthCredentials(page, stepParams, agentContext);
                // If account has a linked profile, skip login when profile already has session
                if (stepParams.authProfile) {
                  const hasSession = await checkProfileHasSession(stepParams.authProfile);
                  if (hasSession) {
                    console.log(`[Auth] Skipping login — profile '${stepParams.authProfile}' already has session.`);
                    continue;
                  } else {
                    console.log(`[Auth] Profile '${stepParams.authProfile}' has no session — logging in to set up.`);
                  }
                }
              }
              const result = await actionFn(page, stepParams);
              if (result) {
                results.push({ action: step.action, result });
              }
            } catch (actionError) {
              console.error(`Error in action '${step.action}': ${actionError.message}`);
              
              // --- SELF-HEALING LOGIC ---
              console.log('Attempting Visual Error Diagnosis...');
              const { diagnoseAndSuggest } = await import('./vision_engine.js');
              const suggestion = await diagnoseAndSuggest(page, `Execute action: ${step.action} with params ${JSON.stringify(step.params)}`, actionError.message);
              
              if (suggestion && ACTION_REGISTRY[suggestion.action]) {
                console.log(`\n>>> SELF-HEALING: Executing alternative action: ${suggestion.action} <<<`);
                const remedialFn = ACTION_REGISTRY[suggestion.action];
                const remedialResult = await remedialFn(page, { ...suggestion.params, isRetry });
                if (remedialResult) {
                    results.push({ action: suggestion.action, result: remedialResult, healed: true });
                }
                console.log('>>> Remedial action completed. Resuming sequence. <<<\n');
              } else {
                console.warn('No effective remedial action found. Propagating error.');
                throw actionError;
              }
            }
          } else {
            console.warn(`Unknown action: ${step.action}`);
          }
        }
        console.log('\nAll actions completed successfully.');
        console.log('__RESULTS_START__');
        console.log(JSON.stringify(results, null, 2));
        console.log('__RESULTS_END__');
      }
      
      // 5. Session Mode - Continue generating actions until minimum duration reached
      if (sessionMode) {
        // 5. Start Session Mode (if enabled)
        // Parse model from args, default to qwen:latest if not set
        // FIX: Use args['ai-model'] passing from Python, fallback to args.model or default
        const sessionAiModel = args['ai-model'] || args.model || 'qwen:latest';
        const minSessionMinutes = parseInt(args['session-duration']) || 10;
        
        console.log(`\n=== SESSION MODE ENABLED (${minSessionMinutes} min minimum) ===\n`);
        
        // Use the original prompt as the User Goal
        const userGoal = prompt || "Browse naturally and interestingly";
        
        // Load Agent Context from file if provided
        let agentContext = null;
        if (args['context-file']) {
            try {
                if (await fs.pathExists(args['context-file'])) {
                    agentContext = await fs.readJson(args['context-file']);
                    console.log(`[Session] Loaded agent context for: ${agentContext.agent_name}`);
                }
            } catch (e) {
                console.error('[Session] Failed to load context file:', e.message);
            }
        }

        const session = new SessionManager(minSessionMinutes, userGoal, aiModel, agentContext, args.profile || 'default');
        
        // Initial Stat Load for AI context
        try {
          const initialStats = await browserManager.getStats(profileName);
          session.updateStats(initialStats);
        } catch (e) {}
        
        console.log(`\n>>> STARTING SESSION MODE (${minSessionMinutes} min) with Model: ${sessionAiModel} <<<`);
        console.log(`Goal: "${userGoal}"`);
        
        // Navigate to a starter page if on about:blank to give the session context
        if (page.url() === 'about:blank') {
           console.log('[Session] Starting from blank page. Navigating to Google...');
           const MAX_RETRIES = 3;
           for (let i = 0; i < MAX_RETRIES; i++) {
               try {
                   if (i > 0) console.log(`[Session] Retry attempt ${i+1}/${MAX_RETRIES} for initial navigation...`);
                   await page.goto('https://www.google.com', { waitUntil: 'domcontentloaded', timeout: 30000 });
                   break;
               } catch (e) {
                   console.warn(`[Session] Initial navigation failed: ${e.message}`);
                   if (i === MAX_RETRIES - 1) throw e; // Propagate last error to trigger browser restart
                   console.log('[Session] Waiting 5s before retry...');
                   await page.waitForTimeout(5000);
               }
           }
        }

        // === AUTO-LOGIN: Attempt Google login if profile not logged in yet ===
        if (agentContext && agentContext.auth && agentContext.auth.google && agentContext.auth.google.length > 0) {
          const loginResult = await autoLoginIfNeeded(page, profileName, agentContext);
          if (loginResult === 'success') {
            console.log('[Session] Auto-login complete. Resuming session...');
          } else if (loginResult === 'failed') {
            console.log('[Session] Auto-login failed. Continuing session without login.');
          } else if (loginResult === 'skipped') {
            console.log('[Session] Auto-login skipped (already logged in or previously failed).');
          }
        }

        // ═══════════════════════════════════════════════════════
        // 🎯 MISSION-FIRST: Claim & execute a pending mission
        //    before the AI free-session begins.
        // ═══════════════════════════════════════════════════════
        let claimedMission = null;
        if (missionManager) {
          try {
            const taskTags = agentContext?.task_tags || [];
            console.log(`[Mission] Checking for pending missions (tags: [${taskTags.join(', ') || 'any'}])...`);
            claimedMission = missionManager.claimMission(profileName, taskTags);

            if (claimedMission) {
              console.log(`[Mission] 🎯 Claimed: "${claimedMission.title}" (${claimedMission.id})`);
              console.log(`[Mission]    Progress: ${claimedMission.completed_count}/${claimedMission.target_count}`);

              // Report mission start to dashboard
              await reportStatus(args, {
                status: `mission: ${claimedMission.title.substring(0, 40)}`,
                missionId: claimedMission.id
              });

              try {
                await executeMissionActions(
                  page,
                  claimedMission.actions,
                  claimedMission.id,
                  profileName,
                  agentContext
                );
                missionManager.completeMission(claimedMission.id, profileName);
                console.log(`[Mission] ✅ ${claimedMission.id} marked complete by ${profileName}`);
              } catch (missionErr) {
                console.error(`[Mission] ❌ Mission execution error: ${missionErr.message}`);
                missionManager.failMission(claimedMission.id, missionErr.message);
              }
            } else {
              console.log('[Mission] No pending missions matching profile tags — entering free session.');
            }
          } catch (missionCheckErr) {
            console.warn('[Mission] Could not check missions:', missionCheckErr.message);
          }
        }
        // ═══════════════════════════════════════════════════════

        session.start(page.url(), userGoal, actionSequence);
        
        // Status reporting loop (every 5 seconds) - lightweight, no screenshots
        const statusInterval = setInterval(async () => {
          try {
            if (!page || page.isClosed()) {
              clearInterval(statusInterval);
              return;
            }
            
            const currentUrl = page.url();
            const status = session.getStatus();
            
            // Also fetch latest stats to display on dashboard
            let stats = null;
            try {
              stats = await browserManager.getStats(profileName);
            } catch (e) {}

            // Send status update to server for dashboard
            try {
              const fetch = (await import('node-fetch')).default;
              await fetch('http://localhost:9000/api/browser-status', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                  instanceId,
                  profile: profileName,
                  agentName: agentContext?.agent_name,
                  avatarType: agentContext?.avatar_type,
                  avatarColor: agentContext?.avatar_color,
                  url: currentUrl,
                  status: session.currentContext?.pageType || 'browsing',
                  actionCount: status.actionsCompleted,
                  lastAction: `${status.elapsedMinutes}/${minSessionMinutes} min`,
                  aiFrequency: session.getCallFrequencyStatus(),
                  stats: stats // Include RPG stats
                })
              });
            } catch (e) {
              // Server not available, skip
            }
          } catch (e) {
            // Status update failed
          }
        }, 5000);
        
        while (!session.hasReachedMinimum()) {
          try {
            // Safety check: is browser still connected?
            const browserInstance = context.browser();
            if (browserInstance && !browserInstance.isConnected()) {
              throw new Error('BROWSER_DISCONNECTED');
            }

            // Page Recovery: If page was closed (e.g. by ChatGPT glitch), recover
            if (!page || page.isClosed()) {
                const allPages = context.pages();
                if (allPages.length > 0) {
                    // Switch to the last available page (likely the original one)
                    page = allPages[allPages.length - 1];
                    console.log(`[TabManager] Recovered focus to existing tab: ${page.url()}`);
                    try { await page.bringToFront(); } catch(e) {}
                } else {
                    // No pages left, create new one
                    console.warn('[Session] All pages closed. Recreating main page...');
                    page = await context.newPage();
                    await page.goto('https://www.google.com', { waitUntil: 'domcontentloaded' });
                }
            }

            // Update context from current page
            try {
                session.updateContext(page.url());
            } catch (e) {
                // If accessing url fails, we might need one more check
                if (!page || page.isClosed()) continue; 
            }
            
            // Check if stuck on same URL
            if (session.isStuckOnSameUrl()) {
              console.log('[Session] Detected stuck on same URL. Triggering recovery...');
              throw new Error('Stuck on same URL - triggering recovery');
            }
            
            // DYNAMIC: Scan page content to detect available elements
            const pageContent = await session.scanPageContent(page);
            
            // Record the page visit
            if (!pageContent.isErrorPage && page) {
                await session.recordPageVisit(page.url(), pageContent.title, page);
            }

            if (pageContent.isErrorPage) {
                console.log('\n[Session] ❌ Network error page detected.');
                
                // Step 1: Try reloading the current page
                console.log('[Session] Step 1: Reloading page...');
                try {
                    await page.reload({ waitUntil: 'domcontentloaded', timeout: 15000 });
                    await page.waitForTimeout(3000);
                    const afterReload = await session.scanPageContent(page);
                    if (!afterReload.isErrorPage) {
                        console.log('[Session] ✅ Page recovered after reload!');
                        continue; // Resume session loop
                    }
                } catch (e) {
                    console.warn('[Session] Reload failed:', e.message);
                }
                
                // Step 2: Try navigating to Google
                console.log('[Session] Step 2: Navigating to Google...');
                try {
                    await page.goto('https://www.google.com', { waitUntil: 'domcontentloaded', timeout: 15000 });
                    await page.waitForTimeout(3000);
                    const afterGoogle = await session.scanPageContent(page);
                    if (!afterGoogle.isErrorPage) {
                        console.log('[Session] ✅ Google loaded. Resuming session from Google.');
                        session.updateContext(page.url());
                        continue; // Resume session loop
                    }
                } catch (e) {
                    console.warn('[Session] Google navigation failed:', e.message);
                }
                
                // Step 3: Rotate proxy (last resort)
                console.log('[Session] Step 3: All recovery failed. Rotating proxy...');
                await page.waitForTimeout(5000);
                throw new Error('BROWSER_CRASHED'); // Force rotation by crashing to outer loop
            }

            // --- AUTO-DISMISS POPUPS ---
            if (pageContent.blockingPopup) {
                console.log(`[Session] Blocking popup detected: ${pageContent.blockingPopup.selector}. Attempting dismissal...`);
                let popupCleared = false;
                let attempts = 0;
                const dismissTerms = ['close', 'not now', 'dismiss', 'no thanks', 'maybe later', 'deny', 'block', 'reject'];

                while (attempts < 5) {
                    attempts++;
                    // A. Prioritize known dismiss buttons
                    let targetBtn = null;
                    for (const btn of pageContent.blockingPopup.buttons) {
                        if (dismissTerms.some(term => btn.text.toLowerCase().includes(term))) {
                            targetBtn = btn;
                            break;
                        }
                    }

                    // B. Fallback: Random button inside popup
                    if (!targetBtn && pageContent.blockingPopup.buttons.length > 0) {
                        console.log(`[Session] No clear dismissal button found. Picking a random button (Attempt ${attempts})...`);
                        targetBtn = pageContent.blockingPopup.buttons[Math.floor(Math.random() * pageContent.blockingPopup.buttons.length)];
                    }

                    if (targetBtn) {
                        console.log(`[Session] Clicking popup button: "${targetBtn.text}"`);
                        try {
                            // Use the existing click action logic (text-based)
                            const clickAction = ACTION_REGISTRY['click'];
                            await clickAction.click(page, { text: targetBtn.text });
                            await page.waitForTimeout(2000); // Wait for popup to disappear

                            // Re-check
                            const reScan = await session.scanPageContent(page);
                            if (!reScan.blockingPopup) {
                                console.log('[Session] Popup successfully cleared.');
                                popupCleared = true;
                                break;
                            }
                        } catch (e) {
                            console.warn(`[Session] Popup click failed: ${e.message}`);
                        }
                    } else {
                        console.log('[Session] No interactive elements in popup to click.');
                        break;
                    }
                }
                
                if (!popupCleared) {
                    console.warn('[Session] Failed to clear popup after multiple attempts. Proceeding anyway...');
                } else {
                    // If cleared, re-scan one last time to get clean page content
                    const cleanScan = await session.scanPageContent(page);
                    Object.assign(pageContent, cleanScan);
                }

            }
            
            // Generate next action chain based on actual page content (await async AI generation)
            const actionChain = await session.generateNextAction(page, pageContent);
            
            if (!actionChain || !Array.isArray(actionChain) || actionChain.length === 0) {
              console.log('[Session] No more actions or invalid chain. Ending session.');
              break;
            }
            
            // Execute each action in the chain sequentially
            for (const nextAction of actionChain) {
              // Display session status for each step
              const status = session.getStatus();
              console.log(`\n[Session] ${status.elapsedMinutes}/${minSessionMinutes} min | Step: ${nextAction.action} (${status.actionsCompleted + 1}) | Page: ${status.pageType}`);
              
              // Execute the action
              let actionFn = ACTION_REGISTRY[nextAction.action];
              
              // Map 'read' to 'browse' if not explicitly defined
              if (!actionFn && nextAction.action === 'read') {
                  console.log('[Session] Mapping "read" action to "browse" implementation');
                  actionFn = ACTION_REGISTRY['browse'];
              }

              if (actionFn) {
                try {
                  // Auto-inject auth credentials if this is a login action
                  let actionParams = { ...nextAction.params, isRetry, aiModel: sessionAiModel };
                  // Inject profileName for extract_content action
                  if (nextAction.action === 'extract_content') {
                    actionParams.profileName = profileName;
                    actionParams.enable_scraping = agentContext?.enable_scraping !== false; // handle absent defaults
                    actionParams.scraper_text_limit = agentContext?.scraper_text_limit || 10000;
                  }
                  if (nextAction.action === 'login') {
                    actionParams = injectAuthCredentials(page, actionParams, agentContext);
                    // If account has a linked profile, skip login when profile already has session
                    if (actionParams.authProfile) {
                      const hasSession = await checkProfileHasSession(actionParams.authProfile, profilesDir);
                      if (hasSession) {
                        console.log(`[Auth] Skipping login — profile '${actionParams.authProfile}' already has session.`);
                        session.recordAction('login', actionParams, 'skipped', 'profile already has session');
                        continue;
                      } else {
                        console.log(`[Auth] Profile '${actionParams.authProfile}' has no session — logging in to set up.`);
                      }
                    }
                  }
                  const actionResult = await actionFn(page, actionParams);
                  session.recordAction(nextAction.action, nextAction.params, 'success');
                  
                  // Track scraped URL to prevent duplicate extraction
                  if (nextAction.action === 'extract_content' && actionResult) {
                    session.addScrapedUrl(page.url());
                  }
                  
                  // Update RPG Stats
                  const updatedStats = await browserManager.updateStats(profileName, nextAction.action, {
                    url: page.url(),
                    keyword: nextAction.params.keyword
                  });
                  session.updateStats(updatedStats); // Sync with AI
                } catch (actionError) {
                  // Record error in stats
                  const updatedStats = await browserManager.updateStats(profileName, 'error');
                  session.updateStats(updatedStats); // Sync with AI

                  if (actionError.message === 'NO_VIDEO_FOUND') {
                    console.log('[Session] Fallback: No video found during watch. Switching to browse behavior...');
                    const browseFn = ACTION_REGISTRY['browse'];
                    if (browseFn) {
                      await browseFn(page, { iterations: 10 });
                      session.recordAction('browse', { iterations: 10, note: 'fallback from watch' }, 'success');
                      await browserManager.updateStats(profileName, 'browse');
                    }
                  } else {
                    console.warn(`[Session] Action error: ${actionError.message}. Skipping remaining chain.`);
                    session.recordAction(nextAction.action, nextAction.params, 'error', actionError.message);
                    break; // Stop current chain on error
                  }
                }
              } else {
                console.warn(`[Session] Unknown action: ${nextAction.action}`);
              }
              
              // Brief pause between steps for stability
              await page.waitForTimeout(2000);
              session.updateContext(page.url());
            }
            
          } catch (sessionError) {
            console.error(`[Session] Error during action: ${sessionError.message}`);
            
            // CRITICAL: Detect browser crash or Network failure - cannot be recovered in-session
            if (sessionError.message.includes('Page crashed') || 
                sessionError.message.includes('Target crashed') ||
                sessionError.message.includes('Browser closed') ||
                sessionError.message.includes('ERR_PROXY_CONNECTION_FAILED') ||
                sessionError.message.includes('ERR_TUNNEL_CONNECTION_FAILED') ||
                sessionError.message.includes('ERR_CONNECTION_RESET') ||
                sessionError.message.includes('ERR_NAME_NOT_RESOLVED') ||
                sessionError.message.includes('ERR_CONNECTION_TIMED_OUT') ||
                sessionError.message.includes('ERR_CONNECTION_CLOSED')) {
              console.error(`[Session] CRITICAL: ${sessionError.message}. Restarting browser required.`);
              throw new Error('BROWSER_CRASHED'); // Signal outer retry loop to restart
            }
            
            console.log('[Session] Recovering by starting a new task...');
            
            // Recovery strategy: Navigate to a safe page and start fresh
            try {
              // CRITICAL: Check if page is valid before navigating
              if (!page || page.isClosed()) {
                  console.error('[Session] Page is closed/detached. Cannot recover in-session.');
                  throw new Error('BROWSER_CRASHED');
              }

              const currentUrl = page.url();
              
              // If we're stuck on an error page or the same URL, navigate to a fresh start
              if (sessionError.message.includes('Stuck on same URL') ||
                  sessionError.message.includes('not visible') || 
                  sessionError.message.includes('Target') || 
                  sessionError.message.includes('closed')) {
                const recoveryActions = [
                  { url: 'https://www.youtube.com', type: 'youtube_home' },
                  { url: 'https://news.google.com', type: 'news' },
                  { url: 'https://github.com/trending', type: 'github_general' }
                ];
                
                const recovery = recoveryActions[Math.floor(Math.random() * recoveryActions.length)];
                console.log(`[Session] Navigating to ${recovery.url} to recover...`);
                
                await page.goto(recovery.url, { waitUntil: 'domcontentloaded', timeout: 15000 });
                session.updateContext(recovery.url);
                session.resetStuckCounter(); // Reset stuck detection after recovery
                session.updateContext(page.url());
                
                console.log(`[Session] Recovery successful. Context: ${session.currentContext.pageType}`);
              }
            } catch (recoveryError) {
              console.warn(`[Session] Recovery navigation failed: ${recoveryError.message}`);
              
              // If recovery also fails with crash OR DETACHED FRAME, propagate up
              if (recoveryError.message.includes('crashed') || 
                  recoveryError.message.includes('closed') || 
                  recoveryError.message.includes('detached') || 
                  recoveryError.message.includes('Target closed') ||
                  recoveryError.message.includes('Frame was detached')) {
                console.error('[Session] Critical recovery failure (Detached/Crashed). Restarting browser...');
                throw new Error('BROWSER_CRASHED');
              }
            }
            
            // Brief pause before continuing
            await page.waitForTimeout(3000);
          }
        }
        
        clearInterval(statusInterval);
        const finalStatus = session.end();
        console.log('\n=== SESSION COMPLETED ===');
        console.log(`Duration: ${finalStatus.elapsedMinutes} minutes`);
        console.log(`Actions: ${finalStatus.actionsCompleted}`);
        console.log(`Final URL: ${finalStatus.currentUrl}`);
      }
      
      success = true;

    } catch (error) {
      if (error.message === 'BROWSER_CRASHED' && attempt < maxAttempts) {
        console.error('\n>>> BROWSER CRASHED! Restarting with new fingerprint...');
        // Close current context if still available
        try {
          if (context) await context.close();
        } catch (e) {
          // Context already dead, ignore
        }
        attempt++;
      } else if (error.message === 'CAPTCHA_DETECTED' && attempt < maxAttempts) {
        console.error('\n>>> CAPTCHA detected on first attempt. Retrying...');
        attempt++;
      } else if ((error.message === 'FINGERPRINT_RETRY' || error.message === 'FINGERPRINT_FATAL_ERROR') && attempt < maxAttempts) {
        console.error('\n>>> Retrying with fresh fingerprint (Fatal Error Detected)...');
        // Force delete fingerprint
        try {
             const fingerprintPath = path.join(profilePath, 'fingerprint.json');
             await fs.remove(fingerprintPath);
        } catch (e) {}
        attempt++;
      } else if ((error.message.includes('Failed to get proxy ip') ||
                  error.message.includes('Failed to launch browser') ||
                  error.message.includes('socks5 reply has wrong version') ||
                  error.message.includes('User was rejected by the SOCKS5 server') ||
                  error.message.includes('cannot complete SOCKS5 connection') ||
                  error.message.includes('Incorrect format')) && attempt < maxAttempts) {
        // Proxy is dead/expired - try to fetch a fresh one from dynamic provider
        console.error(`\n>>> Proxy error: ${error.message}. Trying to refresh proxy...`);
        if (agentContext && agentContext.proxy_provider && agentContext.proxy_provider.mode === 'dynamic') {
            const freshProxy = await fetchProxyFromProvider(agentContext.proxy_provider);
            if (freshProxy) {
                console.log(`[ProxyRefresh] Got fresh proxy: ${freshProxy}`);
                proxy = freshProxy;
            } else {
                console.warn('[ProxyRefresh] Could not get fresh proxy. Retrying with no proxy...');
                proxy = null;
            }
        }
        try { if (context && !isManual) await context.close(); } catch (e) {}
        attempt++;
      } else if ((error.message.includes('Page crashed') || 
                  error.message.includes('Target page, context or browser has been closed') || 
                  error.message.includes('Target closed') || 
                  error.message.includes('ERR_CONNECTION_TIMED_OUT') ||
                  error.message.includes('ERR_PROXY_CONNECTION_FAILED') ||
                  error.message.includes('ERR_TUNNEL_CONNECTION_FAILED') ||
                  error.message.includes('ERR_CONNECTION_RESET') ||
                  error.message.includes('ERR_NAME_NOT_RESOLVED') ||
                  error.message.includes('ERR_SSL_PROTOCOL_ERROR') ||
                  error.message.includes('ERR_CONNECTION_CLOSED')) && attempt < maxAttempts) {
        console.error(`\n>>> Browser Crash/Network Error detected: ${error.message}. Retrying...`);
        attempt++;
      } else if (error.message === 'CAPTCHA_TIMEOUT') {
        console.error('\n>>> Manual CAPTCHA resolution timed out. Closing...');
        break;
      } else {
        console.error('\nExecution failed:', error.message);
        break;
      }
    } finally {
      // Skip auto-close in manual mode — manual mode handles its own exit
      if (!isManual) {
        console.log('Closing browser in 5 seconds...');
        if (page && !page.isClosed()) {
          await page.waitForTimeout(5000);
        }
        if (typeof context !== 'undefined') {
          try { await context.close(); } catch (e) {}
        }
      }
    }
  }

  if (success) {
    process.exit(0);
  } else {
    console.error('\n>>> Process finished with FAILURE status.');
    console.log('Closing in 20 seconds...');
    setTimeout(() => process.exit(1), 20000);
  }
}

main().catch((err) => {
  console.error('\n!!! CRITICAL ERROR !!!');
  console.error(err);
  console.log('\nClosing in 20 seconds...');
  setTimeout(() => process.exit(1), 20000);
});
