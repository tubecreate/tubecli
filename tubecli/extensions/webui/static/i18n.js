/**
 * TubeCLI Dashboard — Internationalization (i18n)
 * Loads aggregated translations from all extension locales via API.
 *
 * Public surface (other pages call these — keep the names and signatures):
 *   T(key, vars)            translate one key, {name} placeholders filled from vars
 *   applyI18n()             translate every [data-i18n], [data-i18n-placeholder], [data-i18n-title]
 *   loadI18nFromApi(opts)   fetch the dictionaries; opts.ns = ['codex', ...] trims the bundle
 *   changeLanguage(lang)    persist the language on the server and reload
 */
let _lang = 'en';
let _translations = {};
let _fallback = {};      // English, consulted per key — see T()

/**
 * Translate key, with optional replacements.
 * T('ollama.pulling', {name:'qwen'})  →  '正在拉取 "qwen"...'
 *
 * A missing key falls back to English and only then to the key itself. It used
 * to go straight to the key, so anything absent from a locale rendered on the
 * page as the literal text "agent_modal.agent_id_label" — worse than English
 * and unrecognisable as a translation gap. There are ~250 such keys today; the
 * whole-file fallback below only covers a locale that fails to load at all,
 * not the far more common case of a file that loads with holes in it.
 */
function T(key, vars) {
    let s = _translations[key] || _fallback[key] || key;
    if (vars) {
        Object.keys(vars).forEach(k => {
            s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]);
        });
    }
    return s;
}

/**
 * Apply translations to all elements with data-i18n attribute.
 */
// Does this key resolve anywhere? T() answers with the key itself when it does
// not, which is fine for a log line and wrong for the screen: writing that key
// over the element replaces authored English with "modal.export.title".
function _resolves(key) {
    return Object.prototype.hasOwnProperty.call(_translations, key)
        || Object.prototype.hasOwnProperty.call(_fallback, key);
}

function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        // An unresolved key leaves the markup's own text alone. Most elements
        // here were authored with real English inside them, and that is a far
        // better fallback than the key — which is what the user used to see.
        if (_resolves(key)) el.textContent = T(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        if (_resolves(key)) el.placeholder = T(key);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        const key = el.getAttribute('data-i18n-title');
        if (_resolves(key)) el.title = T(key);
    });
    // Update html lang attribute
    document.documentElement.lang = _lang;
}

// ── Nạp từ điển ──────────────────────────────────────────────────────────────
//
// Đo 25/9/2026 trên dashboard tiếng Việt: mỗi lần mở trang là hai lượt tải trọn
// bộ (vi + en, ~230–260 KB mỗi gói) với ?v=Date.now() — URL mới mỗi lượt nên
// trình duyệt không bao giờ dùng lại được, và lượt đó chỉ bắt đầu SAU khi
// /api/v1/settings/language trả lời. Giờ:
//   • không gắn Date.now() nữa. Máy chủ trả ETag + Cache-Control: no-cache, nên
//     trình duyệt giữ bản đã tải và chỉ hỏi «còn như cũ không?» — 304 thì không
//     tải lại byte nào. Trang nào khai phiên bản ổn định (window.TUBECLI_VERSION
//     hoặc <meta name="tubecli-version">) thì ghép ?v=<phiên bản>; hôm nay chưa
//     trang nào khai, và không cần: ETag đã lo độ tươi;
//   • trang chỉ cần vài nhóm khoá thì xin đúng nhóm đó — loadI18nFromApi({ns: ['codex']})
//     hoặc window.I18N_NS = ['codex'] đặt trước khi script này chạy → ?ns=codex
//     (gói riêng codex ≈ 8 % gói trọn bộ). Không khai → trọn bộ như trước;
//   • ngôn ngữ đã nằm trong localStorage thì xin từ điển NGAY, không đợi máy chủ
//     — xem loadI18nFromApi().

function _i18nVersion() {
    try {
        if (typeof window.TUBECLI_VERSION === 'string' && window.TUBECLI_VERSION) return window.TUBECLI_VERSION;
        const m = document.querySelector('meta[name="tubecli-version"]');
        if (m && m.content) return m.content;
    } catch (e) { /* không có DOM chuẩn → coi như không khai */ }
    return '';
}

// Danh sách tiền tố khoá trang cần. Ưu tiên tham số gọi, rồi window.I18N_NS;
// nhận cả mảng lẫn chuỗi «codex,common». Rỗng → tải trọn bộ.
function _i18nNamespaces(opts) {
    let ns = (opts && typeof opts === 'object' && opts.ns !== undefined) ? opts.ns : window.I18N_NS;
    if (typeof ns === 'string') ns = ns.split(',');
    if (!Array.isArray(ns)) return [];
    return ns.map(s => String(s).trim()).filter(Boolean);
}

