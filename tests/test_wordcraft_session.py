from src import auth, db, wordcraft_session


class Session(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error

    def __setattr__(self, key, value):
        self[key] = value


def _session():
    return {
        "usuario": {"id": "u-a", "auth_user_id": "auth-a", "login": "a",
                    "tenant_id": "tenant-a", "secretaria_id": "secretary-a"},
        "tenant_id": "tenant-a",
    }


def test_clear_revokes_owner_bridges_documents_preparations_widgets_and_component_state():
    session = _session()
    session.update({
        "_wordcraft_owner": object(),
        "_wordcraft_tr_document": b"private checkpoint",
        "_wordcraft_tr_preparation": {"private": True},
        "_wordcraft_tr_patch_reason": "private draft",
        "wordcraft_11111111-1111-1111-1111-111111111111": {"edit": "private"},
        "_documentos_editor_contexto": {"tr": "private text"},
        "unrelated_preference": "keep",
    })

    wordcraft_session.clear(session)

    assert not any(key.startswith(wordcraft_session._PREFIXES) for key in session)
    assert session["unrelated_preference"] == "keep"


def test_bind_preserves_same_identity_and_revokes_everything_after_direct_change():
    session = _session()
    assert wordcraft_session.bind(session) is False
    owner = object()
    session["_wordcraft_owner"] = owner
    assert wordcraft_session.bind(session) is False
    assert session["_wordcraft_owner"] is owner

    session["usuario"]["secretaria_id"] = "secretary-b"
    assert wordcraft_session.bind(session) is True
    assert "_wordcraft_owner" not in session
    assert session["_wordcraft_identity"] == wordcraft_session.identity(session)


def test_identity_never_uses_token_or_arbitrary_user_metadata():
    session = _session()
    first = wordcraft_session.identity(session)
    session["usuario"]["_token"] = "secret"
    session["usuario"]["display_name"] = "Changed"
    assert wordcraft_session.identity(session) == first


def test_logout_revokes_native_owner_private_bytes_and_component_events(monkeypatch):
    session = Session(_session())
    session.update({
        db.CHAVE_DA_SESSAO: "private-jwt",
        "dados": {"private": True}, "documentos": {"tr": "private"},
        "aprovados": {"tr"}, "processo_id": "process-a", "etapa": 4,
        "_wordcraft_owner": object(), "_wordcraft_tr_document": b"private",
        "_wordcraft_tr_preparation": {"private": True},
        "wordcraft_11111111-1111-1111-1111-111111111111": {"edit": "private"},
        "_documentos_editor_contexto": {"tr": "private"},
    })
    monkeypatch.setattr(auth, "st", type("St", (), {"session_state": session})())

    auth.sair()

    assert session[db.CHAVE_DA_SESSAO] == ""
    assert session["usuario"] is None and session["tenant_id"] is None
    assert session["dados"] == session["documentos"] == {}
    assert session["aprovados"] == set() and session["processo_id"] is None
    assert not any(key.startswith(wordcraft_session._PREFIXES) for key in session)


def test_login_as_another_identity_revokes_native_state_before_storing_user(monkeypatch):
    session = Session(_session())
    old_owner = object()
    session["_wordcraft_owner"] = old_owner
    session["_wordcraft_tr_document"] = b"private"
    monkeypatch.setattr(auth, "st", type("St", (), {"session_state": session})())

    auth.entrar({"id": "u-b", "auth_user_id": "auth-b", "login": "b",
                "tenant_id": "tenant-b", "secretaria_id": "secretary-b",
                "_token": "new-private-jwt"})

    assert "_wordcraft_owner" not in session
    assert "_wordcraft_tr_document" not in session
    assert session["usuario"]["id"] == "u-b"
    assert session["tenant_id"] == "tenant-b"
    assert session[db.CHAVE_DA_SESSAO] == "new-private-jwt"


def test_platform_login_without_tenant_cannot_inherit_previous_tenant(monkeypatch):
    session = Session(_session())
    session["_wordcraft_owner"] = object()
    monkeypatch.setattr(auth, "st", type("St", (), {"session_state": session})())

    auth.entrar({"id": "platform-admin", "auth_user_id": "platform-auth",
                "login": "platform", "tenant_id": None,
                "secretaria_id": None, "_token": "platform-jwt"})

    assert session["tenant_id"] is None
    assert "_wordcraft_owner" not in session
