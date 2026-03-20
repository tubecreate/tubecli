import { analyzeScreen } from '../vision_engine.js';

/**
 * Action: Perform a visual scan of the page using AI.
 * @param {import('playwright').Page} page
 */
export async function visual_scan(page) {
  console.log('Initiating Visual AI Scan...');
  
  const prompt = `You are an automation assistant. Analyze this webpage screenshot.
1. Describe the main layout (e.g., "News homepage", "Video player").
2. SUMMARIZE the main visible content (e.g., read the main headlines, article titles, or key text).
3. List 3 specific actions a user could take next.
Format the output as a structured list.`;

  const analysis = await analyzeScreen(page, prompt);
  
  if (analysis) {
    console.log('\n>>> VISUAL AI ANALYSIS <<<');
    console.log(analysis);
    console.log('>>> END ANALYSIS <<<\n');
  } else {
    console.warn('Visual Scan returned no results.');
  }
}