function _i18nUrl(apiBase, lang, nsList) {
    const q = [];
    if (nsList.length) q.push('ns=' + encodeURIComponent(nsList.join(',')));
    const v = _i18nVersion();
    if (v) q.push('v=' + encodeURIComponent(v));
    return apiBase + '/api/v1/i18n/' + encodeURIComponent(lang) + (q.length ? '?' + q.join('&') : '');
}

// Xin từ điển của một ngôn ngữ (+ tiếng Anh để lót). Không ném: hỏng thì trả null
// từng phần, người gọi giữ nguyên những gì đang có.
async function _fetchDictionaries(apiBase, lang, nsList) {
    const out = { dict: null, en: null, wantEn: lang === 'en' };
    try {
        // English is fetched alongside the chosen language, not instead of it,
        // so a key missing from one locale can borrow the English string.
        // Both requests go out together; the page waits for one round trip.
        const [rDict, rEn] = await Promise.all([
            fetch(_i18nUrl(apiBase, lang, nsList)),
            out.wantEn ? null : fetch(_i18nUrl(apiBase, 'en', nsList)).catch(() => null),
        ]);
        if (rDict && rDict.ok) out.dict = await rDict.json();
        if (!out.wantEn && rEn && rEn.ok) out.en = await rEn.json();
    } catch (e) {
        console.warn('Failed to load i18n from API', e);
    }
    return out;
}

function _applyDictionaries(res) {
    if (res.dict) _translations = res.dict;
    if (res.wantEn) {
        _fallback = _translations;
    } else if (res.en) {
        _fallback = res.en;
        // The locale failed entirely — English is then the whole dictionary,
        // which is what the old code did and is still the right answer.
        if (!res.dict) _translations = _fallback;
    }
}

/**
 * Fetch current language from API, then load aggregated translations.
 * The /api/v1/i18n/{lang} endpoint merges all extension locales.
 *
 * opts (optional): { ns: ['codex', 'common'] } — see _i18nNamespaces().
 *
 * Ngôn ngữ: trước đây đợi /api/v1/settings/language xong MỚI xin từ điển — hai
 * lượt đi-về nối đuôi nhau trên mọi trang, qua tunnel là cả giây. Giờ đã có ngôn
 * ngữ trong localStorage (changeLanguage() ghi vào, và mỗi lần máy chủ trả lời
 * cũng ghi lại) thì xin từ điển NGAY bằng ngôn ngữ đó; lượt hỏi máy chủ chạy
 * SONG SONG.
 *
 * Lựa chọn: vẫn đợi lượt hỏi máy chủ trước khi trả về — nhưng vì nó chạy song
 * song với lượt tải từ điển (nặng hơn nhiều) nên thời gian chờ là lượt lâu nhất,
 * không cộng dồn; đổi lại sau `await loadI18nFromApi()` _lang chắc chắn là ngôn
 * ngữ máy chủ, như trước, nên trang không vẽ nhầm ngôn ngữ rồi phải vẽ lại. Chỉ
 * khi máy chủ nói khác localStorage (đổi từ máy khác / CLI — hiếm) mới xin lại
 * từ điển. Lần đầu (localStorage trống) thì như cũ: hỏi máy chủ rồi mới xin.
 */
async function loadI18nFromApi(opts) {
    const apiBase = localStorage.getItem('tubecli_api') || window.location.origin;
    const nsList = _i18nNamespaces(opts);
    let stored = null;
    try { stored = localStorage.getItem('tubecli_lang'); } catch (e) { /* localStorage bị chặn */ }

    // 1. Ngôn ngữ trên máy chủ — bắt đầu ngay; chỉ đợi khi localStorage chưa có gì.
    const serverLang = fetch(apiBase + '/api/v1/settings/language')
        .then(r => r.json())
        .then(d => (d && d.language) ? String(d.language) : null)
        .catch(() => null);

    // 2. Từ điển — bằng ngôn ngữ đã biết, không đợi máy chủ.
    _lang = stored || (await serverLang) || 'en';
    let loaded = await _fetchDictionaries(apiBase, _lang, nsList);

    // 3. Máy chủ nói khác? Ghi nhớ cho lần sau và tải lại đúng ngôn ngữ.
    const fromServer = await serverLang;
    if (fromServer) {
        try { localStorage.setItem('tubecli_lang', fromServer); } catch (e) { /* bị chặn */ }
        if (fromServer !== _lang) {
            _lang = fromServer;
            loaded = await _fetchDictionaries(apiBase, _lang, nsList);
        }
    }
    _applyDictionaries(loaded);
    applyI18n();
}

/**
 * Save language to API and reload page.
 */
async function changeLanguage(lang) {
    _lang = lang;
    localStorage.setItem('tubecli_lang', lang);
    try {
        await fetch((localStorage.getItem('tubecli_api') || window.location.origin) + '/api/v1/settings/language', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language: lang })
        });
    } catch (e) { /* ignore */ }
    applyI18n();
    // Reload current tab content
    location.reload();
}
