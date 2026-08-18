"""
Varredura de segredos — testes dos defeitos corrigidos.

A ferramenta que confere o patch antes da revisão externa precisa de
conferência própria: uma varredura que erra para o lado permissivo é
pior que nenhuma, porque produz um laudo tranquilizador.

Este arquivo NÃO contém literal de segredo. Todas as amostras são
MONTADAS em tempo de execução, a partir de pedaços que sozinhos não
casam padrão nenhum. É o que permite a varredura não ter isenção por
arquivo: se um segredo de verdade for colado aqui um dia — numa
depuração apressada, digamos — ele é detectado como em qualquer outro
lugar do repositório.
"""

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from varredura_segredos import (  # noqa: E402
    CATEGORIA_POR_HASH,
    FALSO_DOCUMENTADO,
    FALSOS_CONHECIDOS,
    Achado,
    sanitizar,
    varrer,
)


def _montar(*pedacos: str) -> str:
    """
    Junta pedaços num valor com forma de segredo.

    A junção acontece em RUNTIME: no disco só existem fragmentos como
    "sk-" e "proj-", que não casam padrão algum sozinhos.
    """
    return "".join(pedacos)


# Segredo "real" para os testes: forma válida, valor inventado, e
# ausente da allowlist — é o que ele precisa ser para provar detecção.
SEGREDO_REAL = _montar("sk-", "proj-", "9f3aB7cD1eF5gH8i",
                       "J2kL4mN6oP0qR3sT")
# Este está na allowlist, por valor exato.
FALSO_CONHECIDO = _montar("sk-", "proj-", "ABCDEFGHIJKLMNOP",
                          "QRSTUVWXYZ012345")


# ---------------------------------------------------------------------------
# Defeito 1 — allowlist por substring liberava a linha inteira
# ---------------------------------------------------------------------------
def test_falso_conhecido_vira_ocorrencia_documentada():
    """
    Ele APARECE no laudo — como falso documentado. Sumir da contagem
    era o defeito: o laudo dizia "0 achados" sobre um patch que tinha
    dez ocorrências, e quem lia não sabia se o scanner não encontrou
    nada ou se alguém, algum dia, decidiu que não contavam.
    """
    achados = varrer("p", f"+ chave = {FALSO_CONHECIDO}")
    assert len(achados) == 1
    assert achados[0].situacao == FALSO_DOCUMENTADO
    assert achados[0].e_real is False


def test_segredo_real_na_mesma_linha_de_um_falso_e_encontrado():
    """
    O defeito exato: a linha continha um literal de teste, a allowlist
    casava por substring contra a LINHA, e tudo nela era liberado — o
    segredo real junto.
    """
    linha = f'+ falsa="{FALSO_CONHECIDO}"  real="{SEGREDO_REAL}"'
    achados = varrer("p", linha)
    reais = [a.valor for a in achados if a.e_real]
    documentados = [a.valor for a in achados if not a.e_real]
    assert reais == [SEGREDO_REAL], reais
    assert documentados == [FALSO_CONHECIDO], documentados


def test_prefixo_de_falso_conhecido_nao_libera():
    """
    Um segredo real que COMECE igual a um falso conhecido não pode
    passar: a comparação é por igualdade, não por prefixo.
    """
    quase = FALSO_CONHECIDO + "MAISCARACTERES"
    achados = varrer("p", f"+ {quase}")
    assert [a.valor for a in achados] == [quase]


def test_a_allowlist_e_comparada_por_igualdade():
    for valor in FALSOS_CONHECIDOS:
        assert isinstance(valor, str)
        achados = varrer("p", f"+ x = {valor}")
        assert all(not a.e_real for a in achados), valor


# ---------------------------------------------------------------------------
# Defeito 2 — laudo com zeros literais por categoria
# ---------------------------------------------------------------------------
def _laudo(texto: str, tmp_path: Path) -> tuple[str, int]:
    (tmp_path / "a.patch").write_text(texto)
    processo = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "varredura_segredos.py"),
         str(tmp_path)],
        capture_output=True, text=True)
    return processo.stdout, processo.returncode


