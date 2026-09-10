#!/usr/bin/env python3
"""Gate operacional para aplicar o mapa de vínculos do Supabase Auth.

Mantém ``scripts/vincular_contas_auth.py`` como motor e acrescenta duas
barreiras que não podem depender só da atenção do operador:

1. o ``project ref`` da SUPABASE_URL precisa ser exatamente o declarado;
2. uma aplicação completa recusa se o mapa deixar processos sem auth_user_id.

Para o primeiro usuário de teste, ``--canario`` permite sobras de propósito,
mas exige mapa com exatamente um vínculo. A flag ``price_research`` precisa
permanecer ``off`` durante toda a operação.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from urllib.parse import urlparse

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import vincular_contas_auth as vinc  # noqa: E402


class ErroGate(vinc.ErroVinculo):
    pass


def project_ref_da_url(url: str) -> str:
    host = (urlparse(url).hostname or "").strip().lower()
    if not host.endswith(".supabase.co"):
        return ""
    return host.removesuffix(".supabase.co")


def conferir_projeto(url: str, esperado: str) -> None:
    atual = project_ref_da_url(url)
    if not atual:
        raise ErroGate("SUPABASE_URL não identifica projeto Supabase hospedado")
    if atual != esperado:
        raise ErroGate(
            f"projeto divergente: esperado {esperado}, SUPABASE_URL aponta para {atual}")


def flag_price_research_desligada(cliente) -> bool:
    resposta = (cliente.table("config_app").select("valor")
                .eq("chave", "flag_price_research").limit(1).execute())
    linhas = resposta.data or []
    return len(linhas) == 1 and str(linhas[0].get("valor") or "").lower() == "off"


def validar_sobras(antes: int, a_preencher: int, *, canario: bool,
                    quantidade_vinculos: int) -> int:
    sobras = antes - a_preencher
    if sobras < 0:
        raise ErroGate("contagem impossível: mapa preencheria mais processos que os órfãos atuais")
    if canario:
        if quantidade_vinculos != 1:
            raise ErroGate("--canario exige mapa com exatamente um vínculo")
        return sobras
    if sobras:
        raise ErroGate(
            f"aplicação completa deixaria {sobras} processos sem auth_user_id; amplie o mapa")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aplica vínculos Auth com gate de projeto, flag e órfãos")
    parser.add_argument("--mapa", required=True, type=pathlib.Path)
    parser.add_argument("--projeto-ref", required=True)
    parser.add_argument("--canario", action="store_true",
                        help="permite processos restantes; mapa deve ter um único usuário")
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args(argv)

    from src import db  # noqa: PLC0415 — import tardio; `src` é PACOTE

    try:
        mapa = vinc.ler_mapa(args.mapa)
        conferir_projeto(db._segredo("SUPABASE_URL"), args.projeto_ref)  # noqa: SLF001
        if not db.disponivel():
            raise ErroGate("banco indisponível ou credencial de servidor sem capacidade")
        cliente = db._cliente()  # noqa: SLF001
        if not flag_price_research_desligada(cliente):
            raise ErroGate("flag_price_research precisa permanecer off durante o vínculo")

        plano = vinc.conferir(cliente, mapa)
        inconsistentes = vinc.processos_inconsistentes(cliente, plano)
        if inconsistentes:
            p = inconsistentes[0]
            raise ErroGate(
                f"processo {p['processo_id']} já possui dono divergente {p['encontrado']}")
        pendentes = vinc.processos_a_preencher(cliente, plano)
        antes = vinc.orfaos(cliente)
        preencher = sum(pendentes.values())
        sobras = validar_sobras(antes, preencher, canario=args.canario,
                                quantidade_vinculos=len(plano))
    except vinc.ErroVinculo as erro:
        print(f"RECUSADO: {erro}")
        return 2

    print(f"Projeto conferido: {args.projeto_ref}")
    print("flag_price_research: off")
    print(f"Vínculos conferidos: {len(plano)}")
    for item in plano:
        print(f"  - {item['nome']} <{item['email']}> auth={item['auth_uid']}")
        print(f"      processos a preencher: {pendentes[item['usuario_id']]}")
    print(f"Processos sem auth_user_id agora: {antes}")
    print(f"Processos que este mapa preencheria: {preencher}")
    print(f"Processos que sobrariam: {sobras}")

    if not args.aplicar:
        print("\nNada foi gravado. Revise o relatório antes de usar --aplicar.")
        return 0

    try:
        escritos = vinc.aplicar(cliente, plano)
        depois = vinc.orfaos(cliente)
        if not args.canario and depois != 0:
            raise ErroGate(
                f"validação posterior encontrou {depois} processos sem auth_user_id; mantenha a flag off")
    except vinc.ErroVinculo as erro:
        print(f"RECUSADO DURANTE A APLICAÇÃO: {erro}")
        return 2

    print(f"\nGravado: {escritos['usuarios']} usuários e {escritos['processos']} processos.")
    print(f"Processos ainda sem auth_user_id: {depois}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
