import axios from 'axios';
import { getGpuUsage } from './gpu_monitor.js';
import fs from 'fs-extra';
import path from 'path';

/**
 * Session Manager for Generative Browser Sessions
 * Maintains minimum 10-minute browsing sessions with context-aware action chaining
 */

export class SessionManager {
  constructor(minDurationMinutes = 10, userGoal = null, aiModel = 'qwen:latest', agentContext = null, profileName = 'default') {
    this.minDurationMs = minDurationMinutes * 60 * 1000;
    this.sessionId = null;
    this.startTime = null;
    this.actionHistory = [];
    this.currentContext = {
      url: null,
      pageType: 'unknown',
      domain: null
    };
    this.userGoal = userGoal;
    this.aiModel = aiModel;
    this.agentContext = agentContext; // NEW: Store agent context (interests, routine)
    this.profileName = profileName; // NEW: Profile name for loading blacklist
    this.blacklist = []; // NEW: Website blacklist
    this.currentIp = null; // NEW: Track IP address for history logs
    
    this.maxVisitsPerWeek = 3;
    this.maxVisitsPerDay = 1; // NEW: Daily limit
    this.domainAccessHistory = {}; 
    
    // Load history per profile
    this.loadHistory().catch(e => console.warn('[SessionManager] Failed to load history:', e.message));
    
    this.aiUrl = 'http://localhost:5295/api/v1/localai/chat/completions';
    this.lastRefuelTime = 0;
    this.REFUEL_COOLDOWN_MS = 120000;
    this.taskQueue = [];
    this.gpuUsageHistory = []; // Track last 1 minute of GPU usage
    this.MAX_GPU_HISTORY = 12; // 12 samples @ 5s interval = 1 minute
    this.stats = null; // RPG Stats
    this.failedElements = new Set(); // Track elements that failed to be interacted with
    this.aiCallHistory = []; // Track timestamps of AI calls for frequency warning
    this.scrapedUrls = new Set(); // Track URLs already scraped (cross-session)
    
    // Load blacklist from profile config
    this.loadBlacklist().catch(e => console.warn('[SessionManager] Failed to load blacklist:', e.message));
    // Load previously scraped URLs to avoid duplicates across sessions
    this.loadScrapedUrls().catch(e => console.warn('[SessionManager] Failed to load scraped URLs:', e.message));
  }

  /**
   * Get credentials for a given URL/domain from agentContext.auth
   * Maps domain → platform → first enabled account
   * @param {string} url - Current page URL
   * @returns {{ username, email, password, recoveryEmail, twoFactorCodes, platform } | null}
   */
  getCredentialsForSite(url = '') {
    if (!this.agentContext || !this.agentContext.auth) return null;
    const auth = this.agentContext.auth;

    // Domain → Platform mapping
    const DOMAIN_MAP = {
      'google.com': 'google',
      'accounts.google.com': 'google',
      'gmail.com': 'google',
      'mail.google.com': 'google',
      'docs.google.com': 'google',
      'sheets.google.com': 'google',
      'drive.google.com': 'google',
      'youtube.com': 'google',
      'facebook.com': 'facebook',
      'fb.com': 'facebook',
      'tiktok.com': 'tiktok',
      'twitter.com': 'x',
      'x.com': 'x',
      'discord.com': 'discord',
      'telegram.org': 'telegram',
      'web.telegram.org': 'telegram'
    };

    let platform = null;
    try {
      const hostname = new URL(url).hostname.replace(/^www\./, '');
      // Exact match first
      platform = DOMAIN_MAP[hostname];
      // Suffix match fallback
      if (!platform) {
        for (const [domain, p] of Object.entries(DOMAIN_MAP)) {
          if (hostname.endsWith(domain)) { platform = p; break; }
        }
      }
    } catch (e) { /* invalid url */ }

    if (!platform || !auth[platform] || !Array.isArray(auth[platform])) return null;

    // Return first enabled account
    const account = auth[platform].find(a => a.enabled !== false);
    if (!account) {
      console.log(`[Auth] No enabled account found for platform: ${platform}`);
      return null;
    }

    const creds = {
      platform,
      email: account.username || account.email,
      username: account.username || account.email,
      password: account.password,
      recoveryEmail: account.recoveryEmail || null,
      twoFactorCodes: account.twoFactorCodes || null,
      notes: account.notes || ''
    };
    console.log(`[Auth] Found ${platform} credentials for: ${creds.email}`);
    return creds;
  }

  /**
   * Start a new session
   */
  start(initialUrl = null, userGoal = null, initialActions = []) {
    this.sessionId = `session_${Date.now()}`;
    this.startTime = Date.now();
    this.actionHistory = [];
    this.taskQueue = Array.isArray(initialActions) ? [...initialActions] : [];
    
    if (userGoal) this.userGoal = userGoal;
    
    if (initialUrl) {
      this.updateContext(initialUrl);
    }
    
    // Start GPU monitoring (sample every 5 seconds)
    if (this.gpuMonitorInterval) clearInterval(this.gpuMonitorInterval);
    this.gpuMonitorInterval = setInterval(async () => {
        const usage = await getGpuUsage();
        this.gpuUsageHistory.push(usage);
        if (this.gpuUsageHistory.length > this.MAX_GPU_HISTORY) {
            this.gpuUsageHistory.shift();
        }
    }, 5000);

    console.log(`[SessionManager] Started session ${this.sessionId} (Goal: "${this.userGoal || 'Browse naturally'}")`);
    return this.sessionId;
  }