def test_o_laudo_conta_de_verdade(tmp_path):
    saida, _ = _laudo(
        f"+ um {SEGREDO_REAL}\n+ dois AIzaSy{'B' * 33}\n", tmp_path)
    assert "segredos reais ........... 2" in saida, saida
    assert "ocorrências .............. 2" in saida, saida


def test_o_laudo_separa_os_tres_estados(tmp_path):
    """
    Ocorrência, falso documentado e segredo real são três números
    distintos, e os três aparecem sempre.
    """
    saida, codigo = _laudo(
        f"+ falso {FALSO_CONHECIDO}\n+ real {SEGREDO_REAL}\n", tmp_path)
    assert "ocorrências .............. 2" in saida, saida
    assert "falsos documentados ...... 1" in saida, saida
    assert "segredos reais ........... 1" in saida, saida
    assert codigo != 0


def test_o_laudo_nao_diz_zero_quando_ha_ocorrencia(tmp_path):
    """
    O ponto: com só falsos documentados, o total de ocorrências
    continua visível e o texto NÃO afirma que nada foi encontrado.
    """
    saida, codigo = _laudo(f"+ {FALSO_CONHECIDO}\n", tmp_path)
    assert "ocorrências .............. 1" in saida, saida
    assert "segredos reais ........... 0" in saida, saida
    assert "NENHUMA OCORRÊNCIA" not in saida, saida
    assert "SEM SEGREDO REAL" in saida, saida
    assert codigo == 0        # não bloqueia, mas não mente


def test_o_laudo_nao_afirma_zero_quando_ha_achado(tmp_path):
    """
    A versão anterior imprimia "credenciais reais: 0" como texto fixo,
    o que tornava o laudo um documento de tranquilização.
    """
    saida, _ = _laudo(f"+ {SEGREDO_REAL}\n", tmp_path)
    assert "OpenAI                   0" not in saida, saida


def test_laudo_sem_ocorrencia_alguma(tmp_path):
    saida, codigo = _laudo("+ apenas codigo comum aqui\n", tmp_path)
    assert "NENHUMA OCORRÊNCIA" in saida
    assert "ocorrências .............. 0" in saida
    assert codigo == 0


# ---------------------------------------------------------------------------
# Defeito 3 — código de saída sempre 0
# ---------------------------------------------------------------------------
def test_saida_diferente_de_zero_com_achado(tmp_path):
    _, codigo = _laudo(f"+ {SEGREDO_REAL}\n", tmp_path)
    assert codigo != 0


def test_saida_zero_com_falso_documentado(tmp_path):
    """Só segredo REAL bloqueia — mas a ocorrência continua no laudo."""
    _, codigo = _laudo(f"+ {FALSO_CONHECIDO}\n", tmp_path)
    assert codigo == 0


def test_diretorio_sem_patch_tambem_falha(tmp_path):
    processo = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "varredura_segredos.py"),
         str(tmp_path)],
        capture_output=True, text=True)
    assert processo.returncode != 0     # nada varrido não é "tudo limpo"


# ---------------------------------------------------------------------------
# O laudo não pode ele próprio vazar o segredo
# ---------------------------------------------------------------------------
def test_o_relatorio_nao_imprime_o_segredo(tmp_path):
    saida, _ = _laudo(f"+ {SEGREDO_REAL}\n", tmp_path)
    assert SEGREDO_REAL not in saida, saida
    assert "sk-pro…" in saida


def test_a_referencia_do_projeto_nao_aparece_no_relatorio():
    achado = Achado(CATEGORIA_POR_HASH, "qualquerreferencia", "p", 1)
    assert "qualquerreferencia" not in achado.resumo()


