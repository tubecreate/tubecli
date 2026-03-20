
/**
 * Generic Typing Action
 * @param {import('playwright').Page} page 
 * @param {object} params { text, selector }
 */
export async function type(page, params) {
  const { text, selector } = params;
  if (!text) throw new Error('Type action: text is required');

  let target = null;

  if (selector) {
    console.log(`[TYPE] Targeting explicit selector: ${selector}...`);
    target = page.locator(selector).first();
    // Verify visibility with a short timeout
    const isReady = await target.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isReady) {
        console.warn(`[TYPE] Selector "${selector}" not found or hidden. Falling back to smart discovery...`);
        target = null;
    }
  }

  if (!target) {
    console.log(`[TYPE] Discovering primary input field...`);
    const smartSelectors = [
        'textarea[placeholder*="Ask"]', 'textarea[placeholder*="message"]', 'textarea[placeholder*="Grok"]',
        'input[type="text"][placeholder*="Search"]', '[role="textbox"]', 'textarea', 'input[type="text"]'
    ];
    
    for (const sel of smartSelectors) {
        const candidate = page.locator(sel).first();
        if (await candidate.isVisible().catch(() => false)) {
            console.log(`[TYPE] Found candidate: ${sel}`);
            target = candidate;
            break;
        }
    }
  }

  if (target) {
    await target.click().catch(() => {});
    await target.fill(''); // Clear
    await target.type(text, { delay: 50 });
    console.log(`[TYPE] Finished typing into detected field.`);
  } else {
    console.log(`[TYPE] No specific input found. Typing globally...`);
    await page.keyboard.type(text, { delay: 50 });
  }
  
  // Default to pressing Enter for prompt-like requests
  if (text.length > 5) {
      console.log(`[TYPE] Auto-pressing Enter...`);
      await page.keyboard.press('Enter');
  }
}
