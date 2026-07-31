"""
TubeCLI i18n — Internationalization module.
Provides t() function for translating user-facing messages.
AI prompts and internal structures remain in English.
"""

_TRANSLATIONS = {}
_CURRENT_LANG = "en"

# Catalogues are maintained by hand and drift apart, so a key present in en is
# often missing in one of the other eight. Without a fallback layer t() returned
# the key itself, which surfaces to the user as literal text like
# "panel.ollama_not_installed_short" and reads as a broken program. English is
# loaded underneath every language so a missing key degrades to readable English
# instead. Merge order matters: English first, then the chosen language on top.
_FALLBACK: dict = {}


def _english() -> dict:
    global _FALLBACK
    if not _FALLBACK:
        from tubecli.i18n import en
        _FALLBACK = dict(en.MESSAGES)
    return _FALLBACK


_MODULES = {
    "vi": "vi", "zh": "zh", "zh-TW": "zh_tw", "ja": "ja",
    "ko": "ko", "es": "es", "tr": "tr", "ru": "ru", "en": "en",
}


def load_language(lang: str):
    """Load translation catalog for the given language code.

    English is always merged underneath, so a key missing from the requested
    language falls back to readable English rather than leaking the key name.
    """
    global _TRANSLATIONS, _CURRENT_LANG
    _CURRENT_LANG = lang
    catalog = dict(_english())
    mod_name = _MODULES.get(lang)
    if mod_name and mod_name != "en":
        try:
            import importlib
            mod = importlib.import_module(f"tubecli.i18n.{mod_name}")
            catalog.update(mod.MESSAGES)
        except Exception:
            pass  # keep English rather than failing to start
    _TRANSLATIONS = catalog


def get_current_language() -> str:
    """Return the currently loaded language code."""
    return _CURRENT_LANG


def t(key: str, **kwargs) -> str:
    """Translate a key, with optional format args.

    If key is not found, returns the key itself as fallback.
    Usage:
        t("init.workspace_ready")
        t("agent.created", name="Bot1")
    """
    text = _TRANSLATIONS.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text
