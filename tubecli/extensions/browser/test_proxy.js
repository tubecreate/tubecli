import { chromium } from 'playwright';

(async () => {
    try {
        console.log(`Launching browser with proxy: http://ipv6-ti-or04:1260`);
        const browser = await chromium.launch({
            headless: false,
            proxy: {
                server: 'http://ipv6-ti-or04:1260',
                username: 'SzAFy3Vn',
                password: 'JylZMBuVPqsi'
            }
        });
        const context = await browser.newContext();
        const page = await context.newPage();
        
        console.log("Navigating to IP checking site (api.ipify.org)...");
        try {
            await page.goto('https://api.ipify.org', { timeout: 60000, waitUntil: 'domcontentloaded' });
            const ip = await page.innerText('body');
            console.log("Successfully connected! Detected IP:", ip);
        } catch (gotoError) {
            console.error("Navigation failed:", gotoError.message);
        }
        
        console.log("Browser window is open. You can check it. Script will wait for manual close.");
        await new Promise(resolve => browser.on('disconnected', resolve));
        
    } catch (e) {
        console.error("Failed to launch or connect:", e.message);
    }
})();
