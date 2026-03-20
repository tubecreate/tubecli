import { chromium } from 'playwright';
import { diagnoseAndSuggest } from './vision_engine.js';
import * as clickAction from './actions/click.js';
import * as searchAction from './actions/search.js';

// Mock Registry
const ACTION_REGISTRY = {
  click: clickAction.click,
  search: searchAction.search
};

(async () => {
  console.log('Launching browser for Self-Healing Test...');
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    console.log('Navigating to Google...');
    await page.goto('https://www.google.com');
    await page.waitForTimeout(2000);

    // INTENTIONAL FAILURE
    const badStep = {
      action: 'click',
      params: { selector: '#this_selector_does_not_exist' } // This will fail
    };

    console.log(`\n--- Executing Broken Action: ${badStep.action} with ${badStep.params.selector} ---`);
    
    try {
      await clickAction.click(page, badStep.params);
    } catch (actionError) {
      console.error(`\n[EXPECTED ERROR] Action failed: ${actionError.message}`);
      
      // --- SELF-HEALING SIMULATION ---
      console.log('Triggering Visual Error Diagnosis...');
      
      // We instruct AI that our GOAL was to "Click the Google Search Text Input"
      // but we "accidentally" used the wrong selector.
      const goal = "Click the main Google Search text input area";
      const suggestion = await diagnoseAndSuggest(page, goal, actionError.message);
      
      if (suggestion) {
        console.log(`\n>>> AI SUGGESTION RECEIVED: ${JSON.stringify(suggestion)} <<<`);
        
        if (ACTION_REGISTRY[suggestion.action]) {
            console.log(`Executing Remedial Action: ${suggestion.action}`);
            await ACTION_REGISTRY[suggestion.action](page, suggestion.params);
            console.log('>>> Remedial Action Executed Successfully. <<<');
        } else {
            console.warn(`Suggested action '${suggestion.action}' not in registry.`);
        }
      } else {
        console.error('Visual AI could not find a solution.');
      }
    }

  } catch (e) {
    console.error('Test Test failed:', e);
  } finally {
    console.log('Closing browser in 5s...');
    await page.waitForTimeout(5000);
    await browser.close();
  }
})();
