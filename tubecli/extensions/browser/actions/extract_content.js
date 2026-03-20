import fs from 'fs-extra';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Dedicated folder for all scraped data
const SCRAPED_DATA_DIR = path.resolve(__dirname, '..', 'scraped_data');

// Service/commercial domains to SKIP — only scrape news/knowledge sites
const SKIP_DOMAINS = [
  'apple.com', 'microsoft.com', 'google.com', 'amazon.com', 'facebook.com',
  'instagram.com', 'twitter.com', 'x.com', 'linkedin.com', 'tiktok.com',
  'youtube.com', 'netflix.com', 'spotify.com', 'github.com', 'gitlab.com',
  'stackoverflow.com', 'reddit.com', 'discord.com', 'slack.com', 'zoom.us',
  'dropbox.com', 'adobe.com', 'salesforce.com', 'oracle.com', 'ibm.com',
  'samsung.com', 'sony.com', 'mozilla.org', 'wordpress.org', 'shopify.com',
  'paypal.com', 'stripe.com', 'cloudflare.com', 'aws.amazon.com',
  'accounts.google.com', 'mail.google.com', 'drive.google.com',
  'play.google.com', 'maps.google.com', 'translate.google.com',
  'pinterest.com', 'tumblr.com', 'twitch.tv', 'ebay.com', 'aliexpress.com',
  'notion.so', 'figma.com', 'canva.com', 'trello.com'
];

/**
 * Extract Content Action
 * Detects news/blog/article pages and extracts:
 * - Title, author, published date
 * - Full article body text
 * - Article images (downloaded locally)
 * Saves structured JSON to profile history.
 *
 * @param {import('playwright').Page} page
 * @param {object} params { profileName, minImageWidth, maxImages }
 * @returns {Promise<object|null>} Extracted article data or null
 */
