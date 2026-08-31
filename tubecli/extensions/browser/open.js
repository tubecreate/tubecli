// Loaded dynamically, not as a static import — the same treatment browser_manager.js
// already got. playwright-with-fingerprints is the BAS binding and its npm package
// declares os=win32, so package.json keeps it in optionalDependencies and npm simply
// skips it on Linux and macOS. A static import is resolved before any statement runs,
// so this one line made open.js unloadable on exactly the platforms where it was meant
// to degrade gracefully: node exited 1 before printing anything, and a scheduled agent
// browser run died with no usable message. Only the BAS paths below touch it; ShardX
// does its own fingerprinting.
let plugin = null;
try {
    ({ plugin } = await import('playwright-with-fingerprints'));
} catch (e) {
    console.log('[Browser] BAS fingerprint plugin not available on this platform — ShardX only.');
}

function requirePlugin() {
    if (!plugin) {
        throw new Error(
            'This profile uses a BAS engine, which only runs on Windows. '
            + 'Edit the profile to use a ShardX engine instead.'
        );
    }
    return plugin;
}

import minimist from 'minimist';
import fs from 'fs-extra';
import path from 'path';
import { fileURLToPath } from 'url';
import { AIEngine } from './ai_engine.js';
import { initTrail, logTrail } from './run_trail.js';
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
// Guarded: on Linux/macOS the plugin never loads, and this call at module top level
// would throw before main() is ever reached — engine storage only matters to BAS.
if (plugin) {
  plugin.setWorkingFolder(path.join(__dirname, 'data'));
}
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
    const hasData = contents.some(f => ['Default', 'Cookies', 'Local Storage', 'fingerprint.json', 'fingerprint_saved.json', 'stats.json'].includes(f));
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
 * Sync all version descriptor files (*_64.json) from __dirname to __dirname/data
 */
async function syncDescriptors() {
  try {
    const files = await fs.readdir(__dirname);
    const descriptorFiles = files.filter(f => f.endsWith('_64.json'));
    const dataDir = path.join(__dirname, 'data');
    await fs.ensureDir(dataDir);
    for (const file of descriptorFiles) {
      const srcPath = path.join(__dirname, file);
      const destPath = path.join(dataDir, file);
      await fs.copy(srcPath, destPath, { overwrite: true });
    }
    console.log('[Config] Synced version descriptor files to data directory.');
  } catch (e) {
    console.warn('[Config] Failed to sync version descriptor files:', e.message);
  }
}

/**
 * Main Orchestrator
 */