# ---------------------------------------------------------------------------
# Sanitização
# ---------------------------------------------------------------------------
def test_sanitizar_remove_o_achado_e_conta_as_trocas():
    texto = f"linha um {SEGREDO_REAL}\nlinha dois {SEGREDO_REAL}\n"
    limpo, trocas = sanitizar(texto, varrer("p", texto))
    assert SEGREDO_REAL not in limpo
    assert trocas == 2
    assert "[OPENAI-REDIGIDO]" in limpo


def test_sanitizar_preserva_o_resto_do_patch():
    texto = f"@@ -1,2 +1,2 @@\n-antigo\n+novo com {SEGREDO_REAL}\n"
    limpo, _ = sanitizar(texto, varrer("p", texto))
    assert "@@ -1,2 +1,2 @@" in limpo
    assert "-antigo" in limpo


def test_sanitizar_nao_toca_nos_falsos_documentados():
    texto = f"+ {FALSO_CONHECIDO}\n"
    limpo, trocas = sanitizar(texto, varrer("p", texto))
    assert limpo == texto and trocas == 0


# ---------------------------------------------------------------------------
# Sem isenção por arquivo — nem para este arquivo
# ---------------------------------------------------------------------------
ESTE_ARQUIVO = "tests/test_varredura_segredos.py"


def test_segredo_neste_proprio_arquivo_e_detectado():
    """
    A versão anterior isentava este arquivo por caminho. Parecia
    estreito e auditável, mas criava um ponto cego com nome e endereço:
    um segredo REAL colado aqui — numa depuração apressada — passaria
    despercebido para sempre.
    """
    diff = (f"diff --git a/{ESTE_ARQUIVO} b/{ESTE_ARQUIVO}\n"
            f"+ amostra = \"{SEGREDO_REAL}\"\n")
    achados = varrer("p", diff)
    assert [a.valor for a in achados] == [SEGREDO_REAL], achados


def test_nenhum_arquivo_tem_tratamento_especial():
    """O mesmo segredo, em qualquer caminho, dá o mesmo resultado."""
    caminhos = (ESTE_ARQUIVO, "src/db.py", "scripts/varredura_segredos.py",
                "docs/relatorio.md", "README.md")
    for caminho in caminhos:
        diff = (f"diff --git a/{caminho} b/{caminho}\n"
                f"+ chave = \"{SEGREDO_REAL}\"\n")
        assert len(varrer("p", diff)) == 1, caminho


def test_a_varredura_nao_conhece_lista_de_isencao():
    """Guarda contra reintrodução silenciosa da isenção por caminho."""
    import varredura_segredos

    assert not hasattr(varredura_segredos, "ARQUIVOS_ISENTOS")
    # a varredura nem sabe em que arquivo do diff está: não há mais
    # rastreamento de caminho dentro dela
    fonte = (RAIZ / "scripts" / "varredura_segredos.py").read_text()
    assert "arquivo_atual" not in fonte


def test_este_arquivo_nao_contem_literal_de_segredo():
    """
    A condição que torna a ausência de isenção sustentável: as amostras
    são montadas em runtime, e no disco só há fragmentos.
    """
    fonte = (RAIZ / ESTE_ARQUIVO).read_text()
    achados = varrer(ESTE_ARQUIVO, fonte)
    assert achados == [], [(a.categoria, a.linha) for a in achados]


@pytest.mark.parametrize("categoria,amostra", [
    ("JWT", _montar("eyJhbGciOiJIUzI1NiJ9.", "eyJzdWIiOiIxMjM0NTY3ODkwIn0.",
                    "assinaturafalsa")),
    ("Supabase secreta", _montar("sb_", "secret_", "9f3aB7cD1eF5gH8i")),
    ("Supabase publicável", _montar("sb_", "publishable_",
                                    "9f3aB7cD1eF5gH8i")),
    ("GitHub", _montar("ghp_", "9f3aB7cD1eF5gH8iJ2kL4mN6oP0qR3sT4uV5")),
    ("CPF", _montar("123.", "456.", "789-", "00")),
    ("e-mail", _montar("servidor", "@", "prefeitura.gov.br")),
    ("chave privada", _montar("-----BEGIN ", "RSA PRIVATE KEY", "-----")),
    ("hash PBKDF2", _montar("pbkdf2_", "sha256$200000$a1b2c3d4$", "f" * 40)),
])
def test_cada_categoria_e_detectada(categoria, amostra):
    achados = varrer("p", f"+ {amostra}")
    assert categoria in {a.categoria for a in achados}, achados


