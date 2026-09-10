import { waitForCaptcha, detectCaptcha } from './captcha_helper.js';

async function handleCaptcha(page, isRetry) {
  if (await detectCaptcha(page)) {
    if (isRetry) {
      // 60s chứ không phải mặc định 10 PHÚT: lượt lịch chạy headless trên VPS
      // không có ai ngồi giải captcha — chờ 10 phút chỉ để watchdog vào giết
      // (log thật: hàng chục dòng "Captcha detected" mỗi 3s cho tới hết giờ).
      await waitForCaptcha(page, 60000);
    } else {
      throw new Error('CAPTCHA_DETECTED');
    }
  }
}

// ── Trang đang mở là gì? So theo TÊN MIỀN, không phải chuỗi con của cả URL ──
//
// VÌ SAO: 'mail.google.com'.includes('google.com') là ĐÚNG. Bản trước dùng đúng
// phép thử ấy ở HAI chỗ (cờ máy-tìm-kiếm, và "chưa ở Google thì mới goto"), nên
// khi phiên mở lại trúng tab Gmail còn sót của hồ sơ — open.js chỉ tự vào Google
// khi tab đang là about:blank — thì cả hai đều tưởng đang ở Google: không mở
// www.google.com, rồi gõ câu tìm vào input[name="q"], mà trên Gmail đó là ô TÌM
// THƯ. Lượt chạy vẫn báo thành công vì mã chỉ chờ #search rồi in cảnh báo khi
// không thấy. Người dùng báo 10/9/2026: agent tìm chủ đề ngay trong hộp thư.
function hostOf(url) {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, '');
  } catch (_) {
    return '';
  }
}

const SEARCH_HOSTS = new Set([
  'google.com', 'bing.com', 'duckduckgo.com', 'search.yahoo.com',
  'search.brave.com', 'startpage.com', 'ecosia.org', 'baidu.com', 'yandex.com',
]);

export function isSearchEngineHost(host) {
  if (!host) return false;
  if (SEARCH_HOSTS.has(host)) return true;
  // Tên miền quốc gia: google.de, google.co.uk, google.com.vn
  if (/^google\.[a-z]{2,3}(\.[a-z]{2,3})?$/.test(host)) return true;
  if (/^search\.yahoo\.[a-z]{2,3}(\.[a-z]{2,3})?$/.test(host)) return true;
  return false;
}

// Trang ỨNG DỤNG, không phải trang nội dung: ô tìm ở đây tìm THƯ / TỆP / LỊCH /
// tin nhắn, không bao giờ là thứ một lượt "đọc web theo chủ đề" cần. Chỉ sửa cờ
// máy-tìm-kiếm là CHƯA ĐỦ: Gmail khi đó rơi vào nhánh tìm-trong-site và vẫn gõ
// đúng vào ô tìm thư. Gặp mấy host này thì đi thẳng ra máy tìm kiếm.
const APP_HOSTS = new Set([
  'mail.google.com', 'drive.google.com', 'docs.google.com', 'sheets.google.com',
  'slides.google.com', 'calendar.google.com', 'contacts.google.com', 'keep.google.com',
  'photos.google.com', 'chat.google.com', 'meet.google.com', 'groups.google.com',
  'accounts.google.com', 'myaccount.google.com', 'admin.google.com', 'takeout.google.com',
  'outlook.live.com', 'outlook.office.com', 'outlook.office365.com',
  'mail.yahoo.com', 'mail.proton.me', 'mail.zoho.com',
  'web.whatsapp.com', 'web.telegram.org', 'teams.microsoft.com', 'discord.com',
]);

export function isAppHost(host) {
  if (!host) return false;
  if (APP_HOSTS.has(host)) return true;
  if (host === 'slack.com' || host.endsWith('.slack.com')) return true;
  return false;
}

/**
 * Action: Search for a keyword on Google
 * @param {import('playwright').Page} page
 * @param {object} params
 * @param {string} params.keyword - The search query.
 */
