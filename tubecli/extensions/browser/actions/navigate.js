
/**
 * Generic Navigation Action
 * @param {import('playwright').Page} page 
 * @param {object} params { url }
 */
export async function navigate(page, params) {
  const { url } = params;
  if (!url) throw new Error('Navigate action: URL is required');
  
  console.log(`[NAVIGATE] Going to: ${url}...`);
  
  // Basic URL cleanup
  let targetUrl = url.trim();
  
  // Detect if this is a "search query" disguised as a URL (e.g. "grok tạo ảnh")
  const isLikelySearch = targetUrl.includes(' ') || (!targetUrl.includes('.') && !targetUrl.includes('localhost'));
  
  if (isLikelySearch) {
      console.log(`[NAVIGATE] "${targetUrl}" looks like a search term. Redirecting to search...`);
      const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(targetUrl)}`;
      await page.goto(searchUrl, { waitUntil: 'domcontentloaded' });
      return;
  }

  if (!targetUrl.startsWith('http')) {
      targetUrl = `https://${targetUrl}`;
  }

  const MAX_RETRIES = 3;
  for (let i = 0; i < MAX_RETRIES; i++) {
      try {
        console.log(`[NAVIGATE] Attempt ${i + 1}/${MAX_RETRIES}: Going to ${targetUrl}...`);
        await page.goto(targetUrl, { waitUntil: 'load', timeout: 60000 });
        await page.waitForLoadState('networkidle').catch(() => console.log('[NAVIGATE] Network not idle, but continuing...'));
        break; // Success
      } catch (err) {
        console.error(`[NAVIGATE] Failed attempt ${i + 1}: ${err.message}`);
        
        if (i === MAX_RETRIES - 1) {
             // Final attempt failed, fallback to search
             console.log(`[NAVIGATE] All retry attempts failed. Falling back to search...`);
             const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(url)}`;
             await page.goto(searchUrl, { waitUntil: 'domcontentloaded' });
        } else {
             // Wait before retry
             console.log(`[NAVIGATE] Retrying in 5 seconds...`);
             await page.waitForTimeout(5000);
        }
      }
  }
  
  // Wait for a bit more to be sure
  await page.waitForTimeout(3000);
  
  console.log(`[NAVIGATE] Arrived at: ${page.url()}`);
}