# ---------------------------------------------------------------------------
# Ponto 5 — escopo declarado, e exit 1 bloqueando "limpo"
# ---------------------------------------------------------------------------
def _laudo_com_escopo(texto: str, tmp_path: Path, escopo: str):
    (tmp_path / "a.patch").write_text(texto)
    processo = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "varredura_segredos.py"),
         str(tmp_path), "--escopo", escopo],
        capture_output=True, text=True)
    return processo.stdout, processo.returncode


@pytest.mark.parametrize("escopo,marca", [
    ("arvore", "ÁRVORE FINAL"),
    ("historico", "HISTÓRICO"),
])
def test_o_laudo_declara_o_escopo(tmp_path, escopo, marca):
    """
    Anunciar "árvore limpa" a partir de uma varredura de histórico é a
    contradição que o parâmetro existe para impedir.
    """
    saida, _ = _laudo_com_escopo("+ nada aqui\n", tmp_path, escopo)
    assert marca in saida, saida


def test_o_escopo_historico_avisa_sobre_linhas_removidas(tmp_path):
    saida, _ = _laudo_com_escopo("+ nada\n", tmp_path, "historico")
    assert "commit posterior REMOVIDO" in saida


def test_segredo_real_impede_declarar_limpo(tmp_path):
    """Exit 1 e texto explícito: nenhum dos dois pode ser ignorado."""
    saida, codigo = _laudo_com_escopo(
        f"+ {SEGREDO_REAL}\n", tmp_path, "arvore")
    assert codigo == 1
    assert "NÃO declare limpo" in saida
    assert "LIMPO" not in saida.replace("NÃO declare limpo", "")


def test_o_texto_final_nomeia_o_escopo(tmp_path):
    saida, _ = _laudo_com_escopo(f"+ {SEGREDO_REAL}\n", tmp_path, "arvore")
    assert "escopo ARVORE" in saida


# ---------------------------------------------------------------------------
# Bloqueio 3 — `--escopo` deixou de ser rótulo digitado
#
# A versão anterior aceitava qualquer palavra e imprimia a afirmação
# correspondente: bastava passar um `format-patch` com `--escopo arvore`
# para o laudo assinar a afirmação MAIS FORTE sobre o material MAIS
# FRACO. O parâmetro existia para impedir exatamente essa contradição e
# não impedia nada.
#
# Agora há duas defesas. No modo derivado o escopo ESCOLHE O COMANDO —
# rótulo e conteúdo são a mesma decisão e não podem divergir. No modo
# arquivo o conteúdo é CLASSIFICADO e a declaração é conferida contra a
# classificação.
# ---------------------------------------------------------------------------
import hashlib  # noqa: E402

from varredura_segredos import (  # noqa: E402
    FORMATO_DIFF,
    FORMATO_INDETERMINADO,
    FORMATO_MBOX,
    RECUSA,
    formato_do_conteudo,
)

VARREDURA = str(RAIZ / "scripts" / "varredura_segredos.py")


def _rodar(*argumentos: str):
    processo = subprocess.run([sys.executable, VARREDURA, *argumentos],
                              capture_output=True, text=True)
    return processo.stdout + processo.stderr, processo.returncode


# Endereço montado em runtime, como todo o resto deste arquivo: um
# literal de e-mail aqui seria achado da própria varredura — e a
# ausência de isenção por arquivo só se sustenta se o disco não tiver
# nada com forma de segredo.
_REMETENTE = _montar("alguem", "@", "exemplo", ".invalid")