export async function extract_content(page, params = {}) {
  const {
    profileName = 'default',
    minImageWidth = 200,
    maxImages = 10,
    enable_scraping = true,
    scraper_text_limit = 10000
  } = params;

  const currentUrl = page.url();
  console.log(`[EXTRACT_CONTENT] Starting extraction on: ${currentUrl}`);

  if (enable_scraping === false) {
      console.log(`[EXTRACT_CONTENT] ⛔ Web scraping is disabled for this agent. Skipping extraction.`);
      return null;
  }

  try {
    // ═══════════════════════════════════════════
    // 0.5. RAW TEXT EXTRACTION (Bypass article checks)
    // ═══════════════════════════════════════════
    if (params.type === 'text') {
      console.log(`[EXTRACT_CONTENT] 📄 Raw text extraction requested for: ${currentUrl}`);
      const textContent = await page.evaluate(() => {
        // Try to find the main content area, fallback to body
        const main = document.querySelector('main, [role="main"], #main, .main, article, .content');
        return (main || document.body).innerText;
      });
      
      const result = {
        title: await page.title(),
        url: currentUrl,
        content: textContent,
        scrapedAt: new Date().toISOString()
      };
      
      console.log(`[EXTRACT_CONTENT] Extracted ${result.content.length} chars of raw text.`);
      return result;
    }

    // ═══════════════════════════════════════════
    // 0. CHECK if domain is allowed (skip service/commercial sites)
    // ═══════════════════════════════════════════
    try {
      const urlObj = new URL(currentUrl);
      const hostname = urlObj.hostname.replace('www.', '');
      const isBlocked = SKIP_DOMAINS.some(d => hostname === d || hostname.endsWith('.' + d));
      if (isBlocked) {
        console.log(`[EXTRACT_CONTENT] ⛔ Skipping commercial/service domain: ${hostname}`);
        return null;
      }
    } catch (e) {
      // URL parse failed, continue anyway
    }
    // ═══════════════════════════════════════════
    // 1. DETECT if this is a content/article page
    // ═══════════════════════════════════════════
    const pageInfo = await page.evaluate(() => {
      const ogType = document.querySelector('meta[property="og:type"]')?.content || '';
      const hasArticleTag = document.querySelectorAll('article, [role="article"]').length > 0;
      const h1 = document.querySelector('h1');
      const paragraphs = document.querySelectorAll('article p, .post-content p, .entry-content p, .article-body p, main p, .content p');
      const hasEnoughText = paragraphs.length >= 3;

      return {
        isArticle: ogType === 'article' || hasArticleTag || (!!h1 && hasEnoughText),
        ogType,
        hasArticleTag,
        hasH1: !!h1,
        paragraphCount: paragraphs.length
      };
    });

    if (!pageInfo.isArticle) {
      console.log(`[EXTRACT_CONTENT] Page does not appear to be an article (ogType: "${pageInfo.ogType}", article tag: ${pageInfo.hasArticleTag}, h1: ${pageInfo.hasH1}, paragraphs: ${pageInfo.paragraphCount}). Skipping.`);
      return null;
    }

    console.log(`[EXTRACT_CONTENT] ✅ Article page detected! Extracting content...`);

    // ═══════════════════════════════════════════
    // 2. EXTRACT article metadata & content
    // ═══════════════════════════════════════════
    const articleData = await page.evaluate((opts) => {
      const { minImageWidth, textLimit } = opts;

      // --- Title ---
      const ogTitle = document.querySelector('meta[property="og:title"]')?.content;
      const h1 = document.querySelector('h1')?.innerText?.trim();
      const docTitle = document.title;
      const title = ogTitle || h1 || docTitle || 'Untitled';

      // --- Description ---
      const ogDesc = document.querySelector('meta[property="og:description"]')?.content;
      const metaDesc = document.querySelector('meta[name="description"]')?.content;
      const description = ogDesc || metaDesc || '';

      // --- Author ---
      const metaAuthor = document.querySelector('meta[name="author"]')?.content;
      const schemaAuthor = document.querySelector('[itemprop="author"]')?.innerText?.trim();
      const authorEl = document.querySelector('.author, .byline, [rel="author"], .post-author');
      const author = metaAuthor || schemaAuthor || authorEl?.innerText?.trim() || '';

      // --- Published Date ---
      const timeEl = document.querySelector('time[datetime]');
      const metaDate = document.querySelector('meta[property="article:published_time"]')?.content;
      const publishedDate = timeEl?.getAttribute('datetime') || metaDate || '';

      // --- Content (Body Text) ---
      // Try multiple common article container selectors, ordered by specificity
      const contentSelectors = [
        'article .post-content',
        'article .entry-content',
        'article .article-body',
        'article .article-content',
        '.post-content',
        '.entry-content',
        '.article-body',
        '.article-content',
        '.story-body',
        '.td-post-content',
        '.single-post-content',
        '[itemprop="articleBody"]',
        'article',
        'main article',
        'main .content',
        'main'
      ];

      let contentEl = null;
      for (const sel of contentSelectors) {
        const el = document.querySelector(sel);
        if (el && el.innerText.trim().length > 200) {
          contentEl = el;
          break;
        }
      }

      let content = '';
      if (contentEl) {
        // Extract paragraphs for cleaner text
        const paras = contentEl.querySelectorAll('p');
        if (paras.length > 0) {
          content = Array.from(paras)
            .map(p => p.innerText.trim())
            .filter(t => t.length > 20) // skip tiny fragments
            .join('\n\n');
        } else {
          content = contentEl.innerText.trim();
        }
      }

      // Limit content to configured limit to avoid excessive storage
      if (textLimit > 0 && content.length > textLimit) {
        content = content.substring(0, textLimit) + '\n\n[... truncated]';
      }

      // --- Images (only descriptive/content images, not logos/thumbnails) ---
      const imageContainer = contentEl || document.querySelector('article');
      if (!imageContainer) return { title, description, author, publishedDate, content, images: [] };
      
      const imgs = Array.from(imageContainer.querySelectorAll('img'));
      const images = imgs
        .map(img => {
          const rect = img.getBoundingClientRect();
          return {
            src: img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || '',
            alt: img.alt || '',
            width: img.naturalWidth || parseInt(img.getAttribute('width')) || rect.width || 0,
            height: img.naturalHeight || parseInt(img.getAttribute('height')) || rect.height || 0,
            // Check if image is inside article body (not header/sidebar/footer)
            isInBody: !!img.closest('.post-content, .entry-content, .article-body, .article-content, .story-body, [itemprop="articleBody"], article > div, article > section')
          };
        })
        .filter(img => {
          if (!img.src || img.src.startsWith('data:')) return false;
          // Must be large enough to be a descriptive image (min 400px wide)
          if (img.width > 0 && img.width < 400) return false;
          if (img.height > 0 && img.height < 200) return false;
          // Filter out logos, thumbnails, icons, avatars
          const lower = img.src.toLowerCase();
          const skipPatterns = [
            'logo', 'icon', 'avatar', 'emoji', 'badge', 'sprite',
            'tracking', 'pixel', 'spacer', 'blank', 'placeholder',
            'thumbnail', 'thumb', 'profile', 'author', 'gravatar',
            'share', 'social', 'button', 'arrow', 'chevron',
            'facebook', 'twitter', 'linkedin', 'pinterest', 'whatsapp',
            'banner', 'advert', 'sponsor', 'promo', 'popup',
            'favicon', 'loader', 'spinner', 'widget'
          ];
          if (skipPatterns.some(p => lower.includes(p))) return false;
          // Skip very common small image extensions in path
          if (lower.match(/\/(\d+x\d+)\//)) {
            const match = lower.match(/(\d+)x(\d+)/);
            if (match && parseInt(match[1]) < 400) return false;
          }
          return true;
        })
        .map(img => ({ url: img.src, alt: img.alt }));

      // --- Featured Image (og:image as backup) ---
      const ogImage = document.querySelector('meta[property="og:image"]')?.content;
      if (ogImage && !images.find(i => i.url === ogImage)) {
        images.unshift({ url: ogImage, alt: 'Featured image' });
      }

      return {
        title,
        description,
        author,
        publishedDate,
        content,
        images
      };
    }, { minImageWidth, textLimit: scraper_text_limit });

    if (!articleData.content || articleData.content.length < 100) {
      console.log(`[EXTRACT_CONTENT] Content too short (${articleData.content?.length || 0} chars). Skipping save.`);
      return null;
    }

    console.log(`[EXTRACT_CONTENT] Title: "${articleData.title}"`);
    console.log(`[EXTRACT_CONTENT] Author: "${articleData.author || 'Unknown'}"`);
    console.log(`[EXTRACT_CONTENT] Content: ${articleData.content.length} chars`);
    console.log(`[EXTRACT_CONTENT] Images found: ${articleData.images.length}`);

    // ═══════════════════════════════════════════
    // 3. DOWNLOAD article images locally
    // ═══════════════════════════════════════════
    const timestamp = Date.now();
    const profileDir = path.join(SCRAPED_DATA_DIR, profileName);
    const articleDir = path.join(profileDir, 'images', `${timestamp}`);
    await fs.ensureDir(articleDir);

    const downloadedImages = [];
    const imagesToDownload = articleData.images.slice(0, maxImages);

    for (let i = 0; i < imagesToDownload.length; i++) {
      const img = imagesToDownload[i];
      try {
        console.log(`[EXTRACT_CONTENT] Downloading image ${i + 1}/${imagesToDownload.length}: ${img.url.substring(0, 80)}...`);

        // Use page.evaluate + fetch to download via browser context (bypasses CORS)
        const imageBuffer = await page.evaluate(async (imgUrl) => {
          try {
            const resp = await fetch(imgUrl);
            if (!resp.ok) return null;
            const blob = await resp.blob();
            const arrayBuffer = await blob.arrayBuffer();
            return Array.from(new Uint8Array(arrayBuffer));
          } catch (e) {
            return null;
          }
        }, img.url);

        if (imageBuffer && imageBuffer.length > 0) {
          // Determine file extension from URL
          const urlPath = new URL(img.url).pathname;
          let ext = path.extname(urlPath).split('?')[0] || '.jpg';
          if (!['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.avif'].includes(ext.toLowerCase())) {
            ext = '.jpg';
          }

          const filename = `img_${i}${ext}`;
          const savePath = path.join(articleDir, filename);

          await fs.writeFile(savePath, Buffer.from(imageBuffer));
          downloadedImages.push({
            url: img.url,
            alt: img.alt,
            localPath: savePath
          });
          console.log(`[EXTRACT_CONTENT] ✅ Saved: ${filename} (${Math.round(imageBuffer.length / 1024)} KB)`);
        }
      } catch (e) {
        console.warn(`[EXTRACT_CONTENT] Failed to download image ${i}: ${e.message}`);
      }
    }

    // ═══════════════════════════════════════════
    // 4. BUILD final article object
    // ═══════════════════════════════════════════
    const result = {
      title: articleData.title,
      url: currentUrl,
      description: articleData.description,
      author: articleData.author,
      publishedDate: articleData.publishedDate,
      content: articleData.content,
      images: downloadedImages,
      imageCount: downloadedImages.length,
      scrapedAt: new Date().toISOString()
    };

    // ═══════════════════════════════════════════
    // 5. SAVE to profile's scraped_articles.json
    // ═══════════════════════════════════════════
    try {
      const articlesPath = path.join(SCRAPED_DATA_DIR, profileName, 'articles.json');
      await fs.ensureDir(path.dirname(articlesPath));

      let existingArticles = [];
      if (await fs.pathExists(articlesPath)) {
        try {
          existingArticles = await fs.readJson(articlesPath);
          if (!Array.isArray(existingArticles)) existingArticles = [];
        } catch (e) {
          existingArticles = [];
        }
      }

      // Avoid duplicates by URL
      let alreadyExists = false;
      alreadyExists = existingArticles.some(a => a.url === currentUrl);
      if (alreadyExists) {
        console.log(`[EXTRACT_CONTENT] Article already saved for this URL. Skipping duplicate.`);
      } else {
        existingArticles.push(result);

        // Keep max 100 articles per profile to prevent unbounded growth
        if (existingArticles.length > 100) {
          existingArticles = existingArticles.slice(-100);
        }

        await fs.writeJson(articlesPath, existingArticles, { spaces: 2 });
        console.log(`[EXTRACT_CONTENT] 💾 Saved to: ${articlesPath} (Total: ${existingArticles.length} articles)`);
      }
    } catch (e) {
      console.error(`[EXTRACT_CONTENT] Failed to save article JSON: ${e.message}`);
    }

    // ═══════════════════════════════════════════
    // 6. ALSO SAVE to profile history.json
    // ═══════════════════════════════════════════
    try {
      // Get IP
      let currentIp = 'Unknown';
      try {
        if (page) {
            // Evaluate in-page using https so it uses the browser's own network stack/proxy
            currentIp = await page.evaluate(async () => {
                try {
                    const res = await fetch('https://checkip.amazonaws.com', { signal: AbortSignal.timeout(8000) });
                    return res.ok ? (await res.text()).trim() : null;
                } catch (e) { return null; }
            });

            // Fallback to context request if evaluate failed
            if (!currentIp || currentIp === 'Unknown') {
                try {
                    const response = await page.context().request.get('https://checkip.amazonaws.com', { timeout: 8000 });
                    if (response.ok()) {
                        const text = await response.text();
                        currentIp = text.trim() || 'Unknown';
                    }
                } catch (e) {}
            }
        }
      } catch (e) {
        // ignore IP fetch error
      }

      const historyPath = path.join(SCRAPED_DATA_DIR, profileName, 'history.json');
      let history = {};
      if (await fs.pathExists(historyPath)) {
        try { history = await fs.readJson(historyPath); } catch (e) { history = {}; }
      }

      if (!Array.isArray(history.scrapedArticles)) {
        history.scrapedArticles = [];
      }

      const existingIdx = history.scrapedArticles.findIndex(a => a.url === currentUrl);
      if (existingIdx === -1) {
        history.scrapedArticles.push({
          title: result.title,
          url: result.url,
          ip: currentIp,
          author: result.author,
          imageCount: result.imageCount,
          contentLength: result.content.length,
          scrapedAt: result.scrapedAt,
          isScraped: true
        });
      } else {
        history.scrapedArticles[existingIdx].isScraped = true;
        history.scrapedArticles[existingIdx].imageCount = result.imageCount;
        history.scrapedArticles[existingIdx].contentLength = result.content.length;
        history.scrapedArticles[existingIdx].scrapedAt = result.scrapedAt;
        if (!history.scrapedArticles[existingIdx].ip || history.scrapedArticles[existingIdx].ip === 'Unknown') {
            history.scrapedArticles[existingIdx].ip = currentIp;
        }
      }

      if (history.scrapedArticles.length > 500) {
        history.scrapedArticles = history.scrapedArticles.slice(-500);
      }

      await fs.writeJson(historyPath, history, { spaces: 2 });
      console.log(`[EXTRACT_CONTENT] 📋 Updated history.json (${history.scrapedArticles.length} articles tracked)`);
    } catch (e) {
      console.warn(`[EXTRACT_CONTENT] Failed to update history: ${e.message}`);
    }

    console.log(`\n>>> EXTRACT CONTENT COMPLETE <<<`);
    console.log(`Title: "${result.title}"`);
    console.log(`Content: ${result.content.length} chars | Images: ${result.imageCount}`);
    console.log(`>>> END EXTRACTION <<<\n`);

    return result;

  } catch (error) {
    console.error(`[EXTRACT_CONTENT] Extraction failed: ${error.message}`);
    return null;
  }
}
