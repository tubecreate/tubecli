import { chromium } from 'playwright';
import { analyzeScreen } from './vision_engine.js';

(async () => {
  console.log('Launching browser for Vision Test...');
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    console.log('Navigating to Google...');
    await page.goto('https://www.google.com');
    await page.waitForTimeout(2000);

    console.log('Running Visual Analysis...');
    const result = await analyzeScreen(page, "What website is this? What visible actions can I take here?");
    
    console.log('\n--- AI RESPONSE ---');
    console.log(result);
    console.log('-------------------\n');

  } catch (e) {
    console.error('Test failed:', e);
  } finally {
    console.log('Closing browser...');
    await browser.close();
  }
})();
