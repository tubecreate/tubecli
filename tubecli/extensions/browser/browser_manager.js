
import { plugin } from 'playwright-with-fingerprints';
import fs from 'fs-extra';
import path from 'path';
import axios from 'axios';
import { fileURLToPath } from 'url';

function extractRawKey(jsonString, key) {
    const searchStr = `"${key}":`;
    const startIdx = jsonString.indexOf(searchStr);
    if (startIdx === -1) return null;
    
    let valStart = startIdx + searchStr.length;
    while (valStart < jsonString.length && /\s/.test(jsonString[valStart])) {
        valStart++;
    }
    
    let braceCount = 0;
    let inString = false;
    let escape = false;
    
    for (let i = valStart; i < jsonString.length; i++) {
        const char = jsonString[i];
        if (escape) {
            escape = false;
            continue;
        }
        if (char === '\\') {
            escape = true;
            continue;
        }
        if (char === '"') {
            inString = !inString;
            continue;
        }
        if (!inString) {
            if (char === '{' || char === '[') {
                braceCount++;
            } else if (char === '}' || char === ']') {
                braceCount--;
                if (braceCount === 0) {
                    return jsonString.slice(valStart, i + 1);
                }
            } else if (braceCount === 0 && (char === ',' || char === '}')) {
                return jsonString.slice(valStart, i);
            }
        }
    }
    return null;
}

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
        const fingerprintPath = path.join(profilePath, 'fingerprint_saved.json');
        const legacyFingerprintPath = path.join(profilePath, 'fingerprint.json');
        const configPath = path.join(profilePath, 'config.json');

        let fingerprint;

        // 1. Try to load existing
        if (await fs.pathExists(fingerprintPath) || await fs.pathExists(legacyFingerprintPath)) {
            console.log('Loading saved fingerprint...');
            try {
                const targetFpPath = await fs.pathExists(fingerprintPath) ? fingerprintPath : legacyFingerprintPath;
                const data = await fs.readFile(targetFpPath, 'utf8');
                // Check if it's a plugin.fetch() string token (not JSON object)
                if (data && data.length > 20) {
                    try {
                        const parsed = JSON.parse(data);
                        // If it's an object with very few keys, it might be a wrapped token
                        if (typeof parsed === 'object' && parsed !== null) {
                            fingerprint = data; // Keep as string for plugin.useFingerprint
                        }
                    } catch (e) {
                        fingerprint = data; // Not JSON — likely a raw string token
                    }
                    if (!fingerprint) fingerprint = data;
                    console.log(`Fingerprint loaded successfully (${typeof fingerprint}, ${fingerprint.length} chars).`);
                    return fingerprint;
                }
            } catch (e) {
                console.warn('Failed to load saved fingerprint, fetching new one:', e.message);
            }
        }

        // Read config for tags/version/window_size
        let tags = options.tags || ['Windows', 'Chrome'];
        let minBrowserVersion = null;
        let windowSize = null;
        
        if (await fs.pathExists(configPath)) {
             try {
                 const config = await fs.readJson(configPath);
                 if (config.tags && Array.isArray(config.tags)) tags = config.tags;
                 if (config.browser_version && config.browser_version !== 'default' && config.browser_version !== 'latest') {
                     minBrowserVersion = config.browser_version.split('.')[0];
                 }
                 if (config.window_size) windowSize = config.window_size;
             } catch (e) {}
        }
        
        // Map common OS names to Security Browser expected tags
        const tagMap = { 'Windows': 'Microsoft Windows', 'macOS': 'Mac OS X' };
        const mappedTags = tags.map(t => tagMap[t] || t);

        // 2. Fetch via PHP API (key stays on server)
        console.log(`Fetching fingerprint via api.tubecreate.com [tags: ${mappedTags.join(',')}, size: ${windowSize ? `${windowSize.width}x${windowSize.height}` : 'default'}]...`);
        let attempts = 0;
        let triedWithoutSize = false;
        while (attempts < 3) {
            try {
                const params = { tags: mappedTags.join(',') };
                if (minBrowserVersion) params.min_browser_version = minBrowserVersion;
                if (windowSize && !triedWithoutSize) {
                    // Use ranges instead of exact match — Security Browser pool may not have exact resolution
                    params.min_width = Math.max(windowSize.width - 200, 1024);
                    params.max_width = windowSize.width + 200;
                    params.min_height = Math.max(windowSize.height - 200, 600);
                    params.max_height = windowSize.height + 200;
                }
                
                const resp = await axios.get('https://api.tubecreate.com/api/fingerprints/getfinger.php', { 
                    params,
                    responseType: 'text',
                    timeout: 180000,
                    maxContentLength: 50 * 1024 * 1024,
                    maxBodyLength: 50 * 1024 * 1024
                });
                const rawText = resp.data;
                const data = JSON.parse(rawText);
                
                if (data && data.status === 'success') {
                    // New format: fingerprint included directly in response
                    if (data.fingerprint) {
                        console.log(`Got fingerprint directly from API response.`);
                        // Extract RAW JSON string to preserve exact cryptographic signature and key order
                        fingerprint = extractRawKey(rawText, 'fingerprint') || JSON.stringify(data.fingerprint);
                    } 
                    // Old format: download via file_path
                    else if (data.file_path) {
                        const fpUrl = `https://api.tubecreate.com/${data.file_path}`;
                        console.log(`Downloading fingerprint from API...`);
                        const fpResp = await axios.get(fpUrl, { responseType: 'text', timeout: 120000 });
                        fingerprint = fpResp.data;
                    } else {
                        throw new Error('No fingerprint data in API response');
                    }
                    
                    // Validate: Security Browser may return {valid: false, message: "..."}
                    if (typeof fingerprint === 'object' && fingerprint.valid === false) {
                        console.warn(`[Fingerprint] Security Browser returned invalid: ${fingerprint.message}`);
                        if (!triedWithoutSize && windowSize) {
                            console.log('[Fingerprint] Retrying without size constraints...');
                            triedWithoutSize = true;
                            attempts++;
                            continue;
                        }
                        throw new Error(`Security Browser: ${fingerprint.message}`);
                    }
                    
                    if (!fingerprint || (typeof fingerprint !== 'object' && typeof fingerprint !== 'string')) {
                        throw new Error('Invalid fingerprint data received from API');
                    }

                    // Save it
                    const toSave = typeof fingerprint === 'object' ? JSON.stringify(fingerprint) : fingerprint;
                    await fs.outputFile(fingerprintPath, toSave, 'utf8');
                    await fs.outputFile(legacyFingerprintPath, toSave, 'utf8');
                    return toSave;
                } else {
                    throw new Error('Invalid response from getfinger.php');
                }
            } catch (e) {
                console.error(`Fingerprint fetch attempt ${attempts + 1} failed: ${e.message}`);
                attempts++;
                await new Promise(r => setTimeout(r, 2000));
            }
        }
        throw new Error('Failed to fetch fingerprint after all attempts');
    }

    /**
     * Patch the fingerprint's User-Agent to match the actual engine Chromium version.
     * This prevents mismatch where fingerprint says Chrome/124 but engine is Chrome/146.
     * @param {object|string} fingerprint - The fingerprint data
     * @param {string} targetChromiumVer - Target Chromium version (e.g. '146.0.7680.80')
     * @returns {object|string} - Patched fingerprint
     */
    patchFingerprintUserAgent(fingerprint, targetChromiumVer) {
        if (!fingerprint || !targetChromiumVer) return fingerprint;
        
        const majorVersion = targetChromiumVer.split('.')[0]; // e.g. '147'
        
        try {
            let fp = typeof fingerprint === 'string' ? JSON.parse(fingerprint) : fingerprint;
            const wasString = typeof fingerprint === 'string';
            
            // Handle Security Browser v5 wrapper format: { canvas, webgl, fingerprint: { navigator, attr, ... } }
            // Patch the INNER fingerprint object, but return the full wrapper
            let target = fp;
            if (fp.fingerprint) {
                target = typeof fp.fingerprint === 'string' ? JSON.parse(fp.fingerprint) : fp.fingerprint;
                console.log('[Fingerprint] Patching inside Security Browser wrapper...');
            }
            
            // 1. Patch navigator.userAgent — replace Chrome/XXX.0.0.0 with correct major version
            if (target.navigator && target.navigator.userAgent) {
                const oldUA = target.navigator.userAgent;
                const newUA = oldUA
                    .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                    .replace(/ Edg\/[\d.]+/g, '')
                    .replace(/ Edge\/[\d.]+/g, '');
                if (oldUA !== newUA) {
                    target.navigator.userAgent = newUA;
                    console.log(`[Fingerprint] Patched navigator.userAgent: Chrome/${oldUA.match(/Chrome\/(\d+)/)?.[1] || '?'} → Chrome/${majorVersion}`);
                }
            }
            
            // 1b. Patch Security Browser specific attr object
            if (target.attr && target.attr['navigator.userAgent']) {
                const oldUA = target.attr['navigator.userAgent'];
                const newUA = oldUA
                    .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                    .replace(/ Edg\/[\d.]+/g, '')
                    .replace(/ Edge\/[\d.]+/g, '');
                if (oldUA !== newUA) {
                    target.attr['navigator.userAgent'] = newUA;
                    console.log(`[Fingerprint] Patched attr[navigator.userAgent]: Chrome/${oldUA.match(/Chrome\/(\d+)/)?.[1] || '?'} → Chrome/${majorVersion}`);
                }
            }
            
            // 2. Patch navigator.appVersion
            if (target.navigator && target.navigator.appVersion) {
                target.navigator.appVersion = target.navigator.appVersion
                    .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                    .replace(/ Edg\/[\d.]+/g, '')
                    .replace(/ Edge\/[\d.]+/g, '');
            }
            
            // 2b. Patch Security Browser specific attr appVersion
            if (target.attr && target.attr['navigator.appVersion']) {
                target.attr['navigator.appVersion'] = target.attr['navigator.appVersion']
                    .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                    .replace(/ Edg\/[\d.]+/g, '')
                    .replace(/ Edge\/[\d.]+/g, '');
            }
            
            // 3. Patch navigator.userAgentData.brands
            if (target.navigator && target.navigator.userAgentData && Array.isArray(target.navigator.userAgentData.brands)) {
                for (const brand of target.navigator.userAgentData.brands) {
                    if (brand.brand === 'Google Chrome' || brand.brand === 'Chromium') {
                        brand.version = majorVersion;
                    }
                }
            }
            
            // 4. Patch navigator.userAgentData.fullVersionList
            if (target.navigator && target.navigator.userAgentData && Array.isArray(target.navigator.userAgentData.fullVersionList)) {
                for (const entry of target.navigator.userAgentData.fullVersionList) {
                    if (entry.brand === 'Google Chrome' || entry.brand === 'Chromium') {
                        entry.version = targetChromiumVer;
                    }
                }
            }
            
            // 5. Patch HTTP Headers
            if (target.headers) {
                const keys = Object.keys(target.headers);
                
                const uaKey = keys.find(k => k.toLowerCase() === 'user-agent');
                if (uaKey && target.headers[uaKey]) {
                    target.headers[uaKey] = target.headers[uaKey]
                        .replace(/Chrome\/\d+\.0\.0\.0/g, `Chrome/${majorVersion}.0.0.0`)
                        .replace(/ Edg\/[\d.]+/g, '')
                        .replace(/ Edge\/[\d.]+/g, '');
                }
                
                const secChUaKey = keys.find(k => k.toLowerCase() === 'sec-ch-ua');
                if (secChUaKey && target.headers[secChUaKey]) {
                    target.headers[secChUaKey] = target.headers[secChUaKey]
                        .replace(/"Chromium";v="\d+"/g, `"Chromium";v="${majorVersion}"`)
                        .replace(/"Google Chrome";v="\d+"/g, `"Google Chrome";v="${majorVersion}"`);
                }
                
                const secChUaFullKey = keys.find(k => k.toLowerCase() === 'sec-ch-ua-full-version-list');
                if (secChUaFullKey && target.headers[secChUaFullKey]) {
                    target.headers[secChUaFullKey] = target.headers[secChUaFullKey]
                        .replace(/"Chromium";v="[\d.]+"/g, `"Chromium";v="${targetChromiumVer}"`)
                        .replace(/"Google Chrome";v="[\d.]+"/g, `"Google Chrome";v="${targetChromiumVer}"`);
                }
            }
            
            // Write patched target back into wrapper if applicable
            if (fp.fingerprint && target !== fp.fingerprint && target !== fp) {
                fp.fingerprint = typeof fp.fingerprint === 'string' ? JSON.stringify(target) : target;
            }
            
            return wasString ? JSON.stringify(fp) : fp;
        } catch (e) {
            console.warn(`[Fingerprint] Failed to patch UA: ${e.message}`);
            return fingerprint;
        }
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

        // Check if bypass marker exists
        const skipFingerprintPath = path.join(profilePath, 'skip_fingerprint.txt');
        if (await fs.pathExists(skipFingerprintPath)) {
            console.warn(`\n[Launch] 🛡️ BYPASS DETECTED: skipping fingerprint application to force Free Mode!\n`);
            try { plugin.setServiceKey(''); } catch(ex){}
            fingerprint = null;
        }

        // Apply proxy (already normalized if it came from args, or loaded from config)
        this.applyProxy(proxy);

        // Resolve browser engine version FIRST (needed for fingerprint UA patching)
        let targetChromiumVer = null;
        let targetBasVer = null;
        let shardxExePath = null;
        try {
                const conf = await fs.pathExists(configPath) ? await fs.readJson(configPath) : {};
                targetChromiumVer = conf.browser_version;
                
                let isShardX = false;
                if (targetChromiumVer && targetChromiumVer.includes('ShardX')) {
                    isShardX = true;
                    const versionNum = targetChromiumVer.replace('ShardX', '').replace('-', '').trim();
                    const appdata = process.env.APPDATA;
                    if (appdata) {
                        let p1 = path.join(appdata, 'shardx-launcher', 'runtime', 'engines', versionNum, `ShardX-Windows-${versionNum}`, 'chrome.exe');
                        let p2 = path.join(appdata, 'shardx-launcher', 'runtime', 'engines', versionNum, 'chrome.exe');
                        let p3 = path.join(appdata, 'shardx-launcher', 'runtime', 'engines', versionNum, 'ShardX-Windows', 'chrome.exe');
                        if (await fs.pathExists(p1)) {
                            shardxExePath = p1;
                        } else if (await fs.pathExists(p2)) {
                            shardxExePath = p2;
                        } else if (await fs.pathExists(p3)) {
                            shardxExePath = p3;
                        }
                    }
                    
                    if (!shardxExePath) {
                        // macOS support fallback
                        const home = process.env.HOME || process.env.USERPROFILE;
                        if (home) {
                            let pMac = path.join(home, 'Library', 'Application Support', 'shardx-launcher', 'runtime', 'engines', versionNum, `ShardX-Mac-arm64-${versionNum}`, 'ShardX.app', 'Contents', 'MacOS', 'ShardX');
                            if (await fs.pathExists(pMac)) {
                                shardxExePath = pMac;
                            }
                        }
                    }
                    
                    if (!shardxExePath) {
                        throw new Error(`ShardX browser engine (${versionNum}) not found. Please install it in ShardBrowser first.`);
                    }
                    
                    targetChromiumVer = versionNum;
                    targetBasVer = null;
                    console.log(`[Launch] Resolved ShardX engine version: ${versionNum} at ${shardxExePath}`);
                }
                
                if (!isShardX) {
                    const ENGINE_MAP = {
                        '30.1.0': '148.0.7778.97',
                        '30.0.0': '147.0.7727.56',
                        '29.9.2': '146.0.7680.80',
                        '29.8.1': '145.0.7632.46',
                        '29.7.0': '144.0.7559.60',
                        '29.5.0': '142.0.7444.60',
                        '28.3.1': '138.0.7333.45',
                        '28.2.0': '137.0.7222.35'
                    };
                    
                    const REVERSE_MAP = Object.fromEntries(Object.entries(ENGINE_MAP).map(([k, v]) => [v, k]));
                    
                    // If not set or default, find the latest downloaded engine
                    if (!targetChromiumVer || targetChromiumVer === 'default' || targetChromiumVer === 'latest') {
                        const __dirname = path.dirname(fileURLToPath(import.meta.url));
                        const scriptDir = path.join(__dirname, 'data', 'script');
                        if (await fs.pathExists(scriptDir)) {
                            const dirs = await fs.readdir(scriptDir);
                            const versions = dirs.filter(d => /^\d+\.\d+\.\d+$/.test(d)).sort((a, b) => b.localeCompare(a, undefined, { numeric: true, sensitivity: 'base' }));
                            if (versions.length > 0) {
                                targetBasVer = versions[0];
                                targetChromiumVer = ENGINE_MAP[targetBasVer] || targetBasVer; // Fallback to raw if unknown
                                console.log(`[Launch] Auto-detected installed BAS engine: ${targetBasVer} (Chromium ${targetChromiumVer})`);
                            }
                        }
                    } else {
                        // Try to resolve targetBasVer from config's chromium version
                        targetBasVer = REVERSE_MAP[targetChromiumVer];
                        
                        // Verify this engine version is actually installed
                        if (targetBasVer) {
                            const __dirname = path.dirname(fileURLToPath(import.meta.url));
                            const requestedEngineDir = path.join(__dirname, 'data', 'script', targetBasVer);
                            const isInstalled = await fs.pathExists(requestedEngineDir) &&
                                await fs.pathExists(path.join(requestedEngineDir, 'FastExecuteScript.exe'));
                            
                            if (!isInstalled) {
                                console.warn(`[Launch] ⚠️ Requested engine ${targetBasVer} (Chrome ${targetChromiumVer}) is NOT installed!`);
                                // Fall back to latest installed engine
                                const scriptDir = path.join(__dirname, 'data', 'script');
                                if (await fs.pathExists(scriptDir)) {
                                    const dirs = await fs.readdir(scriptDir);
                                    const candidates = dirs.filter(d => /^\d+\.\d+\.\d+$/.test(d))
                                        .sort((a, b) => b.localeCompare(a, undefined, { numeric: true, sensitivity: 'base' }));
                                    let fallbackBas = null;
                                    for (const d of candidates) {
                                        const exePath = path.join(scriptDir, d, 'FastExecuteScript.exe');
                                        if (await fs.pathExists(exePath)) { fallbackBas = d; break; }
                                    }
                                    if (fallbackBas) {
                                        targetBasVer = fallbackBas;
                                        targetChromiumVer = ENGINE_MAP[targetBasVer] || targetBasVer;
                                        console.warn(`[Launch] ↩️ Falling back to latest installed engine: ${targetBasVer} (Chrome ${targetChromiumVer})`);
                                    }
                                }
                            } else {
                                console.log(`[Launch] ✅ Verified engine ${targetBasVer} is installed.`);
                            }
                        }
                    }
    
                    if (targetChromiumVer && targetChromiumVer !== 'default' && targetChromiumVer !== 'latest') {
                        console.log(`[Launch] Using browser version: ${targetChromiumVer}`);
                        plugin.useBrowserVersion(targetChromiumVer);
                        
                        // CRITICAL HOTFIX: The plugin's engine.js ignores useBrowserVersion() when 
                        // deciding which FastExecuteScript.exe to spawn, relying on project.xml instead.
                        // We must dynamically rewrite its project.xml to match our target BAS version!
                        if (targetBasVer) {
                            try {
                                const __dirname = path.dirname(fileURLToPath(import.meta.url));
                                const projectXmlPath = path.join(__dirname, 'node_modules', 'browser-with-fingerprints', 'project.xml');
                                if (await fs.pathExists(projectXmlPath)) {
                                    let xmlContent = await fs.readFile(projectXmlPath, 'utf8');
                                    xmlContent = xmlContent.replace(/<EngineVersion>.*?<\/EngineVersion>/, `<EngineVersion>${targetBasVer}</EngineVersion>`);
                                    await fs.writeFile(projectXmlPath, xmlContent, 'utf8');
                                    console.log(`[Launch] Hotfixed plugin project.xml engine version to ${targetBasVer}`);
                                }
                            } catch (err) {
                                console.warn('[Launch] Failed to apply project.xml hotfix:', err.message);
                            }
                        }
                    }
                }
        } catch (e) {
            console.warn('Failed to resolve browser_version path:', e.message);
        }

        // Patch fingerprint User-Agent to match actual engine version
        // Bypassed to prevent fingerprint signature corruption causing 'Incorrect format' errors
        /*
        if (fingerprint && targetChromiumVer && targetChromiumVer !== 'default' && targetChromiumVer !== 'latest') {
            fingerprint = this.patchFingerprintUserAgent(fingerprint, targetChromiumVer);
        }
        */

        // Apply fingerprint with retry logic
        if (fingerprint) {
             let fpAttempts = 0;
             while (fpAttempts < 2) {
                 try {

                    if (fingerprint) {
                        // Pass stringified JSON or raw token to plugin.useFingerprint (always string)
                        const fpString = typeof fingerprint === 'object' ? JSON.stringify(fingerprint) : fingerprint;
                        plugin.useFingerprint(fpString);
                    }
                    break; // Success
                 } catch (e) {
                     console.error(`Error applying fingerprint (Attempt ${fpAttempts + 1}/2):`, e.message);
                     if (fpAttempts === 0) {
                         console.warn('Fingerprint might be corrupted. Deleting and re-fetching...');
                         try {
                              const fingerprintPath = path.join(profilePath, 'fingerprint_saved.json');
                              const legacyFingerprintPath = path.join(profilePath, 'fingerprint.json');
                              await fs.remove(fingerprintPath);
                              await fs.remove(legacyFingerprintPath);
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

        // Default args
        const launchArgs = [
            '--start-maximized',
            '--proxy-bypass-list=localhost,127.0.0.1,::1',
            '--disable-blink-features=AutomationControlled',
            '--test-type',
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
                    userDataDir: profilePath,
                    ignoreDefaultArgs: ['--enable-automation'],
                    ...(shardxExePath ? { executablePath: shardxExePath } : {})
                });
                return context;
            } catch (e) {
                lastError = e;
                const errMsg = e.message.toLowerCase();
                const isProxyError = errMsg.includes('failed to get proxy ip') || 
                                     errMsg.includes('proxy') ||
                                     errMsg.includes('timeout') ||
                                     errMsg.includes('http request error') ||
                                     errMsg.includes('incorrect format');
                const isEngineFlake = errMsg.includes('browserautomationstudio') || 
                                      errMsg.includes('referenceerror: can\'t find variable');
                const isKeyError    = errMsg.includes('key expired') || errMsg.includes('invalid key');
                const isFingerprintError = errMsg.includes('fingerprint') && (errMsg.includes('not found') || errMsg.includes('error'));

                if (isFingerprintError && launchAttempt === 1) {
                    // Fingerprint incompatible with engine — delete old, fetch fresh, retry
                    console.warn(`[Launch] ⚠️ Fingerprint rejected by engine: ${e.message}`);
                    console.warn(`[Launch] Deleting old fingerprint and fetching a fresh one...`);
                    try {
                        const fingerprintPath = path.join(profilePath, 'fingerprint_saved.json');
                        const legacyFingerprintPath = path.join(profilePath, 'fingerprint.json');
                        await fs.remove(fingerprintPath);
                        await fs.remove(legacyFingerprintPath);
                        fingerprint = await this.getFingerprint(profileName, { tags: ['Microsoft Windows', 'Chrome'] });
                        // User-Agent patching is bypassed to prevent cryptographic signature corruption
                        /*
                        if (fingerprint && targetChromiumVer && targetChromiumVer !== 'default' && targetChromiumVer !== 'latest') {
                            fingerprint = this.patchFingerprintUserAgent(fingerprint, targetChromiumVer);
                        }
                        */
                        // Re-apply fingerprint directly (always stringified if object)
                        const fpString = typeof fingerprint === 'object' ? JSON.stringify(fingerprint) : fingerprint;
                        plugin.useFingerprint(fpString);
                        console.log('[Launch] Fresh fingerprint applied. Retrying launch...');
                    } catch (refreshErr) {
                        console.error('[Launch] Failed to refresh fingerprint:', refreshErr.message);
                    }
                    launchAttempt++;
                    continue;
                }

                if (isProxyError || isEngineFlake || isKeyError) {
                    if (isKeyError) {
                         console.warn(`[Launch] 🛡️ Security Browser key is expired! Marking profile for FREE mode bypass...`);
                         try { 
                             const fs = await import('fs-extra');
                             await fs.writeFile(path.join(profilePath, 'skip_fingerprint.txt'), 'true');
                         } catch(ex){}
                         
                         throw new Error('Key expired! I have installed a Bypass hook. Please click OPEN BROWSER again to launch in Free Mode (no antidetect).');
                    }

                    if (errMsg.includes('incorrect format')) {
                         if (!options.proxy) {
                             console.warn(`[Launch] 'Incorrect format' persisted with NO PROXY! This confirms FINGERPRINT is invalid.`);
                             throw new Error('FINGERPRINT_FATAL_ERROR');
                         }
                         console.warn(`[Launch] 'Incorrect format' error detected. This likely means PROXY is invalid.`);
                         console.warn(`[Launch] Disabling proxy for next attempt to verify...`);
                         this.applyProxy(null);
                         options.proxy = null;
                         launchAttempt++;
                         continue;
                    }

                    console.warn(`[Launch] Attempt ${launchAttempt} failed with recoverable error: ${e.message}. Retrying...`);
                    launchAttempt++;
                    await new Promise(r => setTimeout(r, 3000));
                } else {
                    throw e; // Non-recoverable error, fail immediately
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