export async function search(page, params) {
  const { keyword } = params;
  if (!keyword) throw new Error('Keyword is required for search action');

  console.log(`Action: SEARCH '${keyword}'`);

  // STRATEGY 1: Check if keyword is a URL -> Navigate directly
  const isUrl = /^(http|https):\/\/[^ "]+$/.test(keyword) || /^[a-zA-Z0-9-]+\.(com|net|org|io|vn)(\/[^ "]+)?$/.test(keyword);
  
  if (isUrl) {
      let targetUrl = keyword;
      if (!targetUrl.startsWith('http')) targetUrl = 'https://' + targetUrl;
      console.log(`Detected URL: ${targetUrl}. Navigating directly...`);
      try {
          await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
          console.log('Navigation complete.');
          
          // Optional: handle consents popup (e.g. generic cookies)
          try {
             const consent = await page.getByRole('button', { name: /Accept|Agree|Consent|Đồng ý/i }).first();
             if (await consent.isVisible()) await consent.click();
          } catch(e) {}
          
          return; // Done
      } catch (e) {
          console.warn(`Direct navigation failed: ${e.message}. Falling back to search.`);
      }
  }

  // STRATEGY 2: Contextual Search (Search ON the current site)
  // Chỉ làm khi trang đang mở là trang NỘI DUNG: không phải máy tìm kiếm (đã có
  // đường riêng ở STRATEGY 3) và không phải ứng dụng (ô tìm thư/tệp/lịch).
  const currentUrl = page.url();
  const currentHost = hostOf(currentUrl);
  const onSearchEngine = isSearchEngineHost(currentHost);
  const onAppSite = isAppHost(currentHost);
  if (onAppSite) {
    console.log(`On app site ${currentHost}: its search box searches mail/files, not the web. Going to a search engine.`);
  }

  if (!onSearchEngine && !onAppSite && currentUrl !== 'about:blank') {
      console.log(`Attempting internal search on ${new URL(currentUrl).hostname}...`);
      try {
          // Comprehensive internal search selectors (covers most websites)
          const searchSelectors = [
              // Type-based
              'input[type="search"]',
              
              // Name-based (common patterns)
              'input[name="q"]',           // Google, GitHub, many sites
              'input[name="query"]',
              'input[name="search"]',
              'input[name="s"]',           // WordPress default
              'input[name="keyword"]',
              'input[name="searchTerm"]',
              
              // Placeholder-based (multilingual)
              'input[placeholder*="Search" i]',
              'input[placeholder*="Tìm" i]',      // Vietnamese
              'input[placeholder*="搜索" i]',     // Chinese
              'input[placeholder*="検索" i]',     // Japanese
              'input[placeholder*="Buscar" i]',   // Spanish
              
              // Class-based (common naming conventions)
              'input[class*="search" i]',
              'input[class*="query" i]',
              
              // ID-based
              'input[id*="search" i]',
              'input[id*="query" i]',
              '#search-input',
              '#searchbox',
              '#q',
              
              // ARIA attributes
              'input[aria-label*="search" i]',
              'input[role="searchbox"]',
              
              // Generic text inputs in search containers
              '.search input[type="text"]',
              '#search input[type="text"]',
              '[role="search"] input',
              
              // Buttons/Icons that might open search (click to reveal)
              'button[aria-label*="Search" i]',
              'button[class*="search" i]',
              'svg[aria-label*="Search" i]',
              'a[aria-label*="Search" i]'
          ];
          
          let searchInput = null;
          let searchButton = null;
          
          for (const sel of searchSelectors) {
              const el = page.locator(sel).first();
              if (await el.isVisible()) {
                  const tagName = await el.evaluate(node => node.tagName.toLowerCase());
                  
                  if (tagName === 'input') {
                      searchInput = el;
                      console.log(`Found internal search input: ${sel}`);
                      break;
                  } else if (tagName === 'button' || tagName === 'svg' || tagName === 'a') {
                      // Click button/icon to reveal search
                      searchButton = el;
                      console.log(`Found search trigger button: ${sel}`);
                      break;
                  }
              }
          }

          // If found a button, click it to reveal search input
          if (searchButton && !searchInput) {
              await searchButton.click();
              await page.waitForTimeout(500);
              
              // Try to find the revealed input
              for (const sel of searchSelectors.slice(0, 15)) { // Try input selectors only
                  const el = page.locator(sel).first();
                  if (await el.isVisible()) {
                      searchInput = el;
                      console.log(`Found revealed search input: ${sel}`);
                      break;
                  }
              }
          }

          if (searchInput) {
              console.log('Found internal search input. Typing query...');
              await searchInput.click();
              await searchInput.fill(''); // clear potential text
              
              // Human-like typing
              for (const char of keyword) {
                   await page.keyboard.type(char, { delay: 50 + Math.random() * 50 });
              }
              await page.waitForTimeout(500);
              await page.keyboard.press('Enter');
              console.log('Internal search executed.');
              await page.waitForTimeout(2000); // Wait for internal results
              return;
          } else {
              console.warn('No internal search bar found. Falling back to Google.');
          }
      } catch (e) {
          console.warn(`Internal search failed: ${e.message}. Falling back to Google.`);
      }
  }

  // STRATEGY 3: Google Search (Fallback)
  console.log('Performing Google Search...');
  
  // Navigate to Google if not already there — theo TÊN MIỀN. Phép thử chuỗi con
  // cũ ('mail.google.com'.includes('google.com') === true) khiến bước này KHÔNG
  // BAO GIỜ chạy khi tab đang ở Gmail, và câu tìm rơi vào ô tìm thư ngay dưới đây.
  if (!isSearchEngineHost(hostOf(page.url()))) {
    await page.goto('https://www.google.com', { waitUntil: 'domcontentloaded', timeout: 30000 });
    try {
      await page.waitForSelector('textarea[name="q"], input[name="q"]', { timeout: 10000 });
    } catch (e) {
      console.warn('Search input not found after navigation, continuing anyway...');
    }
  }
  
  await handleCaptcha(page, params.isRetry);

  // Handle potential cookie consent
  try {
    const consentButton = await page.getByRole('button', { name: /Accept all|Tôi đồng ý/i }).first();
    if (await consentButton.isVisible()) {
      await consentButton.click();
    }
  } catch (e) {}

  const searchBoxSelection = page.locator('textarea[name="q"], input[name="q"]');
  const searchBox = (await searchBoxSelection.count()) > 1 
    ? searchBoxSelection.filter({ visible: true }).first() 
    : searchBoxSelection.first();

  await searchBox.click();
  await searchBox.fill(''); 
  
  // Human-like typing
  for (const char of keyword) {
    await page.keyboard.type(char, { delay: 50 + Math.random() * 100 });
  }
  
  await page.waitForTimeout(500);
  await page.keyboard.press('Enter');
  
  // --- CAPTCHA DETECTION ---
  await handleCaptcha(page, params.isRetry);

  await page.waitForSelector('#search', { timeout: 10000 }).catch(() => {
    console.warn('Search results took too long to load or blocked by Captcha.');
  });
  console.log('Search results loaded.');
  
  // Human-like delay: simulate reading search results before clicking
  const readingDelay = 2000 + Math.random() * 3000; // 2-5 seconds
  console.log(`Simulating reading time: ${Math.round(readingDelay)}ms...`);
  await page.waitForTimeout(readingDelay);
}
