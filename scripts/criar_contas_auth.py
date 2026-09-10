#!/usr/bin/env python3
"""Cria contas no Supabase Auth sem adivinhar identidade nem autorização.

O arquivo de entrada contém SOMENTE a identidade declarada pelo operador:

    [
      {"usuario_id": "<uuid de public.usuarios>", "auth_email": "pessoa@org.br"}
    ]

Papel, tenant, secretaria e papel de governança NUNCA vêm do JSON. Eles são
lidos de ``public.usuarios`` e gravados em ``app_metadata`` pela Admin API.
Assim o arquivo não pode escalar privilégio por erro de digitação.

Por padrão nada é criado. ``--aplicar`` envia convite pelo Supabase Auth e,
logo depois, grava o ``app_metadata`` institucional. Se a segunda etapa
falhar, a conta pode existir sem escopo; isso é seguro porque o script de
vínculo recusará a conta até o metadata ser corrigido.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import uuid
from urllib.parse import urlparse

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ErroCriacao(Exception):
    """Recusa deliberada antes de criar ou alterar identidade."""


def project_ref_da_url(url: str) -> str:
    host = (urlparse(url).hostname or "").strip().lower()
    if not host.endswith(".supabase.co"):
        return ""
    return host.removesuffix(".supabase.co")


def conferir_projeto(url: str, esperado: str) -> None:
    atual = project_ref_da_url(url)
    if not atual:
        raise ErroCriacao("SUPABASE_URL não identifica um projeto hospedado válido")
    if atual != esperado:
        raise ErroCriacao(
            f"projeto divergente: esperado {esperado}, SUPABASE_URL aponta para {atual}")


def ler_mapa(caminho: pathlib.Path) -> list[dict]:
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErroCriacao(f"mapa não encontrado: {caminho}") from None
    except json.JSONDecodeError as erro:
        raise ErroCriacao(f"mapa não é JSON válido: {erro}") from None

    if not isinstance(bruto, list) or not bruto:
        raise ErroCriacao("o mapa precisa ser uma lista não vazia")

    saida: list[dict] = []
    usuarios: set[str] = set()
    emails: set[str] = set()
    for indice, item in enumerate(bruto, start=1):
        if not isinstance(item, dict) or set(item) != {"usuario_id", "auth_email"}:
            raise ErroCriacao(
                f"item {indice}: use exatamente `usuario_id` e `auth_email`")
        try:
            usuario_id = str(uuid.UUID(str(item["usuario_id"]).strip()))
        except (ValueError, AttributeError):
            raise ErroCriacao(f"item {indice}: `usuario_id` não é UUID válido") from None
        email = str(item["auth_email"] or "").strip().lower()
        if not _EMAIL.match(email):
            raise ErroCriacao(f"item {indice}: e-mail inválido")
        if usuario_id in usuarios:
            raise ErroCriacao(f"usuario_id repetido: {usuario_id}")
        if email in emails:
            raise ErroCriacao(f"e-mail repetido: {email}")
        usuarios.add(usuario_id)
        emails.add(email)
        saida.append({"usuario_id": usuario_id, "auth_email": email})
    return saida


def app_metadata_da_linha(linha: dict) -> dict:
    papel = str(linha.get("papel") or "").strip()
    tenant = str(linha.get("tenant_id") or "").strip()
    if papel not in {"admin", "usuario"}:
        raise ErroCriacao(f"papel inválido em usuarios: {papel or '(vazio)'}")
    try:
        tenant = str(uuid.UUID(tenant))
    except ValueError:
        raise ErroCriacao("tenant_id inválido em usuarios") from None

    meta = {"papel": papel, "tenant_id": tenant}
    secretaria = str(linha.get("secretaria_id") or "").strip()
    if secretaria:
        try:
            meta["secretaria_id"] = str(uuid.UUID(secretaria))
        except ValueError:
            raise ErroCriacao("secretaria_id inválido em usuarios") from None
    governanca = str(linha.get("papel_governanca") or "").strip()
    if governanca:
        meta["papel_governanca"] = governanca
    return meta


def _contas_do_auth(cliente) -> list[dict]:
    contas: list[dict] = []
    pagina = 1
    while True:
        lote = cliente.auth.admin.list_users(page=pagina, per_page=200)
        usuarios = getattr(lote, "users", lote) or []
        if not usuarios:
            break
        for conta in usuarios:
            contas.append({
                "id": str(getattr(conta, "id", "")),
                "email": (getattr(conta, "email", "") or "").strip().lower(),
            })
        if len(usuarios) < 200:
            break
        pagina += 1
    return contas


def montar_plano(cliente, mapa: list[dict]) -> list[dict]:
    ids = [item["usuario_id"] for item in mapa]
    resposta = (cliente.table("usuarios")
                .select("id, nome, papel, tenant_id, secretaria_id, "
                        "papel_governanca, auth_user_id, ativo")
                .in_("id", ids).execute())
    linhas = {str(linha["id"]): linha for linha in (resposta.data or [])}
    existentes = _contas_do_auth(cliente)
    emails_existentes = {c["email"] for c in existentes if c["email"]}

    plano: list[dict] = []
    for item in mapa:
        linha = linhas.get(item["usuario_id"])
        if linha is None:
            raise ErroCriacao(f"usuarios não tem a linha {item['usuario_id']}")
        if not bool(linha.get("ativo")):
            raise ErroCriacao(f"usuário inativo: {item['usuario_id']}")
        if linha.get("auth_user_id"):
            raise ErroCriacao(
                f"usuário {item['usuario_id']} já possui auth_user_id; não criar outra conta")
        if item["auth_email"] in emails_existentes:
            raise ErroCriacao(
                f"já existe conta Auth para {item['auth_email']}; revise e use o vínculo, não crie duplicata")
        plano.append({
            "usuario_id": item["usuario_id"],
            "nome": str(linha.get("nome") or ""),
            "email": item["auth_email"],
            "app_metadata": app_metadata_da_linha(linha),
        })
    return plano


def _usuario_da_resposta(resposta):
    usuario = getattr(resposta, "user", None) or getattr(
        getattr(resposta, "data", None), "user", None)
    if usuario is None and getattr(resposta, "id", None):
        usuario = resposta
    return usuario


def aplicar(cliente, plano: list[dict]) -> list[dict]:
    criadas: list[dict] = []
    for item in plano:
        convite = cliente.auth.admin.invite_user_by_email(item["email"])
        usuario = _usuario_da_resposta(convite)
        uid = str(getattr(usuario, "id", "") or "")
        if not uid:
            raise ErroCriacao(
                f"convite para {item['email']} não retornou UID; pare antes de vincular")
        cliente.auth.admin.update_user_by_id(
            uid, {"app_metadata": item["app_metadata"]})
        criadas.append({"usuario_id": item["usuario_id"],
                        "email": item["email"], "auth_uid": uid})
    return criadas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cria contas Supabase Auth a partir de identidades declaradas")
    parser.add_argument("--mapa", required=True, type=pathlib.Path)
    parser.add_argument("--projeto-ref", required=True,
                        help="project ref esperado; evita apontar para o projeto errado")
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args(argv)

    from src import db  # noqa: PLC0415 — import tardio; `src` é PACOTE

    try:
        mapa = ler_mapa(args.mapa)
        url = db._segredo("SUPABASE_URL")  # noqa: SLF001
        conferir_projeto(url, args.projeto_ref)
        if not db.disponivel():
            raise ErroCriacao(
                "banco indisponível; confira SUPABASE_URL e SUPABASE_SECRET_KEY")
        cliente = db._cliente()  # noqa: SLF001
        plano = montar_plano(cliente, mapa)
    except ErroCriacao as erro:
        print(f"RECUSADO: {erro}")
        return 2
    except Exception:
        print("RECUSADO: falha ao conferir Auth/banco. Consulte o log seguro do servidor.")
        return 2

    print(f"Projeto conferido: {args.projeto_ref}")
    print(f"Contas a criar: {len(plano)}")
    for item in plano:
        print(f"  - {item['nome']} <{item['email']}>")
        print(f"      usuario={item['usuario_id']}")
        print(f"      app_metadata={json.dumps(item['app_metadata'], sort_keys=True)}")

    if not args.aplicar:
        print("\nNada foi criado. Revise pessoa, e-mail e escopo antes de usar --aplicar.")
        return 0

    try:
        criadas = aplicar(cliente, plano)
    except ErroCriacao as erro:
        print(f"RECUSADO DURANTE A CRIAÇÃO: {erro}")
        return 2
    except Exception:
        print("RECUSADO DURANTE A CRIAÇÃO: falha da Admin API. Não vincule contas até revisar o estado no Auth.")
        return 2

    print("\nContas criadas/invitadas:")
    for item in criadas:
        print(f"  - usuario={item['usuario_id']} auth_uid={item['auth_uid']} email={item['email']}")
    print("Não vincule ainda: rode o dry-run de scripts/aplicar_vinculos_auth.py com estes UIDs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
