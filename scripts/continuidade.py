#!/usr/bin/env python3
"""
Continuidade de tarefa de implementação: objetivo, critérios de aceite,
evidências, pendências e próxima ação — num arquivo que sobrevive à sessão.

Serve a quem DESENVOLVE (camada `.claude/`), nunca ao produto: nada em
`src/` importa isto. Só biblioteca padrão, porque roda dentro de gancho.

    python scripts/continuidade.py iniciar --objetivo "..." \\
        --criterio "C1: provas de preços verdes" --criterio "C2: PR mesclado"
    python scripts/continuidade.py provar C1 --arquivos src/precos tests \\
        --barato -- python -m pytest -q tests/test_precos_jev.py
    python scripts/continuidade.py etapa "migração 0045 aplicada"
    python scripts/continuidade.py proxima "abrir o PR"
    python scripts/continuidade.py bloquear --motivo "senha da chave SSH" \\
        --falta "o dono digitar a senha na aba do Terminal"
    python scripts/continuidade.py status
    python scripts/continuidade.py concluir      # só fecha com tudo provado

**Critério só fica cumprido por evidência EXECUTADA**: `provar` roda o
comando, grava o log com hash, o código de saída e a assinatura dos
arquivos que o comando cobre. Não existe "marcar como feito". Se os
arquivos cobertos mudam depois, a evidência vence e precisa ser refeita
— o gancho Stop refaz sozinho as marcadas `--barato`; as caras ele pede.

Estado: `.claude/continuidade/estado.json` (máquina) e
`.claude/continuidade/CONTINUIDADE.md` (gente), ambos fora do git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VERSAO = 1
# arquivos da própria continuidade não entram na assinatura do código
_IGNORAR = (".claude/continuidade/",)
SEGUNDOS_BARATO = 120


# ---------------------------------------------------------------------------
# Onde mora
# ---------------------------------------------------------------------------
def _caminho_nativo(texto: str) -> str:
    """`/c/Users/...` (Git Bash) vira `C:/Users/...` no Python do Windows."""
    if os.name == "nt" and len(texto) > 2 and texto[0] == "/" and texto[2] == "/" \
            and texto[1].isalpha():
        return f"{texto[1].upper()}:{texto[2:]}"
    return texto


def raiz(inicio: str | os.PathLike | None = None) -> Path:
    candidatos = [inicio, os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()]
    for candidato in candidatos:
        if not candidato:
            continue
        base = Path(_caminho_nativo(str(candidato)))
        if not base.is_dir():
            continue
        try:
            saida = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=base,
                                   capture_output=True, text=True, timeout=20)
            if saida.returncode == 0 and saida.stdout.strip():
                return Path(_caminho_nativo(saida.stdout.strip()))
        except (OSError, subprocess.SubprocessError):
            continue
    return Path(os.getcwd()).resolve()


def pasta(r: Path) -> Path:
    return r / ".claude" / "continuidade"


def caminho_estado(r: Path) -> Path:
    return pasta(r) / "estado.json"


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def carregar(r: Path) -> dict | None:
    arq = caminho_estado(r)
    if not arq.exists():
        return None
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"corrompido": True}


def salvar(r: Path, estado: dict) -> None:
    pasta(r).mkdir(parents=True, exist_ok=True)
    (pasta(r) / ".gitignore").write_text("*\n", encoding="utf-8")
    estado["atualizado_em"] = agora()
    tmp = caminho_estado(r).with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(caminho_estado(r))
    (pasta(r) / "CONTINUIDADE.md").write_text(renderizar(r, estado), encoding="utf-8")


# ---------------------------------------------------------------------------
# A versão do código que uma evidência cobre
# ---------------------------------------------------------------------------
def _git(r: Path, *args: str) -> str:
    try:
        saida = subprocess.run(["git", *args], cwd=r, capture_output=True,
                               timeout=60)
        return saida.stdout.decode("utf-8", "replace") if saida.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def head(r: Path) -> str:
    return _git(r, "rev-parse", "HEAD").strip()


def _arquivos_cobertos(r: Path, cobertos: list[str]) -> list[str]:
    """Rastreados e não ignorados dentro dos caminhos dados (vazio = repo)."""
    lista = _git(r, "ls-files", "--cached", "--others", "--exclude-standard",
                 "--", *(cobertos or ["."])).splitlines()
    return sorted({a for a in lista if a and not a.startswith(_IGNORAR)})


def assinatura(r: Path, cobertos: list[str]) -> str:
    """Hash do CONTEÚDO dos arquivos cobertos — muda quando o código muda."""
    h = hashlib.sha256()
    for rel in _arquivos_cobertos(r, cobertos):
        arq = r / rel
        h.update(rel.encode("utf-8") + b"\0")
        try:
            h.update(hashlib.sha256(arq.read_bytes()).digest())
        except OSError:
            h.update(b"<ausente>")
    return h.hexdigest()


def _sha_arquivo(arq: Path) -> str:
    try:
        return hashlib.sha256(arq.read_bytes()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Avaliação — o que o gancho Stop usa
# ---------------------------------------------------------------------------
def avaliar_criterio(r: Path, criterio: dict) -> tuple[str, str]:
    """
    ('ok' | 'sem_evidencia' | 'falhou' | 'adulterada' | 'vencida', explicação).
    A declaração do agente não conta: só o registro de uma execução cujo
    log existe, bate com o hash, saiu com zero e cobre o código de agora.
    """
    ev = criterio.get("evidencia")
    if not ev:
        return "sem_evidencia", "sem evidência executada"
    log = r / ev.get("log", "")
    if not ev.get("log") or not log.exists():
        return "adulterada", "o log da evidência não existe"
    if _sha_arquivo(log) != ev.get("saida_sha256"):
        return "adulterada", "o log não bate com o hash registrado"
    if ev.get("codigo") != 0:
        return "falhou", f"o comando saiu com código {ev.get('codigo')}"
    if assinatura(r, ev.get("arquivos") or []) != ev.get("assinatura"):
        return "vencida", "o código coberto mudou depois da evidência"
    return "ok", f"provado em {ev.get('quando')} ({ev.get('head', '')[:12]})"


ESPERA_MAXIMA_MIN = 120


def espera_valida(estado: dict) -> dict | None:
    """A espera declarada ainda dentro do prazo (`aguardar`), ou None."""
    espera = estado.get("aguardando")
    if not espera or not espera.get("ate"):
        return None
    try:
        ate = datetime.fromisoformat(espera["ate"])
    except ValueError:
        return None
    return espera if datetime.now(timezone.utc) < ate else None


def pendencias(r: Path, estado: dict) -> list[tuple[dict, str, str]]:
    saida = []
    for c in estado.get("criterios", []):
        situacao, porque = avaliar_criterio(r, c)
        if situacao != "ok":
            saida.append((c, situacao, porque))
    return saida


def comando_de_prova(c: dict) -> str:
    ev = c.get("evidencia") or {}
    if ev.get("argv"):
        arquivos = " ".join(ev.get("arquivos") or [])
        extra = (f" --arquivos {arquivos}" if arquivos else "") + (
            " --barato" if ev.get("barato") else "")
        return (f"python scripts/continuidade.py provar {c['id']}{extra} -- "
                + " ".join(ev["argv"]))
    return (f"python scripts/continuidade.py provar {c['id']} "
            "--arquivos <caminhos cobertos> -- <comando que prova o critério>")


# ---------------------------------------------------------------------------
# Execução de evidência
# ---------------------------------------------------------------------------
def executar_prova(r: Path, estado: dict, cid: str, argv: list[str],
                   cobertos: list[str], barato: bool,
                   timeout: int | None = None) -> dict:
    criterio = next((c for c in estado.get("criterios", []) if c["id"] == cid), None)
    if criterio is None:
        raise SystemExit(f"critério desconhecido: {cid}")
    evid = pasta(r) / "evidencias"
    evid.mkdir(parents=True, exist_ok=True)
    inicio = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=r, capture_output=True, timeout=timeout,
                              shell=(os.name == "nt" and len(argv) == 1))
        codigo, saida = proc.returncode, proc.stdout + b"\n--- stderr ---\n" + proc.stderr
    except subprocess.TimeoutExpired:
        codigo, saida = 124, b"tempo esgotado"
    except OSError as exc:
        codigo, saida = 127, f"não executou: {exc}".encode()
    duracao = round(time.monotonic() - inicio, 1)
    nome = f"{cid}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    cabecalho = (f"$ {' '.join(argv)}\n# código {codigo} · {duracao}s · "
                 f"HEAD {head(r)}\n").encode("utf-8")
    (evid / nome).write_bytes(cabecalho + saida)
    criterio["evidencia"] = {
        "argv": argv, "codigo": codigo, "duracao_s": duracao,
        "log": f".claude/continuidade/evidencias/{nome}",
        "saida_sha256": _sha_arquivo(evid / nome),
        "arquivos": cobertos, "assinatura": assinatura(r, cobertos),
        "head": head(r), "barato": barato, "quando": agora(),
    }
    return criterio


# ---------------------------------------------------------------------------
# Texto para gente
# ---------------------------------------------------------------------------
_ROTULO = {"ok": "provado", "sem_evidencia": "pendente", "falhou": "falhou",
           "adulterada": "evidência inválida", "vencida": "evidência vencida"}


def renderizar(r: Path, estado: dict) -> str:
    linhas = [f"# Continuidade — {estado.get('objetivo', '')}", "",
              f"Situação: **{estado.get('situacao', 'em_andamento')}** · "
              f"atualizado em {estado.get('atualizado_em', '')} · "
              f"HEAD {head(r)[:12]}", ""]
    linhas += ["## Critérios de aceite", ""]
    for c in estado.get("criterios", []):
        situacao, porque = avaliar_criterio(r, c)
        linhas.append(f"- [{'x' if situacao == 'ok' else ' '}] **{c['id']}** "
                      f"{c['descricao']} — {_ROTULO[situacao]}: {porque}")
        ev = c.get("evidencia")
        if ev:
            linhas.append(f"  - `{' '.join(ev['argv'])}` → código {ev['codigo']}, "
                          f"log `{ev['log']}`")
    linhas += ["", "## Etapas concluídas", ""]
    linhas += [f"- {e['quando'][:16]} {e['texto']}" for e in estado.get("etapas", [])] or ["- (nenhuma)"]
    linhas += ["", "## Pendências", ""]
    linhas += [f"- {p}" for p in estado.get("pendencias", [])] or ["- (nenhuma registrada)"]
    bloqueio = estado.get("bloqueio_externo")
    if bloqueio:
        linhas += ["", "## Bloqueio externo", "",
                   f"- Motivo: {bloqueio['motivo']}", f"- Falta: {bloqueio['falta']}",
                   f"- Desde: {bloqueio['quando']}"]
    espera = estado.get("aguardando")
    if espera:
        valida = "em curso" if espera_valida(estado) else "VENCIDA — retome"
        linhas += ["", "## Aguardando", "", f"- {espera['o_que']} (até {espera['ate']}, {valida})"]
    linhas += ["", "## Próxima ação", "", estado.get("proxima_acao") or "(não definida)", ""]
    if estado.get("interrupcoes"):
        linhas += ["## Encerramentos sem conclusão", ""]
        linhas += [f"- {i['quando']}: {i['motivo']}" for i in estado["interrupcoes"]]
        linhas.append("")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _exigir(r: Path) -> dict:
    estado = carregar(r)
    if not estado or estado.get("corrompido"):
        raise SystemExit("nenhuma tarefa ativa (use `iniciar`)")
    return estado


def principal(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")  # console do Windows é cp1252
        except (AttributeError, ValueError):
            pass
    args_brutos = list(sys.argv[1:] if argv is None else argv)
    comando_prova: list[str] = []
    if "--" in args_brutos:
        i = args_brutos.index("--")
        args_brutos, comando_prova = args_brutos[:i], args_brutos[i + 1:]

    p = argparse.ArgumentParser(prog="continuidade", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="acao", required=True)
    s = sub.add_parser("iniciar")
    s.add_argument("--objetivo", required=True)
    s.add_argument("--criterio", action="append", default=[],
                   help='"C1: descrição" (repita)')
    s.add_argument("--tipo", default="implementacao")
    s.add_argument("--substituir", action="store_true")
    s = sub.add_parser("criterio")
    s.add_argument("texto", help='"C3: descrição"')
    s = sub.add_parser("provar")
    s.add_argument("id")
    s.add_argument("--arquivos", nargs="*", default=[])
    s.add_argument("--barato", action="store_true",
                   help="o gancho Stop pode refazer sozinho quando vencer")
    s.add_argument("--timeout", type=int, default=None)
    s = sub.add_parser("etapa")
    s.add_argument("texto")
    s = sub.add_parser("pendencia")
    s.add_argument("texto")
    s.add_argument("--resolver", action="store_true")
    s = sub.add_parser("proxima")
    s.add_argument("texto")
    s = sub.add_parser("bloquear")
    s.add_argument("--motivo", required=True)
    s.add_argument("--falta", required=True, help="o que só alguém de fora resolve")
    sub.add_parser("desbloquear")
    s = sub.add_parser("aguardar", help="job em segundo plano que acorda a sessão")
    s.add_argument("o_que", help="o que está rodando (ex.: 'suíte completa, tarefa bg123')")
    s.add_argument("--minutos", type=int, default=30)
    sub.add_parser("retomar", help="encerra a espera declarada")
    sub.add_parser("status")
    sub.add_parser("concluir")
    s = sub.add_parser("encerrar", help="desativa sem concluir (registra o motivo)")
    s.add_argument("--motivo", required=True)
    a = p.parse_args(args_brutos)

    r = raiz()
    if a.acao == "iniciar":
        atual = carregar(r)
        if atual and atual.get("ativo") and not a.substituir:
            raise SystemExit("já há tarefa ativa; use --substituir ou `concluir`")
        criterios = []
        for i, texto in enumerate(a.criterio, 1):
            cid, _, desc = texto.partition(":")
            if not desc:
                cid, desc = f"C{i}", texto
            criterios.append({"id": cid.strip(), "descricao": desc.strip(), "evidencia": None})
        if not criterios:
            raise SystemExit("informe ao menos um --criterio")
        salvar(r, {"versao": VERSAO, "tipo": a.tipo, "ativo": True,
                   "situacao": "em_andamento", "objetivo": a.objetivo,
                   "criado_em": agora(), "criterios": criterios, "etapas": [],
                   "pendencias": [], "proxima_acao": "", "bloqueio_externo": None,
                   "interrupcoes": []})
    elif a.acao == "criterio":
        estado = _exigir(r)
        cid, _, desc = a.texto.partition(":")
        if not desc:
            cid, desc = f"C{len(estado['criterios']) + 1}", a.texto
        estado["criterios"].append({"id": cid.strip(), "descricao": desc.strip(), "evidencia": None})
        salvar(r, estado)
    elif a.acao == "provar":
        if not comando_prova:
            raise SystemExit("informe o comando depois de `--`")
        estado = _exigir(r)
        c = executar_prova(r, estado, a.id, comando_prova, a.arquivos, a.barato, a.timeout)
        salvar(r, estado)
        situacao, porque = avaliar_criterio(r, c)
        print(f"{a.id}: {_ROTULO[situacao]} — {porque}")
        return 0 if situacao == "ok" else 1
    elif a.acao == "etapa":
        estado = _exigir(r)
        estado["etapas"].append({"quando": agora(), "texto": a.texto})
        salvar(r, estado)
    elif a.acao == "pendencia":
        estado = _exigir(r)
        if a.resolver:
            estado["pendencias"] = [x for x in estado["pendencias"] if x != a.texto]
        elif a.texto not in estado["pendencias"]:
            estado["pendencias"].append(a.texto)
        salvar(r, estado)
    elif a.acao == "proxima":
        estado = _exigir(r)
        estado["proxima_acao"] = a.texto
        salvar(r, estado)
    elif a.acao == "bloquear":
        estado = _exigir(r)
        estado["bloqueio_externo"] = {"motivo": a.motivo, "falta": a.falta, "quando": agora()}
        estado["situacao"] = "bloqueado"
        salvar(r, estado)
    elif a.acao == "desbloquear":
        estado = _exigir(r)
        estado["bloqueio_externo"] = None
        estado["situacao"] = "em_andamento"
        salvar(r, estado)
    elif a.acao == "aguardar":
        estado = _exigir(r)
        minutos = max(1, min(a.minutos, ESPERA_MAXIMA_MIN))
        from datetime import timedelta
        estado["aguardando"] = {"o_que": a.o_que, "desde": agora(),
                                "ate": (datetime.now(timezone.utc) + timedelta(minutes=minutos))
                                .isoformat(timespec="seconds")}
        salvar(r, estado)
    elif a.acao == "retomar":
        estado = _exigir(r)
        estado["aguardando"] = None
        salvar(r, estado)
    elif a.acao == "status":
        estado = _exigir(r)
        print(renderizar(r, estado))
    elif a.acao == "concluir":
        estado = _exigir(r)
        faltam = pendencias(r, estado)
        if faltam:
            for c, situacao, porque in faltam:
                print(f"{c['id']}: {_ROTULO[situacao]} — {porque}")
            print("não concluída: há critério sem prova válida")
            return 1
        estado.update(ativo=False, situacao="concluida", concluida_em=agora())
        salvar(r, estado)
        print("concluída: todos os critérios provados no código atual")
    elif a.acao == "encerrar":
        estado = _exigir(r)
        estado.setdefault("interrupcoes", []).append(
            {"quando": agora(), "motivo": f"encerrada sem concluir: {a.motivo}"})
        estado.update(ativo=False, situacao="encerrada_sem_concluir")
        salvar(r, estado)
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
