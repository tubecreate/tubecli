
import { BrowserManager } from './browser_manager.js';
import fs from 'fs-extra';
import path from 'path';

async function test() {
    const manager = new BrowserManager({ baseDir: './browser-laucher/profiles' });
    const profileName = "debug_keys_test";
    
    // Create Config
    const profilePath = path.resolve('./profiles', profileName);
    await fs.remove(profilePath);
    await fs.ensureDir(profilePath);
    await fs.writeJson(path.join(profilePath, 'config.json'), { tags: ['Android', 'Firefox'] });

    console.log("Fetching fingerprint...");
    try {
        const fp = await manager.getFingerprint(profileName);
        console.log("Fingerprint Keys:", Object.keys(fp));
        if (fp.navigator) {
             console.log("Navigator Keys:", Object.keys(fp.navigator));
             console.log("UA:", fp.navigator.userAgent);
        } else {
             console.log("NO NAVIGATOR OBJECT FOUND!");
        }
    } catch (e) {
        console.error("Error:", e);
    }
}

test();
