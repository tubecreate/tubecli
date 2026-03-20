import { chromium } from 'playwright';

(async () => {
    try {
        console.log("Launching browser with HTTPS proxy (Cổng 24949)...");
        const browser = await chromium.launch({
            headless: false,
            proxy: {
                server: 'http://69.12.25.5:24949', // Dùng cổng HTTPS
                username: 'SzAFy3Vn',
                password: 'JylZMBuVPqsi'
            }
        });
        const context = await browser.newContext();
        const page = await context.newPage();
        
        console.log("Navigating to IP checking site...");
        await page.goto('https://api.ipify.org', { timeout: 40000 });
        
        const ip = await page.innerText('body');
        console.log("Detected IP:", ip);
        
        console.log("Browser is open. Close the window when done.");
        await new Promise(resolve => browser.on('disconnected', resolve));
        
    } catch (e) {
        console.error("Failed connect via HTTPS Proxy:", e.message);
    }
})();
