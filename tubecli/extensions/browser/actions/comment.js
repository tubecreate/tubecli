import axios from 'axios';

/**
 * Action: bình luận dưới video đang mở — YouTube (/watch) hoặc TikTok (trang / khung video).
 *
 * Chữ do AI (model của phiên — params.aiModel, rỗng = AI mặc định qua /localai) viết theo TIÊU ĐỀ video,
 * đúng ngôn ngữ agent; được làm sạch (một dòng, không link / hashtag / @, ≤ 220 ký tự). AI hỏng ⇒ KHÔNG đăng
 * (bản cũ đăng câu chung chung tiếng Việt «Video rất hay…» — rác, lộ là bot). Gõ xong KIỂM chữ trong ô rồi
 * mới bấm gửi. TUBECLI_ENGAGE_DRY_RUN=1: gõ, kiểm, rồi xoá — không đăng (để thử).
 *
 * @param {import('playwright').Page} page
 * @param {object} params  aiModel, language, agentName, interests, instruction (gợi ý thêm, tuỳ chọn)
 */
const TUBECLI_PORT = process.env.TUBECLI_PORT || '5295';
const LOCAL_AI_URL = `http://localhost:${TUBECLI_PORT}/api/v1/localai/generate`;

export function cleanComment(text) {
  let t = String(text || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  t = t.replace(/^```\w*\s*|\s*```$/g, '').trim();
  t = (t.split(/\r?\n/).find((l) => l.trim()) || '').trim();
  t = t.replace(/^(comment|bình luận)\s*:\s*/i, '').replace(/^["“”']+|["“”']+$/g, '').trim();
  t = t.replace(/(^|\s)#[\p{L}\p{N}_]+/gu, '').trim();
  if (t.length < 3) throw new Error('AI_COMMENT_EMPTY');
  if (/https?:\/\/|www\.|\.(com|net|org|vn|io)\b|@/i.test(t)) throw new Error('AI_COMMENT_HAS_LINK');
  if (/^\[?[\w ]*(error|lỗi)\b/i.test(t)) throw new Error('AI_COMMENT_ERROR_TEXT');
  return t.slice(0, 220);
}

export function commentPrompt({ title, platform, language, agentName, interests, instruction }) {
  const lang = String(language || '').trim();
  const langLine = lang && lang.toLowerCase() !== 'auto'
    ? `Write it in the language with code '${lang}'.`
    : 'Write it in the same language as the video title.';
  const who = agentName ? `You are ${agentName}, an ordinary viewer` : 'You are an ordinary viewer';
  const about = Array.isArray(interests) && interests.length ? ` You are interested in: ${interests.slice(0, 5).join(', ')}.` : '';
  const extra = instruction && !/^nice video$/i.test(instruction) ? `\nExtra hint: ${instruction}` : '';
  return `${who} who just watched this ${platform} video.${about}\nVideo title: ${title || '(unknown)'}\n\n`
    + 'Write ONE short, natural comment a real viewer would post about THIS video (5-25 words). '
    + `${langLine} Be specific to the title, friendly and genuine. No links, no hashtags, no @mentions, at most one emoji, `
    + 'no self-promotion, do not ask people to subscribe or visit anything, never say you are an AI. '
    + `Reply with the comment text only.${extra}`;
}

async function writeComment(params, title, platform) {
  const prompt = commentPrompt({ ...params, title, platform });
  const res = await axios.post(LOCAL_AI_URL, { model: params.aiModel || '', prompt, stream: false },
    { headers: { 'Content-Type': 'application/json' }, timeout: 90000 });
  return cleanComment(res.data && res.data.response);
}

const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
const typedOk = (seen, want) => { const a = norm(seen), b = norm(want); return !!a && (a === b || a.includes(b.slice(0, 30))); };

async function typeHuman(page, text) {
  for (const ch of text) await page.keyboard.type(ch, { delay: 45 + Math.random() * 40 });
  await page.waitForTimeout(800 + Math.random() * 800);
}

async function clearFocused(page) {
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
}

async function youtubeTitle(page) {
  return page.evaluate(() => {
    const el = document.querySelector('#title h1 yt-formatted-string') || document.querySelector('#title h1');
    if (el && el.innerText.trim()) return el.innerText.trim();
    const og = document.querySelector('meta[property="og:title"]');
    return (og && og.content) || document.title.replace(/^\(\d+\)\s*/, '').replace(/\s*-\s*YouTube$/, '');
  });
}

async function commentYouTube(page, params, dry) {
  const signedIn = await page.locator('button#avatar-btn').first().isVisible().catch(() => false);
  if (!signedIn) throw new Error('NOT_LOGGED_IN_ON_YOUTUBE');
  const title = await youtubeTitle(page);
  const text = await writeComment(params, title, 'YouTube');
  console.log(`[comment] YouTube «${title}» → "${text}"`);
  // Khu bình luận nạp lười — cuộn tới khi thấy ô «Add a comment…»
  const placeholder = page.locator('#simple-box #placeholder-area').first();
  for (let i = 0; i < 8 && !(await placeholder.isVisible().catch(() => false)); i++) {
    await page.mouse.wheel(0, 450);
    await page.waitForTimeout(1200 + Math.random() * 600);
  }
  if (!(await placeholder.isVisible().catch(() => false))) throw new Error('COMMENTS_UNAVAILABLE (turned off or not loaded)');
  await placeholder.click();
  const input = page.locator('#contenteditable-root').first();
  await input.waitFor({ state: 'visible', timeout: 8000 });
  await input.click();
  await typeHuman(page, text);
  const seen = await input.innerText().catch(() => '');
  if (!typedOk(seen, text)) { await clearFocused(page); throw new Error('COMMENT_NOT_TYPED'); }
  if (dry) { await clearFocused(page); console.log('[comment] dry run — discarded'); return { comment: text, posted: false }; }
  await page.locator('#submit-button').first().click();
  await page.waitForTimeout(3000);
  const left = await input.innerText().catch(() => '');
  if (typedOk(left, text)) throw new Error('COMMENT_NOT_POSTED (text still in the box)');
  return { comment: text, posted: true };
}

async function commentTikTok(page, params, dry) {
  const title = await page.evaluate(() => {
    const d = document.querySelector('[data-e2e="browse-video-desc"], [data-e2e="video-desc"]');
    return (d && d.innerText.trim()) || document.title.replace(/\s*\|\s*TikTok$/, '');
  });
  const text = await writeComment(params, title, 'TikTok');
  console.log(`[comment] TikTok «${title.slice(0, 80)}» → "${text}"`);
  let box = page.locator('[data-e2e="comment-input"] [contenteditable="true"], div[contenteditable="true"][role="textbox"]').first();
  if (!(await box.isVisible().catch(() => false))) {
    const icon = page.locator('[data-e2e="comment-icon"], [data-e2e="browse-comment-icon"]').first();
    if (await icon.isVisible().catch(() => false)) { await icon.click(); await page.waitForTimeout(2000); }
  }
  if (!(await box.isVisible().catch(() => false))) {
    const login = await page.locator('[data-e2e="top-login-button"], button:has-text("Log in")').first().isVisible().catch(() => false);
    throw new Error(login ? 'NOT_LOGGED_IN_ON_TIKTOK' : 'COMMENTS_UNAVAILABLE');
  }
  await box.click();
  await typeHuman(page, text);
  const seen = await box.innerText().catch(() => '');
  if (!typedOk(seen, text)) { await clearFocused(page); throw new Error('COMMENT_NOT_TYPED'); }
  if (dry) { await clearFocused(page); console.log('[comment] dry run — discarded'); return { comment: text, posted: false }; }
  const post = page.locator('[data-e2e="comment-post"]').first();
  if (!(await post.isVisible().catch(() => false))) { await clearFocused(page); throw new Error('POST_BUTTON_NOT_FOUND'); }
  await post.click();
  await page.waitForTimeout(3000);
  box = page.locator('[data-e2e="comment-input"] [contenteditable="true"], div[contenteditable="true"][role="textbox"]').first();
  if (typedOk(await box.innerText().catch(() => ''), text)) throw new Error('COMMENT_NOT_POSTED (text still in the box)');
  return { comment: text, posted: true };
}

export async function comment(page, params = {}) {
  const dry = process.env.TUBECLI_ENGAGE_DRY_RUN === '1';
  const url = page.url();
  console.log(`Initiating Comment Action on ${url}${dry ? ' (dry run)' : ''}`);
  if (/youtube\.com\/watch/.test(url)) return commentYouTube(page, params, dry);
  if (/tiktok\.com\//.test(url)) return commentTikTok(page, params, dry);
  throw new Error('COMMENT_SKIPPED: not on a YouTube or TikTok video page');
}
