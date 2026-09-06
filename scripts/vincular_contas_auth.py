#!/usr/bin/env python3
"""
Vincula os `usuarios` do produto às contas do Supabase Auth e preenche
`processos.auth_user_id`.

É a MIGRAÇÃO DE DADOS que a 0020 deliberadamente não fez. A 0020 criou
a coluna e as políticas; ligar linha a conta é ato administrativo, com
consequência de acesso, e não pertence a um arquivo de schema que roda
sozinho num deploy.

POR QUE ISTO NÃO É AUTOMÁTICO
-----------------------------
Não há e-mail em `public.usuarios`. A tabela tem `login`, e os logins
em produção (medidos em 06/09/2026) NÃO são endereços de e-mail. Não
existe, portanto, chave natural entre `usuarios` e `auth.users`:
qualquer casamento automático seria adivinhação, e adivinhar errado
aqui entrega o processo de um servidor à conta de outro.

Por isso o vínculo é DECLARADO, num arquivo que uma pessoa escreve e
confere:

    [
      {"usuario_id": "679d43c6-...", "auth_email": "fulano@example.org"},
      {"usuario_id": "d76ab816-...", "auth_email": "beltrano@example.net"}
    ]

`auth_uid` pode substituir `auth_email` quando se prefere apontar a
conta pelo identificador.

O QUE O SCRIPT RECUSA (e recusar é o ponto)
-------------------------------------------
* e-mail que não existe no Auth, ou que casa com mais de uma conta;
* `usuario_id` que não existe, ou já vinculado a OUTRA conta;
* duas linhas do mapa apontando para a mesma conta, ou o mesmo usuário
  aparecendo duas vezes;
* `app_metadata` da conta divergindo de `usuarios` em papel, tenant,
  secretaria ou papel de governança.

A última é a que mais importa e a menos óbvia. Quem decide o que o RLS
enxerga é o JWT, não a tabela: `tenant_do_jwt()`, `secretaria_do_jwt()`
e `e_admin()` leem `app_metadata`. Se a conta disser "tenant A" e a
linha disser "tenant B", o servidor entra e vê o município errado —
com a tela mostrando o certo. Vincular nesse estado é pior do que não
vincular.

E é `app_metadata`, nunca `user_metadata`: o segundo é editável pelo
próprio titular pela API do cliente. Papel gravado ali é papel que o
usuário se dá sozinho.

Forma esperada do `app_metadata`:

    {"papel": "admin" | "usuario",
     "tenant_id": "<uuid>",
     "secretaria_id": "<uuid ou ausente>",
     "papel_governanca": "<texto, opcional>"}

USO
---
    # confere e não grava nada (padrão)
    python scripts/vincular_contas_auth.py --mapa vinculos.json

    # grava, depois de o relatório acima estar limpo
    python scripts/vincular_contas_auth.py --mapa vinculos.json --aplicar

Credenciais vêm de `SUPABASE_URL` e `SUPABASE_SECRET_KEY` pelo mesmo
caminho do produto (`src/db.py`). O script NÃO imprime a chave.

O relatório traz e-mails de servidores públicos: é o que a pessoa
precisa conferir. Não cole a saída em issue, PR ou chat de terceiros.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "src"))

CAMPOS_DO_ESCOPO = ("papel", "tenant_id", "secretaria_id", "papel_governanca")


class ErroVinculo(Exception):
    """Recusa deliberada. A mensagem diz o que corrigir."""


# ---------------------------------------------------------------------------
# Leitura do mapa
# ---------------------------------------------------------------------------
def ler_mapa(caminho: pathlib.Path) -> list[dict]:
    """
    Lê e valida a FORMA do mapa. Conteúdo é conferido depois, contra o
    banco — aqui só se recusa o que já dá para recusar sem rede.
    """
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErroVinculo(f"mapa não encontrado: {caminho}") from None
    except json.JSONDecodeError as erro:
        raise ErroVinculo(f"mapa não é JSON válido: {erro}") from None

    if not isinstance(bruto, list) or not bruto:
        raise ErroVinculo("o mapa precisa ser uma lista não vazia de vínculos")

    vinculos: list[dict] = []
    vistos_usuario: set[str] = set()
    vistos_conta: set[str] = set()
    for indice, item in enumerate(bruto, start=1):
        if not isinstance(item, dict):
            raise ErroVinculo(f"vínculo {indice}: esperava um objeto")
        usuario = str(item.get("usuario_id") or "").strip()
        email = str(item.get("auth_email") or "").strip().lower()
        uid = str(item.get("auth_uid") or "").strip()
        if not usuario:
            raise ErroVinculo(f"vínculo {indice}: falta `usuario_id`")
        if bool(email) == bool(uid):
            raise ErroVinculo(
                f"vínculo {indice}: informe `auth_email` OU `auth_uid`, "
                "exatamente um dos dois")
        # Duplicata no próprio mapa é erro de digitação com consequência
        # de acesso: duas linhas para o mesmo usuário deixariam o
        # resultado dependendo da ordem de aplicação.
        if usuario in vistos_usuario:
            raise ErroVinculo(f"`usuario_id` repetido no mapa: {usuario}")
        chave_conta = email or uid
        if chave_conta in vistos_conta:
            raise ErroVinculo(f"a mesma conta aparece duas vezes: {chave_conta}")
        vistos_usuario.add(usuario)
        vistos_conta.add(chave_conta)
        vinculos.append({"usuario_id": usuario, "auth_email": email,
                         "auth_uid": uid})
    return vinculos


# ---------------------------------------------------------------------------
# Conferência
# ---------------------------------------------------------------------------
def _contas_do_auth(cliente) -> list[dict]:
    """
    Lista as contas do Supabase Auth pela API de administração.

    `list_users` pagina; um município pequeno cabe numa página, mas
    depender disso faria o script casar errado justamente quando a
    prefeitura crescesse.
    """
    contas: list[dict] = []
    pagina = 1
    while True:
        lote = cliente.auth.admin.list_users(page=pagina, per_page=200)
        # A lib já devolveu tanto uma lista quanto um objeto com
        # `.users` conforme a versão; aceitar os dois evita que uma
        # atualização de dependência quebre a migração de dados.
        usuarios = getattr(lote, "users", lote) or []
        if not usuarios:
            break
        for conta in usuarios:
            contas.append({
                "id": str(getattr(conta, "id", "")),
                "email": (getattr(conta, "email", "") or "").strip().lower(),
                "app_metadata": dict(getattr(conta, "app_metadata", {}) or {}),
            })
        if len(usuarios) < 200:
            break
        pagina += 1
    return contas


def _achar_conta(vinculo: dict, contas: list[dict]) -> dict:
    if vinculo["auth_uid"]:
        achadas = [c for c in contas if c["id"] == vinculo["auth_uid"]]
        alvo = vinculo["auth_uid"]
    else:
        achadas = [c for c in contas if c["email"] == vinculo["auth_email"]]
        alvo = vinculo["auth_email"]
    if not achadas:
        raise ErroVinculo(f"nenhuma conta no Auth para {alvo}")
    if len(achadas) > 1:
        raise ErroVinculo(
            f"{len(achadas)} contas no Auth para {alvo} — desfaça a "
            "ambiguidade antes de vincular")
    return achadas[0]


def _divergencias_de_escopo(linha: dict, conta: dict) -> list[str]:
    """
    Compara `app_metadata` com a linha de `usuarios`, campo a campo.

    Ausente e vazio são tratados como iguais: `secretaria_id` é
    NULLABLE desde a 0007, e uma conta sem a chave não está em
    desacordo com uma linha sem secretaria.
    """
    meta = conta["app_metadata"]
    fora: list[str] = []
    for campo in CAMPOS_DO_ESCOPO:
        na_linha = str(linha.get(campo) or "").strip()
        na_conta = str(meta.get(campo) or "").strip()
        if na_linha != na_conta:
            fora.append(
                f"{campo}: usuarios={na_linha or '(vazio)'} "
                f"× app_metadata={na_conta or '(vazio)'}")
    if "papel" not in meta:
        fora.append("papel: ausente no app_metadata — o JWT sairia sem papel")
    return fora


def conferir(cliente, vinculos: list[dict]) -> list[dict]:
    """
    Devolve o plano: um item por vínculo, com a conta resolvida e o que
    seria escrito. Levanta na PRIMEIRA recusa — plano meio conferido
    não é plano.
    """
    contas = _contas_do_auth(cliente)
    ids = [v["usuario_id"] for v in vinculos]
    resposta = (cliente.table("usuarios")
                .select("id, nome, papel, tenant_id, secretaria_id, "
                        "papel_governanca, auth_user_id, ativo")
                .in_("id", ids).execute())
    linhas = {str(l["id"]): l for l in (resposta.data or [])}

    plano: list[dict] = []
    for vinculo in vinculos:
        uid_usuario = vinculo["usuario_id"]
        linha = linhas.get(uid_usuario)
        if linha is None:
            raise ErroVinculo(f"`usuarios` não tem a linha {uid_usuario}")
        conta = _achar_conta(vinculo, contas)

        ja = str(linha.get("auth_user_id") or "")
        if ja and ja != conta["id"]:
            raise ErroVinculo(
                f"{uid_usuario} já está vinculado a OUTRA conta ({ja}). "
                "Desfazer vínculo é decisão administrativa: o script não "
                "sobrescreve.")

        fora = _divergencias_de_escopo(linha, conta)
        if fora:
            raise ErroVinculo(
                f"escopo divergente em {uid_usuario} ({conta['email']}):\n"
                + "\n".join(f"    - {d}" for d in fora)
                + "\n  Corrija o `app_metadata` da conta (nunca o "
                  "`user_metadata`) e rode de novo. Vincular assim faria "
                  "o RLS julgar por um escopo e a tela mostrar outro.")

        plano.append({
            "usuario_id": uid_usuario,
            "nome": linha.get("nome", ""),
            "email": conta["email"],
            "auth_uid": conta["id"],
            "ja_vinculado": bool(ja),
            "ativo": bool(linha.get("ativo")),
        })
    return plano


def processos_a_preencher(cliente, plano: list[dict]) -> dict[str, int]:
    """
    Conta os processos que ganhariam dono, por usuário.

    O caminho é determinístico e não envolve adivinhação:
    `processos.usuario_id` → `usuarios.id` → `usuarios.auth_user_id`.
    """
    contagem: dict[str, int] = {}
    for item in plano:
        resposta = (cliente.table("processos")
                    .select("id", count="exact")
                    .eq("usuario_id", item["usuario_id"])
                    .is_("auth_user_id", "null").execute())
        contagem[item["usuario_id"]] = resposta.count or 0
    return contagem


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------
def aplicar(cliente, plano: list[dict]) -> dict[str, int]:
    """
    Escreve. Usuário primeiro, processos depois — nesta ordem, porque a
    segunda etapa lê o resultado da primeira.

    Sem transação: o PostgREST não a oferece por aqui. Por isso cada
    escrita é idempotente e condicionada, e rodar de novo depois de uma
    queda no meio termina o que faltou em vez de duplicar.
    """
    escritos = {"usuarios": 0, "processos": 0}
    for item in plano:
        if not item["ja_vinculado"]:
            (cliente.table("usuarios")
             .update({"auth_user_id": item["auth_uid"]})
             .eq("id", item["usuario_id"])
             .is_("auth_user_id", "null").execute())
            escritos["usuarios"] += 1

        resposta = (cliente.table("processos")
                    .update({"auth_user_id": item["auth_uid"]})
                    .eq("usuario_id", item["usuario_id"])
                    .is_("auth_user_id", "null").execute())
        escritos["processos"] += len(resposta.data or [])
    return escritos


def orfaos(cliente) -> int:
    """
    Processos que não ganhariam dono nem depois deste mapa.

    Um processo sem `auth_user_id` fica invisível para o dono sob o RLS
    da 0020 — some da tela sem nenhuma mensagem. Contar é obrigatório;
    calar seria entregar a migração pela metade.
    """
    resposta = (cliente.table("processos").select("id", count="exact")
                .is_("auth_user_id", "null").execute())
    return resposta.count or 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Vincula usuarios a contas do Supabase Auth e "
                    "preenche processos.auth_user_id.")
    parser.add_argument("--mapa", required=True, type=pathlib.Path,
                        help="JSON com os vínculos declarados")
    parser.add_argument("--aplicar", action="store_true",
                        help="grava. Sem isto, só confere e relata.")
    args = parser.parse_args(argv)

    import db  # noqa: PLC0415 — import tardio: o app abre sem a lib

    try:
        vinculos = ler_mapa(args.mapa)
        if not db.disponivel():
            raise ErroVinculo(
                "banco indisponível: defina SUPABASE_URL e "
                "SUPABASE_SECRET_KEY (o script não lê nem imprime a chave).")
        cliente = db._cliente()  # noqa: SLF001 — é a credencial de servidor
        plano = conferir(cliente, vinculos)
        pendentes = processos_a_preencher(cliente, plano)
    except ErroVinculo as erro:
        print(f"RECUSADO: {erro}")
        return 2

    print(f"Vínculos conferidos: {len(plano)}")
    for item in plano:
        marca = "já vinculado" if item["ja_vinculado"] else "a vincular"
        inativo = "" if item["ativo"] else "  [INATIVO]"
        print(f"  - {item['nome']} <{item['email']}>{inativo}")
        print(f"      usuarios={item['usuario_id']}  auth={item['auth_uid']}"
              f"  ({marca})")
        print(f"      processos sem dono a preencher: "
              f"{pendentes[item['usuario_id']]}")

    antes = orfaos(cliente)
    somados = sum(pendentes.values())
    print(f"\nProcessos sem `auth_user_id` hoje: {antes}")
    print(f"Este mapa preencheria: {somados}")
    if antes - somados > 0:
        print(f"SOBRARIAM {antes - somados} processos sem dono — eles ficam "
              "invisíveis para o titular sob o RLS da 0020. Amplie o mapa "
              "ou decida explicitamente o que fazer com eles.")

    if not args.aplicar:
        print("\nNada foi gravado (modo de conferência). "
              "Use --aplicar quando o relatório acima estiver como você quer.")
        return 0

    escritos = aplicar(cliente, plano)
    print(f"\nGravado: {escritos['usuarios']} usuários vinculados, "
          f"{escritos['processos']} processos com dono.")
    print(f"Processos ainda sem `auth_user_id`: {orfaos(cliente)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