def _mbox(corpo: str, commits: int = 1) -> str:
    """format-patch sintético: a linha sentinela é o que o git escreve."""
    partes = []
    for i in range(commits):
        partes.append(
            f"From {'a1b2c3d' + '0' * 33} Mon Sep 17 00:00:00 2001\n"
            f"From: Alguem <{_REMETENTE}>\n"
            f"Subject: [PATCH {i + 1}/{commits}] mudança\n\n"
            f"diff --git a/x.py b/x.py\n{corpo}")
    return "".join(partes)


def _reais_da_categoria(saida: str, categoria: str) -> int:
    """Coluna REAIS da linha da categoria no laudo."""
    for linha in saida.splitlines():
        if linha.strip().startswith(categoria):
            return int(linha.split()[-1])
    raise AssertionError(f"categoria {categoria} ausente do laudo:\n{saida}")


def _diff(corpo: str) -> str:
    return f"diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n{corpo}"


# --- classificação ----------------------------------------------------------
def test_o_formato_do_conteudo_e_reconhecido():
    assert formato_do_conteudo(_mbox("+ nada\n")) == FORMATO_MBOX
    assert formato_do_conteudo(_diff("+ nada\n")) == FORMATO_DIFF
    assert formato_do_conteudo("+ texto solto\n") == FORMATO_INDETERMINADO


# --- a regressão que o achado pede ------------------------------------------
def test_format_patch_nao_pode_ser_anunciado_como_arvore_final(tmp_path):
    """
    A REGRESSÃO deste achado. O material é histórico; a declaração diz
    árvore final; a ferramenta recusa em vez de assinar.
    """
    (tmp_path / "a.patch").write_text(_mbox(f"+ {SEGREDO_REAL}\n", commits=3))
    saida, codigo = _rodar(str(tmp_path), "--escopo", "arvore")

    assert codigo == RECUSA, saida
    assert "RECUSADO" in saida
    assert "format-patch" in saida
    assert "3 commit(s)" in saida
    # e, sobretudo: nenhum laudo foi emitido sobre o escopo errado
    assert "=== LAUDO ===" not in saida
    assert "ÁRVORE FINAL" not in saida.split("Use `--escopo")[0].replace(
        "declarado como ÁRVORE FINAL", "")


def test_o_mesmo_material_declarado_como_historico_e_varrido(tmp_path):
    """
    A recusa é da declaração falsa, não do material: o mesmo arquivo,
    com o escopo verdadeiro, é varrido normalmente.
    """
    (tmp_path / "a.patch").write_text(_mbox(f"+ {SEGREDO_REAL}\n"))
    saida, codigo = _rodar(str(tmp_path), "--escopo", "historico")

    assert codigo == 1, saida            # achou segredo, não recusou escopo
    assert "=== LAUDO ===" in saida
    # o cabeçalho do mbox traz um e-mail, que também é ocorrência: o que
    # se confere é a categoria do segredo plantado, não o total
    assert _reais_da_categoria(saida, "OpenAI") == 1, saida


def test_git_diff_nao_pode_ser_anunciado_como_historico(tmp_path):
    """
    O sentido inverso também mente: um diff acumulado não contém os
    commits intermediários, e declarar histórico a partir dele afirma
    cobertura que a varredura não teve.
    """
    (tmp_path / "a.patch").write_text(_diff("+ nada\n"))
    saida, codigo = _rodar(str(tmp_path), "--escopo", "historico")
    assert codigo == RECUSA, saida
    assert "cobertura que a varredura não teve" in saida


