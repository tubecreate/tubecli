/**
 * Action: đăng ký kênh (YouTube) / theo dõi người đăng (TikTok) của video đang mở.
 * Đã đăng ký / đang theo dõi ⇒ không bấm gì (bấm lại là HUỶ theo dõi). Bấm xong kiểm nút đổi trạng thái.
 * TUBECLI_ENGAGE_DRY_RUN=1: chỉ tìm nút, không bấm.
 *
 * @param {import('playwright').Page} page
 */
const label = async (loc) => ((await loc.getAttribute('aria-label').catch(() => '')) || (await loc.innerText().catch(() => '')) || '').trim();

async function followYouTube(page, dry) {
  const signedIn = await page.locator('button#avatar-btn').first().isVisible().catch(() => false);
  if (!signedIn) throw new Error('NOT_LOGGED_IN_ON_YOUTUBE');
  const btn = page.locator('#owner #subscribe-button button, ytd-watch-metadata #subscribe-button button').first();
  await btn.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});
  if (!(await btn.isVisible().catch(() => false))) throw new Error('SUBSCRIBE_BUTTON_NOT_FOUND');
  const before = await label(btn);
  const channel = (await page.locator('#owner #channel-name a, ytd-channel-name a').first().innerText().catch(() => '')).trim();
  if (/unsubscribe|subscribed|đã đăng ký|hủy đăng ký|huỷ đăng ký/i.test(before)) {
    return { followed: false, channel, note: 'already subscribed' };
  }
  if (dry) return { followed: false, channel, note: 'found Subscribe (dry run)' };
  await btn.click();
  await page.waitForTimeout(2500);
  const after = await label(page.locator('#owner #subscribe-button button, ytd-watch-metadata #subscribe-button button').first());
  if (!/unsubscribe|subscribed|đã đăng ký|hủy|huỷ/i.test(after)) throw new Error(`SUBSCRIBE_DID_NOT_TAKE (button says "${after}")`);
  return { followed: true, channel };
}

async function followTikTok(page, dry) {
  const btn = page.locator('[data-e2e="browse-follow"], [data-e2e="feed-follow"], [data-e2e="follow-button"]').first();
  if (!(await btn.isVisible().catch(() => false))) {
    const login = await page.locator('[data-e2e="top-login-button"]').first().isVisible().catch(() => false);
    throw new Error(login ? 'NOT_LOGGED_IN_ON_TIKTOK' : 'FOLLOW_BUTTON_NOT_FOUND');
  }
  const before = await label(btn);
  const who = (await page.locator('[data-e2e="browse-username"], [data-e2e="video-author-uniqueid"]').first().innerText().catch(() => '')).trim();
  if (/following|friends|đang theo dõi|bạn bè/i.test(before)) return { followed: false, channel: who, note: 'already following' };
  if (dry) return { followed: false, channel: who, note: 'found Follow (dry run)' };
  await btn.click();
  await page.waitForTimeout(2500);
  const after = await label(page.locator('[data-e2e="browse-follow"], [data-e2e="feed-follow"], [data-e2e="follow-button"]').first());
  if (/^follow$/i.test(after) || /^theo dõi$/i.test(after)) throw new Error('FOLLOW_DID_NOT_TAKE');
  return { followed: true, channel: who };
}

export async function follow(page, params = {}) {
  const dry = process.env.TUBECLI_ENGAGE_DRY_RUN === '1';
  const url = page.url();
  console.log(`Initiating Follow Action on ${url}${dry ? ' (dry run)' : ''}`);
  if (/youtube\.com\/watch/.test(url)) return followYouTube(page, dry);
  if (/tiktok\.com\//.test(url)) return followTikTok(page, dry);
  throw new Error('FOLLOW_SKIPPED: not on a YouTube or TikTok video page');
}
