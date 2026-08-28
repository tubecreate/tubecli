/**
 * TubeCLI Dashboard — Internationalization (i18n)
 * Loads aggregated translations from all extension locales via API.
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

/**
 * Fetch current language from API, then load aggregated translations.
 * The /api/v1/i18n/{lang} endpoint merges all extension locales.
 */
async function loadI18nFromApi() {
    const apiBase = localStorage.getItem('tubecli_api') || window.location.origin;

    // 1. Get current language setting
    try {
        const r = await fetch(apiBase + '/api/v1/settings/language');
        const d = await r.json();
        if (d && d.language) {
            _lang = d.language;
        }
    } catch (e) {
        _lang = localStorage.getItem('tubecli_lang') || 'en';
    }

    // 2. Fetch aggregated translations from all extensions
    try {
        const cacheBuster = '?v=' + new Date().getTime();
        // English is fetched alongside the chosen language, not instead of it,
        // so a key missing from one locale can borrow the English string.
        // Both requests go out together; the page waits for one round trip.
        const wantEn = _lang === 'en';
        const [rDict, rEn] = await Promise.all([
            fetch(apiBase + '/api/v1/i18n/' + _lang + cacheBuster),
            wantEn ? null : fetch(apiBase + '/api/v1/i18n/en' + cacheBuster).catch(() => null),
        ]);
        if (rDict && rDict.ok) {
            _translations = await rDict.json();
        }
        if (wantEn) {
            _fallback = _translations;
        } else if (rEn && rEn.ok) {
            _fallback = await rEn.json();
            // The locale failed entirely — English is then the whole dictionary,
            // which is what the old code did and is still the right answer.
            if (!rDict || !rDict.ok) _translations = _fallback;
        }
    } catch (e) {
        console.warn('Failed to load i18n from API', e);
    }

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
