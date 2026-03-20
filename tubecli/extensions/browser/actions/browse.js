import { humanMove } from './mouse_helper.js';

/**
 * Action: Simulate natural browsing behavior (scrolling and mouse movements).
 * @param {import('playwright').Page} page
 * @param {object} params
 * @param {number} [params.iterations=5] - Number of browsing cycles.
 */
export async function browse(page, params = {}) {
  const iterations = params.iterations || 5;
  console.log(`Simulating natural browsing (${iterations} iterations)...`);

  for (let i = 0; i < iterations; i++) {
    if (page.isClosed()) {
      console.warn('Page was closed, stopping browse action.');
      return;
    }

    try {
      // Random human-like move
      const x = Math.floor(Math.random() * 800) + 100;
      const y = Math.floor(Math.random() * 600) + 100;
      await humanMove(page, x, y);

      // Random scroll (weighted for downward reading)
      const isUp = Math.random() < 0.15; // 15% chance to scroll back up slightly
      const scrollAmount = isUp 
        ? -Math.floor(Math.random() * 200) 
        : Math.floor(Math.random() * 500) + 200;
        
      await page.mouse.wheel(0, scrollAmount);
      console.log(`${isUp ? 'Scrolled up' : 'Scrolled down'} ${Math.abs(scrollAmount)}px`);

      // Natural reading pause (longer occasional pauses)
      const isLongPause = Math.random() < 0.2;
      const pauseDuration = isLongPause 
        ? 5000 + Math.random() * 5000  // 5-10s "deep reading"
        : 1000 + Math.random() * 2000; // 1-3s "skimming"
        
      if (isLongPause) console.log('Taking a moment to read...');
      await page.waitForTimeout(pauseDuration);
    } catch (e) {
      if (e.message.includes('Target page, context or browser has been closed')) {
        console.warn('Browser closed during browse loop.');
        return;
      }
      throw e;
    }
  }
}
