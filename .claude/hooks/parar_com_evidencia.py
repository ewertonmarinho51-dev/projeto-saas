#!/usr/bin/env python3
"""
Gancho Stop: não deixa encerrar tarefa de implementação com critério de
aceite sem prova executada no código atual.

Quando age:
- só com `.claude/continuidade/estado.json` ativo e do tipo
  "implementacao" (criado por `scripts/continuidade.py iniciar`). Sem
  tarefa registrada, conversa e pergunta encerram normalmente;
- com bloqueio externo documentado (`continuidade.py bloquear`), deixa
  encerrar e diz o que falta de fora.

O que conta como prova: o registro de `continuidade.py provar`, com log
existente que bate com o hash, código de saída zero e assinatura dos
arquivos cobertos igual à de agora. Declaração do agente não conta.

Custo: nunca roda a suíte. Refaz sozinho só a evidência VENCIDA marcada
`--barato` (teto de 120 s cada); as caras ele pede, com o comando exato.

Laço: conta os bloqueios da sessão e a "impressão" do trabalho (estado +
HEAD + árvore). Três tentativas sem progresso nenhum, ou oito bloqueios
na sessão, liberam o encerramento — registrado como interrupção no
estado, com a pendência à vista. Desligar: `CLAUDE_CONTINUIDADE=0` no
ambiente, ou `python scripts/continuidade.py encerrar --motivo ...`.

Falha aberta: erro interno nunca prende a sessão.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

RAIZ_HOOK = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ_HOOK / "scripts"))

SEM_PROGRESSO_MAX = 3
BLOQUEIOS_MAX = 8


def _saida(obj: dict | None) -> int:
    if obj:
        print(json.dumps(obj))  # ASCII com escapes: chega intacto em qualquer console
    return 0


def _impressao(c, r: Path, estado: dict) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({k: v for k, v in estado.items() if k != "atualizado_em"},
                        sort_keys=True, ensure_ascii=False).encode())
    h.update(c.head(r).encode())
    h.update(c._git(r, "status", "--porcelain").encode())
    h.update(c._git(r, "diff").encode())
    return h.hexdigest()


def decidir(entrada: dict, r: Path | None = None) -> dict | None:
    if os.environ.get("CLAUDE_CONTINUIDADE", "1") == "0":
        return None
    import continuidade as c

    r = r or c.raiz(entrada.get("cwd"))
    estado = c.carregar(r)
    if not estado or estado.get("corrompido"):
        return None
    if not estado.get("ativo") or estado.get("tipo") != "implementacao":
        return None

    bloqueio = estado.get("bloqueio_externo")
    if bloqueio and bloqueio.get("motivo") and bloqueio.get("falta"):
        return {"systemMessage": f"Tarefa parada por bloqueio externo: {bloqueio['motivo']}. "
                                 f"Falta: {bloqueio['falta']}."}

    # espera declarada por job em segundo plano (suíte, CI, carga): o
    # harness acorda a sessão quando ele termina; vencido o prazo, cobra
    espera = c.espera_valida(estado)
    if espera:
        return {"systemMessage": f"Aguardando: {espera['o_que']} (até {espera['ate'][:16]} UTC)."}

    # refaz sozinho o que é barato e só venceu
    for criterio in estado.get("criterios", []):
        situacao, _ = c.avaliar_criterio(r, criterio)
        ev = criterio.get("evidencia") or {}
        if situacao == "vencida" and ev.get("barato") and ev.get("argv"):
            c.executar_prova(r, estado, criterio["id"], ev["argv"],
                             ev.get("arquivos") or [], True, c.SEGUNDOS_BARATO)
            c.salvar(r, estado)

    faltam = c.pendencias(r, estado)
    guarda = c.pasta(r) / ".gancho_stop.json"
    if not faltam:
        guarda.unlink(missing_ok=True)
        return {"systemMessage": "Todos os critérios de aceite estão provados no código atual. "
                                 "Feche com `python scripts/continuidade.py concluir`."}

    sessao = str(entrada.get("session_id") or "")
    try:
        g = json.loads(guarda.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        g = {}
    if g.get("sessao") != sessao:
        g = {"sessao": sessao, "bloqueios": 0, "sem_progresso": 0, "impressao": ""}
    impressao = _impressao(c, r, estado)
    g["sem_progresso"] = g["sem_progresso"] + 1 if impressao == g["impressao"] else 0
    g["impressao"] = impressao
    g["bloqueios"] += 1

    lista = "; ".join(f"{cr['id']} ({c._ROTULO[sit]}: {porque})" for cr, sit, porque in faltam)
    if g["sem_progresso"] >= SEM_PROGRESSO_MAX or g["bloqueios"] > BLOQUEIOS_MAX:
        motivo = ("sem progresso em %d tentativas" % g["sem_progresso"]
                  if g["sem_progresso"] >= SEM_PROGRESSO_MAX
                  else "limite de %d bloqueios na sessão" % BLOQUEIOS_MAX)
        estado.setdefault("interrupcoes", []).append(
            {"quando": c.agora(), "motivo": f"{motivo}; pendente: {lista}"})
        c.salvar(r, estado)
        guarda.unlink(missing_ok=True)
        return {"systemMessage": f"Encerrando SEM concluir ({motivo}). Pendente: {lista}. "
                                 "Registre o bloqueio externo (`continuidade.py bloquear`) "
                                 "se a pendência depende de alguém de fora."}
    guarda.parent.mkdir(parents=True, exist_ok=True)
    guarda.write_text(json.dumps(g), encoding="utf-8")

    primeiro = faltam[0][0]
    proxima = estado.get("proxima_acao") or ""
    razao = (f"A tarefa \"{estado.get('objetivo')}\" ainda não está concluída. "
             f"Critérios sem prova válida: {lista}. "
             f"Próxima ação concreta: {proxima or 'provar ' + primeiro['id']} — "
             f"`{c.comando_de_prova(primeiro)}`. "
             "Se o que falta depende de credencial, decisão ou autorização que você "
             "não tem, registre com `python scripts/continuidade.py bloquear --motivo ... "
             "--falta ...` e encerre explicando.")
    return {"decision": "block", "reason": razao}


def main() -> int:
    try:
        entrada = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        entrada = {}
    try:
        return _saida(decidir(entrada))
    except Exception as exc:  # noqa: BLE001 — falha aberta: nunca prende a sessão
        return _saida({"systemMessage": f"gancho de continuidade falhou ({type(exc).__name__}); "
                                        "encerramento liberado"})


if __name__ == "__main__":
    raise SystemExit(main())
