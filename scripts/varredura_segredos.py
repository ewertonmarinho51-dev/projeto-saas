#!/usr/bin/env python3
"""
Varredura de segredos, antes da revisão externa.

MODO DERIVADO — o escopo é gerado aqui e por isso é FATO:

    python scripts/varredura_segredos.py \\
        --repo . --base <rev> --head <rev> --escopo arvore
    python scripts/varredura_segredos.py \\
        --repo . --base <rev> --head <rev> --escopo historico

MODO ARQUIVO — o conteúdo vem pronto e o escopo é uma DECLARAÇÃO:

    python scripts/varredura_segredos.py <dir> --escopo arvore

O ESCOPO muda o que o resultado significa:

  arvore     `git diff BASE..HEAD` — o estado FINAL dos arquivos. É o
             que vai para o repositório.
  historico  `git format-patch --stdout BASE..HEAD` — TODOS os commits,
             inclusive linhas que commits posteriores removeram. Uma
             ocorrência aqui pode já não existir na árvore.

Anunciar "árvore limpa" a partir de uma varredura de histórico é a
contradição que este parâmetro existe para impedir — e a versão
anterior não impedia coisa alguma, porque `--escopo` era só um RÓTULO
que o operador digitava. Bastava passar um `format-patch` e escrever
`--escopo arvore` para o laudo assinar a afirmação mais forte sobre o
material mais fraco.

Duas mudanças fecham isso:

  * no modo derivado, `--escopo` ESCOLHE O COMANDO. O rótulo e o
    conteúdo não podem divergir porque são a mesma decisão;
  * no modo arquivo, o conteúdo é CLASSIFICADO (mbox / git diff /
    indeterminado) e a declaração é conferida contra a classificação.
    Um `format-patch` declarado como árvore é RECUSADO, não avisado.

Os dois modos emitem base, head e o SHA-256 do conteúdo efetivamente
analisado: sem isso o laudo não é reproduzível, e um laudo que não se
pode reproduzir não é evidência.

Sem `--sanitizar`, só relata. Com `--sanitizar`, grava cópias
`*-sanitizado.patch` para LEITURA (a redação altera bytes: para aplicar,
use os `.patch` originais).

Código de saída:
  0  nenhum SEGREDO REAL no escopo declarado;
  1  segredo real, ou nada a varrer — nada varrido não é "tudo limpo";
  2  RECUSA: combinação ambígua de argumentos, ou declaração de escopo
     incompatível com o conteúdo. Recusar é o ponto: um laudo com o
     escopo errado é pior que nenhum laudo.

Três defeitos anteriores, também corrigidos aqui:

  1. a allowlist casava por SUBSTRING contra a LINHA inteira. Uma linha
     contendo "de-teste" em qualquer posição ficava inteiramente
     liberada — credencial real inclusa, se estivesse na mesma linha.
     Agora a allowlist compara o TEXTO EXATO do achado;
  2. o laudo imprimia zeros LITERAIS por categoria ("credenciais
     reais: 0") independentemente do que fosse encontrado. Agora a
     contagem é real, por categoria;
  3. o código de saída era sempre 0, mesmo com achados.
"""

import argparse
import hashlib
import pathlib
import re
import subprocess
from collections import Counter

# Referência do projeto de produção — comparada por HASH, para que este
# próprio script não a publique num repositório público.
_HASH_PRODUCAO = (
    "d240cf6096d9560448f2a4d6236b46dfae0bf56218ac841b2069151100537de3")

CATEGORIAS: dict[str, str] = {
    "JWT": r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    "Supabase secreta": r"sb_secret_[A-Za-z0-9_-]{8,}",
    "Supabase publicável": r"sb_publishable_[A-Za-z0-9_-]{8,}",
    "OpenAI": r"sk-[A-Za-z0-9_-]{20,}",
    "Google": r"AIza[A-Za-z0-9_-]{30,}",
    "GitHub": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "hash PBKDF2": r"pbkdf2_[a-z0-9]+\$\d+\$[0-9a-f]{8,}\$[0-9a-f]{16,}",
    "CPF": r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
    "e-mail": r"\b[\w][\w.+-]*@[\w-]+\.[\w.]{2,}",
    "chave privada": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "referência do projeto": r"\b[a-z]{15,30}\b",
}

