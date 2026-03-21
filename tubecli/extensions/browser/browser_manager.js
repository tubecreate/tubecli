
import { plugin } from 'playwright-with-fingerprints';
import fs from 'fs-extra';
import path from 'path';
import axios from 'axios';
import { fileURLToPath } from 'url';

export class BrowserManager {
    constructor(config = {}) {
        this.baseDir = config.baseDir || './profiles';
        this.serviceKey = null;
    }

    async fetchServiceKey() {
        if (this.serviceKey) return this.serviceKey;
        try {
            console.log('Fetching service key from API...');
            const response = await axios.get('https://api.tubecreate.com/api/fingerprints/key.php', { timeout: 10000 });
            if (response.data && response.data.status === 'success' && response.data.key) {
                // Decode Base64 key
                this.serviceKey = Buffer.from(response.data.key, 'base64').toString('utf8');
                plugin.setServiceKey(this.serviceKey);
                console.log('Service key fetched and decoded.');
                return this.serviceKey;
            }
            // Fallback: no key available
            return null;
        } catch (e) {
            console.error(`Error fetching service key: ${e.message}`);
        }
        return null;
    }

    async ensureProfile(profileName) {
        const profilePath = path.resolve(this.baseDir, profileName);
        await fs.ensureDir(profilePath);
        return profilePath;
    }

    async cleanProfile(profileName) {
        const profilePath = path.resolve(this.baseDir, profileName);
        if (await fs.pathExists(profilePath)) {
            console.log(`Cleaning up profile at ${profilePath}...`);
            try {
                // Preserve config.json if it exists
                const configPath = path.join(profilePath, 'config.json');
                if (await fs.pathExists(configPath)) {
                    await fs.copy(configPath, `${configPath}.bak`);
                }
                
                await fs.emptyDir(profilePath);
                
                if (await fs.pathExists(`${configPath}.bak`)) {
                    await fs.move(`${configPath}.bak`, configPath);
                }
            } catch (e) {
                console.warn(`Could not remove/restore profile directory: ${e.message}`);
            }
        }
    }

    async getFingerprint(profileName, options = {}) {
        const profilePath = await this.ensureProfile(profileName);
        const fingerprintPath = path.join(profilePath, 'fingerprint.json');
        const configPath = path.join(profilePath, 'config.json');

        let fingerprint;

        // 1. Try to load existing
        if (await fs.pathExists(fingerprintPath)) {
            console.log('Loading saved fingerprint...');
            try {
                const data = await fs.readFile(fingerprintPath, 'utf8');
                fingerprint = JSON.parse(data);
                if (!fingerprint || (typeof fingerprint !== 'object' && typeof fingerprint !== 'string') || (typeof fingerprint === 'object' && Object.keys(fingerprint).length < 10)) {
                     throw new Error('Invalid fingerprint');
                }
                console.log(`Fingerprint loaded successfully.`);
                return fingerprint;
            } catch (e) {
                console.warn('Failed to parse saved fingerprint, fetching new one:', e.message);
                // Fall through to fetch
            }
        }

        // 2. Fetch new
        let tags = options.tags || ['Microsoft Windows', 'Chrome'];
        
        // Try to read tags from config if not provided in options
        if (!options.tags && await fs.pathExists(configPath)) {
             try {
                 const config = await fs.readJson(configPath);
                 if (config.tags && Array.isArray(config.tags)) {
                     tags = config.tags;
                 }
             } catch (e) {}
        }

        console.log(`Fetching NEW Fingerprint via api.tubecreate.com...`);
        // Retry logic for fetching
        let attempts = 0;
        while (attempts < 3) {
            try {
                const resp = await axios.get('https://api.tubecreate.com/api/fingerprints/getfinger.php', { timeout: 120000 });
                const data = resp.data;
                
                if (data && data.status === 'success' && data.file_path) {
                    const fpUrl = `https://api.tubecreate.com/${data.file_path}`;
                    console.log(`Downloading fingerprint from API...`);
                    const fpResp = await axios.get(fpUrl, { timeout: 120000 });
                    fingerprint = fpResp.data;
                    
                    if (!fingerprint || (typeof fingerprint !== 'object' && typeof fingerprint !== 'string')) {
                        throw new Error('Invalid fingerprint data received from API');
                    }

                    // Save it
                    await fs.outputFile(fingerprintPath, JSON.stringify(fingerprint), 'utf8');
                    return fingerprint;
                } else {
                    throw new Error('Invalid response from getfinger.php');
                }
            } catch (e) {
                console.error(`Fingerprint fetch attempt ${attempts + 1} failed: ${e.message}`);
                attempts++;
                await new Promise(r => setTimeout(r, 2000));
            }
        }
        throw new Error('Failed to fetch fingerprint after 3 attempts');
    }

    normalizeProxy(proxy) {
        if (!proxy) return null;
        
        // Handle socks5://user:pass:host:port format (common in some providers)
        // Convert to socks5://user:pass@host:port
        const simpleFormatRegex = /^(socks5|http|https):\/\/([^:@]+):([^:@]+):([^:@]+):(\d+)$/i;
        const match = proxy.match(simpleFormatRegex);
        
        if (match) {
            const [_, protocol, user, pass, host, port] = match;
            const normalized = `${protocol.toLowerCase()}://${user}:${pass}@${host}:${port}`;
            console.log(`[BrowserManager] Normalized proxy: ${proxy} -> ${normalized}`);
            return normalized;
        }
        
        return proxy;
    }

