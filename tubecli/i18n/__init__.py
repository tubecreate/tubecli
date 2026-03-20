"""
TubeCLI i18n — Internationalization module.
Provides t() function for translating user-facing messages.
AI prompts and internal structures remain in English.
"""

_TRANSLATIONS = {}
_CURRENT_LANG = "en"


def load_language(lang: str):
    """Load translation catalog for the given language code."""
    global _TRANSLATIONS, _CURRENT_LANG
    _CURRENT_LANG = lang
    if lang == "vi":
        from tubecli.i18n import vi
        _TRANSLATIONS = dict(vi.MESSAGES)
    else:
        from tubecli.i18n import en
        _TRANSLATIONS = dict(en.MESSAGES)


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
