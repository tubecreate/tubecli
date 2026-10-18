/**
 * Đóng popup che trang (user 18/10/2026: «các action vào web vẫn chưa tắt (bỏ qua) các popup»).
 *
 * Trước đây chỉ hộp Google «Before you continue» được đóng (search.js). Trang báo (informador.mx…) hiện hộp xin
 * phép cookie «Consentir / No consentir», hộp đăng ký nhận tin, lớp phủ modal… và agent cứ đọc xuyên qua: cuộn
 * không nhúc nhích vì body bị khoá, nội dung lấy về lẫn chữ của hộp thoại.
 *
 * Thứ tự xử lý, trong MỌI frame (CMP hay nằm trong iframe):
 *   1. nút của các bộ quản lý đồng ý (CMP) đã biết — OneTrust, Didomi, Quantcast, Cookiebot, TrustArc, Google
 *      Funding Choices, Osano, Iubenda, CookieYes, Complianz, Usercentrics, Sourcepoint…;
 *   2. nút nằm TRONG hộp thoại / lớp phủ (role=dialog, aria-modal, position fixed che màn hình, id/class có
 *      cookie|consent|modal|popup…) có chữ «đồng ý / chấp nhận» (nhiều thứ tiếng), rồi «đóng / để sau», rồi
 *      «từ chối», rồi nút ×/aria-label=close;
 *   3. vẫn còn lớp phủ cố định che ≥ 60 % màn hình → gỡ khỏi DOM và mở khoá cuộn (overflow / modal-open).
 *
 * Không chạy ở trang ứng dụng và trang đăng nhập (isAppHost, /login|signin/, accounts.google.com) để không bấm
 * nhầm trong luồng đăng nhập. Best-effort tuyệt đối: không bao giờ ném, trả {clicked[], removed} để ghi log.
 * Chạy sau mỗi lần tải trang (open.js attachPopupDismisser: 0,9 s và 3,2 s sau domcontentloaded — CMP vẽ muộn)
 * và trước khi browse / extract_content / sau navigate.
 */
import { isAppHost } from './search.js';