    applyProxy(proxyString) {
        const normalized = this.normalizeProxy(proxyString);
        if (normalized) {
            console.log(`Applying proxy: ${normalized}`);
            plugin.useProxy(normalized, {
                changeTimezone: true,
                changeGeolocation: true
            });
        } else {
            console.log('No proxy configured. Clearing proxy settings.');
            // Directly unset the proxy property to ensure no proxy is sent to the engine
            plugin.proxy = null;
        }
    }

    async launch(profileName, options = {}) {
        await this.fetchServiceKey();
        const profilePath = await this.ensureProfile(profileName);
        let {
            headless = false,
            proxy = null,
            fingerprint = null,
            args = []
        } = options;

        const configPath = path.join(profilePath, 'config.json');
        
        // Proxy Persistence Logic
        if (proxy) {
            // New proxy provided -> Normalize and Save it
            const normalizedProxy = this.normalizeProxy(proxy);
            if (normalizedProxy) {
                proxy = normalizedProxy; // Use normalized version
                console.log(`Saving new proxy configuration to profile: ${proxy}`);
                try {
                    const currentConfig = await fs.pathExists(configPath) ? await fs.readJson(configPath) : {};
                    currentConfig.proxy = proxy;
                    await fs.writeJson(configPath, currentConfig, { spaces: 2 });
                } catch (e) {
                    console.warn('Failed to save proxy config:', e.message);
                }
            }
        } else {
            // No proxy provided -> Try to load from config
            try {
                if (await fs.pathExists(configPath)) {
                    const savedConfig = await fs.readJson(configPath);
                    if (savedConfig.proxy) {
                        console.log(`Loaded saved proxy: ${savedConfig.proxy}`);
                        proxy = savedConfig.proxy;
                    }
                }
            } catch (e) {
                console.warn('Failed to load proxy config:', e.message);
            }
        }

        // Apply fingerprint with retry logic
        if (fingerprint) {
             let fpAttempts = 0;
             while (fpAttempts < 2) {
                 try {

                    // plugin.useFingerprint accepts either the fingerprint object or the token string
                    // BUT in practice it often requires the JSON string if fetched as string
                    if (fingerprint) {
                        try {
                            // The plugin often expects the JSON string for raw fingerprints
                            const fpToUse = typeof fingerprint === 'object' ? JSON.stringify(fingerprint) : fingerprint;
                            plugin.useFingerprint(fpToUse);
                        } catch (err) {
                             console.warn(`[BrowserManager] Initial fingerprint application failed: ${err.message}. Retrying with direct object...`);
                             try {
                                 const parsed = typeof fingerprint === 'string' ? JSON.parse(fingerprint) : fingerprint;
                                 plugin.useFingerprint(parsed);
                             } catch (finalErr) {
                                 throw err; // Throw original error if both fail
                             }
                        }
                        break; // Success
                    } else {
                        throw new Error('Fingerprint is empty');
                    }
                 } catch (e) {
                     console.error(`Error applying fingerprint (Attempt ${fpAttempts + 1}/2):`, e.message);
                     if (fpAttempts === 0) {
                         console.warn('Fingerprint might be corrupted. Deleting and re-fetching...');
                         try {
                             const fingerprintPath = path.join(profilePath, 'fingerprint.json');
                             await fs.remove(fingerprintPath);
                             // Fetch new one
                             fingerprint = await this.getFingerprint(profileName, { tags: ['Microsoft Windows', 'Chrome'] });
                         } catch (err) {
                             console.error('Failed to refresh fingerprint:', err.message);
                         }
                     } else {
                         throw e; // Fail on second attempt
                     }
                     fpAttempts++;
                 }
             }
        }

        // Apply proxy (already normalized if it came from args, or loaded from config)
        this.applyProxy(proxy);

        // Apply browser version if saved in config
        try {
                const conf = await fs.pathExists(configPath) ? await fs.readJson(configPath) : {};
                if (conf.browser_version && conf.browser_version !== 'default') {
                    console.log(`[Launch] Using browser version: ${conf.browser_version}`);
                    plugin.useBrowserVersion(conf.browser_version);
                }
        } catch (e) {
            console.warn('Failed to resolve browser_version path:', e.message);
        }

        // Default args
        const launchArgs = [
            '--start-maximized',
            ...args
        ];

        console.log(`Launching browser [Profile: ${profileName}]...`);
        
        // Explicitly configure profile to NOT load proxy from storage
        // This ensures that if we provided a proxy, it's used. If we didn't, NO proxy is used.
        // We also handle fingerprint manually, so loadFingerprint: false is safer too.
        plugin.useProfile(profilePath, { loadProxy: false, loadFingerprint: false });

        // LAUNCH RETRY LOGIC (Specifically for "Failed to get proxy ip")
        let launchAttempt = 1;
        const maxLaunchAttempts = 3;
        let lastError = null;

        while (launchAttempt <= maxLaunchAttempts) {
            try {
                const context = await plugin.launchPersistentContext(profilePath, {
                    headless,
                    args: launchArgs,
                    userDataDir: profilePath
                });
                return context;
            } catch (e) {
                lastError = e;
                if ((options.skipProxyCheck || e.message.toLowerCase().includes('http request error')) && (
                    e.message.toLowerCase().includes('failed to get proxy ip') || 
                    e.message.toLowerCase().includes('proxy') ||
                    e.message.toLowerCase().includes('timeout') ||
                    e.message.toLowerCase().includes('http request error') ||
                    e.message.toLowerCase().includes('incorrect format')
                )) {
                    console.warn(`[Launch] Proxy/HTTP issue detected (${e.message}). Retrying while keeping proxy active...`);
                    // DO NOT call this.applyProxy(null) here if skipProxyCheck is true!
                    // We only disable if we want it to definitely fall back to home IP on failure.
                    // If it's the 3rd attempt, maybe then we disable? 
                    // No, let's keep it consistent with the user's intent.
                    launchAttempt++;
                    await new Promise(r => setTimeout(r, 2000));
                    continue;
                }

                if (e.message.toLowerCase().includes('failed to get proxy ip') || 
                    e.message.toLowerCase().includes('proxy') ||
                    e.message.toLowerCase().includes('timeout') ||
                    e.message.toLowerCase().includes('http request error') ||
                    e.message.toLowerCase().includes('incorrect format')) {
                    
                    if (e.message.toLowerCase().includes('incorrect format')) {
                         if (!options.proxy) {
                             console.warn(`[Launch] 'Incorrect format' persisted with NO PROXY! This confirms FINGERPRINT is invalid.`);
                             throw new Error('FINGERPRINT_FATAL_ERROR');
                         }
                         console.warn(`[Launch] 'Incorrect format' error detected. This likely means PROXY is invalid: ${proxy}`);
                         console.warn(`[Launch] Disabling proxy for next attempt to verify...`);
                         this.applyProxy(null);
                         options.proxy = null;
                         launchAttempt++;
                         continue;
                    }

                    console.warn(`[Launch] Attempt ${launchAttempt} failed: ${e.message}. Retrying in 5 seconds...`);
                    launchAttempt++;
                    await new Promise(r => setTimeout(r, 5000));
                } else {
                    throw e; // Non-proxy error, fail immediately
                }
            }
        }
        
        throw new Error(`Failed to launch browser after ${maxLaunchAttempts} attempts. Last error: ${lastError?.message}`);
    }