  getAverageGpuUsage() {
      if (this.gpuUsageHistory.length === 0) return 0;
      const sum = this.gpuUsageHistory.reduce((a, b) => a + b, 0);
      return Math.round(sum / this.gpuUsageHistory.length);
  }

  /**
   * Record a completed action to history
   */
  recordAction(action, params = {}, status = 'success', errorMsg = null) {
    this.actionHistory.push({
      action,
      params,
      status,
      error: errorMsg,
      url: this.currentContext.url,
      timestamp: Date.now()
    });
    console.log(`[SessionManager] Recorded action: ${action} (${status})`);
  }

  /**
   * Get elapsed time in milliseconds
   */
  getElapsedTime() {
    if (!this.startTime) return 0;
    return Date.now() - this.startTime;
  }

  /**
   * Get remaining time to reach minimum duration (in milliseconds)
   */
  getRemainingTime() {
    const elapsed = this.getElapsedTime();
    const remaining = this.minDurationMs - elapsed;
    return Math.max(0, remaining);
  }

  /**
   * Check if minimum duration has been reached
   */
  hasReachedMinimum() {
    return this.getElapsedTime() >= this.minDurationMs;
  }

  /**
   * Update current context based on URL
   */
  updateContext(url) {
    this.currentContext.url = url;
    
    try {
      const urlObj = new URL(url);
      if (this.currentContext.domain && this.currentContext.domain !== urlObj.hostname) {
          console.log(`[SessionManager] Domain changed from ${this.currentContext.domain} to ${urlObj.hostname}. Clearing failure cache.`);
          this.failedElements.clear();
      }
      this.currentContext.domain = urlObj.hostname;
      
      // Detect page type based on domain
      if (urlObj.hostname.includes('youtube.com')) {
        this.currentContext.pageType = url.includes('/watch') ? 'youtube_video' : 'youtube_home';
      } else if (urlObj.hostname.includes('github.com')) {
        this.currentContext.pageType = url.match(/\/[^\/]+\/[^\/]+$/) ? 'github_repo' : 'github_general';
      } else if (urlObj.hostname.includes('news') || urlObj.hostname.includes('article')) {
        this.currentContext.pageType = 'news';
      } else {
        this.currentContext.pageType = 'general_website';
      }
      
      console.log(`[SessionManager] Context updated: ${this.currentContext.pageType} @ ${this.currentContext.domain}`);
    } catch (e) {
      console.warn('[SessionManager] Failed to parse URL:', e.message);
    }
  }

  /**
   * Update RPG Stats in session (for AI context)
   */
  updateStats(stats) {
    this.stats = stats;
  }

  /**
   * Check AI call frequency
   * Returns { level: 'normal'|'high'|'critical', callsPerMinute: float }
   */
  getCallFrequencyStatus() {
      const now = Date.now();
      const oneMinAgo = now - 60000;
      const callsLastMinute = this.aiCallHistory.filter(t => t > oneMinAgo).length;
      
      let level = 'normal';
      if (callsLastMinute > 10) level = 'critical';
      else if (callsLastMinute > 5) level = 'high';
      
      return { 
          level, 
          callsPerMinute: callsLastMinute,
          warning: level !== 'normal' ? `Warning: High AI usage detected (${callsLastMinute} calls/min)` : null
      };
  }

  /**
   * Check if stuck on same URL (for recovery)
   */
  isStuckOnSameUrl() {
    if (this.actionHistory.length < 5) return false;
    // Only count navigation-type actions (exclude browse/watch/extract_content which stay on same URL)
    const NON_NAV_ACTIONS = ['browse', 'watch', 'extract_content', 'visual_scan', 'comment'];
    const navActions = this.actionHistory.filter(a => !NON_NAV_ACTIONS.includes(a.action));
    if (navActions.length < 5) return false;
    const recent = navActions.slice(-5);
    const urls = recent.map(a => a.url);
    return urls.every(u => u === urls[0]);
  }

  /**
   * Reset stuck counter by clearing recent history (called after recovery)
   */
  resetStuckCounter() {
    // Keep only last 2 actions to maintain some context
    if (this.actionHistory.length > 2) {
      this.actionHistory = this.actionHistory.slice(-2);
    }
    console.log('[SessionManager] Reset stuck counter');
  }
  /**
   * Load blacklist from profile config
   */
  
  async loadHistory() {
    if (!this.profileName) return;
    try {
      const historyPath = path.resolve('./profiles', this.profileName, 'history.json');
      if (await fs.pathExists(historyPath)) {
        const data = await fs.readJson(historyPath);
        this.domainAccessHistory = data.domainAccessHistory || {};
        // console.log(`[SessionManager] Loaded history for profile ${this.profileName}`);
      }
    } catch (e) {
      console.warn('[SessionManager] Failed to load history:', e.message);
    }
  }

  async saveHistory() {
    if (!this.profileName) return;
    try {
      const profileDir = path.resolve('./profiles', this.profileName);
      await fs.ensureDir(profileDir);
      const historyPath = path.join(profileDir, 'history.json');
      await fs.writeJson(historyPath, { domainAccessHistory: this.domainAccessHistory }, { spaces: 2 });
    } catch (e) {
      console.warn('[SessionManager] Failed to save history:', e.message);
    }
  }

  /**
   * Load previously scraped article URLs to avoid duplicate extraction across sessions.
   */
  async loadScrapedUrls() {
    if (!this.profileName) return;
    try {
      const articlesPath = path.resolve('./scraped_data', this.profileName, 'articles.json');
      if (await fs.pathExists(articlesPath)) {
        const articles = await fs.readJson(articlesPath);
        if (Array.isArray(articles)) {
          for (const a of articles) {
            if (a.url) this.scrapedUrls.add(a.url);
          }
          console.log(`[SessionManager] Loaded ${this.scrapedUrls.size} previously scraped URLs.`);
        }
      }
    } catch (e) {
      console.warn('[SessionManager] Failed to load scraped URLs:', e.message);
    }
  }