async function main() {
  await syncDescriptors();
  const args = minimist(process.argv.slice(2));
  
  // --- ENGINE MANAGEMENT ---
  if (args['list-versions']) {
    try {
      const versions = await requirePlugin().versions('extended');
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
        const tmpFile = progressFile + '.tmp';
        await fs.writeJson(tmpFile, { 
            version: v, 
            status: 'downloading', 
            percent: 0, 
            ...data 
        }, { spaces: 2 });
        await fs.move(tmpFile, progressFile, { overwrite: true });
    }

    console.log(`[Download] Starting download for version: ${v}...`);
    try {
        await updateProgress({ status: 'fetching-list', percent: 5 });
        const list = await requirePlugin().versions('extended');
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
        
        await requirePlugin().useBrowserVersion(v).fetch();

        await updateProgress({ status: 'completed', percent: 100 });
        console.log(`[Download] ✅ Version ${v} is ready.`);
        process.exit(0);
    } catch (e) {
        console.error(`[Download] ❌ Failed: ${e.message}`);
        await updateProgress({ status: 'error', error: e.message, percent: 0 });
        process.exit(1);
    }
  }

  // Redacted. This printed the raw argv, which carries --login-password and
  // --login-email for any profile with a saved login, straight into the launcher
  // log file — a plaintext credential on disk, and one the new run log would have
  // captured excerpts of and served over HTTP.
  const SECRET_ARG = /^--login-(password|email|recovery|2fa)$|password|token|secret|api-?key/i;
  const safeArgv = [];
  for (let i = 0; i < process.argv.length; i++) {
    safeArgv.push(process.argv[i]);
    if (SECRET_ARG.test(process.argv[i]) && i + 1 < process.argv.length) {
      safeArgv.push('***');
      i++;
    }
  }
  const safeArgs = {};
  for (const [k, v] of Object.entries(args)) {
    safeArgs[k] = SECRET_ARG.test(k) ? '***' : v;
  }
  console.log('RAW ARGV:', safeArgv);
  console.log('PARSED ARGS:', JSON.stringify(safeArgs));
  const keyword = args.keyword || '';
  const actionsArg = args.action || '';
  const prompt = args.prompt || '';
  const isNewProfile = args['new-profile'] || false;
  const exportCookies = args['export-cookies'] || false;
  const isManual = args['manual'] || false;
  const isHeadless = args['headless'] || false; // Run browser in headless mode
  const sessionMode = args['session'] || false; // Enable generative session mode
  const minSessionMinutes = parseInt(args['session-duration']) || 10;
  // Python resolves which AI drives this session (the agent's own pick, then
  // the default browser AI, then the user's default AI) and passes the answer
  // on argv, so there is no chain to repeat here. Empty means Python had
  // nothing either: send no model and let the /localai proxy decide, rather
  // than naming a model nobody chose.
  const aiModel = args['ai-model'] || '';
  const cliTags = args['tags']; // Raw CLI arg for overrides
  const instanceId = args['instance-id'] || null; // Instance ID from BrowserProcessManager
  const proxyArg = args['proxy'] || ''; // CLI override
  const skipProxyCheck = args['skip-proxy-check'] || false;
  const profilesDir = args['profiles-dir'] || './profiles'; // Custom profiles directory from TubeCLI
  let profileName = args.profile || 'default';
  const startUrlArg = args['url'] || ''; // URL to open directly (e.g. OAuth callback)
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
        // Nhật ký diễn biến theo run_id — thư mục anh em của browser_profiles
        // (đường dẫn data duy nhất mà argv cho biết).
        if (agentContext.run_id && args['profiles-dir']) {
          initTrail(path.join(path.dirname(String(args['profiles-dir'])), 'session_actions'), agentContext.run_id);
        }
        
        // --- Normalization: support new JSON structure (personality.interests -> interests) ---
        if (agentContext.personality && agentContext.personality.interests && !agentContext.interests) {
          console.log('[Session] Normalizing agent context: personality.interests -> interests');
          agentContext.interests = agentContext.personality.interests;
        }
    } catch (e) {
        console.error('[Session] Failed to load context file:', e.message);
    }
  } else {
    // If no context file, try to find an agent in agents.json that has this profile in allowed_profiles
    try {
      const agentsPath = path.resolve(profilesDir, '..', 'agents.json');
      const fallbackPath = path.resolve(__dirname, '..', '..', '..', 'data', 'agents.json');
      let targetPath = agentsPath;
      if (!await fs.pathExists(targetPath) && await fs.pathExists(fallbackPath)) {
        targetPath = fallbackPath;
      }
      
      if (await fs.pathExists(targetPath)) {
        const agents = await fs.readJson(targetPath);
        if (Array.isArray(agents)) {
          const matchingAgent = agents.find(a => 
            Array.isArray(a.allowed_profiles) && a.allowed_profiles.includes(profileName)
          );
          if (matchingAgent) {
            agentContext = {
              agent_id: matchingAgent.id,
              agent_name: matchingAgent.name,
              enable_scraping: matchingAgent.enable_scraping,
              scraper_text_limit: matchingAgent.scraper_text_limit || 10000,
              interests: matchingAgent.persona?.interests || matchingAgent.interests || [],
              routine: matchingAgent.routine || {}
            };
            console.log(`[Session] Implicitly loaded context for agent '${agentContext.agent_name}' associated with profile '${profileName}' (enable_scraping: ${agentContext.enable_scraping})`);
          }
        }
      }
    } catch (e) {
      console.warn(`[Config] Failed to resolve implicit agent context from agents.json: ${e.message}`);
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
  
  if (!exportCookies && !isManual) { // Skip planning if exporting cookies or manual mode
      if (prompt) { 
        // OPTIMIZATION: If prompt looks like a structured command (contains 'then' or starts with 'read gmail' or 'login'), skip AI planning
        if (prompt.includes(', then ') || prompt.includes(', and then ') || prompt.startsWith('read gmail') || prompt.toLowerCase().startsWith('login ')) {
            console.log('>>> Detected structured prompt. Skipping AI planning for speed.');
            // Simple heuristic parsing
            // ", and " cũng là ranh giới bước: prompt cũ kiểu "click a video
            // result, and watch it for 120 seconds" từng bị nuốt mất nửa sau
            // (chỉ click, phần watch bị vứt). Thứ tự regex quan trọng:
            // ", and then " phải đứng trước ", and " kẻo chỉ ăn mất "and".
            actionSequence = prompt.split(/, then |, and then |, and /).map(step => {
                const s = step.trim().toLowerCase();
                const sRaw = step.trim(); // Keep original case for credentials
                let action = 'browse';
                let params = {};
                if (s.startsWith('login ')) {
                    action = 'login';
                    const loginBody = sRaw.substring(6).trim(); // Remove 'login '
                    const knownPlatforms = ['google', 'facebook', 'tiktok', 'x', 'twitter', 'discord', 'telegram'];
                    let platform = 'google', email = '', password = '', recoveryEmail = '', twoFactorCodes = '';

                    if (loginBody.includes('\t')) {
                        // Tab-separated mode (legacy)
                        const parts = loginBody.split(/\t+/);
                        let idx = 0;
                        if (parts[0] && knownPlatforms.includes(parts[0].trim().toLowerCase())) {
                            platform = parts[0].trim().toLowerCase();
                            idx = 1;
                        }
                        email = (parts[idx] || '').trim();
                        password = (parts[idx + 1] || '').trim();
                        recoveryEmail = (parts[idx + 2] || '').trim();
                        twoFactorCodes = parts.slice(idx + 3).join(' ').trim();
                    } else {
                        // Smart space-separated: detect fields by pattern
                        const words = loginBody.split(/\s+/);
                        let idx = 0;
                        // Check platform keyword
                        if (words[0] && knownPlatforms.includes(words[0].toLowerCase())) {
                            platform = words[0].toLowerCase();
                            if (platform === 'twitter') platform = 'x';
                            idx = 1;
                        }
                        // Find emails by @ sign
                        let emailIdx = -1, recoveryIdx = -1;
                        for (let i = idx; i < words.length; i++) {
                            if (words[i].includes('@')) {
                                if (emailIdx === -1) emailIdx = i;
                                else if (recoveryIdx === -1) recoveryIdx = i;
                            }
                        }
                        if (emailIdx >= 0) {
                            email = words[emailIdx];
                            // Password = word right after first email
                            password = words[emailIdx + 1] || '';
                            if (recoveryIdx >= 0) {
                                recoveryEmail = words[recoveryIdx];
                                // Everything after recovery email = 2FA codes
                                twoFactorCodes = words.slice(recoveryIdx + 1).join(' ');
                            }
                        } else {
                            // No @ found — assume: email password
                            email = words[idx] || '';
                            password = words[idx + 1] || '';
                        }
                    }
                    if (platform === 'twitter') platform = 'x';
                    params = { platform, email, password };
                    if (recoveryEmail) params.recoveryEmail = recoveryEmail;
                    if (twoFactorCodes) params.twoFactorCodes = twoFactorCodes;
                    console.log(`[Login Parse] platform=${platform} email=${email} recovery=${recoveryEmail} 2FA=${twoFactorCodes ? 'yes' : 'no'}`);
                } else if (s.startsWith('navigate to ')) {
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
                    // "click a video result" phải nhắm VIDEO thật (click.js có
                    // nhánh type:'video') — không thì trên trang kết quả YouTube
                    // nó bấm link nội bộ đầu tiên (chip lọc/kênh) và bước watch
                    // sau đó nổ NO_VIDEO_FOUND.
                    if (s.includes('video')) params.type = 'video';
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

  // --- AUTO-LOGIN FROM PROFILE SETTINGS ---
  // If --login-email is provided (from profile config's google_account), inject login action
  if (args['login-email']) {
      const autoLoginParams = {
          platform: 'google',
          email: args['login-email'],
          password: args['login-password'] || '',
      };
      if (args['login-recovery']) autoLoginParams.recoveryEmail = args['login-recovery'];
      if (args['login-2fa']) autoLoginParams.twoFactorCodes = args['login-2fa'];
      
      // Prepend login to action sequence (runs before other actions)
      actionSequence.unshift({ action: 'login', params: autoLoginParams });
      console.log(`[AutoLogin] Injected login action for: ${autoLoginParams.email}`);
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
      
      // Try to load key from settings first
      try {
          const settingsPath = path.resolve(__dirname, '..', '..', 'data', 'global_settings.json');
          if (await fs.pathExists(settingsPath)) {
              const settings = await fs.readJson(settingsPath);
              if (settings.bas_fingerprint_key && settings.bas_fingerprint_key.trim()) {
                  serviceKey = settings.bas_fingerprint_key.trim();
                  console.log('Service key loaded from settings.');
              }
          }
      } catch (e) {
          console.warn('Failed to load global settings in open.js:', e.message);
      }

      if (!serviceKey) {
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
      }
      
      if (serviceKey && plugin) {
        // Guarded with `plugin`, NOT requirePlugin(). The service key is fetched
        // on the common path for both engines, but only BAS consumes it — so
        // demanding the plugin here refused every ShardX profile on Linux with
        // "this profile uses a BAS engine", which was both wrong and unfixable
        // by the person reading it. A ShardX run simply has no key to set.
        plugin.setServiceKey(serviceKey);
      }

      let fingerprint;
      const fingerprintPath = path.join(profilePath, 'fingerprint_saved.json');
      const legacyFingerprintPath = path.join(profilePath, 'fingerprint.json');
      const configPath = path.join(profilePath, 'config.json');

      const targetPath = await fs.pathExists(fingerprintPath) ? fingerprintPath : legacyFingerprintPath;
      if (await fs.pathExists(targetPath)) {
          console.log('Loading saved fingerprint...');
          try {
              const fingerprintData = await fs.readFile(targetPath, 'utf8');
              if (fingerprintData && fingerprintData.length > 20) {
                  // Check signature wrapper format without modifying the raw string
                  try {
                      const parsed = typeof fingerprintData === 'string' ? JSON.parse(fingerprintData) : fingerprintData;
                      
                      // Security Browser v5 fingerprints use a wrapper structure:
                      // { canvas: ..., webgl: ..., audio: ..., fingerprint: { ua, tags, ... } }
                      // The wrapper contains canvas/webgl noise data needed for spoofing.
                      // DO NOT extract the inner 'fingerprint' key — pass the FULL object/string to the engine.
                      if (parsed && parsed.fingerprint) {
                          console.log('Detected Security Browser wrapper fingerprint. Using full raw string to prevent engine signature verification and format errors.');
                      }
                      fingerprint = fingerprintData; // Keep raw string to preserve signature order
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
          } catch (e) {
              // Lấy được thì tốt, không thì thôi — KHÔNG chết ở đây. Cùng cách xử lý
              // với preview_server.cjs:906-918, vốn vẫn chạy tốt suốt.
              console.warn(`[Fingerprint] Could not fetch one: ${e.message}`);
              fingerprint = null;
          }
          if (!fingerprint) {
              // null là câu trả lời HỢP LỆ, không phải lỗi: getFingerprint() cố ý trả
              // null khi chạy nhân ShardX (browser_manager.js:783-786) vì ShardX tự cấp
              // vân tay qua --fingerprint-profile; launch() cũng khai fingerprint=null
              // làm mặc định. Bản cũ process.exit(1) ở đây, nên MỌI phiên theo lịch chết
              // trước khi mở trang — mà nhật ký vẫn ghi "browser running" vì tiến trình
              // đã spawn được. Live view không dính vì nó đi đường preview_server.cjs.
              console.log('[Fingerprint] None from the API — continuing; the engine supplies its own.');
          }
      }

      console.log('Launching browser...');
      const finalHeadless = isHeadless || !!exportCookies;

      const launchArgs = [
          '--remote-debugging-port=0', // Force random port
          '--test-type',               // Hide unsupported command-line flag warnings
      ];

      // NB: a start URL cannot be passed here — Playwright refuses positional
      // arguments outright ("Arguments can not specify page to be opened").
      // Manual mode navigates from inside the page instead; see openStartUrl.

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

      // Ensure a page exists — và DÙNG LẠI tab gần nhất + DỌN tab trắng thừa mà
      // session-restore mang về. Chromium khôi phục tab phiên trước (đúng ý người
      // dùng) nhưng mỗi lần mở lại kèm một about:blank; không dọn thì tab trắng
      // chồng thành một đống qua nhiều lượt. Cùng quy tắc với preview_server: giữ
      // tab thật, chỉ chừa 1 tab trắng khi KHÔNG còn tab thật (đóng sạch thì context
      // chết); chọn tab THẬT gần nhất để phiên nối tiếp đúng chỗ vừa dừng.
      {
          const all = context.pages().filter(p => !p.isClosed());
          const real = all.filter(p => (p.url() || '') !== 'about:blank');
          const blanks = all.filter(p => (p.url() || '') === 'about:blank');
          const keep = real.length ? 0 : 1;
          for (let i = 0; i < blanks.length - keep; i++) { try { await blanks[i].close(); } catch (_) {} }
          page = real[real.length - 1] || context.pages().filter(p => !p.isClosed())[0] || await context.newPage();
      }

      // --- LOCALHOST OAUTH BYPASS (Crucial for proxied profiles) ---
      // Proxies will often fail to resolve localhost and drop with ERR_CONNECTION_RESET
      try {
          await context.route('**/api/v1/auth-manager/oauth/callback**', async route => {
              const url = route.request().url();
              console.log(`[OAuth Intercept] Intercepting local callback to bypass proxy: ${url}`);
              try {
                  const res = await axios.get(url, { timeout: 15000 });
                  await route.fulfill({
                      status: res.status,
                      contentType: 'text/html; charset=utf-8',
                      body: res.data
                  });
                  console.log(`[OAuth Intercept] Success!`);
              } catch (axiosErr) {
                  if (axiosErr.response) {
                      await route.fulfill({
                          status: axiosErr.response.status,
                          contentType: 'text/html; charset=utf-8',
                          body: axiosErr.response.data
                      });
                  } else {
                      console.error(`[OAuth Intercept] Localhost call failed:`, axiosErr.message);
                      await route.continue();
                  }
              }
          });
      } catch (e) {
          console.warn(`[OAuth Intercept] Failed to register route: ${e.message}`);
      }

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

      // --- Execute auto-login from actionSequence BEFORE manual mode check ---
      // This ensures login runs even in manual mode when google_account is set
      if (actionSequence.length > 0 && actionSequence[0].action === 'login') {
          const loginStep = actionSequence[0];
          console.log(`\n--- Executing: auto-login ---`);
          try {
              const actionFn = ACTION_REGISTRY['login'];
              if (actionFn) {
                  await actionFn(page, loginStep.params);
                  console.log('[AutoLogin] Login action completed.');
              }
          } catch (err) {
              console.error(`[AutoLogin] Login failed: ${err.message}`);
          }
          // Remove the login action so it doesn't run again
          actionSequence.shift();
          // Navigate to google.com so remaining actions (search, etc.) work
          try {
              await page.goto('https://www.google.com', { waitUntil: 'domcontentloaded', timeout: 10000 });
          } catch (e) { /* ignore */ }
          await page.waitForTimeout(1000);
          console.log(`[AutoLogin] Remaining actions: ${actionSequence.length}`);
      }

      // 3. Manual Mode Check
      if (isManual) {
        console.log('>>> MANUAL MODE: Browser launched. Waiting for user to close window...');

        // Initialize session manager for history recording in manual mode
        const session = new SessionManager(minSessionMinutes, prompt || "", aiModel, agentContext, profileName);

        const setupPageListeners = (p) => {
          const handlePageVisit = async () => {
            try {
              const url = p.url();
              if (!url || url === 'about:blank' || url.startsWith('chrome-extension://')) return;
              const title = await p.title();
              console.log(`[Manual History] Recording page visit: ${title} (${url})`);
              await session.recordPageVisit(url, title, p);

              // Auto-scrape content in manual mode if enable_scraping is true
              if (agentContext?.enable_scraping && !url.includes('youtube.com') && !url.includes('google.com')) {
                const pageContent = await session.scanPageContent(p);
                if (pageContent.isContentPage) {
                  if (!session.scrapedUrls.has(url)) {
                    console.log(`[Manual Scraper] Content page detected: "${title}". Auto-extracting content...`);
                    const actionParams = {
                      profileName: profileName,
                      enable_scraping: true,
                      scraper_text_limit: agentContext.scraper_text_limit || 10000,
                      agentId: agentContext.agent_id || null,
                      agentName: agentContext.agent_name || null
                    };
                    const actionResult = await extractContentAction.extract_content(p, actionParams);
                    if (actionResult) {
                      session.addScrapedUrl(url);
                      console.log(`[Manual Scraper] Scraped successfully: ${url}`);
                      // Re-record to update isScraped to true in history.json
                      await session.recordPageVisit(url, title, p);
                    }
                  } else {
                    console.log(`[Manual Scraper] URL already scraped: ${url}`);
                  }
                }
              }
            } catch (err) {
              console.warn('[Manual Scraper] Error during manual auto-extraction:', err.message);
            }
          };

          p.on('domcontentloaded', handlePageVisit);
          p.on('framenavigated', async (frame) => {
            if (frame === p.mainFrame()) {
              await handlePageVisit();
            }
          });
        };

        // Apply to the first page
        if (page) {
          setupPageListeners(page);
        }

        // Also listen for any new tabs opened by the user
        context.on('page', async (newPage) => {
          setupPageListeners(newPage);
        });
        
        // Open the start URL on a tab nobody is using.
        //
        // The profile opens its own startup pages a moment after launch. Firing
        // goto() at the original about:blank tab raced them: the navigation
        // never landed, timed out after 30s, and — because a failed goto leaves
        // the load pending — that first tab sat there spinning forever while
        // the user looked at a different one.
        const openStartUrl = async (targetUrl) => {
            await page.waitForTimeout(1500);   // let the startup pages settle

            // Already showing it? Nothing to drive.
            try {
                const host = new URL(targetUrl).hostname;
                if (context.pages().some(p => (p.url() || '').includes(host))) {
                    console.log('[Manual] Start page already open — nothing to navigate.');
                    return;
                }
            } catch (_) { /* fall through and try to navigate */ }

            // DÙNG LẠI một tab đang có thay vì đẻ tab mới mỗi lần mở. Trước đây luôn
            // context.newPage() (để né race "tab khởi động bị đóng dưới chân"), nhưng
            // cộng với session-restore của Chromium thì mỗi lần mở là +1 tab → vài hôm
            // thành một đống. Cùng quy tắc với preview_server: ưu tiên tab TRẮNG (đúng
            // tab khởi động), không có thì tab gần nhất; chỉ newPage khi context rỗng.
            const isBlankTab = (p) => { const u = (p && !p.isClosed() && p.url && p.url()) || ''; return u === '' || u === 'about:blank' || u.startsWith('chrome://new'); };
            const usable = context.pages().filter(p => !p.isClosed());
            let target = usable.find(isBlankTab) || usable[usable.length - 1] || null;
            if (!target || target.isClosed()) {
                // Không có tab dùng được (race đóng mất) → giờ mới tạo mới.
                try { target = await context.newPage(); }
                catch (e) { target = (page && !page.isClosed()) ? page : null; }
            }
            if (!target || target.isClosed()) {
                console.warn('[Manual] No page available to navigate; leaving the browser as it is.');
                return;
            }
            // Dọn các tab TRẮNG thừa (không phải target) để không tích tụ qua mỗi lần mở.
            for (const p of usable) {
                if (p !== target && isBlankTab(p)) { try { await p.close(); } catch (_) {} }
            }

            console.log(`[Manual] Navigating to provided URL: ${targetUrl}`);
            try { await target.bringToFront(); } catch (_) {}

            try {
                // 'commit' resolves as soon as the navigation is accepted —
                // we are only putting a page in front of a human, so waiting
                // for domcontentloaded (and failing at 30s on a slow redirect
                // chain) bought nothing.
                await target.goto(targetUrl, { waitUntil: 'commit', timeout: 15000 });
                console.log('[Manual] Navigation committed.');
                return;
            } catch (e) {
                console.warn(`[Manual] goto() did not commit: ${e.message.split('\n')[0]}`);
            }

            // Fall back to navigating from inside the page. On this engine
            // goto() can hang without ever committing, yet the browser itself
            // loads pages perfectly well — so ask the page to move instead of
            // driving it through the automation channel.
            try {
                await target.evaluate((u) => { window.stop(); window.location.href = u; }, targetUrl);
                await target.waitForTimeout(3000);
                console.log(`[Manual] Navigated in-page. Now on: ${target.url()}`);
            } catch (e2) {
                console.warn(`[Manual] In-page navigation failed too: ${e2.message.split('\n')[0]}`);
                // Leave no spinner behind.
                try { await target.evaluate(() => window.stop()); } catch (_) {}
            }
        };

        // Only when a start page was actually asked for. Manual mode used to
        // force google.com on every open, which on this engine could not be
        // driven and simply left a tab spinning.
        if (startUrlArg) {
            await openStartUrl(startUrlArg);
        } else {
            console.log('[Manual] No start page requested — leaving the browser to the user.');
        }

        // Wait until the browser context is closed by the user
        await new Promise((resolve) => {
          let hasInitialized = false;
          // 10 second grace period to prevent immediate exit on slow CDP/networking
          setTimeout(() => { hasInitialized = true; }, 10000);

          context.on('close', () => {
            if (hasInitialized) {
              console.log('Browser context closed event received.');
              resolve();
            }
          });
          
          const pollInterval = setInterval(() => {
            if (!hasInitialized) return;
            try {
              const browser = context.browser();
              if (browser && !browser.isConnected()) {
                clearInterval(pollInterval);
                console.log('Browser CDP disconnected.');
                resolve();
              } else if (context.pages().length === 0) {
                clearInterval(pollInterval);
                console.log('All browser tabs closed by user.');
                resolve();
              }
            } catch (e) {
              clearInterval(pollInterval);
              resolve();
            }
          }, 3000);
        });
        return process.exit(0);
      }

      // 4. Execute Action Sequence (ALWAYS runs first, even if session mode follows)
      if (actionSequence.length > 0) {
        let initialActionsSucceeded = true;
        const results = [];
        for (const step of actionSequence) {
          const actionFn = ACTION_REGISTRY[step.action];
          if (actionFn) {
            console.log(`\n--- Executing: ${step.action} ---`);
            try {
              let stepParams = { ...step.params, isRetry, aiModel };
              if (step.action === 'extract_content') {
                stepParams.profileName = profileName;
                stepParams.enable_scraping = agentContext?.enable_scraping !== false;
                stepParams.scraper_text_limit = agentContext?.scraper_text_limit || 10000;
                stepParams.agentId = agentContext?.agent_id || null;
                stepParams.agentName = agentContext?.agent_name || null;
              }
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
                logTrail({ phase: 'opening', action: step.action, params: step.params, status: 'success', url: (() => { try { return page.url(); } catch (e) { return ''; } })() });
              }
            } catch (actionError) {
              // A step that could not find something OPTIONAL is not a failed
              // session. Behaviour pattern 2 ends with "click an internal link
              // within the SAME site"; plenty of pages have no such link, and
              // the old code turned that into >>> FAILURE <<< for a run that had
              // already searched, opened a result and read it — most of the job,
              // reported as none of it. Skip the step, keep what was achieved.
              if (actionError && actionError.softFail) {
                console.warn(`Skipping optional step '${step.action}': ${actionError.message}`);
                results.push({ action: step.action, skipped: true, reason: actionError.message });
                logTrail({ phase: 'opening', action: step.action, params: step.params, status: 'skipped', error: String(actionError.message || '').slice(0, 160) });
                continue;
              }

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
        // Already resolved on the Python side; empty means "unset there too",
        // which the /localai proxy resolves again rather than us guessing here.
        const sessionAiModel = args['ai-model'] || args.model || '';
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

        // Chuỗi mở màn ĐÃ chạy trọn ở bước 4 ("ALWAYS runs first") — nạp lại
        // vào taskQueue là PHÁT LẠI nguyên si navigate+search+click ngay đầu
        // phiên: chính là cảnh "gõ Google thêm một lần nữa" trong live view.
        session.start(page.url(), userGoal, []);
        // Kế thừa lịch sử mở màn SAU start() (start() reset actionHistory):
        // cú search đầu phải được đếm vào alreadySearched, kẻo AI phiên được
        // search "miễn phí" lần hai.
        try {
          for (const a of (actionSequence || [])) {
            if (a && a.action === 'search') {
              session.actionHistory.push({ action: 'search', url: page.url(), status: 'success' });
            }
          }
        } catch (e) {}
        // Ghi NGAY trang hiện tại vào lịch sử: chuỗi mở màn (navigate/search/
        // click/watch) chạy TRƯỚC khi session tồn tại nên cả đoạn đó không ghi
        // gì — lượt watchVideos đứng ở bước watch dài (hoặc chết giữa chừng)
        // là lịch sử trắng tinh dù đã xem video thật.
        try { await session.recordPageVisit(page.url(), await page.title(), page); } catch (e) {}
        
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
                        // Auto-search the original keyword to continue the task
                        try {
                            const recoveryKeyword = session.context?.keyword || session.context?.task || '';
                            if (recoveryKeyword) {
                                console.log(`[Session] Auto-searching keyword after recovery: "${recoveryKeyword}"`);
                                const searchFn = ACTION_REGISTRY['search'];
                                if (searchFn) await searchFn(page, { keyword: recoveryKeyword });
                            }
                        } catch (recovErr) {
                            console.warn('[Session] Auto-search after recovery failed:', recovErr.message);
                        }
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
                const dismissTerms = [
                    'close', 'not now', 'dismiss', 'no thanks', 'maybe later',
                    'deny', 'block', 'reject', 'decline', 'refuse',
                    // Affirmative dismiss (GDPR confirm, proceed, etc.)
                    'confirm', 'do not proceed', 'continue', 'proceed', 'yes',
                    'i accept', 'i consent', 'i agree', 'accept all', 'allow all',
                    'essential only', 'necessary only', 'save settings'
                ];

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
                    actionParams.agentId = agentContext?.agent_id || null;
                    actionParams.agentName = agentContext?.agent_name || null;
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
             const fingerprintPath = path.join(profilePath, 'fingerprint_saved.json');
             const legacyFingerprintPath = path.join(profilePath, 'fingerprint.json');
             await fs.remove(fingerprintPath);
             await fs.remove(legacyFingerprintPath);
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
        // Check if user manually closed the browser (no pages left = user closed)
        let userClosed = false;
        try {
          if (!context || context.pages().length === 0) {
            userClosed = true;
          }
        } catch (e) {
          // Context destroyed = user closed the browser
          userClosed = true;
        }
        if (userClosed) {
          console.log('\n>>> Browser closed by user. Exiting gracefully.');
          success = true; // Don't treat as failure
          break;
        }
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
