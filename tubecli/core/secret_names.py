"""The one list of credential-looking NAMES, shared by everything that must not
keep a value found under one.

WHY A MODULE OF ITS OWN
    group_log.py grew this list first. A handler reply is where a password
    turned up on the canvas, so its redactor learned every spelling of
    "password", "2fa", "recovery" and "token" that a reply can carry.

    The same names were then needed one layer down, and for a different SHAPE.
    browser_scripts stores the variables of every script run into
    executions.variables, and POST /api/v1/scripts/{id}/run fills that dict
    from the profile's saved account ({service}_password, _recovery, _2fa). The
    question there is not "does this text look leaky?" but "is this mapping KEY
    a credential?" — a different match, the same names.

    Two copies of a list like this drift. The day someone adds "passkey" to one
    of them, the other keeps writing it to disk. So the names live here, once,
    and both sides import them.

WHAT THIS IS NOT
    Not a redactor for free text: that is group_log.scrub(), which layers
    run_log.redact(), spreadsheet urls, auth headers and profile paths on top of
    these names. This module knows names and nothing else.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# Names that are an id of a capability rather than a secret in themselves —
# holding one plus the owner's session opens the thing. group_log wants these
# in its free-text rule; a mapping key called `sheet_id` is the same leak.
ID_NAME_ALT = (
    r"sheet_id|spreadsheet_id|cred_id|credential_id|token_id"
)
# ...and the names whose value IS the credential. `mat_?khau` is here because
# script variables and handler replies are written in Vietnamese as often as in
# English on this product.
SECRET_NAME_ALT = (
    r"access_token|refresh_token|api[_-]?key|apikey|token|password|passwd|pwd|"
    r"secret|otp|cookie|recovery|two[_-]?factor|2fa|totp|mat_?khau"
)

MASK = "***"

# How deep scrub_mapping walks. `variables` arrives straight off an HTTP body,
# so its shape is the caller's choice, not ours; past this depth the whole
# subtree is replaced rather than explored.
MAX_DEPTH = 6

# A KEY is matched by SUBSTRING, not as a whole word. The names that matter
# arrive glued to something else — google_password, loginPwd, twoFactorCodes,
# recoveryEmail — and inside camelCase there is no `\b` to anchor on. Masking a
# key that did not have to be masked costs one cell of a history table;
# missing one costs a password.
_KEY_RE = re.compile("(?:%s|%s)" % (ID_NAME_ALT, SECRET_NAME_ALT), re.IGNORECASE)


def is_secret_name(name: Any) -> bool:
    """Would a value stored under this key be a credential?

    Fails CLOSED: a key that cannot even be read as text is treated as a
    credential, because the alternative is deciding it is safe without looking.
    """
    if isinstance(name, str):
        text = name
    else:
        try:
            text = str(name)
        except Exception:
            return True
    return bool(_KEY_RE.search(text))


def scrub_mapping(value: Any, extra_names: Iterable[str] = (), mask: str = MASK,
                  _depth: int = 0) -> Any:
    """A copy of `value` with every credential-looking key's value replaced.

    Recursive because the shape is not ours to assume: a password sits one
    level down ({"account": {"password": …}}) as readily as at the top, and the
    caller here is a JSON body.

    `extra_names` is for a caller that knows names this list cannot — an exact
    key, compared lower-cased. Nothing is removed from the mapping: a reader
    still sees WHICH inputs a run was given, only not what they were.
    """
    extra = set()
    for name in extra_names or ():
        try:
            extra.add(str(name).lower())
        except Exception:
            continue
    return _walk(value, extra, mask, _depth)


def _walk(value: Any, extra: set, mask: str, depth: int) -> Any:
    if depth > MAX_DEPTH:
        return mask
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str):
                name = key
            else:
                try:
                    name = str(key)
                except Exception:
                    # A key that will not even render: mask and move on, same
                    # rule as is_secret_name.
                    out[key] = mask
                    continue
            if is_secret_name(name) or name.lower() in extra:
                out[key] = mask
            else:
                out[key] = _walk(item, extra, mask, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        # Tuples come back as lists: everything here is on its way to JSON.
        return [_walk(item, extra, mask, depth + 1) for item in value]
    return value