// Khớp TRỌN nhãn nút (sau khi gộp khoảng trắng), không khớp «Accept and pay» hay «Sign in and agree».
export const ACCEPT_TEXT = /^(?:accept(?: all)?(?: cookies)?|accept & close|accept and close|allow(?: all)?(?: cookies)?|agree|i agree|i accept|i understand|understood|got it|ok(?:ay)?|yes,? i agree|consent|consentir|acepto|aceptar(?: todo| todas| cookies)?|entendido|de acuerdo|aceitar(?: tudo| todos)?|concordo|entendi|accetta(?: tutto| tutti)?|accetto|ho capito|akzeptieren|alle akzeptieren|alles akzeptieren|zustimmen|einverstanden|verstanden|accepter(?: tout)?|tout accepter|j'accepte|j’accepte|compris|đồng ý|tôi đồng ý|chấp nhận(?: tất cả)?|đã hiểu|同意|全部同意|接受|全部接受|我同意|同意する|すべて同意(?:する)?|承諾(?:する)?|확인|동의|모두 동의|수락|принять(?: все| всё)?|согласен|принимаю|понятно|kabul(?: et| ediyorum)?|tümünü kabul et|anladım|tamam|zgadzam się|akceptuj(?:ę)?|accepteren|alles accepteren|akkoord|godkänn(?: alla)?|accepter alle|hyväksy(?: kaikki)?|elfogad(?:om)?|souhlasím|přijmout(?: vše)?)\s*[!.]?$/i;
export const CLOSE_TEXT = /^(?:close|dismiss|no,? thanks|not now|maybe later|later|skip|continue without accepting|continue to site|cerrar|ahora no|no,? gracias|más tarde|omitir|fermer|plus tard|non merci|schließen|später|nein,? danke|đóng|để sau|bỏ qua|không,? cảm ơn|chiudi|più tardi|no,? grazie|fechar|agora não|não,? obrigado|关闭|稍后|跳过|關閉|閉じる|後で|닫기|나중에|закрыть|позже|нет,? спасибо|kapat|daha sonra|hayır,? teşekkürler|×|✕|✖|x)\s*$/i;
export const REJECT_TEXT = /^(?:reject(?: all)?(?: cookies)?|decline(?: all)?|deny(?: all)?|refuse(?: all)?|no consent|do not consent|no consentir|rechazar(?: todo| todas)?|rejeitar(?: tudo)?|rifiuta(?: tutto)?|alle ablehnen|ablehnen|tout refuser|refuser|từ chối(?: tất cả)?|拒绝|全部拒绝|拒否|すべて拒否|거부|모두 거부|отклонить(?: все)?|отказаться|reddet|tümünü reddet)\s*[!.]?$/i;
// aria-label / title của nút biểu tượng đóng.
export const CLOSE_LABEL = /(^|\b)(close|dismiss|đóng|cerrar|fechar|fermer|schließen|chiudi|закрыть|关闭|關閉|閉じる|닫기|kapat)(\b|$)/i;
// id / class / role gợi ý «đây là lớp phủ».
export const OVERLAY_HINT = /(cookie|consent|gdpr|ccpa|privacy|cmp|didomi|onetrust|qc-cmp|sp_message|usercentrics|modal|popup|pop-up|overlay|backdrop|lightbox|dialog|newsletter|subscribe-?(?:box|modal|popup)|paywall|interstitial|notice|banner)/i;

// Bộ CMP đã biết — thứ tự ưu tiên «đồng ý tất cả» (agent chỉ cần đọc trang).
export const KNOWN_SELECTORS = [
  '#onetrust-accept-btn-handler', '#accept-recommended-btn-handler',
  '#didomi-notice-agree-button', '.didomi-continue-without-agreeing',
  '.qc-cmp2-summary-buttons button[mode="primary"]', '.qc-cmp2-summary-buttons button[mode="secondary"]',
  '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll', '#CybotCookiebotDialogBodyButtonAccept',
  '#truste-consent-button', '.truste-button1',
  '.fc-cta-consent', '.fc-button.fc-cta-consent',
  '.osano-cm-accept-all', '.osano-cm-accept',
  '.iubenda-cs-accept-btn', '#cky-btn-accept', '.cky-btn-accept', '.cmplz-accept', '.cmplz-btn.cmplz-accept',
  'button[data-testid="uc-accept-all-button"]', '#uc-btn-accept-banner',
  '#sp-cc-accept', 'button.sp_choice_type_11', '.message-component.sp_choice_type_11',
  '#L2AGLb', 'button[aria-label="Accept all"]', 'button[aria-label="Aceptar todo"]',
  '#cookie_action_close_header', '.cc-btn.cc-allow', '.cc-allow', '.cc-dismiss',
  '#accept-cookies', '#acceptCookies', '#accept-all-cookies', '.js-accept-cookies', '.js-cookie-consent-agree',
  'button[id*="accept-all" i]', 'button[id*="acceptall" i]', 'button[class*="accept-all" i]',
  '#consent-accept', '#cookieChoiceDismiss', '#gdpr-consent-accept', '.gdpr-accept',
  '#ez-accept-all', '#ez-accept-necessary', '.bcpConsentOKButton', '#BorlabsCookieBoxSaveAllButton', '._brlbs-btn-accept-all',
];

// Trang ứng dụng / đăng nhập: không bấm bừa.
export function shouldSkipUrl(url) {
  const u = String(url || '');
  if (!u || u === 'about:blank' || u.startsWith('chrome') || u.startsWith('devtools')) return true;
  let host = '', path = '';
  try { const x = new URL(u); host = x.hostname.toLowerCase().replace(/^www\./, ''); path = x.pathname.toLowerCase(); } catch { return true; }
  if (isAppHost(host)) return true;
  if (/^(accounts|login|signin|auth|id|sso)\./.test(host)) return true;
  if (/\/(login|signin|sign-in|log-in|oauth|auth|sso|checkout|payment|cart)(\/|$|\?)/.test(path)) return true;
  return false;
}

// Chọn nút theo thứ tự ưu tiên; trả {index, how} hoặc null. Thuần — test bằng node.
export function pickLabel(labels) {
  const list = (labels || []).map((s) => String(s || '').replace(/\s+/g, ' ').trim());
  for (const [how, re] of [['accept', ACCEPT_TEXT], ['close', CLOSE_TEXT], ['reject', REJECT_TEXT]]) {
    const i = list.findIndex((t) => t && t.length <= 48 && re.test(t));
    if (i >= 0) return { index: i, how };
  }
  return null;
}

const CFG = {
  known: KNOWN_SELECTORS,
  accept: ACCEPT_TEXT.source, close: CLOSE_TEXT.source, reject: REJECT_TEXT.source,
  closeLabel: CLOSE_LABEL.source, hint: OVERLAY_HINT.source,
};

// ── chạy TRONG trang ──────────────────────────────────────────────────────────
function inPageDismiss(cfg) {
  const acc = new RegExp(cfg.accept, 'i'), clo = new RegExp(cfg.close, 'i'), rej = new RegExp(cfg.reject, 'i');
  const closeLabel = new RegExp(cfg.closeLabel, 'i'), hint = new RegExp(cfg.hint, 'i');
  const out = { clicked: '', how: '' };
  const vis = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  // 1. CMP đã biết
  for (const sel of cfg.known) {
    let el = null;
    try { el = document.querySelector(sel); } catch { continue; }
    if (el && vis(el)) {
      out.clicked = ((el.innerText || el.value || el.getAttribute('aria-label') || sel) + '').replace(/\s+/g, ' ').trim().slice(0, 60);
      out.how = 'known';
      el.click();
      return out;
    }
  }
  // 2. nút trong lớp phủ
  const vw = innerWidth || 1, vh = innerHeight || 1;
  const isOverlay = (el) => {
    if (!el || el === document.body || el === document.documentElement) return false;
    const role = el.getAttribute('role') || '';
    if (role === 'dialog' || role === 'alertdialog' || el.getAttribute('aria-modal') === 'true' || el.tagName === 'DIALOG') return true;
    const idc = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '');
    if (hint.test(idc)) return true;
    const s = getComputedStyle(el);
    if (s.position === 'fixed' || s.position === 'sticky') {
      const r = el.getBoundingClientRect();
      if (r.width * r.height >= 0.25 * vw * vh) return true;
      if ((parseInt(s.zIndex, 10) || 0) >= 100 && r.height >= 60) return true;   // thanh cookie dưới đáy
    }
    return false;
  };
  const inOverlay = (b) => {
    let n = b;
    for (let i = 0; i < 14 && n && n !== document.body; i++) { if (isOverlay(n)) return true; n = n.parentElement; }
    return false;
  };
  const label = (b) => ((b.innerText || b.value || b.getAttribute('aria-label') || b.title || '') + '').replace(/\s+/g, ' ').trim();
  const btns = [];
  for (const b of document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"], a')) {
    if (btns.length > 400) break;
    if (vis(b) && inOverlay(b)) btns.push(b);
  }
  const cands = btns.map((b) => ({ b, t: label(b) })).filter((x) => x.t && x.t.length <= 48);
  for (const [how, re] of [['accept', acc], ['close', clo], ['reject', rej]]) {
    const hit = cands.find((x) => re.test(x.t));
    if (hit) { out.clicked = hit.t.slice(0, 60); out.how = how; hit.b.click(); return out; }
  }
  const icon = btns.find((b) => closeLabel.test(b.getAttribute('aria-label') || b.title || ''));
  if (icon) { out.clicked = (icon.getAttribute('aria-label') || icon.title || 'close').slice(0, 60); out.how = 'close-icon'; icon.click(); return out; }
  return out;
}