# --- combinações ambíguas ---------------------------------------------------
@pytest.mark.parametrize("argumentos,marca", [
    ([], "informe um diretório"),
    (["--repo", "."], "exige `--base` E `--head`"),
    (["--base", "x", "--head", "y"], "informe um diretório"),
    (["DIR", "--base", "x"], "só existem com `--repo`"),
    (["DIR", "--repo", "."], "ambíguo"),
    (["--repo", ".", "--base", "x", "--head", "y", "--sanitizar"],
     "exige `--saida"),
    (["DIR", "--saida", "s"], "é do modo derivado"),
])
def test_combinacao_ambigua_e_recusada(tmp_path, argumentos, marca):
    """
    Recusa ANTES de varrer. Cada combinação aqui produziria um laudo
    cuja procedência ninguém consegue reconstruir depois.
    """
    (tmp_path / "a.patch").write_text("+ nada\n")
    concretos = [str(tmp_path) if a == "DIR" else a for a in argumentos]
    saida, codigo = _rodar(*concretos)
    assert codigo == RECUSA, saida
    assert marca in saida, saida


# --- modo derivado ----------------------------------------------------------
def _repo(tmp_path: Path) -> Path:
    raiz = tmp_path / "repo"
    raiz.mkdir()
    subprocess.run(["git", "init", "-q", str(raiz)], check=True)
    return raiz


