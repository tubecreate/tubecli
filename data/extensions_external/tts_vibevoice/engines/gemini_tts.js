const minimist = require('minimist');
const fs = require('fs');
const path = require('path');
const { plugin } = require('playwright-with-fingerprints');

const args = minimist(process.argv.slice(2));
const profileName = args.profile || args.p;
const textFile = args['text-file'];
const voiceName = args.voice || 'Aoede';
const outputPath = args.output;
const profilesDir = args['profiles-dir'] || path.join(__dirname, '..', '..', '..', '..', 'data', 'browser_profiles');
const headless = args.headless === true || args.headless === 'true';

if (!profileName || !textFile || !outputPath) {
    console.error(JSON.stringify({ status: 'error', message: 'Required: --profile, --text-file, --output' }));
    process.exit(1);
}

let text = '';
try {
    text = fs.readFileSync(textFile, 'utf-8');
} catch (e) {
    console.error(JSON.stringify({ status: 'error', message: 'Could not read text-file' }));
    process.exit(1);
}

const profileDir = path.join(profilesDir, profileName);

// Configure antidetect browser engine path
const browserExtDir = path.join(__dirname, '..', '..', '..', '..', 'tubecli', 'extensions', 'browser');
plugin.setWorkingFolder(path.join(browserExtDir, 'data'));

function log(msg) {
    console.error(`[Gemini TTS] ${msg}`);
}

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

