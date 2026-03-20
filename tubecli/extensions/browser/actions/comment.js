import { generateContextAwareComment } from '../vision_engine.js';
import { humanMove } from './mouse_helper.js';

/**
 * Action: Post a comment on a YouTube video using Visual AI.
 * @param {import('playwright').Page} page
 * @param {object} params
 */
export async function comment(page, params = {}) {
  console.log('Initiating Comment Action (Visual AI)...');

  try {
    // 1. Ensure we are on a YouTube video page
    if (!page.url().includes('youtube.com/watch')) {
      console.warn('Comment action skipped: Not a YouTube video page.');
      // If we are on a search page, we might have clicked a result but not waited enough.
      return;
    }

    // 1.5 Check if logged in (YouTube requires login to comment)
    // We check for the avatar button which indicates a logged-in state.
    try {
        await page.waitForSelector('button#avatar-btn', { timeout: 5000 });
    } catch (e) {
        console.error('Comment action failed: Not logged in (Avatar not found).');
        throw new Error('NOT_LOGGED_IN_ON_YOUTUBE');
    }

    // 2. Scroll to comment section
    // YouTube comments are lazily loaded. We need to scroll down.
    console.log('Scrolling to comments...');
    await page.evaluate(() => window.scrollBy(0, 500));
    await page.waitForTimeout(1500 + Math.random() * 1000);
    
    // 3. Scrape Metadata (Title) for context
    console.log('Scraping video metadata...');
    const metadata = await page.evaluate(() => {
      // 1. Try YouTube Title Element
      const titleEl = document.querySelector('#title h1 yt-formatted-string') 
                   || document.querySelector('#title h1');
      if (titleEl && titleEl.innerText.trim()) return { title: titleEl.innerText.trim() };

      // 2. Try Meta Tags
      const metaTitle = document.querySelector('meta[name="title"]');
      if (metaTitle && metaTitle.content) return { title: metaTitle.content };

      const ogTitle = document.querySelector('meta[property="og:title"]');
      if (ogTitle && ogTitle.content) return { title: ogTitle.content };

      // 3. Fallback to Document Title
      let docTitle = document.title;
      docTitle = docTitle.replace(/^\(\d+\)\s*/, ''); // Remove notification count (1)
      docTitle = docTitle.replace(/\s*-\s*YouTube$/, ''); // Remove suffix
      
      return { 
        title: docTitle || 'Video thú vị'
      };
    });
    console.log(`Video Title: "${metadata.title}"`);

    // 4. Generate Comment via Visual AI
    console.log('Generating comment using Visual AI...');
    console.log('Ignoring params.instruction as requested. Relying on Title + Vision only.');
    // Pass "" as instruction to force AI to rely only on Title/Vision
    const aiModel = params.aiModel || "qwen:latest";
    let commentText = await generateContextAwareComment(page, metadata.title, "", aiModel);
    
    if (!commentText) {
       commentText = "Video rất hay, cảm ơn bạn đã chia sẻ!";
    }

    // 5. Post the comment
    console.log(`Posting comment: "${commentText}"`);

    // Click the placeholder to activate the input
    const placeholderSelector = '#simple-box #placeholder-area';
    const inputSelector = '#contenteditable-root';
    const submitSelector = '#submit-button';

    const placeholder = page.locator(placeholderSelector).first();
    if (await placeholder.isVisible()) {
        await placeholder.click();
        await page.waitForTimeout(500 + Math.random() * 500);
    } else {
        console.warn('Comment placeholder not found, trying generic input...');
    }

    // Type the comment human-like
    const inputField = page.locator(inputSelector).first();
    await inputField.click();
    
    for (const char of commentText) {
        await page.keyboard.type(char, { delay: 50 + Math.random() * 30 });
    }
    await page.waitForTimeout(1000 + Math.random() * 1000);

    // Click submit
    const submitBtn = page.locator(submitSelector).first();
    await submitBtn.click();
    console.log('Comment submitted.');

    await page.waitForTimeout(2000); // Wait for post

  } catch (err) {
    console.error(`Comment action failed: ${err.message}`);
    throw err;
  }
}
