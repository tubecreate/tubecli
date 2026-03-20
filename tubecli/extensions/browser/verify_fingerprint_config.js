
import { BrowserManager } from './browser_manager.js';
import fs from 'fs-extra';
import path from 'path';

async function test() {
    console.log("Starting Fingerprint Config Verification...");
    
    const profileName = "test_config_debug";
    const profilePath = path.resolve('./browser-laucher/profiles', profileName);
    const manager = new BrowserManager({ baseDir: './browser-laucher/profiles' });

    // Cleanup
    await fs.remove(profilePath);
    await fs.ensureDir(profilePath);

    // 1. Create Config with Android + Firefox
    const config = {
        tags: ['Android', 'Firefox']
    };
    await fs.writeJson(path.join(profilePath, 'config.json'), config);
    console.log(`Created profile ${profileName} with tags:`, config.tags);

    // 2. Fetch Fingerprint
    console.log("Fetching fingerprint...");
    try {
        const fp = await manager.getFingerprint(profileName);
        console.log("Fingerprint UA:", fp.navigator.userAgent);
        console.log("Fingerprint Platform:", fp.navigator.platform);

        // 3. Verify
        let isAndroid = fp.navigator.platform.toLowerCase().includes('android') || fp.navigator.userAgent.includes('Android');
        let isFirefox = fp.navigator.userAgent.includes('Firefox');
        
        console.log(`Check: isAndroid=${isAndroid}, isFirefox=${isFirefox}`);
        
        if (isAndroid && isFirefox) {
             const msg = "✅ SUCCESS: Got Android Firefox fingerprint.";
             console.log(msg);
             await fs.writeFile('verification_result.txt', msg);
        } else {
             const msg = `❌ FAILURE: Fingerprint does not match config. isAndroid=${isAndroid}, isFirefox=${isFirefox}, UA=${fp.navigator.userAgent}`;
             console.log(msg);
             await fs.writeFile('verification_result.txt', msg);
        }

    } catch (e) {
        console.error("Error:", e);
    }
}

test();
