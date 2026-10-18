"""Revocation boundary for document state kept in a Streamlit session.

The browser component, native owner and prepared operations are scoped to the
authenticated identity.  They must never survive logout or an identity change
inside the same browser session.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

_PREFIXES = ("_wordcraft_", "wordcraft_", "_documentos_editor_")
_IDENTITY_KEY = "_wordcraft_identity"


def _get(session: Any, key: str, default=None):
    getter = getattr(session, "get", None)
    return getter(key, default) if callable(getter) else getattr(session, key, default)


def identity(session: MutableMapping | Any) -> tuple[str | None, ...]:
    """Return the security identity from Streamlit or its attribute-style stubs."""
    user = _get(session, "usuario")
    if not isinstance(user, dict):
        user = {}
    value = (
        user.get("id"),
        user.get("auth_user_id"),
        user.get("login"),
        user.get("tenant_id"),
        user.get("secretaria_id"),
        _get(session, "tenant_id"),
    )
    return tuple(item if isinstance(item, str) else None for item in value)


def clear(session: MutableMapping | Any) -> None:
    """Remove every document-owned value and widget from this session."""
    keys = tuple(session) if isinstance(session, MutableMapping) else tuple(vars(session))
    for key in keys:
        if isinstance(key, str) and key.startswith(_PREFIXES):
            if isinstance(session, MutableMapping):
                session.pop(key, None)
            elif hasattr(session, key):
                delattr(session, key)


def bind(session: MutableMapping | Any) -> bool:
    """Bind WordCraft state to the current identity, revoking stale state."""
    current = identity(session)
    previous = _get(session, _IDENTITY_KEY)
    if previous is not None and previous != current:
        clear(session)
    if isinstance(session, MutableMapping):
        session[_IDENTITY_KEY] = current
    else:
        setattr(session, _IDENTITY_KEY, current)
    return previous is not None and previous != current
