/**
 * Action to save images from the page
 * Ensure we capture the final HIGH-RESOLUTION version, not the blurry preview.
 * @param {import('playwright').Page} page 
 * @param {object} params { selector, index }
 * @returns {Promise<{path: string, url: string}>}
 */
export async function save_image(page, params = {}) {
  const { selector, index = 0 } = params;
  const url = page.url();
  
  console.log(`[SAVE_IMAGE] specific logic for: ${url}`);

  if (url.includes('chatgpt.com') || url.includes('openai.com')) {
      console.log('[SAVE_IMAGE] Detected ChatGPT. Waiting for generation to complete...');
      
      // 1. Wait for "Stop generating" button to DISAPPEAR (implies generation done)
      // Or wait for the "Send message" button to be enabled/visible again
      try {
          await page.waitForSelector('[data-testid="send-button"]', { state: 'visible', timeout: 60000 });
          // double check - sometimes it flickers. Wait for stability.
          await page.waitForTimeout(2000); 
      } catch (e) {
          console.log('[SAVE_IMAGE] Timeout waiting for send-button (generation might be stuck or very long). Proceeding anyway...');
      }

      // 2. Select the LAST generated image
      // ChatGPT images are usually in: div[role="img"] or img tags within the conversation
      // We look for large images.
      console.log('[SAVE_IMAGE] Searching for generated images...');
      
      const bestImg = await page.evaluate(() => {
          // Find all images in the conversation
          // ChatGPT specific: generated images often have specific classes or are inside specific containers.
          // Generic fallback: look for large images in the main chat area.
          const imgs = Array.from(document.querySelectorAll('img'));
          const candidates = imgs.map(img => ({
              src: img.src,
              width: img.naturalWidth,
              height: img.naturalHeight,
              area: img.naturalWidth * img.naturalHeight,
              y: img.getBoundingClientRect().top // Position on screen (lower is usually newer)
          })).filter(img => img.area > 100000 && img.width > 500); // Filter specifically for generated content size
          
          if (candidates.length === 0) return null;
          
          // Sort by Y position (descending) to get the latest one at the bottom
          candidates.sort((a, b) => b.y - a.y);
          return candidates[0]; // Returns the last (bottom-most) large image
      });

      if (bestImg) {
          console.log(`[SAVE_IMAGE] Found ChatGPT image: ${bestImg.width}x${bestImg.height} at Y=${bestImg.y}`);
          const imgElement = await page.$(`img[src="${bestImg.src}"]`);
          if (imgElement) {
              await imgElement.scrollIntoViewIfNeeded();
              const timestamp = new Date().getTime();
              const filename = `chatgpt_gen_${timestamp}.png`;
              const savePath = `./downloads/${filename}`;
              
              const fs = await import('fs-extra');
              await fs.ensureDir('./downloads');
              
              await imgElement.screenshot({ path: savePath });
              console.log(`[SAVE_IMAGE] Saved to: ${savePath}`);
              return { path: savePath };
          }
      }
      console.warn('[SAVE_IMAGE] No valid ChatGPT image found.');
      return null;
  }

  // FORCE wait if generic
  console.log('[SAVE_IMAGE] Waiting 10s for Generic rendering...');
  await page.waitForTimeout(10000);
  
  // 2. Poll for the largest image
  let bestImg = null;
  const startTime = Date.now();
  const timeout = 20000; 

  while (Date.now() - startTime < timeout) {
      bestImg = await page.evaluate(() => {
          const imgs = Array.from(document.querySelectorAll('img'));
          const candidates = imgs.map(img => ({
              src: img.src,
              width: img.naturalWidth,
              height: img.naturalHeight,
              area: img.naturalWidth * img.naturalHeight,
              complete: img.complete
          })).filter(img => img.area > 200000 && img.complete);
          
          if (candidates.length === 0) return null;
          candidates.sort((a, b) => b.area - a.area);
          return candidates[0];
      });

      if (bestImg) break;
      await page.waitForTimeout(2000);
  }

  if (bestImg) {
      console.log(`[SAVE_IMAGE] SUCCESS: High-res image detected (${bestImg.width}x${bestImg.height})`);
      const imgElement = await page.$(`img[src="${bestImg.src}"]`);
      if (imgElement) {
          const timestamp = new Date().getTime();
          const filename = `saved_image_${timestamp}.png`;
          const savePath = `./downloads/${filename}`;
          
          const fs = await import('fs-extra');
          await fs.ensureDir('./downloads');
          
          await imgElement.screenshot({ path: savePath });
          console.log(`[SAVE_IMAGE] Image saved to: ${savePath}`);
          return { path: savePath };
      }
  }

  console.warn('[SAVE_IMAGE] No high-res image found.');
  return null;
}