  /**
   * Mark a URL as scraped (called after successful extract_content)
   */
  addScrapedUrl(url) {
    if (url) this.scrapedUrls.add(url);
  }

async loadBlacklist() {
    try {
      const settingsPath = path.resolve('./data/global_settings.json');
      
      if (await fs.pathExists(settingsPath)) {
        const settings = await fs.readJson(settingsPath);
        this.blacklist = settings.blacklist || [];
        this.maxVisitsPerWeek = settings.maxVisitsPerWeek || 3;
        this.maxVisitsPerDay = settings.maxVisitsPerDay || 1;
        console.log(`[SessionManager] Loaded ${this.blacklist.length} blacklist patterns, maxVisits: ${this.maxVisitsPerWeek}`);
      }
    } catch (e) {
      console.warn('[SessionManager] Failed to load global settings:', e.message);
    }
  }

  /**
   * Check if a URL/domain matches blacklist patterns
   */
  isBlacklisted(url) {
    if (!url || this.blacklist.length === 0) return false;
    
    const lowerUrl = url.toLowerCase();
    return this.blacklist.some(pattern => {
      const lowerPattern = pattern.toLowerCase();
      return lowerUrl.includes(lowerPattern);
    });
  }

  /**
   * Track domain access and return visit count for current week
   */
  trackDomainAccess(domain) {
    if (!domain) return { day: 0, week: 0 };
    
    const now = Date.now();
    const oneDayAgo = now - (24 * 60 * 60 * 1000);
    const oneWeekAgo = now - (7 * 24 * 60 * 60 * 1000);
    
    // Initialize if needed
    if (!this.domainAccessHistory[domain]) {
      this.domainAccessHistory[domain] = [];
    }
    
    // Clean old visits (> 1 week)
    this.domainAccessHistory[domain] = this.domainAccessHistory[domain].filter(t => t > oneWeekAgo);
    
    // Add current visit
    this.domainAccessHistory[domain].push(now);
    
    // Calculate counts
    const weekCount = this.domainAccessHistory[domain].length;
    const dayCount = this.domainAccessHistory[domain].filter(t => t > oneDayAgo).length;
    
    // Persist
    this.saveHistory().catch(e => console.error(e));
    
    return { day: dayCount, week: weekCount };
  }



  /**
   * Get the current IP address using the browser context
   */
  async getCurrentIp(page) {
    if (this._ipFetchedAt && (Date.now() - this._ipFetchedAt < 10 * 60 * 1000) && this.currentIp && this.currentIp !== 'Unknown') {
         return this.currentIp;
    }
    if (!page) return 'Unknown';
    
    let ip = null;
    try {
        // Primary: Evaluate in-page using https
        ip = await page.evaluate(async () => {
            try {
                const res = await fetch('https://checkip.amazonaws.com', { signal: AbortSignal.timeout(8000) });
                return res.ok ? (await res.text()).trim() : null;
            } catch (e) { return null; }
        });
    } catch (e) {}

    if (!ip) {
        // Secondary fallback: Request context (might bypass some proxies but more reliable than failing)
        try {
            const response = await page.context().request.get('https://checkip.amazonaws.com', { timeout: 8000 });
            if (response.ok()) {
                const text = await response.text();
                ip = text.trim();
            }
        } catch (e) {}
    }

    if (ip) {
        this.currentIp = ip;
        this._ipFetchedAt = Date.now();
        console.log(`[SessionManager] Detected Agent IP: ${this.currentIp}`);
        return this.currentIp;
    }
    
    return this.currentIp || 'Unknown';
  }

  /**
   * Record a page visit to the profile's history
   */
  async recordPageVisit(url, title, page = null) {
    if (!this.profileName || !url || url === 'about:blank') return;
    try {
      const ipAddress = page ? await this.getCurrentIp(page) : (this.currentIp || 'Unknown');
      const historyPath = path.resolve('./scraped_data', this.profileName, 'history.json');
      await fs.ensureDir(path.dirname(historyPath));
      let history = {};
      if (await fs.pathExists(historyPath)) {
        try { history = await fs.readJson(historyPath); } catch (e) { history = {}; }
      }
      if (!Array.isArray(history.scrapedArticles)) {
        history.scrapedArticles = [];
      }
      
      // Avoid immediate duplicate entries
      const lastEntry = history.scrapedArticles[history.scrapedArticles.length - 1];
      if (lastEntry && lastEntry.url === url) {
          // Update IP if missing
          if (!lastEntry.ip || lastEntry.ip === 'Unknown') lastEntry.ip = ipAddress;
          await fs.writeJson(historyPath, history, { spaces: 2 });
          return; // Already recorded
      }
      
      history.scrapedArticles.push({
        title: title || 'Untitled',
        url: url,
        ip: ipAddress,
        scrapedAt: new Date().toISOString(),
        isScraped: false
      });
      
      if (history.scrapedArticles.length > 500) {
        history.scrapedArticles = history.scrapedArticles.slice(-500);
      }
      await fs.writeJson(historyPath, history, { spaces: 2 });
    } catch (e) {
      console.warn('[SessionManager] Failed to record page visit to history.json:', e.message);
    }
  }

