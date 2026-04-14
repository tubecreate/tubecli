"""
Bot I18N — Internationalization for Telegram Bot and Extensions.

Reads system language from global_settings.json (set via `tubecli init --lang`).
All bot responses use the same language as the CLI.
"""
import os
import json
from typing import Dict

LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n", "bot_locales")

# --- In-memory translation cache ---
_translations_cache: Dict[str, Dict[str, str]] = {}


def get_system_lang() -> str:
    """Get system language from config (same as CLI --lang setting)."""
    try:
        from tubecli.config import get_language
        return get_language()
    except Exception:
        return "en"


def get_user_lang(chat_id=None) -> str:
    """Get language for bot responses — always uses the system-wide setting."""
    return get_system_lang()


def _load_translations(lang: str) -> Dict[str, str]:
    if lang in _translations_cache:
        return _translations_cache[lang]

    os.makedirs(LOCALES_DIR, exist_ok=True)
    file_path = os.path.join(LOCALES_DIR, f"{lang}.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                _translations_cache[lang] = json.load(f)
        except Exception as e:
            print(f"[Bot_I18N] Failed to load locale {lang}: {e}")
            _translations_cache[lang] = {}
    else:
        _translations_cache[lang] = {}

    return _translations_cache[lang]


def t(key: str, lang: str = None, **kwargs) -> str:
    """
    Translate a key to the target language.
    If lang is not specified, uses system language.

    Usage: t('action.download_fail')
           t('action.download_err', error='timeout')
           t('action.upload_success', lang='en', result='...')
    """
    if lang is None:
        lang = get_system_lang()

    translations = _load_translations(lang)

    # Fallback: target lang → English → key itself
    text = translations.get(key)
    if not text and lang != "en":
        en_translations = _load_translations("en")
        text = en_translations.get(key)

    if not text:
        text = key

    try:
        if kwargs:
            return text.format(**kwargs)
        return text
    except Exception:
        return text