def _commitar(raiz: Path, arquivo: str, conteudo: str, mensagem: str) -> str:
    (raiz / arquivo).write_text(conteudo)
    subprocess.run(["git", "-C", str(raiz), "add", arquivo], check=True)
    subprocess.run(
        ["git", "-C", str(raiz), "-c", f"user.email={_REMETENTE}",
         "-c", "user.name=Ensaio", "commit", "-q", "-m", mensagem], check=True)
    return subprocess.run(
        ["git", "-C", str(raiz), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()


def test_o_modo_derivado_apura_a_procedencia(tmp_path):
    raiz = _repo(tmp_path)
    base = _commitar(raiz, "a.py", "x = 1\n", "inicial")
    head = _commitar(raiz, "a.py", "x = 2\n", "muda")

    saida, codigo = _rodar("--repo", str(raiz), "--base", base,
                           "--head", head, "--escopo", "arvore")
    assert codigo == 0, saida
    assert "ESCOPO APURADO" in saida
    assert base in saida and head in saida
    assert "modo ..................... derivado" in saida


def test_a_sha256_e_do_conteudo_efetivamente_analisado(tmp_path):
    """
    O laudo tem de dizer sobre o QUÊ ele fala. A impressão é conferida
    contra o `git diff` rodado por fora: se o script varresse outra
    coisa, os dois números divergiriam.
    """
    raiz = _repo(tmp_path)
    base = _commitar(raiz, "a.py", "x = 1\n", "inicial")
    head = _commitar(raiz, "a.py", "x = 2\n", "muda")

    esperado = hashlib.sha256(subprocess.run(
        ["git", "-C", str(raiz), "diff", f"{base}..{head}"],
        capture_output=True, text=True, check=True).stdout.encode()).hexdigest()

    saida, _ = _rodar("--repo", str(raiz), "--base", base, "--head", head,
                      "--escopo", "arvore")
    assert esperado in saida, saida


def test_a_arvore_limpa_nao_absolve_o_historico(tmp_path):
    """
    O caso que originou tudo: um segredo entra num commit e sai no
    seguinte. A ÁRVORE está limpa e o HISTÓRICO não — e as duas
    varreduras têm de dizer coisas diferentes, senão o escopo é
    decorativo.
    """
    raiz = _repo(tmp_path)
    base = _commitar(raiz, "a.py", "x = 1\n", "inicial")
    _commitar(raiz, "a.py", f'chave = "{SEGREDO_REAL}"\n', "vaza")
    head = _commitar(raiz, "a.py", "x = 2\n", "remove")

    arvore, codigo_arvore = _rodar("--repo", str(raiz), "--base", base,
                                   "--head", head, "--escopo", "arvore")
    assert codigo_arvore == 0, arvore
    assert "NENHUMA OCORRÊNCIA" in arvore, arvore

    historico, codigo_historico = _rodar("--repo", str(raiz), "--base", base,
                                         "--head", head, "--escopo",
                                         "historico")
    assert codigo_historico == 1, historico
    # DUAS ocorrências no histórico: a linha que entra no commit "vaza" e
    # a mesma linha saindo no commit "remove". É a demonstração literal
    # de que o histórico guarda o que a árvore já não tem.
    assert _reais_da_categoria(historico, "OpenAI") == 2, historico
    assert _reais_da_categoria(arvore, "OpenAI") == 0, arvore
    # e o laudo do histórico avisa que a ocorrência pode já não existir
    assert "commit posterior REMOVIDO" in historico


def test_o_escopo_derivado_nao_pode_divergir_do_conteudo(tmp_path):
    """
    No modo derivado o `--escopo` escolhe o COMANDO. A prova é que o
    formato detectado acompanha o escopo pedido, sempre.
    """
    raiz = _repo(tmp_path)
    base = _commitar(raiz, "a.py", "x = 1\n", "inicial")
    head = _commitar(raiz, "a.py", "x = 2\n", "muda")

    arvore, _ = _rodar("--repo", str(raiz), "--base", base, "--head", head,
                       "--escopo", "arvore")
    historico, _ = _rodar("--repo", str(raiz), "--base", base, "--head", head,
                          "--escopo", "historico")
    assert FORMATO_DIFF in arvore, arvore
    assert FORMATO_MBOX in historico, historico


def test_revisao_inexistente_e_recusada_e_nao_varrida(tmp_path):
    raiz = _repo(tmp_path)
    base = _commitar(raiz, "a.py", "x = 1\n", "inicial")
    saida, codigo = _rodar("--repo", str(raiz), "--base", base,
                           "--head", "revisao-que-nao-existe",
                           "--escopo", "arvore")
    assert codigo == RECUSA, saida
    assert "=== LAUDO ===" not in saida


def test_o_modo_arquivo_declara_que_a_procedencia_nao_e_apurada(tmp_path):
    """
    Modo arquivo continua existindo, e o laudo diz o que ele é: escopo
    DECLARADO, conferido só contra o formato. Quem lê precisa saber a
    diferença.
    """
    (tmp_path / "a.patch").write_text(_diff("+ nada\n"))
    saida, codigo = _rodar(str(tmp_path), "--escopo", "arvore")
    assert codigo == 0, saida
    assert "ESCOPO DECLARADO" in saida
    assert "não declarada (modo arquivo)" in saida
    assert "ESCOPO APURADO" not in saida


# ---------------------------------------------------------------------------
# Domínios reservados (RFC 2606) — regra sobre o VALOR
#
# A alternativa seria acrescentar cada endereço de fixture à allowlist,
# um a um, para sempre — ou pior, isentar o arquivo de teste, que é
# exatamente o que esta ferramenta não faz.
# ---------------------------------------------------------------------------
from varredura_segredos import _e_dominio_reservado  # noqa: E402


@pytest.mark.parametrize("dominio", [".invalid", ".test", ".example",
                                     "@example.com", "@example.org"])
def test_endereco_em_dominio_reservado_e_falso_documentado(dominio):
    """
    Continua APARECENDO no laudo — sai da contagem que bloqueia, não da
    que informa. É a diferença entre descontar e esconder.
    """
    valor = _montar("fulano", dominio) if dominio.startswith("@") \
        else _montar("fulano", "@exemplo", dominio)
    achados = varrer("x.patch", f"+ contato: {valor}\n")
    assert achados, valor
    assert all(a.situacao == FALSO_DOCUMENTADO for a in achados), valor


def test_dominio_parecido_com_reservado_nao_passa():
    """
    `.invalid` reservado é o SUFIXO. `exemplo.invalid.com.br` é um
    domínio que resolve, e o parecido não pode herdar a dispensa.
    """
    valor = _montar("fulano", "@exemplo", ".invalid", ".com", ".br")
    achados = varrer("x.patch", f"+ contato: {valor}\n")
    assert achados
    assert all(a.e_real for a in achados), valor


def test_a_regra_vale_so_para_e_mail():
    """
    Uma chave que por acaso termine em `.test` continua sendo chave. A
    dispensa é sobre endereço não roteável, não sobre segredo em geral.
    """
    assert _e_dominio_reservado(_montar("a", "@b", ".invalid"))
    chave = _montar("sk-", "proj-", "9f3aB7cD1eF5gH8i", "J2kL4mN6oP0q.test")
    achados = varrer("x.patch", f"+ {chave}\n")
    assert any(a.categoria == "OpenAI" and a.e_real for a in achados), achados


def test_o_laudo_nomeia_as_duas_listas(tmp_path):
    """
    O texto final dizia "todas na allowlist por valor exato". Com a
    regra nova isso passou a ser mentira parcial — e um laudo que
    descreve errado o próprio critério não serve de evidência.
    """
    endereco = _montar("fulano", "@exemplo", ".invalid")
    (tmp_path / "a.patch").write_text(f"+ {endereco}\n")
    saida, codigo = _rodar(str(tmp_path), "--escopo", "arvore")
    assert codigo == 0, saida
    assert "domínio reservado" in saida, saida


# ---------------------------------------------------------------------------
# Linha removida não está na árvore
#
# O escopo `arvore` lê um `git diff`, e um diff carrega o que SAIU junto
# com o que ficou. A ferramenta acusava, portanto, exatamente o ato de
# limpeza que ela existe para provocar: o commit que apaga o segredo era
# relatado como se o contivesse.
# ---------------------------------------------------------------------------
def test_linha_removida_nao_conta_na_arvore():
    diff = _diff(f"-  chave = {SEGREDO_REAL}\n+  chave = os.environ['X']\n")
    assert not varrer("d.patch", diff, so_o_que_permanece=True)
    # e o que ENTRA continua contando
    entrando = _diff(f"+  chave = {SEGREDO_REAL}\n")
    assert varrer("d.patch", entrando, so_o_que_permanece=True)


def test_linha_removida_CONTA_no_historico():
    """
    No histórico a remoção é o ponto: um segredo que existiu e foi
    apagado está lá, e é essa a pergunta que aquele escopo responde.
    """
    diff = _diff(f"-  chave = {SEGREDO_REAL}\n")
    assert varrer("d.patch", diff, so_o_que_permanece=False)


def test_o_cabecalho_de_arquivo_nao_e_confundido_com_remocao():
    """`--- a/x.py` começa com hífen e não é linha apagada."""
    from varredura_segredos import _e_remocao

    assert _e_remocao("-  segredo")
    assert not _e_remocao("--- a/x.py")
    assert not _e_remocao("+  segredo")
    assert not _e_remocao("   contexto")


def test_os_dois_escopos_dao_respostas_diferentes_no_mesmo_material(tmp_path):
    """
    A prova de que o escopo mudou de verdade o resultado, e não só o
    rótulo: mesmo repositório, mesmo intervalo, vereditos opostos.
    """
    raiz = _repo(tmp_path)
    base = _commitar(raiz, "a.py", f'chave = "{SEGREDO_REAL}"\n', "com segredo")
    head = _commitar(raiz, "a.py", "chave = None\n", "limpa")

    arvore, codigo_arvore = _rodar("--repo", str(raiz), "--base", base,
                                   "--head", head, "--escopo", "arvore")
    assert codigo_arvore == 0, arvore
    assert _reais_da_categoria(arvore, "OpenAI") == 0, arvore

    historico, codigo_historico = _rodar("--repo", str(raiz), "--base", base,
                                         "--head", head, "--escopo",
                                         "historico")
    assert codigo_historico == 1, historico
    assert _reais_da_categoria(historico, "OpenAI") == 1, historico