  /**
   * Scan page content to detect available elements (DYNAMIC - not domain-based)
   */
  async scanPageContent(page) {
    console.log('[SessionManager] Scanning page content...');
    
    try {
      const content = await page.evaluate(() => {
        if (!document.body) {
           return { isErrorPage: true, hasCaptcha: false, potentialPopups: [], interactiveElements: [], hasVideo: false };
        }
        const bodyText = document.body.innerText || "";
        
        // Error Detection
        const isErrorPage = 
          bodyText.includes("This site can't be reached") ||
          bodyText.includes("This page isn't working") ||
          bodyText.includes("Không thể truy cập trang web này") ||
          bodyText.includes("Trang này không hoạt động") ||
          bodyText.includes("Không có kết nối Internet") ||
          bodyText.includes("ERR_NAME_NOT_RESOLVED") ||
          bodyText.includes("ERR_CONNECTION_TIMED_OUT") ||
          bodyText.includes("ERR_CONNECTION_CLOSED") ||
          bodyText.includes("ERR_CONNECTION_REFUSED") ||
          bodyText.includes("ERR_CONNECTION_RESET") ||
          bodyText.includes("ERR_PROXY_CONNECTION_FAILED") ||
          bodyText.includes("ERR_TUNNEL_CONNECTION_FAILED") ||
          bodyText.includes("ERR_SSL_PROTOCOL_ERROR") ||
          bodyText.includes("ERR_SSL_VERSION_OR_CIPHER_MISMATCH") ||
          bodyText.includes("ERR_CERT") ||
          bodyText.includes("DNS_PROBE_FINISHED_NXDOMAIN") ||
          bodyText.includes("DNS_PROBE_FINISHED_NO_INTERNET") ||
          bodyText.includes("Windows Network Diagnostics") ||
          bodyText.includes("500 Internal Server Error") ||
          bodyText.includes("404 Not Found");
          
        const hasCaptcha = false;
        
        // Popup / Blocking Element Detection
        const potentialPopups = [];
        const dismissTerms = [
          'not interested', 'no thanks', 'close', 'accept', 'agree', 'got it', 
          'maybe later', 'dismiss', 'i agree', 'allow', 'ok', 'not now',
          'no', 'reject', 'decline', 'cookie', 'consent', 'i understand'
        ];
        
        const allInteractive = document.querySelectorAll('a[href], button, input[type="submit"], [role="button"]');
        
        // 1. Find Popup Containers (Modals, Dialogs, Overlays)
        let blockingPopup = null;
        const containers = document.querySelectorAll('[role="dialog"], [role="alertdialog"], .modal, .popup, .overlay');
        for (const container of containers) {
            const rect = container.getBoundingClientRect();
            if (rect.width > 200 && rect.height > 100) { // Safety: ignore tiny ones
                const style = window.getComputedStyle(container);
                if (style.position === 'fixed' || style.position === 'absolute') {
                    // It's a container. Collect all buttons inside.
                    const internalButtons = container.querySelectorAll('a[href], button, [role="button"]');
                    const buttons = Array.from(internalButtons).map(b => ({
                        text: b.innerText?.trim() || b.textContent?.trim() || b.getAttribute('aria-label') || '',
                        tag: b.tagName.toLowerCase()
                    })).filter(b => b.text.length > 0);

                    blockingPopup = {
                        selector: container.id ? `#${container.id}` : (container.className ? `.${container.className.split(' ')[0]}` : 'dialog'),
                        buttons: buttons
                    };
                    break; 
                }
            }
        }

        for (const el of allInteractive) {
          const text = el.innerText?.trim() || el.textContent?.trim() || el.getAttribute('aria-label') || el.getAttribute('title') || '';
          const lowerText = text.toLowerCase();
          
          if (dismissTerms.some(term => lowerText === term || (lowerText.length < 20 && lowerText.includes(term)))) {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
              potentialPopups.push({
                text: text.substring(0, 40),
                tag: el.tagName.toLowerCase()
              });
            }
          }
        }

        // Extract Interactive Elements (links, buttons) for AI selection
        const interactiveElements = [];
        let count = 0;
        for (const el of allInteractive) {
          if (count >= 150) break; // Increased limitation for scanning
          
          const rect = el.getBoundingClientRect();
          const text = el.innerText?.trim() || el.textContent?.trim() || el.getAttribute('aria-label') || el.getAttribute('title') || '';
          
          if (rect.width > 0 && rect.height > 0 && text.length > 0) {
            interactiveElements.push({
              text: text.substring(0, 100),
              tag: el.tagName.toLowerCase(),
              href: (el.tagName === 'A' ? el.href : null)
            });
            count++;
          }
        }
        
        // Video detection
        const videos = document.querySelectorAll('video');
        let interactiveVideoCount = 0;
        for (const vid of videos) {
          const rect = vid.getBoundingClientRect();
          const isVisible = rect.width > 100 && rect.height > 100;
          const isInteractive = !vid.muted || vid.controls;
          if (isVisible && isInteractive) {
            interactiveVideoCount++;
          }
        }
        
        return {
          title: document.title,
          isErrorPage,
          hasCaptcha,
          potentialPopups,
          blockingPopup, // NEW: Full popup context
          interactiveElements, 
          hasVideo: interactiveVideoCount > 0, 
          videoCount: interactiveVideoCount,
          hasArticles: document.querySelectorAll('article, .post, .article, [role="article"]').length > 0,
          articleCount: document.querySelectorAll('article, .post, .article, [role="article"]').length,
          hasForm: document.querySelectorAll('form').length > 0,
          formCount: document.querySelectorAll('form').length,
          linkCount: document.querySelectorAll('a[href]:not([href*="javascript"]):not([href="#"])').length,
          hasSearchBox: document.querySelectorAll('input[type="search"], input[name*="search" i], input[placeholder*="search" i]').length > 0,
          imageCount: document.querySelectorAll('img').length,
          headingCount: document.querySelectorAll('h1, h2, h3').length,
          hasCommentSection: document.querySelectorAll('[class*="comment" i], [id*="comment" i]').length > 0,
          // Content page detection for extract_content action
          isContentPage: (() => {
            const ogType = document.querySelector('meta[property="og:type"]')?.content || '';
            const hasArticleTag = document.querySelectorAll('article, [role="article"]').length > 0;
            const h1 = document.querySelector('h1');
            const contentParas = document.querySelectorAll('article p, .post-content p, .entry-content p, .article-body p, main p');
            return ogType === 'article' || (hasArticleTag && contentParas.length >= 3) || (!!h1 && contentParas.length >= 5);
          })()
        };
      });
      
      return content;
    } catch (e) {
      console.warn('[SessionManager] Page scan failed:', e.message);
      return {
        isErrorPage: true,
        hasCaptcha: false,
        interactiveElements: [],
        hasVideo: false
      };
    }
  }

  /**
   * Generate next action based on current context and page content
   */
  async generateNextAction(page, pageContent = null) {
    const remainingMs = this.getRemainingTime();
    const remainingMinutes = Math.ceil(remainingMs / 60000);
    
    console.log(`[SessionManager] Generating next action (${remainingMinutes} min remaining)`);
    
    if (this.taskQueue.length > 0) {
      const nextFromQueue = this.taskQueue.shift();
      console.log(`[SessionManager] Using action from queue: ${nextFromQueue.action}`);
      return [nextFromQueue];
    }

    if (pageContent && (pageContent.isErrorPage || pageContent.hasCaptcha)) {
        // Just return null/nothing here so scanPageContent findings can be handled by open.js orchestrator
        return null;
    }

    if (this.hasReachedMinimum()) {
      console.log('[SessionManager] Minimum duration reached. Session can end.');
      return null;
    }

    // AI-Driven Generation
    if (this.userGoal) {
      try {
        const gpuUsage = this.getAverageGpuUsage();
        let aiAction = null;
        const now = Date.now();
        const timeSinceLastRefuel = now - this.lastRefuelTime;

        // SKIP ChatGPT Web Refueling for now to simplify testing 2-step logic
        // if (gpuUsage > 90 && timeSinceLastRefuel > this.REFUEL_COOLDOWN_MS) { ... }
        
        aiAction = await this.generateAIAction(pageContent, remainingMinutes);

        if (aiAction) {
          const actionChain = Array.isArray(aiAction) ? aiAction : [aiAction];
          
          for (const action of actionChain) {
            if (action.params) {
               if (action.params.duration) {
                 let seconds = parseInt(action.params.duration);
                 if (!isNaN(seconds)) {
                   const variance = 0.7 + Math.random() * 0.4; 
                   const newSeconds = Math.floor(seconds * variance);
                   action.params.duration = `${newSeconds}s`;
                 }
               }
               if (action.params.iterations) {
                  const base = parseInt(action.params.iterations) || 5;
                  const variance = Math.floor(Math.random() * 4) - 2;
                  action.params.iterations = Math.max(3, base + variance);
               }
            }
          }
          console.log(`[SessionManager] Generated Action Chain (${actionChain.length} steps):`, actionChain);
          return actionChain;
        }
      } catch (e) {
        console.error('[SessionManager] AI generation failed, falling back to heuristic:', e.message);
      }
    }

    const action = this._getContentBasedAction(pageContent, remainingMs);
    console.log(`[SessionManager] Heuristic Action:`, action);
    return action;
  }

  /**
   * Generate action using Local AI based on goal and context (Two-Step: Skeleton -> Grounding)
   */
  async generateAIAction(pageContent, remainingMinutes) {
    const context = {
      url: this.currentContext.url,
      domain: this.currentContext.domain,
      pageType: this.currentContext.pageType,
      hasVideo: pageContent?.hasVideo || false,
      hasSearchBox: pageContent?.hasSearchBox || false,
      isContentPage: pageContent?.isContentPage || false,
      alreadyScraped: pageContent?.isContentPage ? this.scrapedUrls.has(this.currentContext.url) : false,
      currentActivity: this.agentContext?.current_activity || 'browse',
      remainingMinutes,
      recentHistory: this.actionHistory.slice(-5).map(a => `${a.action} on ${a.url} -> ${a.status}${a.error ? ` (Error: ${a.error})` : ''}`)
    };

    // Build Prompt
    const prompt = this._buildAIPrompt(context, '', false, '', pageContent?.potentialPopups || []);

    try {
      console.log(`[SessionManager] Requesting SKELETON from AI model: ${this.aiModel}...`);
      
      // Record call for frequency tracking
      this.aiCallHistory.push(Date.now());
      // Keep only last 5 minutes of history
      const fiveMinsAgo = Date.now() - (5 * 60 * 1000);
      this.aiCallHistory = this.aiCallHistory.filter(t => t > fiveMinsAgo);

      const response = await axios.post(this.aiUrl, {
        model: this.aiModel,
        messages: [{ role: "user", content: prompt }],
        stream: false,
        temperature: 0.7,
        format: "json"
      }, { timeout: 60000 });

      let content = response.data?.choices?.[0]?.message?.content;
      if (!content) return null;

      const skeletonHelper = this._cleanAndParseJSON(content);
      
      if (skeletonHelper && Array.isArray(skeletonHelper)) {
          // GROUNDING STEP: Convert Abstract Skeleton to Concrete Actions
          console.log('[SessionManager] Grounding Skeleton Action Chain:', skeletonHelper);
          const groundedChain = skeletonHelper.map(action => this._resolveActionParams(action, pageContent));
          return groundedChain;
      }
      
      console.warn('[SessionManager] Failed to parse AI skeleton.');
      return null;

    } catch (error) {
      console.warn('[SessionManager] AI Request Error:', error.message);
      return null;
    }
  }

  /**
   * AI Refueling: Generate action via ChatGPT website in a new tab
   */
  async generateAIActionViaChatGPTWeb(page, pageContent, remainingMinutes) {
    // Placeholder - Logic similar to original but requesting skeleton
    return null; 
  }

  /**
   * Dedicated helper to clean and parse AI JSON output
   */
  _cleanAndParseJSON(content) {
    let rawJson = null;
    const codeBlockMatch = content.match(/```(?:json)?\s*(\[[\s\S]*?\])\s*```/);
    if (codeBlockMatch) {
        rawJson = codeBlockMatch[1];
    } else {
        const openBracketIndex = content.indexOf('[');
        if (openBracketIndex !== -1) {
            let balance = 0;
            let startIndex = openBracketIndex;
            let endIndex = -1;
            let insideString = false;
            let escape = false;

            for (let i = startIndex; i < content.length; i++) {
                const char = content[i];
                if (escape) { escape = false; continue; }
                if (char === '\\') { escape = true; continue; }
                if (char === '"') { insideString = !insideString; continue; }
                if (!insideString) {
                    if (char === '[') balance++;
                    else if (char === ']') {
                        balance--;
                        if (balance === 0) { endIndex = i; break; }
                    }
                }
            }
            if (endIndex !== -1) {
                rawJson = content.substring(startIndex, endIndex + 1);
            } else {
                console.warn('[SessionManager] Potential truncated JSON detected. Attempting to salvage...');
                const lastBraceIndex = content.lastIndexOf('}');
                if (lastBraceIndex > startIndex) {
                    let salvaged = content.substring(startIndex, lastBraceIndex + 1);
                    salvaged += ']';
                    rawJson = salvaged;
                }
            }
        } 
        
        if (!rawJson) {
             const firstBrace = content.indexOf('{');
             const lastBrace = content.lastIndexOf('}');
             if (firstBrace !== -1 && lastBrace > firstBrace) {
                 const actionMatches = (content.match(/"action"\s*:/g) || []).length;
                 if (actionMatches > 0) {
                     const candidate = content.substring(firstBrace, lastBrace + 1);
                     rawJson = `[${candidate}]`;
                 }
             }
        }
    }

    if (!rawJson) return null;

    try {
        let cleanJson = rawJson.replace(/[\u0000-\u001F\u200B-\u200D\uFEFF]/g, '');
        cleanJson = cleanJson.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
        cleanJson = cleanJson
          .replace(/\|text:"/g, ', "text_alt":"')
          .replace(/}}\s*,*\s*{/g, '},{')
          .replace(/}\s*,{2,}\s*{/g, '},{')
          .replace(/}\s*{/g, '},{')
          .replace(/,(\s*])/g, '$1')
          .replace(/,(\s*})/g, '$1')
          .replace(/}\s*\d+\.?\s*{/g, '},{');

        const parsed = JSON.parse(cleanJson);
        return (Array.isArray(parsed) && parsed.length > 0) ? parsed : null;
    } catch (e) {
        return null;
    }
  }

  /**
   * Grounding Logic: Resolve abstract skeleton actions to concrete parameters
   */
  _resolveActionParams(skeletonAction, pageContent) {
      const { action, params } = skeletonAction;
      const criteria = params?.criteria || params?.intent || '';
      
      console.log(`[Grounding] Resolving '${action}' with criteria: "${criteria}"`);

      // 1. Search Grounding
      if (action === 'search') {
          let keyword = params?.keyword;
          if (!keyword && criteria) {
              keyword = criteria.replace(/^(find|search for|look up)\s+/i, '');
          }
          return { action: 'search', params: { keyword: keyword || 'latest trends' } };
      }

      // 2. Click Grounding (The Core Logic)
      if (action === 'click_result' || action === 'click_link') {
          if (!pageContent || !pageContent.interactiveElements) {
              console.warn('[Grounding] No interactive elements available.');
              return { action: 'browse', params: { iterations: 2 } };
          }

          const elements = pageContent.interactiveElements;
          let bestEl = null;
          let bestScore = -1;
          
          // Debugging log for history awareness
          if (this.actionHistory.length > 0) {
              const last = this.actionHistory[this.actionHistory.length - 1];
              if (last.status === 'error') {
                  console.log(`[Grounding] Last action failed (${last.error}). Filtering problematic elements.`);
                  if (last.params && last.params.text) {
                      this.failedElements.add(last.params.text);
                  }
              }
          }
          
          const lowerCriteria = criteria.toLowerCase();
          const queryTerms = lowerCriteria.split(' ').filter(t => t.length > 3);

          for (const el of elements) {
              // STRICT PRE-FILTERING
              if (el.href) {
                  // 1. Blacklist Check
                  if (this.isBlacklisted(el.href)) {
                      // console.log(`[Grounding] Skipped blacklisted: ${el.href}`);
                      continue; // SKIP COMPLETELY
                  }
                  
                  // 2. Frequency Check
                  try {
                       const url = new URL(el.href);
                       const domain = url.hostname;
                       const history = this.domainAccessHistory[domain] || [];
                       
                       const now = Date.now();
                       const oneDayAgo = now - (24 * 60 * 60 * 1000);
                       const oneWeekAgo = now - (7 * 24 * 60 * 60 * 1000);
                       
                       const weekVisits = history.filter(t => t > oneWeekAgo).length;
                       const dayVisits = history.filter(t => t > oneDayAgo).length;
                       
                       if (weekVisits >= this.maxVisitsPerWeek) {
                           // console.log(`[Grounding] Skipped (Max Week): ${domain}`);
                           continue; // SKIP COMPLETELY
                       }
                       
                       if (dayVisits >= this.maxVisitsPerDay) {
                           // console.log(`[Grounding] Skipped (Max Day): ${domain}`);
                           continue; // SKIP COMPLETELY
                       }
                  } catch(e) {}
              }

              const text = el.text.toLowerCase();
              let score = 0;

              // A. Criteria Match (Heavy Weight)
              if (text.includes(lowerCriteria)) score += 100;
              
              // B. Term Match
              for (const term of queryTerms) {
                  if (text.includes(term)) score += 15;
              }
              
              // C. Interest Match (Boost based on Agent Persona)
              if (this.agentContext && this.agentContext.interests) {
                  for (const interest of this.agentContext.interests) {
                      if (text.includes(interest.toLowerCase())) score += 20;
                  }
              }

              // D. Tag Priority & Text Length (Heuristic for "Content")
              if (el.tag === 'a') {
                  score += 10;
                  if (el.text.length > 30) score += 30; // Long text = likely specific article/video title
                  if (el.text.length > 60) score += 20; // Very long text
              }
              if (el.tag === 'button') score -= 5; // Prefer links for "results"
              
              // E. Strict Negative Filtering (Avoid Nav/Utility)
              if (text.match(/login|signin|sign up|register|policy|terms|setting|menu|account|feedback|help|privacy|cookies/)) score -= 100;
              if (text.match(/search labs|google apps|more options|tools|filters|all filters|maps|images|news|videos|shopping/)) score -= 80;
              if (text.length < 5 || text.match(/^[0-9]+$/)) score -= 20; // Ignore tiny/number-only links

              // F. Specific Element Boosting
              if (action === 'click_result' && (text.includes('youtube') || text.includes('video'))) score += 15;
              if (el.href && !el.href.includes('google.com')) score += 20; // Prefer external content links

              // G. Failure Penalization
              if (this.failedElements.has(el.text)) {
                  score -= 150; // Heavy penalty for previously failed elements
              }

              
              
              

              if (score > bestScore && score > 0) {
                  bestScore = score;
                  bestEl = el;
              }
          }

          if (bestEl) {
              console.log(`[Grounding] Selected element: "${bestEl.text}" (Score: ${bestScore})`);
              return { action: 'click', params: { text: bestEl.text } };
          } else {
              console.warn(`[Grounding] No match found for "${criteria}". Fallback to browse.`);
              return { action: 'browse', params: { iterations: 3 } }; 
          }
      }

      // 3. Direct Pass-through
      if (action === 'browse' || action === 'watch' || action === 'navigate' || action === 'extract_content') {
          return skeletonAction;
      }
      
      return { action: 'browse', params: { iterations: 3 } };
  }

  _buildAIPrompt(context, contextHint, hasElements, elementList, potentialPopups = []) {
    const popupInfo = potentialPopups.length > 0 
      ? `\nSUSPECTED POPUPS/OVERLAYS DETECTED (Dismissal buttons):
${potentialPopups.map((p, i) => `${i+1}. [${p.tag}] "${p.text}"`).join('\n')}\n`
      : '';

    let statsContext = "";
    if (this.stats) {
        statsContext = `
RPG STATS (YOU ARE A "${this.stats.class.toUpperCase()}" - Level ${this.stats.level}):
- INT: ${this.stats.int} | IMPACT: ${this.stats.impact} | ASSIST: ${this.stats.assist} | MISTAKE: ${this.stats.mistake}
GOAL: Improve your lowest stat while fulfilling the User Goal.
Guidelines:
${this.stats.class === 'Scholar' ? '- Focus on deep researching and reading.' : ''}
${this.stats.class === 'Builder' ? '- Focus on creating content/comments.' : ''}
${this.stats.class === 'Supporter' ? '- Focus on watching/liking.' : ''}
`;
    }

    return `SYSTEM: You are an autonomous browser agent.
OBJECTIVE: Generate a high-level behavioral plan (SKELETON) to achieve the User Goal.
User Goal: "${this.userGoal}"

${statsContext}
Current Context: ${JSON.stringify(context, null, 2)}${contextHint}
${popupInfo}
${context.currentActivity && ['work', 'research', 'study', 'morningCheck'].includes(context.currentActivity) ? `
SCHEDULE MODE: "${context.currentActivity}" — You are in WORK/RESEARCH mode.
- AVOID YouTube and video sites. Focus on reading articles, exploring websites, and extracting content.
- PRIORITIZE: click_result, click_link, browse, extract_content over watch.
- Search for content related to work interests, NOT entertainment.
` : ''}

INSTRUCTIONS:
1. Generate a JSON Array of abstract actions (The SKELETON).
2. DO NOT repeat searches for the same keyword if you are already on the results page.
3. If the current page contains relevant results, FOCUS on clicking them instead of searching again.
4. DO NOT try to guess specific link text. Use "intent" or "criteria".
5. The system will "ground" your abstract actions to real elements.
6. PRIORITIZE browsing and exploring content (click_result, browse, watch) over extract_content.
7. Only use extract_content ONCE per article page. If "alreadyScraped" is true, DO NOT use extract_content — just browse normally.
8. After extract_content, ALWAYS continue with browse or click_link to keep exploring.

Allowed Abstract Actions:
- search { "intent": "what to search for" } -> ONLY use if no relevant results are on page.
- click_result { "criteria": "description of result to click", "limit": 1 } -> Target CONTENT (articles, videos).
- click_link { "criteria": "text/topic to look for" } -> Target SPECIFIC internal/external links.
- browse { "iterations": 5 } -> Use to explore content.
- watch { "duration": "short|medium|long" } -> Use if on a video page.
${context.enable_scraping ? '- extract_content {} -> Use AFTER navigating to a news article or blog post to save its content and images.' : ''}

Example Output:
[
  { "action": "click_result", "params": { "criteria": "latest news article" } },
  { "action": "browse", "params": { "iterations": 3 } },
  { "action": "watch", "params": { "duration": "medium" } }
]

CRITICAL RULES:
1. OUTPUT ONLY RAW JSON.
2. NO COMMENTS.
3. If search fails to find results, try a DIFFERENT keyword or navigate to a different site.
4. BE DECISIVE.
`;
  }

  /**
   * Get action based on actual page content (DYNAMIC - heuristic fallback)
   */
  _getContentBasedAction(pageContent, remainingMs) {
    if (!pageContent) {
      console.warn('[SessionManager] No page content provided, using fallback');
      return this._getFallbackAction();
    }
    
    const rand = Math.random();
    const currentUrl = this.currentContext.url || '';
    const currentActivity = this.agentContext?.current_activity || 'browse';
    const isWorkMode = ['work', 'research', 'study', 'morningCheck', 'checkEmails'].includes(currentActivity);
    
    // PRIORITY 0: YouTube handling (schedule-aware)
    if (currentUrl.includes('youtube.com')) {
      // WORK MODE: Minimize YouTube — navigate away to search articles instead
      if (isWorkMode) {
        // 95% of the time: leave YouTube, search for work-related content
        if (rand > 0.05) {
          console.log(`[SessionManager] WORK MODE: Redirecting away from YouTube to focus on articles.`);
          const topics = [...(this.agentContext?.interests || 
                            (this.agentContext?.personality?.interests) || 
                            ['technology news', 'industry analysis'])];
          const randomTopic = topics[Math.floor(Math.random() * topics.length)];
          return [
            { action: 'navigate', params: { url: 'https://www.google.com' } },
            { action: 'search', params: { keyword: randomTopic + ' article' } },
            { action: 'click_result', params: { criteria: 'article or blog post about ' + randomTopic } }
          ];
        }
        // 5% chance: watch briefly to maintain natural behavior
        if (currentUrl.includes('/watch')) {
          return [{ action: 'watch', params: { duration: '30s' } }];
        }
      } else {
        // ENTERTAINMENT MODE: YouTube is fine
        if (currentUrl.includes('/watch')) {
          return [{ action: 'watch', params: { duration: '60s' } }];
        }
        
        // SEARCH LOGIC
        if (this.agentContext && rand < 0.4) {
          const topics = [...(this.agentContext.interests || 
                            (this.agentContext.personality && this.agentContext.personality.interests) || 
                            [])];
          if (topics.length > 0) {
              const randomTopic = topics[Math.floor(Math.random() * topics.length)];
              return [{ action: 'search', params: { keyword: randomTopic } }];
          }
        }
        
        const videoLinks = (pageContent.interactiveElements || []).filter(el =>
          el.href?.includes('youtube.com/watch') || el.href?.includes('/watch?v=')
        );
        if (videoLinks.length > 0 && rand < 0.8) {
          const randomVideo = videoLinks[Math.floor(Math.random() * videoLinks.length)];
          return [
            { action: 'click', params: { text: randomVideo.text } },
            { action: 'watch', params: { duration: '60s' } }
          ];
        }
      }
    }

    // PRIORITY 1: Content Page - Auto-extract articles (IF ENABLED)
    if (this.agentContext?.enable_scraping && pageContent.isContentPage && !currentUrl.includes('youtube.com') && !currentUrl.includes('google.com')) {
      // Check if we already extracted this URL (current session OR previous sessions)
      const alreadyExtractedThisSession = this.actionHistory.some(
        a => a.action === 'extract_content' && a.url === currentUrl && a.status === 'success'
      );
      const alreadyExtractedBefore = this.scrapedUrls.has(currentUrl);
      if (alreadyExtractedThisSession || alreadyExtractedBefore) {
        console.log(`[SessionManager] URL already scraped — skipping extract_content: ${currentUrl}`);
      } else {
        console.log('[SessionManager] Content page detected! Auto-triggering extract_content.');
        return [
          { action: 'extract_content', params: {} },
          { action: 'browse', params: { iterations: 3 } }
        ];
      }
    }
    
    return [{ action: 'browse', params: { iterations: 5 } }];
  }

  _getFallbackAction() {
    return [
      { action: 'browse', params: { iterations: 10 } }
    ];
  }

  getStatus() {
    const elapsedMs = this.getElapsedTime();
    return {
      sessionId: this.sessionId,
      elapsedMs: elapsedMs,
      elapsedMinutes: Math.floor(elapsedMs / 60000),
      actionsCompleted: this.actionHistory.length,
      currentUrl: this.currentContext.url,
      pageType: this.currentContext.pageType
    };
  }

  end() {
    const status = this.getStatus();
    console.log(`[SessionManager] Session ${this.sessionId} ended.`, status);
    this.sessionId = null;
    this.startTime = null;
    this.actionHistory = [];
    return status;
  }
}