    async getStats(profileName) {
        const profilePath = await this.ensureProfile(profileName);
        const statsPath = path.join(profilePath, 'stats.json');
        
        if (await fs.pathExists(statsPath)) {
            try {
                return await fs.readJson(statsPath);
            } catch (e) {
                console.warn(`Failed to read stats for ${profileName}, resetting...`);
            }
        }
        
        // Default Stats
        return {
            level: 1,
            class: 'Novice',
            exp: 0,
            impact: 0,
            assist: 0,
            mistake: 0,
            int: 0, // Intelligence
            apm: 0, // Actions Per Minute (tracked loosely)
            kda: 0.0
        };
    }

    async updateStats(profileName, actionType, context = {}) {
        const stats = await this.getStats(profileName);
        const profilePath = path.resolve(this.baseDir, profileName);
        
        // 1. Update Core Stats based on Action
        switch (actionType) {
            case 'search':
            case 'browse':
            case 'navigate':
                // Check for INT growth (tech keywords)
                const techKeywords = ['code', 'python', 'javascript', 'ai', 'data', 'algorithm', 'server', 'linux'];
                const content = (context.keyword || context.url || '').toLowerCase();
                if (techKeywords.some(k => content.includes(k))) {
                    stats.int += 1;
                }
                break;
                
            case 'comment':
            case 'type':
                // Impact growth
                stats.impact += 5; 
                stats.int += 0.5;
                break;
                
            case 'watch':
            case 'click':
            case 'like':
                // Assist/Support growth
                stats.assist += 1;
                break;

            case 'error':
                stats.mistake += 1;
                break;
        }

        // 2. Calculate KDA
        // KDA = (Impact + Assist) / (Mistake || 1)
        stats.kda = parseFloat(((stats.impact + stats.assist) / (stats.mistake || 1)).toFixed(2));

        // 3. Level Up Logic (Simple EXP based on total actions)
        stats.exp += 1;
        stats.level = Math.floor(Math.sqrt(stats.exp) * 0.5) + 1;

        // 4. Class Evolution
        if (stats.level >= 5) {
            if (stats.int > stats.impact && stats.int > stats.assist) stats.class = 'Scholar'; 
            else if (stats.impact > stats.assist) stats.class = 'Builder'; 
            else if (stats.assist > stats.impact) stats.class = 'Supporter';
            else stats.class = 'Novice';
        }
        
        // Save
        await fs.writeJson(path.join(profilePath, 'stats.json'), stats, { spaces: 2 });
        return stats;
    }
}
