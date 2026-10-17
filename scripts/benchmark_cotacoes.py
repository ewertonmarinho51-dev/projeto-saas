#!/usr/bin/env python
"""
Benchmark SINTÉTICO de Cotações — mesma fixture, mesma máquina, antes e
depois (G0 e G6 do pacote de implementação).

O que mede, por item e no lote (1, 10, 50, 210 itens):

  * tempo de processamento (p50/p95/total), da coleta à cesta gravada;
  * chamadas às fontes e requisições ao banco por item;
  * cobertura: itens com 3+ preços CONSIDERADOS, incompletos, com erro;
  * chamadas de IA (sempre 0 aqui: nenhum motor é ligado).

O que NÃO mede, e diz isso no JSON: rede real. As fontes são dublês
determinísticos montados a partir das descrições e unidades do caso real
de 210 itens (`tests/fixtures/caso_210_itens.json`); o banco é o dublê de
PostgREST das provas (`tests/conftest.ClientePrecosFalso`). Latência de
rede pode ser SIMULADA com `--latencia-ms`, e o valor usado vai no JSON.
O benchmark com APIs reais continua sendo `scripts/benchmark_precos.py`.

Uso:
    python scripts/benchmark_cotacoes.py --modo legado --saida docs/cotacoes/bench/antes.json
    python scripts/benchmark_cotacoes.py --modo unificado --tamanhos 1 10 50 210
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

FIXTURE = RAIZ / "tests" / "fixtures" / "caso_210_itens.json"


# ---------------------------------------------------------------------------
# Fonte dublê — determinística por item
# ---------------------------------------------------------------------------
def _cenario(numero: int) -> str:
    """Distribui os casos difíceis pela fixture, sempre nos mesmos itens."""
    if numero % 25 == 0:
        return "fonte_fora"          # indisponibilidade técnica
    if numero % 17 == 0:
        return "zero"                # o mercado não tem
    if numero % 13 == 0:
        return "vizinhos"            # só produto aparentado (adversarial)
    if numero % 11 == 0:
        return "dois"                # amostra insuficiente
    if numero % 7 == 0:
        return "unidade_diferente"   # caixa sem fator contra unidade
    return "normal"


class FonteSintetica:
    """Uma fonte de preço praticado que responde pela fixture."""

    def __init__(self, latencia_ms: int = 0, *, volume: int = 0,
                 fonte_id: str = "compras_gov_precos"):
        from src.precos.modelo import Fonte

        self.fonte = Fonte(fonte_id,
                           f"{fonte_id} (sintético)", "sistema_oficial")
        self.latencia = latencia_ms / 1000
        self.chamadas = 0
        # `volume` > 0: devolve N candidatas por item (1 em 4 é produto
        # vizinho, não comparável) — o caso das 301 consideradas.
        self.volume = volume
        self._por_descricao: dict[str, dict] = {}

    def registrar(self, item: dict) -> None:
        self._por_descricao[str(item["descricao"])] = item

    def pesquisar(self, consulta):
        from src.precos.fontes import ResultadoBusca
        from src.precos.modelo import NaturezaValor, Referencia

        self.chamadas += 1
        if self.latencia:
            time.sleep(self.latencia)
        item = self._por_descricao.get(consulta.descricao) or {}
        numero = int(item.get("numero") or 0)
        cenario = _cenario(numero)
        if cenario == "fonte_fora":
            raise RuntimeError("HTTP 503 (sintético)")
        if cenario == "zero":
            return ResultadoBusca(fonte=self.fonte, referencias=[])
        base = Decimal(str(item.get("valor_unitario") or "10")).quantize(
            Decimal("0.01")) or Decimal("10.00")
        fatores = ("0.92", "1.00", "1.05", "1.10", "0.97", "1.02")
        if self.volume:
            fatores = tuple(str(Decimal("0.80") + Decimal(k % 41) / 100)
                            for k in range(self.volume))
        quantas = 2 if cenario == "dois" else len(fatores)
        refs = []
        for i, fator in enumerate(fatores[:quantas]):
            vizinho = cenario == "vizinhos" or (self.volume and i % 4 == 3)
            descricao = (f"PRODUTO DIFERENTE GENERICO {i} ZZZ"
                         if vizinho else consulta.descricao)
            unidade = ("CAIXA" if cenario == "unidade_diferente" and i % 2
                       else str(item.get("unidade") or "UNIDADE"))
            ident = f"{self.fonte.id}-{numero}-{i}"
            refs.append(Referencia(
                fonte=self.fonte, id_externo=ident,
                bruto={"idCompra": ident, "valor": str(base * Decimal(fator))},
                descricao_original=descricao, unidade_original=unidade,
                quantidade_original=Decimal("10"),
                valor_unitario_original=(base * Decimal(fator)).quantize(
                    Decimal("0.01")),
                natureza_valor=NaturezaValor.HOMOLOGADO,
                orgao="Órgão sintético", uf="PA",
                data_compra=date(2026, 6, 1)))
        return ResultadoBusca(fonte=self.fonte, referencias=refs)


# ---------------------------------------------------------------------------
# Banco dublê com contador de requisições
# ---------------------------------------------------------------------------
class Contador:
    def __init__(self):
        self.requisicoes = 0


_CONTADOR_ATIVO: list[Contador] = []


def _banco(contador: Contador):
    """Banco falso NOVO por rodada; o contador é trocado, não empilhado."""
    from src import db
    from tests import conftest

    if not _CONTADOR_ATIVO:
        original = conftest.TabelaPrecosFalsa.execute

        def contar(self):
            _CONTADOR_ATIVO[-1].requisicoes += 1
            return original(self)

        conftest.TabelaPrecosFalsa.execute = contar
    _CONTADOR_ATIVO[:] = [contador]
    cliente = conftest.ClientePrecosFalso()
    db.cliente_do_usuario = lambda: cliente
    return cliente


def _itens(n: int) -> list[dict]:
    dados = json.loads(FIXTURE.read_text(encoding="utf-8"))["itens"][:n]
    return [{"numero": i, "codigo": d.get("codigo"),
             "descricao": d["descricao"], "unidade": d.get("unidade") or "",
             "quantidade": d.get("quantidade"),
             "valor_unitario": d.get("valor_unitario")}
            for i, d in enumerate(dados, start=1)]


# ---------------------------------------------------------------------------
# Modos — o mesmo roteiro, por dois caminhos
# ---------------------------------------------------------------------------
def _rodar_legado(itens: list[dict], fonte, contador: Contador) -> list[dict]:
    """Pesquisa Automática anterior: `execucao.executar_lote`, 1 item/lote."""
    from src.precos import estatistica, execucao
    from src.precos import repositorio as repo
    from src.precos.estados import EstadoPesquisa

    pesquisa = repo.criar_pesquisa(
        "benchmark", auth_user_id="bench",
        versao_regras=estatistica.REGRAS_MEDIA_PADRAO,
        filtros={"janela_dias": 180, "data_base": "2026-10-16"})
    repo.salvar_itens(str(pesquisa["id"]), [
        {k: v for k, v in i.items() if k != "valor_unitario"} for i in itens])
    repo.mover_pesquisa(str(pesquisa["id"]), EstadoPesquisa.NA_FILA)
    medidas = []
    tentados: set[str] = set()
    while True:
        linhas = repo.listar_itens(str(pesquisa["id"]))
        if not execucao.proximo_lote(linhas, 1, ja_tentados=tentados):
            break
        antes_req, antes_fonte = contador.requisicoes, fonte.chamadas
        inicio = time.perf_counter()
        execucao.executar_lote(pesquisa, linhas, fonte.lista, repo, tamanho=1,
                               tentados=tentados,
                               politica=estatistica.POLITICA_AUTOMATICA
                               if TETO[0] else None)
        medidas.append({"segundos": time.perf_counter() - inicio,
                        "req_banco": contador.requisicoes - antes_req,
                        "chamadas_fonte": fonte.chamadas - antes_fonte})
    return medidas, repo.listar_itens(str(pesquisa["id"]))


def _rodar_unificado(itens: list[dict], fonte, contador: Contador):
    """Cotações: `cotacoes.pesquisar_item(modo='automatico')` por item."""
    from src.precos import cotacoes
    from src.precos import repositorio as repo

    ctx = cotacoes.Contexto(auth_user_id="bench")
    cotacao = cotacoes.criar_cotacao(
        ctx, {"nome": "benchmark", "data_base": "2026-10-16"},
        idempotency_key="bench")
    for item in itens:   # inclusão validada, item a item, como na tela
        cotacoes.salvar_item(ctx, str(cotacao["id"]), {
            k: v for k, v in item.items() if k != "valor_unitario"})
    # O MESMO caminho da tela: `pesquisar_em_lote`, LOTE_POR_PASSO itens
    # por passo; a medida por item é o passo dividido pelos itens dele.
    from src.ui.cotacoes_ui import LOTE_POR_PASSO

    medidas = []
    tentados: set[str] = set()
    while True:
        antes_req, antes_fonte = contador.requisicoes, fonte.chamadas
        inicio = time.perf_counter()
        resultados, restantes = cotacoes.pesquisar_em_lote(
            ctx, str(cotacao["id"]), modo="automatico",
            tamanho=LOTE_POR_PASSO, ja_tentados=tentados, fontes=fonte.lista)
        n = max(1, len(resultados))
        for _ in resultados:
            medidas.append({
                "segundos": (time.perf_counter() - inicio) / n,
                "req_banco": (contador.requisicoes - antes_req) / n,
                "chamadas_fonte": (fonte.chamadas - antes_fonte) / n})
        if not restantes or not resultados:
            break
    return medidas, repo.listar_itens(str(cotacao["id"]))


MODOS = {"legado": _rodar_legado, "unificado": _rodar_unificado}

# `--teto`: liga a política da cotação automática (flag
# `cotacao_automatica_teto`) — na unificada pela flag, na legada pelo
# parâmetro que a tela passa.
TETO = [False]


def _ligar_teto() -> None:
    from src import db, governanca

    TETO[0] = True
    db.flag_ativa = lambda nome: nome == governanca.FLAG_TETO_AUTOMATICO


def _percentil(valores: list[float], fracao: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    posicao = (len(ordenados) - 1) * fracao
    baixo = int(posicao)
    alto = min(baixo + 1, len(ordenados) - 1)
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * (posicao - baixo)


class Fontes:
    """Uma ou duas fontes sintéticas com a interface que os modos usam."""

    def __init__(self, fontes):
        self.lista = fontes

    @property
    def chamadas(self) -> int:
        return sum(f.chamadas for f in self.lista)


def medir(modo: str, n: int, latencia_ms: int, *, volume: int = 0,
          duas_fontes: bool = False) -> dict:
    from src.precos import cesta

    contador = Contador()
    cliente = _banco(contador)
    fontes = [FonteSintetica(latencia_ms, volume=volume)]
    if duas_fontes:
        fontes.append(FonteSintetica(latencia_ms, volume=volume,
                                     fonte_id="pncp"))
    fonte = Fontes(fontes)
    itens = _itens(n)
    for item in itens:
        for f in fontes:
            f.registrar(item)
    inicio = time.perf_counter()
    medidas, finais = MODOS[modo](itens, fonte, contador)
    total = time.perf_counter() - inicio
    tempos = [m["segundos"] for m in medidas]
    com_tres = sum(1 for i in finais if (cesta.na_cesta_do_item(i) or 0) >= 3)
    estados: dict[str, int] = {}
    for i in finais:
        estados[str(i.get("estado"))] = estados.get(str(i.get("estado")), 0) + 1
    return {
        "itens": n,
        "rodadas": len(medidas),
        "tempo_total_s": round(total, 4),
        "p50_item_s": round(_percentil(tempos, 0.5), 5),
        "p95_item_s": round(_percentil(tempos, 0.95), 5),
        "chamadas_fonte_por_item": round(
            statistics.mean(m["chamadas_fonte"] for m in medidas), 3)
        if medidas else 0,
        "req_banco_por_item": round(
            statistics.mean(m["req_banco"] for m in medidas), 3)
        if medidas else 0,
        "itens_com_3_considerados": com_tres,
        "volume_por_fonte": volume or 6,
        "fontes": len(fontes),
        "referencias_gravadas_por_item": round(len(cliente.tabelas.get(
            "pesquisa_preco_referencias", [])) / max(1, n), 2),
        "consideradas_por_item_media": round(statistics.mean(
            cesta.na_cesta_do_item(i) or 0 for i in finais), 2)
        if finais else 0,
        "consideradas_por_item_max": max(
            (cesta.na_cesta_do_item(i) or 0 for i in finais), default=0),
        "estados": estados,
        "chamadas_ia": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modo", choices=sorted(MODOS), default="legado")
    parser.add_argument("--tamanhos", type=int, nargs="+",
                        default=[1, 10, 50, 210])
    parser.add_argument("--latencia-ms", type=int, default=0)
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--volume", type=int, default=0,
                        help="candidatas por fonte e item (0 = 6, o padrão)")
    parser.add_argument("--duas-fontes", action="store_true")
    parser.add_argument("--teto", action="store_true",
                        help="liga a política de teto da cotação automática")
    args = parser.parse_args(argv)
    if args.teto:
        _ligar_teto()

    resultado = {
        "modo": args.modo,
        "executado_em": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "maquina": platform.platform(),
        "latencia_simulada_ms": args.latencia_ms,
        "teto_automatico": args.teto,
        "limites": ("fontes e banco são dublês determinísticos; rede real "
                    "NÃO medida. Tempos medem o processamento do GovConnect "
                    "(coleta→procedência→unidade→matching→cesta→gravação)."),
        "rodadas": [medir(args.modo, n, args.latencia_ms,
                          volume=args.volume, duas_fontes=args.duas_fontes)
                    for n in args.tamanhos],
    }
    texto = json.dumps(resultado, ensure_ascii=False, indent=2)
    if args.saida:
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text(texto + "\n", encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