const { chromium } = require('playwright');
// ...
(async () => {
    let browser;
    try {
        log(`Launching standard browser with profile: ${profileName} (headless: ${headless})`);
        
        // --- Kill any existing Chrome process using this profile ---
        try {
            const { execSync } = require('child_process');
            const profileDirNorm = profileDir.replace(/\\/g, '\\\\');
            // Find Chrome PIDs using this specific user-data-dir
            const wmicOut = execSync(
                `wmic process where "name='chrome.exe' and CommandLine like '%${profileDirNorm}%'" get ProcessId /format:list`,
                { encoding: 'utf-8', timeout: 5000 }
            ).trim();
            const pids = wmicOut.match(/ProcessId=(\d+)/g);
            if (pids && pids.length > 0) {
                log(`Found ${pids.length} existing Chrome processes for profile ${profileName}, killing...`);
                for (const pidStr of pids) {
                    const pid = pidStr.split('=')[1];
                    try {
                        execSync(`taskkill /F /PID ${pid}`, { timeout: 5000 });
                        log(`Killed Chrome PID ${pid}`);
                    } catch (e) { /* already dead */ }
                }
                // Wait for processes to fully exit
                await sleep(2000);
            }
        } catch (e) {
            log(`Chrome cleanup check: ${e.message}`);
        }

        // --- Clean up stale Chrome profile lock files ---
        const lockFiles = [
            path.join(profileDir, 'SingletonLock'),
            path.join(profileDir, 'SingletonSocket'),
            path.join(profileDir, 'SingletonCookie'),
            path.join(profileDir, 'Default', 'LOCK'),
        ];
        for (const lf of lockFiles) {
            try {
                if (fs.existsSync(lf)) {
                    fs.unlinkSync(lf);
                    log(`Removed stale lock: ${path.basename(lf)}`);
                }
            } catch (e) {
                log(`Could not remove lock ${path.basename(lf)}: ${e.message}`);
            }
        }
        
        const context = await chromium.launchPersistentContext(profileDir, {
            channel: 'chrome',
            headless: headless,
            args: ['--no-sandbox', '--test-type', '--disable-blink-features=AutomationControlled', '--window-size=1280,800'],
            ignoreDefaultArgs: ['--enable-automation'],
            viewport: { width: 1280, height: 800 }
        });
        
        browser = context;
        const page = context.pages()[0] || await context.newPage();
        
        // Navigate to AI Studio Generate Speech
        log('Navigating to AI Studio Generate Speech...');
        await page.goto('https://aistudio.google.com/generate-speech?model=gemini-2.5-flash-preview-tts', { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(e => log('Goto error: ' + e.message));
        
        // Wait for page to load completely so tokens can be fetched
        await sleep(5000);
        
        // Check if we are logged in (if it redirected to accounts.google.com)
        if (page.url().includes('accounts.google.com') || page.url().includes('signin')) {
            log('Not logged into Google. Attempting auto-login...');
            
            // Read credentials from profile config.json
            const configPath = path.join(profileDir, 'config.json');
            let googleCreds = null;
            try {
                const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
                googleCreds = config.google_account;
            } catch (e) {
                log('Could not read config.json: ' + e.message);
            }
            
            if (googleCreds && googleCreds.email && googleCreds.password) {
                log(`Auto-login with account: ${googleCreds.email}`);
                
                try {
                    // Use the shared login module from browser extension (same as open.js)
                    const loginModule = await import(
                        'file:///' + path.join(browserExtDir, 'actions', 'login.js').replace(/\\/g, '/')
                    );
                    await loginModule.login(page, {
                        email: googleCreds.email,
                        password: googleCreds.password,
                        recoveryEmail: googleCreds.recoveryEmail || '',
                        twoFactorCodes: googleCreds.twoFactorCodes || '',
                        platform: 'google'
                    });
                    log('Login completed via shared login module.');
                } catch (loginErr) {
                    log('Auto-login error: ' + loginErr.message);
                }
                
                // Wait for login to complete (redirect away from accounts.google.com)
                let loginWaitAttempts = 0;
                while (page.url().includes('accounts.google.com') || page.url().includes('signin')) {
                    await sleep(2000);
                    loginWaitAttempts++;
                    if (loginWaitAttempts > 30) {
                        log('Auto-login may have stalled. Waiting for manual intervention...');
                        break;
                    }
                }
            } else {
                log('No Google credentials found in profile config. Waiting for manual login...');
                let loginWaitAttempts = 0;
                while (page.url().includes('accounts.google.com') || page.url().includes('signin')) {
                    await sleep(2000);
                    loginWaitAttempts++;
                    if (loginWaitAttempts > 150) {
                        throw new Error('Timeout waiting for manual login (5 minutes).');
                    }
                }
            }
            
            // Ensure we land on the right page after login
            log('Login complete! Ensuring we are on the right page...');
            if (!page.url().includes('generate-speech')) {
                await page.goto('https://aistudio.google.com/generate-speech?model=gemini-2.5-flash-preview-tts', { waitUntil: 'domcontentloaded', timeout: 60000 });
            }
            await sleep(3000);
        }

        // ═══ Step 1: Open the editor by clicking the text-input-container button ═══
        log('Opening text editor...');
        await sleep(2000); // Extra wait for page to fully render
        
        try {
            const btn = page.locator('button.text-input-container').first();
            if (await btn.count() > 0) {
                await btn.evaluate(node => node.click());
                log('Clicked text-input-container button.');
            } else {
                log('text-input-container button not found, trying placeholder text...');
                const el = page.getByText(/sounding speech/i).first();
                if (await el.count() > 0) {
                    await el.evaluate(node => node.click());
                }
            }
        } catch (e) {
            log('Error clicking text button: ' + e.message);
        }
        
        await sleep(2000);
        
        // ═══ Step 2: Switch to "Text" mode (away from Composer) ═══
        log('Switching to Text mode...');
        try {
            const textToggle = page.locator('span.toggle-label').filter({ hasText: 'Text' }).first();
            if (await textToggle.count() > 0) {
                await textToggle.evaluate(node => node.click());
                log('Clicked Text toggle.');
                await sleep(2000);
            } else {
                log('Text toggle not found - may already be in Text mode.');
            }
        } catch (e) {
            log('Error clicking Text toggle: ' + e.message);
        }
        
        // ═══ Step 3: Find and focus the CORRECT text area (the one under "Text" label) ═══
        log('Looking for text input area...');
        
        // The page has: Scene (1st box), Sample Context (2nd box), Text (last box = the actual speech input)
        // We must find the text area associated with the "Text" label, not Scene or Sample Context.
        let textArea = null;
        
        // Strategy 1: Find the element AFTER the label "Text" using XPath
        try {
            // Look for a div or textarea that comes after a label/heading containing only "Text"
            const textLabel = page.locator('label, .label, p, span, div').filter({ hasText: /^Text$/ }).first();
            if (await textLabel.count() > 0) {
                // Get the next sibling or nearby contenteditable
                const nearbyEditor = page.locator('div[contenteditable="true"], textarea').filter({ 
                    hasNot: page.locator('[placeholder*="bustling"], [placeholder*="Previous speaker"]') 
                }).last();
                if (await nearbyEditor.count() > 0) {
                    textArea = nearbyEditor;
                    log('Found text area via label strategy.');
                }
            }
        } catch (e) {}
        
        // Strategy 2: Use .last() contenteditable - the Text field is the last one on the page
        if (!textArea) {
            const allEditors = page.locator('div[contenteditable="true"]');
            const count = await allEditors.count();
            if (count > 0) {
                textArea = allEditors.nth(count - 1); // Use the LAST one
                log(`Found ${count} contenteditable divs, using the last one.`);
            }
        }
        
        // Strategy 3: Find textarea
        if (!textArea) {
            const ta = page.locator('textarea').last();
            if (await ta.count() > 0) {
                textArea = ta;
                log('Found textarea element (last).');
            }
        }
        
        if (textArea) {
            // Focus the element properly using Playwright's click (with force to bypass visibility)
            try {
                await textArea.click({ force: true, timeout: 5000 });
            } catch (e) {
                await textArea.evaluate(node => node.focus());
            }
            await sleep(500);
            
            // Clear existing content
            await page.keyboard.down('Control');
            await page.keyboard.press('a');
            await page.keyboard.up('Control');
            await page.keyboard.press('Backspace');
            await sleep(300);
            
            // Type text character by character with small delay to trigger Angular input events
            log('Typing text into editor...');
            await page.keyboard.type(text, { delay: 5 });
            
            log('Text typed successfully.');
        } else {
            log('WARNING: No text area found! Trying keyboard.insertText as fallback...');
            await page.keyboard.insertText(text);
        }
        
        // Wait for internal state to sync
        log('Waiting for text to sync...');
        await sleep(2000);
        
        // Dispatch input event on the text area to make sure Angular picks it up
        if (textArea) {
            try {
                await textArea.evaluate(node => {
                    node.dispatchEvent(new Event('input', { bubbles: true }));
                    node.dispatchEvent(new Event('change', { bubbles: true }));
                });
            } catch (e) {}
        }
        
        log(`Selecting voice: ${voiceName}`);
        try {
            // First, check if "Model settings" needs to be expanded
            const modelSettingsBtn = page.getByText('Model settings').first();
            if (await modelSettingsBtn.isVisible()) {
                // Check if it's already expanded by looking for a voice name or a dropdown
                const isExpanded = await page.getByRole('combobox').isVisible() || await page.getByText('Aoede').isVisible();
                if (!isExpanded) {
                    await modelSettingsBtn.click();
                    await sleep(1000);
                }
            }
            
            // Look for the voice dropdown (usually it shows the current voice name like "Aoede" or "Puck")
            const voiceNames = ['Aoede', 'Charon', 'Fenrir', 'Kore', 'Puck', 'Achernar'];
            let foundVoiceSelector = false;
            
            for (const v of voiceNames) {
                const btn = page.locator(`div[role="combobox"]:has-text("${v}"), button:has-text("${v}"), div[role="button"]:has-text("${v}")`).first();
                if (await btn.isVisible({ timeout: 1000 }).catch(() => false)) {
                    await btn.click();
                    foundVoiceSelector = true;
                    await sleep(1000);
                    break;
                }
            }
            
            if (foundVoiceSelector) {
                // Click the target voice
                const targetVoiceBtn = page.getByRole('option', { name: voiceName, exact: false }).first();
                if (await targetVoiceBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
                    await targetVoiceBtn.click();
                } else {
                    const fallbackBtn = page.getByText(voiceName).last(); 
                    if (await fallbackBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
                        await fallbackBtn.click();
                    }
                    await page.keyboard.press('Escape');
                }
                await sleep(500);
            } else {
                log('Voice selector not found, using default voice.');
            }
        } catch (e) {
            log('Error selecting voice: ' + e.message);
        }
        
        log('Waiting a bit before clicking Generate to simulate human behavior...');
        await sleep(3000);
        
        log('Clicking Generate button...');
        // The Run button might be a blue button at the bottom right.
        const generateBtn = page.getByRole('button', { name: 'Run' }).first();
        if (await generateBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
            await generateBtn.click();
        } else {
            const fallbackGen = page.locator('button:has-text("Run"), button:has-text("Generate")').first();
            if (await fallbackGen.isVisible().catch(() => false)) {
                await fallbackGen.click();
            } else {
                log('Run button not found, pressing Ctrl+Enter');
                await page.keyboard.down('Control');
                await page.keyboard.press('Enter');
                await page.keyboard.up('Control');
            }
        }
        // ═══ Set up network interception for audio BEFORE generation starts ═══
        let interceptedAudioUrl = null;
        page.on('response', async (response) => {
            const url = response.url();
            const ct = response.headers()['content-type'] || '';
            if (ct.startsWith('audio/') || url.includes('.wav') || url.includes('.mp3') || url.includes('.ogg')) {
                const size = parseInt(response.headers()['content-length'] || '0');
                if (size > 5000 || size === 0) {
                    interceptedAudioUrl = url;
                    log('*** INTERCEPTED AUDIO URL: ' + url.substring(0, 120));
                }
            }
        });

        // Wait for audio to generate.
        log('Waiting for generation to complete...');
        
        let attempts = 0;
        let audioSaved = false;
        
        while (attempts < 90) { // Max 3 minutes
            await sleep(2000);
            
            // Strategy 0: Network intercepted audio URL (most reliable)
            if (interceptedAudioUrl && !audioSaved) {
                try {
                    log('Strategy 0: Downloading from intercepted audio URL...');
                    const audioBuffer = await page.evaluate(async (url) => {
                        const resp = await fetch(url);
                        const buf = await resp.arrayBuffer();
                        return Array.from(new Uint8Array(buf));
                    }, interceptedAudioUrl);
                    if (audioBuffer && audioBuffer.length > 1000) {
                        fs.writeFileSync(outputPath, Buffer.from(audioBuffer));
                        log(`Strategy 0: Audio saved from network intercept (${audioBuffer.length} bytes)`);
                        audioSaved = true;
                        break;
                    }
                } catch (e) {
                    log('Strategy 0 failed: ' + e.message);
                }
            }
            
            // Strategy 1: Check if there is an audio element with a src
            try {
                const audioSrc = await page.evaluate(() => {
                    const audio = document.querySelector('audio[src]') || document.querySelector('audio');
                    if (audio && audio.src && !audio.src.startsWith('data:') && audio.src !== window.location.href) {
                        return audio.src;
                    }
                    return null;
                });
                
                if (audioSrc && (audioSrc.startsWith('blob:') || audioSrc.includes('.mp3') || audioSrc.includes('.wav') || audioSrc.includes('.ogg'))) {
                    log(`Found audio src: ${audioSrc.substring(0, 80)}...`);
                    
                    // Download the blob or URL directly via page evaluate
                    const audioBuffer = await page.evaluate(async (src) => {
                        const resp = await fetch(src);
                        const buf = await resp.arrayBuffer();
                        return Array.from(new Uint8Array(buf));
                    }, audioSrc);
                    
                    if (audioBuffer && audioBuffer.length > 1000) {
                        fs.writeFileSync(outputPath, Buffer.from(audioBuffer));
                        log(`Audio saved directly from blob (${audioBuffer.length} bytes) to ${outputPath}`);
                        audioSaved = true;
                        break;
                    }
                }
            } catch (e) {
                // Not ready yet, continue
            }
            
            // Strategy 2: Find Google AI Studio's download button (.download-button or aria-label="Download")
            try {
                // Use the exact class name from AI Studio's Angular Material UI
                let downloadBtn = page.locator('button.download-button').first();
                
                if (!(await downloadBtn.isVisible({ timeout: 500 }).catch(() => false))) {
                    downloadBtn = page.locator('button[aria-label="Download"]').first();
                }
                if (!(await downloadBtn.isVisible({ timeout: 500 }).catch(() => false))) {
                    downloadBtn = page.getByRole('button', { name: /download/i }).first();
                }
                if (!(await downloadBtn.isVisible({ timeout: 500 }).catch(() => false))) {
                    downloadBtn = page.locator('[aria-label*="ownload" i], [title*="ownload" i]').first();
                }
                
                if (await downloadBtn.isVisible({ timeout: 500 }).catch(() => false) && !(await downloadBtn.isDisabled().catch(() => true))) {
                    log('Download button found and enabled. Clicking...');
                    
                    // Reset intercepted URL to capture the download response
                    interceptedAudioUrl = null;
                    
                    // Listen for download event JUST before clicking
                    const [download] = await Promise.all([
                        page.waitForEvent('download', { timeout: 15000 }).catch(() => null),
                        downloadBtn.evaluate(b => b.click()).catch(async () => downloadBtn.click())
                    ]);
                    
                    if (download) {
                        log(`Saving download to ${outputPath}...`);
                        await download.saveAs(outputPath);
                        audioSaved = true;
                        break;
                    }
                    
                    // Fallback A: Check if clicking triggered a network audio response  
                    await sleep(3000);
                    if (interceptedAudioUrl) {
                        log('Download click triggered network audio response, fetching...');
                        try {
                            const audioBuffer = await page.evaluate(async (url) => {
                                const resp = await fetch(url);
                                const buf = await resp.arrayBuffer();
                                return Array.from(new Uint8Array(buf));
                            }, interceptedAudioUrl);
                            if (audioBuffer && audioBuffer.length > 1000) {
                                fs.writeFileSync(outputPath, Buffer.from(audioBuffer));
                                log(`Audio saved from post-click network intercept (${audioBuffer.length} bytes)`);
                                audioSaved = true;
                                break;
                            }
                        } catch (e) {}
                    }
                    
                    // Fallback B: Try to read the audio element that appeared after clicking
                    const audioSrcAfter = await page.evaluate(() => {
                        const audio = document.querySelector('audio[src]');
                        return audio ? audio.src : null;
                    });
                    if (audioSrcAfter && audioSrcAfter.startsWith('blob:')) {
                        const audioBuffer = await page.evaluate(async (src) => {
                            const resp = await fetch(src);
                            const buf = await resp.arrayBuffer();
                            return Array.from(new Uint8Array(buf));
                        }, audioSrcAfter);
                        if (audioBuffer && audioBuffer.length > 1000) {
                            fs.writeFileSync(outputPath, Buffer.from(audioBuffer));
                            log(`Audio saved from blob after download click (${audioBuffer.length} bytes)`);
                            audioSaved = true;
                            break;
                        }
                    }
                    
                    // Fallback C: Check if a file was downloaded to the default downloads folder
                    await sleep(2000);
                }
            } catch (e) {
                // Continue looking
            }
            
            attempts++;
        }
        
        if (!audioSaved) {
            throw new Error('Timeout: Could not capture audio after generation (tried blob extraction and download event).');
        }
        
        log('File saved. Waiting 2 seconds before closing...');
        await sleep(2000);
        
        console.log(JSON.stringify({ status: 'success', output: outputPath }));
        
        // Close
        await browser.close();
        process.exit(0);

    } catch (error) {
        console.error(JSON.stringify({ status: 'error', message: error.message }));
        if (browser) {
            try { await browser.close(); } catch (e) {}
        }
        process.exit(1);
    }
})();
