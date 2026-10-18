"""Revocation boundary for document state kept in a Streamlit session.

The browser component, native owner and prepared operations are scoped to the
authenticated identity.  They must never survive logout or an identity change
inside the same browser session.
"""
from __future__ import annotations

from collections.abc import MutableMapping

_PREFIXES = ("_wordcraft_", "wordcraft_", "_documentos_editor_")
_IDENTITY_KEY = "_wordcraft_identity"


def identity(session: MutableMapping) -> tuple[str | None, ...]:
    user = session.get("usuario")
    if not isinstance(user, dict):
        user = {}
    value = (
        user.get("id"),
        user.get("auth_user_id"),
        user.get("login"),
        user.get("tenant_id"),
        user.get("secretaria_id"),
        session.get("tenant_id"),
    )
    return tuple(item if isinstance(item, str) else None for item in value)


def clear(session: MutableMapping) -> None:
    """Remove every document-owned value and widget from this session."""
    for key in tuple(session):
        if isinstance(key, str) and key.startswith(_PREFIXES):
            session.pop(key, None)


def bind(session: MutableMapping) -> bool:
    """Bind WordCraft state to the current identity, revoking stale state."""
    current = identity(session)
    previous = session.get(_IDENTITY_KEY)
    if previous is not None and previous != current:
        clear(session)
    session[_IDENTITY_KEY] = current
    return previous is not None and previous != current
