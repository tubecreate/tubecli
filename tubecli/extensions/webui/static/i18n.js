/**
 * ZhiYing Dashboard — Internationalization (i18n)
 * Loads aggregated translations from all extension locales via API.
 */
let _lang = 'zh';
let _translations = {};

/**
 * Translate key, with optional replacements.
 * T('ollama.pulling', {name:'qwen'})  →  '正在拉取 "qwen"...'
 */
function T(key, vars) {
    let s = (_translations[key]) || key;
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
function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = T(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = T(el.getAttribute('data-i18n-placeholder'));
    });
    // Update html lang attribute
    document.documentElement.lang = _lang;
}

/**
 * Fetch current language from API, then load aggregated translations.
 * The /api/v1/i18n/{lang} endpoint merges all extension locales.
 */
async function loadI18nFromApi() {
    const apiBase = localStorage.getItem('zhiying_api') || 'http://localhost:5295';

    // 1. Get current language setting
    try {
        const r = await fetch(apiBase + '/api/v1/settings/language');
        const d = await r.json();
        if (d && d.language) {
            _lang = d.language;
        }
    } catch (e) {
        _lang = localStorage.getItem('zhiying_lang') || 'zh';
    }

    // 2. Fetch aggregated translations from all extensions
    try {
        const cacheBuster = '?v=' + new Date().getTime();
        const rDict = await fetch(apiBase + '/api/v1/i18n/' + _lang + cacheBuster);
        if (rDict.ok) {
            _translations = await rDict.json();
        } else {
            // Fallback to English
            const ef = await fetch(apiBase + '/api/v1/i18n/en' + cacheBuster);
            if (ef.ok) _translations = await ef.json();
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
    localStorage.setItem('zhiying_lang', lang);
    try {
        await fetch((localStorage.getItem('zhiying_api') || 'http://localhost:5295') + '/api/v1/settings/language', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language: lang })
        });
    } catch (e) { /* ignore */ }
    applyI18n();
    // Reload current tab content
    location.reload();
}