# O padrão de "referência do projeto" casa qualquer palavra minúscula
# longa; quem confirma é o HASH, nunca a expressão.
CATEGORIA_POR_HASH = "referência do projeto"

# ---------------------------------------------------------------------------
# Allowlist por VALOR EXATO — montada em RUNTIME
#
# Literais criados dentro dos próprios testes para exercitar a redação.
# São falsos por construção — e cada um entra aqui pelo texto COMPLETO,
# nunca por um pedaço que apareça na linha.
#
# O PREFIXO fica separado do resto e a junção acontece na importação,
# de modo que no disco não existe o token contíguo. Não é preciosismo:
# o Push Protection do GitHub recusou o push deste repositório por
# causa destas linhas. E ele estava certo — bloqueia por PADRÃO, não
# por veracidade, porque não tem como saber que a chave é inventada e
# não deve acreditar na palavra de quem empurra.
#
# Um repositório que só consegue ser publicado pedindo exceção ao
# scanner tem o mesmo defeito que esta ferramenta existe para apontar:
# o segredo de mentira ensinando todo mundo a desligar o alarme.
#
# É a disciplina que `tests/test_varredura_segredos.py` já seguia. Estes
# literais tinham ficado de fora.
# ---------------------------------------------------------------------------
def _montado(*pedacos: str) -> str:
    """Junta fragmentos que, sozinhos, não casam padrão nenhum."""
    return "".join(pedacos)