function inPageNuke(cfg) {
  const hint = new RegExp(cfg.hint, 'i');
  const vw = innerWidth || 1, vh = innerHeight || 1;
  let removed = 0;
  for (const el of document.querySelectorAll('div, section, aside, dialog, form')) {
    if (removed >= 5) break;
    const s = getComputedStyle(el);
    if (s.position !== 'fixed') continue;
    if (s.display === 'none' || s.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height < 0.6 * vw * vh) continue;
    const idc = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '') + ' ' + (el.getAttribute('role') || '');
    const z = parseInt(s.zIndex, 10) || 0;
    if (!(z >= 10 || hint.test(idc))) continue;
    if (el.tagName === 'VIDEO' || el.querySelector('video, canvas')) continue;   // không gỡ trình phát / trình vẽ
    el.remove();
    removed++;
  }
  if (removed) {
    for (const n of [document.documentElement, document.body]) {
      if (!n) continue;
      n.style.overflow = ''; n.style.overflowY = ''; n.style.position = '';
      for (const c of ['modal-open', 'no-scroll', 'noscroll', 'overflow-hidden', 'scroll-lock', 'is-locked', 'has-modal']) n.classList.remove(c);
    }
  }
  return removed;
}

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

/**
 * Đóng mọi popup đang che trang. Không ném. Trả {clicked: string[], removed: number}.
 * @param {import('playwright').Page} page
 */
export async function dismissPopups(page, opts = {}) {
  const summary = { clicked: [], removed: 0 };
  try {
    if (!page || page.isClosed()) return summary;
    const url = page.url();
    if (shouldSkipUrl(url)) return summary;
    const via = opts.via ? ` (${opts.via})` : '';
    for (let round = 0; round < 3; round++) {
      let any = false;
      for (const f of page.frames()) {
        if (f.isDetached && f.isDetached()) continue;
        const r = await f.evaluate(inPageDismiss, CFG).catch(() => null);
        if (r && r.clicked) {
          any = true;
          summary.clicked.push(r.clicked);
          console.log(`[POPUP] ${r.how}: «${r.clicked}» on ${hostOf(f.url()) || hostOf(url)}${via}`);
        }
      }
      if (!any) break;
      await page.waitForTimeout(700).catch(() => {});
    }
    const removed = await page.evaluate(inPageNuke, CFG).catch(() => 0);
    if (removed) {
      summary.removed = removed;
      console.log(`[POPUP] removed ${removed} overlay(s) still covering ${hostOf(url)}${via}`);
    }
  } catch { /* best-effort */ }
  return summary;
}

const hooked = new WeakSet();

/**
 * Tự đóng popup sau MỖI lần tải trang, ở mọi tab của context (CMP vẽ muộn → thử ở 0,9 s và 3,2 s).
 */
export function attachPopupDismisser(context, firstPage) {
  const hook = (p) => {
    if (!p || hooked.has(p)) return;
    hooked.add(p);
    p.on('domcontentloaded', () => {
      for (const ms of [900, 3200]) {
        setTimeout(() => { dismissPopups(p, { via: 'load' }).catch(() => {}); }, ms);
      }
    });
  };
  try {
    if (firstPage) hook(firstPage);
    if (context && context.on) context.on('page', hook);
  } catch { /* best-effort */ }
}