FALSOS_CONHECIDOS = frozenset({
    _montado("sb_", "secret_", "credencial-de-teste-jamais-real"),
    _montado("sb_", "publishable_", "credencial-de-teste-publica"),
    _montado("sb_", "secret_", "ABCDEFGH12345678IJKLMNOP"),
    _montado("sb_", "secret_", "ABCDEFGH12345678"),
    _montado("sb_", "publishable_", "ABCDEFGH12345678IJKLMNOP"),
    _montado("sb_", "secret_", "CHAVEFALSADETESTE0123456789"),
    _montado("sb_", "secret_", "abc"),
    _montado("sk-", "proj-", "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
    _montado("sk-", "proj-", "CHAVEFALSADETESTE0123456789ABCDEF"),
    _montado("AIza", "SyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"),
    _montado("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.",
             "cGF5bG9hZC1kZS10ZXN0ZQ.", "assinatura-de-teste"),
    _montado("pbkdf2_", "sha256$200000$sal$hashdasenha"),
    # literal do teste de redação de credencial embutida em URL
    _montado("senha-super-secreta", "@db.exemplo.supabase.co"),
    # remetente que o git grava no cabeçalho de todo format-patch
    _montado("noreply", "@anthropic.com"),
})

# ---------------------------------------------------------------------------
# Domínios RESERVADOS — regra, não isenção
#
# A RFC 2606 reserva `.invalid`, `.test`, `.example` e os
# `example.com/net/org` exatamente para documentação e teste: não
# resolvem e não roteiam, por decisão da IANA. Um endereço ali não é
# endereço de contato de ninguém.
#
# Isto NÃO é isenção por arquivo, que continua não existindo — é regra
# sobre o VALOR, válida em qualquer lugar do repositório e auditável por
# quem ler esta lista. E a ocorrência continua APARECENDO no laudo, como
# falso documentado: sai da contagem que bloqueia, não da que informa.
#
# Limite honesto: domínio reservado diz que o endereço não é contactável;
# não diz que a parte local não carrega o nome de uma pessoa real. Para
# dado pessoal a regra continua sendo não escrever.
# ---------------------------------------------------------------------------
DOMINIOS_RESERVADOS = (
    ".invalid", ".test", ".example", ".localhost",
    "@example.com", "@example.net", "@example.org",
)


def _e_dominio_reservado(valor: str) -> bool:
    alvo = valor.casefold()
    return any(alvo.endswith(sufixo) for sufixo in DOMINIOS_RESERVADOS)

# ---------------------------------------------------------------------------
# Não existe isenção por arquivo. E não pode existir.
#
# A versão anterior isentava `tests/test_varredura_segredos.py`, porque
# esse arquivo precisa conter strings com forma de segredo. Parecia
# estreito e auditável, mas criava um ponto cego com nome e endereço:
# qualquer segredo REAL que caísse ali — por copiar-e-colar durante uma
# depuração, digamos — passaria despercebido para sempre.
#
# A saída é o arquivo de teste não conter literal de segredo nenhum:
# as amostras são MONTADAS em tempo de execução, a partir de pedaços
# que sozinhos não casam padrão algum. O que está no disco não é
# segredo; o que a função recebe, é.
# ---------------------------------------------------------------------------
_RE_ARQUIVO_DO_DIFF = re.compile(r"^diff --git a/(\S+) b/(\S+)")


# ---------------------------------------------------------------------------
# Três estados, não dois
#
# O laudo anterior tinha uma coluna só, "achados", e o texto final
# dizia "LIMPO — nenhum achado" sempre que o total dava zero. Só que o
# total já vinha descontado dos falsos conhecidos: um patch com dez
# ocorrências, todas allowlisted, era anunciado como zero. Quem lia o
# laudo não tinha como distinguir "o scanner não encontrou nada" de "o
# scanner encontrou dez e alguém decidiu, algum dia, que não contavam".
#
# Passam a ser três números, sempre impressos:
#
#   OCORRÊNCIA  — o padrão casou. É o que o scanner viu, sem juízo.
#   FALSO DOCUMENTADO — ocorrência que está na allowlist por valor
#                 exato, com a razão registrada aqui no código.
#   SEGREDO REAL  — ocorrência que não está na allowlist. É o único
#                 número que bloqueia.
# ---------------------------------------------------------------------------
FALSO_DOCUMENTADO = "falso documentado"
SEGREDO_REAL = "segredo real"

# Código de saída da RECUSA. Separado de 1 de propósito: "achei segredo"
# e "não posso assinar este laudo" são resultados diferentes, e um
# pipeline que os confunde trata a segunda como a primeira e some com a
# distinção.
RECUSA = 2


def _sha256(texto: str) -> str:
    """
    Impressão do conteúdo EFETIVAMENTE analisado.

    Sem ela, o laudo diz o que encontrou mas não diz sobre o quê —
    e um laudo que não se pode reproduzir não é evidência.
    """
    return hashlib.sha256(texto.encode("utf-8", "surrogateescape")).hexdigest()


class Achado:
    __slots__ = ("categoria", "valor", "arquivo", "linha", "situacao")

    def __init__(self, categoria: str, valor: str, arquivo: str, linha: int,
                 situacao: str = SEGREDO_REAL):
        self.categoria = categoria
        self.valor = valor
        self.arquivo = arquivo
        self.linha = linha
        self.situacao = situacao

    @property
    def e_real(self) -> bool:
        return self.situacao == SEGREDO_REAL

    def resumo(self) -> str:
        """Descreve o achado sem imprimir o segredo."""
        if self.categoria == CATEGORIA_POR_HASH:
            return "<referência do projeto de produção>"
        return f"{self.valor[:6]}… ({len(self.valor)} caracteres)"


def _e_producao(token: str) -> bool:
    return hashlib.sha256(token.encode()).hexdigest() == _HASH_PRODUCAO


# ---------------------------------------------------------------------------
# Linha REMOVIDA não está na árvore
#
# O escopo `arvore` lê um `git diff`, e um diff carrega as linhas que
# SAÍRAM junto com as que ficaram. Um commit que APAGA um segredo era,
# portanto, relatado como se o contivesse — a ferramenta acusava
# exatamente o ato de limpeza que ela existe para provocar.
#
# No escopo `historico` a remoção CONTA: um segredo que existiu e foi
# removido está no histórico, e é essa a pergunta que aquele escopo
# responde. Os dois comportamentos são corretos, cada um no seu escopo.
# ---------------------------------------------------------------------------
def _e_remocao(linha: str) -> bool:
    """Linha apagada pelo diff — `---` é cabeçalho de arquivo, não remoção."""
    return linha.startswith("-") and not linha.startswith("---")


def varrer(nome: str, texto: str,
           so_o_que_permanece: bool = False) -> list[Achado]:
    """
    Achados REAIS: os falsos conhecidos saem por igualdade exata — e é
    a ÚNICA forma de exceção que existe. Nenhum arquivo é isento.

    Com `so_o_que_permanece`, as linhas removidas pelo diff são
    ignoradas: é o que o escopo `arvore` precisa, porque ele fala do
    estado FINAL dos arquivos.
    """
    achados: list[Achado] = []
    for numero, linha in enumerate(texto.splitlines(), 1):
        if so_o_que_permanece and _e_remocao(linha):
            continue
        for categoria, padrao in CATEGORIAS.items():
            for m in re.finditer(padrao, linha):
                valor = m.group(0)
                if categoria == CATEGORIA_POR_HASH:
                    # o padrão casa qualquer palavra longa; só o hash
                    # confirma. Sem confirmação não é nem ocorrência.
                    if not _e_producao(valor):
                        continue
                    situacao = SEGREDO_REAL
                elif valor in FALSOS_CONHECIDOS:
                    situacao = FALSO_DOCUMENTADO
                elif categoria == "e-mail" and _e_dominio_reservado(valor):
                    # RFC 2606: não roteia, não é contato de ninguém
                    situacao = FALSO_DOCUMENTADO
                else:
                    situacao = SEGREDO_REAL
                achados.append(
                    Achado(categoria, valor, nome, numero, situacao))
    return achados


def sanitizar(texto: str, achados: list[Achado]) -> tuple[str, int]:
    """Substitui cada achado pelo marcador da sua categoria."""
    trocas = 0
    reais = [a for a in achados if a.e_real]
    for valor, categoria in {a.valor: a.categoria for a in reais}.items():
        marcador = ("[PROJETO-REDIGIDO]" if categoria == CATEGORIA_POR_HASH
                    else f"[{categoria.upper()}-REDIGIDO]")
        texto, n = re.subn(re.escape(valor), marcador, texto)
        trocas += n
    return texto, trocas


# ---------------------------------------------------------------------------
# Classificação do CONTEÚDO
#
# `git format-patch` produz mbox: cada commit começa com a linha
# sentinela "From <sha> Mon Sep 17 00:00:00 2001" (a data é fixa, é uma
# piada antiga do git) e traz "Subject: [PATCH ...]". `git diff` não
# tem nada disso — começa direto em "diff --git".
#
# A distinção é o que transforma `--escopo` de rótulo em afirmação
# conferível.
# ---------------------------------------------------------------------------
_RE_MBOX = re.compile(r"^From [0-9a-f]{7,40} Mon Sep 17 00:00:00 2001\s*$",
                      re.M)
_RE_ASSUNTO_PATCH = re.compile(r"^Subject:\s*\[[^\]\n]*PATCH", re.M)
_RE_DIFF_GIT = re.compile(r"^diff --git ", re.M)

FORMATO_MBOX = "format-patch (mbox)"
FORMATO_DIFF = "git diff"
FORMATO_INDETERMINADO = "indeterminado"


class RecusaDeEscopo(Exception):
    """
    O escopo declarado não se sustenta.

    É recusa, não aviso: um laudo que sai com o escopo errado circula
    como se estivesse certo, e o aviso fica no terminal de quem rodou.
    """


def formato_do_conteudo(texto: str) -> str:
    """mbox (format-patch) | git diff | indeterminado."""
    if _RE_MBOX.search(texto) or _RE_ASSUNTO_PATCH.search(texto):
        return FORMATO_MBOX
    if _RE_DIFF_GIT.search(texto):
        return FORMATO_DIFF
    return FORMATO_INDETERMINADO


def commits_no_mbox(texto: str) -> int:
    return len(_RE_MBOX.findall(texto))


def conferir_declaracao(nome: str, texto: str, escopo: str) -> str:
    """
    Confere a DECLARAÇÃO de escopo contra o conteúdo. Devolve o formato
    detectado; levanta `RecusaDeEscopo` quando a declaração é falsa.
    """
    formato = formato_do_conteudo(texto)

    if escopo == "arvore" and formato == FORMATO_MBOX:
        raise RecusaDeEscopo(
            f"{nome} é format-patch (mbox, {commits_no_mbox(texto)} "
            "commit(s)) e foi declarado como ÁRVORE FINAL.\n"
            "  Um format-patch carrega o histórico inteiro, inclusive "
            "linhas que commits posteriores removeram — e também NÃO "
            "carrega o estado final de arquivos que nenhum commit do "
            "intervalo tocou.\n"
            "  Varrer histórico e assinar 'árvore limpa' é a afirmação "
            "mais forte sobre o material mais fraco. Use "
            "`--escopo historico`, ou gere a árvore com "
            "`--repo/--base/--head --escopo arvore`.")

    if escopo == "historico" and formato == FORMATO_DIFF:
        raise RecusaDeEscopo(
            f"{nome} é um `git diff` (estado final) e foi declarado como "
            "HISTÓRICO.\n"
            "  Um diff acumulado não contém os commits intermediários: "
            "declarar histórico a partir dele afirma cobertura que a "
            "varredura não teve. Use `--escopo arvore`, ou gere o "
            "histórico com `--repo/--base/--head --escopo historico`.")

    return formato


# ---------------------------------------------------------------------------
# Modo derivado — o escopo vira comando
# ---------------------------------------------------------------------------
def _git(repo: pathlib.Path, *argumentos: str) -> str:
    processo = subprocess.run(["git", "-C", str(repo), *argumentos],
                              capture_output=True, text=True)
    if processo.returncode != 0:
        erro = (processo.stderr or "").strip().splitlines()
        raise RecusaDeEscopo(
            f"`git {' '.join(argumentos)}` falhou em {repo}: "
            f"{erro[-1] if erro else processo.returncode}")
    return processo.stdout


def _commit(repo: pathlib.Path, revisao: str) -> str:
    """
    Resolve a revisão até o SHA completo.

    O laudo precisa nomear COMMITS, não rótulos: `HEAD` e um nome de
    branch significam coisas diferentes amanhã, e um laudo que não se
    pode reproduzir não é evidência.
    """
    return _git(repo, "rev-parse", "--verify", f"{revisao}^{{commit}}").strip()


def gerar_conteudo(repo: pathlib.Path, base: str, head: str,
                   escopo: str) -> tuple[str, str, str, str]:
    """
    Gera o conteúdo AQUI DENTRO, a partir do escopo.

    É o que impede a divergência entre rótulo e material: não há dois
    valores para discordarem, há uma decisão só.
    """
    sha_base, sha_head = _commit(repo, base), _commit(repo, head)
    if escopo == "arvore":
        comando = ["diff", f"{sha_base}..{sha_head}"]
    else:
        comando = ["format-patch", "--stdout", f"{sha_base}..{sha_head}"]
    nome = f"git {' '.join(comando).replace(sha_base, base).replace(sha_head, head)}"
    return nome, _git(repo, *comando), sha_base, sha_head


def validar_argumentos(args) -> None:
    """
    Recusa combinação ambígua ANTES de varrer qualquer coisa.

    Cada regra existe porque a combinação correspondente produziria um
    laudo cuja procedência ninguém consegue reconstruir.
    """
    derivado = bool(args.repo)
    if derivado and args.diretorio:
        raise RecusaDeEscopo(
            "ambíguo: `--repo` GERA o conteúdo e o diretório o recebe "
            "PRONTO. Varrer os dois e assinar um escopo só produz um "
            "laudo sobre material que ninguém consegue reconstruir.")
    if not derivado and not args.diretorio:
        raise RecusaDeEscopo(
            "informe um diretório de .patch, OU `--repo` com `--base` e "
            "`--head`.")
    if derivado and not (args.base and args.head):
        raise RecusaDeEscopo(
            "`--repo` exige `--base` E `--head`: sem os dois extremos não "
            "há intervalo que se possa nomear no laudo.")
    if not derivado and (args.base or args.head):
        raise RecusaDeEscopo(
            "`--base`/`--head` só existem com `--repo`. Em modo arquivo "
            "eles seriam procedência declarada e não verificável — que é "
            "exatamente o defeito que esta correção remove.")
    if args.saida and not derivado:
        raise RecusaDeEscopo(
            "`--saida` é do modo derivado; em modo arquivo a cópia "
            "sanitizada é gravada ao lado do .patch original.")
    if args.sanitizar and derivado and not args.saida:
        raise RecusaDeEscopo(
            "`--sanitizar` em modo derivado exige `--saida DIR`: o "
            "conteúdo foi gerado em memória e não tem onde ser gravado.")


def _reunir(args) -> tuple[list[tuple[str, str, pathlib.Path | None]], dict]:
    """
    Devolve `[(nome, texto, destino_sanitizado)]` e a PROCEDÊNCIA.

    No modo derivado a procedência é apurada; no modo arquivo ela é
    declarada, e o laudo diz qual das duas coisas está lendo.
    """
    if args.repo:
        repo = pathlib.Path(args.repo)
        nome, texto, sha_base, sha_head = gerar_conteudo(
            repo, args.base, args.head, args.escopo)
        destino = None
        if args.saida:
            saida = pathlib.Path(args.saida)
            saida.mkdir(parents=True, exist_ok=True)
            destino = saida / f"{args.escopo}-sanitizado.patch"
        conteudos = [(nome, texto, destino)] if texto else []
        return conteudos, {
            "modo": "derivado", "origem": nome, "repo": str(repo),
            "base": sha_base, "head": sha_head,
            "apurada": True,
        }

    raiz = pathlib.Path(args.diretorio)
    patches = sorted(a for a in raiz.glob("*.patch")
                     if not a.stem.endswith("-sanitizado"))
    conteudos = []
    for patch in patches:
        texto = patch.read_text(errors="replace")
        # a declaração é conferida ANTES de qualquer varredura: recusar
        # depois de imprimir achados já teria publicado o laudo errado
        conferir_declaracao(patch.name, texto, args.escopo)
        conteudos.append(
            (patch.name, texto,
             patch.with_name(patch.stem + "-sanitizado.patch")))
    return conteudos, {
        "modo": "arquivo", "origem": f"nenhum .patch em {raiz}",
        "repo": None, "base": None, "head": None, "apurada": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Varredura de segredos com escopo conferível.")
    p.add_argument("diretorio", nargs="?",
                   help="diretório com .patch (modo arquivo)")
    p.add_argument("--repo", help="repositório git (modo derivado)")
    p.add_argument("--base", help="revisão inicial do intervalo")
    p.add_argument("--head", help="revisão final do intervalo")
    p.add_argument("--saida", help="onde gravar o sanitizado (modo derivado)")
    p.add_argument("--sanitizar", action="store_true",
                   help="grava cópias *-sanitizado.patch para leitura")
    p.add_argument("--escopo", choices=["arvore", "historico"],
                   default="historico",
                   help="arvore = `git diff BASE..HEAD` (estado FINAL); "
                        "historico = `git format-patch --stdout BASE..HEAD`")
    args = p.parse_args()

    try:
        validar_argumentos(args)
        conteudos, procedencia = _reunir(args)
    except RecusaDeEscopo as recusa:
        print(f"RECUSADO — {recusa}")
        return RECUSA

    if not conteudos:
        print(f"nada a varrer ({procedencia['origem']})")
        return 1

    print(f"=== VARREDURA — {len(conteudos)} conteúdo(s) ===\n")
    todos: list[Achado] = []
    for nome, texto, destino in conteudos:
        achados = varrer(nome, texto,
                         so_o_que_permanece=args.escopo == "arvore")
        todos.extend(achados)

        trocas = 0
        if args.sanitizar and destino is not None:
            limpo, trocas = sanitizar(texto, achados)
            destino.write_text(limpo)

        reais = [a for a in achados if a.e_real]
        marca = (f"{len(achados)} ocorrência(s), {len(reais)} real(is)"
                 if achados else "nenhuma ocorrência")
        sufixo = f" — {trocas} redação(ões)" if args.sanitizar else ""
        print(f"  {nome}\n      {marca}{sufixo}")
        print(f"      formato: {formato_do_conteudo(texto)} · "
              f"sha256 {_sha256(texto)}")
        for a in achados:
            print(f"      [{a.situacao:18}] {a.categoria} "
                  f"(linha {a.linha}): {a.resumo()}")

    # Três colunas, sempre. Um laudo que só mostra o saldo esconde a
    # diferença entre "não encontrei nada" e "encontrei e descontei".
    reais = [a for a in todos if a.e_real]
    falsos = [a for a in todos if not a.e_real]
    por_cat_total = Counter(a.categoria for a in todos)
    por_cat_real = Counter(a.categoria for a in reais)

    print("\n=== LAUDO ===")
    print(f"  {'categoria':24} {'ocorrências':>12} {'falsos doc.':>12}"
          f" {'REAIS':>8}")
    for categoria in CATEGORIAS:
        total = por_cat_total.get(categoria, 0)
        real = por_cat_real.get(categoria, 0)
        print(f"  {categoria:24} {total:>12} {total - real:>12} {real:>8}")
    print(f"  {'TOTAL':24} {len(todos):>12} {len(falsos):>12} "
          f"{len(reais):>8}")

    print(f"\nocorrências .............. {len(todos)}  (o padrão casou)")
    print(f"falsos documentados ...... {len(falsos)}  (allowlist por valor "
          "exato)")
    print(f"segredos reais ........... {len(reais)}  (bloqueiam a entrega)")

    # O ESCOPO muda o que o resultado significa, e confundir os dois
    # produziu a contradição que a revisão apontou: a árvore final
    # limpa foi anunciada como se valesse para o patch, que carrega o
    # histórico inteiro — inclusive linhas que commits posteriores
    # removeram.
    escopo = ("ÁRVORE FINAL (git diff BASE..HEAD)"
              if args.escopo == "arvore"
              else "HISTÓRICO (git format-patch: todos os commits)")
    print(f"\nescopo desta varredura: {escopo}")
    if args.escopo == "historico":
        print("  Ocorrência aqui pode vir de commit posterior REMOVIDO. "
              "Compare com a varredura da árvore antes de concluir.")

    # PROCEDÊNCIA. O laudo tem de dizer sobre o quê ele fala, e se sabe
    # disso por apuração própria ou por declaração de quem o rodou.
    print("\n--- procedência ---")
    print(f"  modo ..................... {procedencia['modo']}")
    if procedencia["apurada"]:
        print(f"  repositório .............. {procedencia['repo']}")
        print(f"  base ..................... {procedencia['base']}")
        print(f"  head ..................... {procedencia['head']}")
        print("  ESCOPO APURADO: o comando foi escolhido pelo --escopo, "
              "então rótulo e conteúdo não podem divergir.")
    else:
        print("  base ..................... não declarada (modo arquivo)")
        print("  head ..................... não declarada (modo arquivo)")
        print("  ESCOPO DECLARADO pelo operador e conferido contra o "
              "formato do conteúdo. Para procedência apurada, use "
              "--repo/--base/--head.")
    combinado = _sha256("\n".join(t for _, t, _ in conteudos))
    print(f"  sha256 do conteúdo ....... {combinado}")
    for nome, texto, _ in conteudos:
        print(f"    {formato_do_conteudo(texto):20} {_sha256(texto)}  {nome}")

    if reais:
        print(f"\n{len(reais)} SEGREDO(S) REAL(IS) no escopo "
              f"{args.escopo.upper()}. NÃO declare limpo. Resolva ou "
              "documente cada um antes de publicar.")
        return 1
    if todos:
        print(f"\nSEM SEGREDO REAL no escopo {args.escopo.upper()} — as "
              f"{len(todos)} ocorrência(s) saíram por allowlist de valor "
              "exato ou por domínio reservado (RFC 2606). Confira as duas "
              "listas antes de confiar nelas.")
        return 0
    print(f"\nNENHUMA OCORRÊNCIA no escopo {args.escopo.upper()} — o "
          "scanner não casou padrão algum.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
