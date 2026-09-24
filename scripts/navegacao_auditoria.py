#!/usr/bin/env python3
"""
§5 da auditoria: a sequência do servidor, percorrida num navegador real.

    python scripts/homologacao_stack.py --executar \
        "GOVDOCS_IA_SIMULADA=coerente .venv/bin/python \
         scripts/navegacao_auditoria.py --cenario A"

POR QUE UM NAVEGADOR, E NÃO O AppTest

O projeto já tem provas de interface com `streamlit.testing`. Elas
rodam o script do app no processo do pytest: pegam lógica de tela, e
não pegam o que só existe no navegador — rerun que perde estado,
componente que não monta, botão que fica desabilitado, recarregar a
página, voltar uma etapa, reabrir um processo salvo depois de fechar a
aba. O §5 pede exatamente essas coisas, e o §2 manda registrar a
diferença quando ela existir em vez de trocar uma pela outra.

O QUE ELE PERCORRE

    Login → Painel → Novo processo → Dados da demanda → Geração
          → Revisão e edição → Aprovação → Exportação → Salvamento
          → Recarregar a página → Reabertura do processo salvo

Cada passo grava captura de tela e o texto da página em
`/tmp/auditoria/`, e o roteiro CONFERE o que viu — um roteiro que só
clica e tira foto não distingue "funcionou" de "abriu".

O QUE ELE NÃO PODE PROVAR

Nada sobre a qualidade do texto gerado: a resposta vem de fixture. E
nada sobre o Supabase Auth: a pilha de homologação não tem GoTrue, o
login percorre o caminho legado da tabela `usuarios`. As duas fronteiras
vão ao laudo.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

import massas_auditoria as massas  # noqa: E402

SAIDA = pathlib.Path("/tmp/auditoria")
NAVEGADOR = "/opt/pw-browsers/chromium"

USUARIO = "auditor"
SENHA = "homologacao-2026"
NOME = "Servidor de Homologação"


class Reprovado(AssertionError):
    """Um passo do §5 não fez o que devia. É achado, não exceção solta."""


class Roteiro:
    """Percurso com evidência: cada passo grava tela, texto e veredito."""

    def __init__(self, pagina, rotulo: str):
        self.p = pagina
        self.rotulo = rotulo
        self.passo = 0
        self.diario: list[dict] = []
        self.erros_de_console: list[str] = []
        SAIDA.mkdir(parents=True, exist_ok=True)
        pagina.on("console", self._console)
        pagina.on("pageerror",
                  lambda e: self.erros_de_console.append(f"PAGEERROR {e}"[:200]))

    def _console(self, mensagem) -> None:
        if mensagem.type == "error":
            self.erros_de_console.append(mensagem.text[:200])

    # -- espera ------------------------------------------------------
    def parar(self, ms: int = 900) -> None:
        """
        Espera o Streamlit terminar o rerun.

        `wait_for_load_state` não serve: o Streamlit não navega, ele
        troca o DOM por WebSocket. O sinal é o indicador de execução
        sumir — e depois dele ainda há um respiro, porque o widget
        aparece antes de o valor chegar.
        """
        self.p.wait_for_timeout(ms)
        limite = time.time() + 90
        while time.time() < limite:
            if self.p.locator('[data-testid="stStatusWidget"]').count() == 0:
                break
            self.p.wait_for_timeout(250)
        self.p.wait_for_timeout(400)

    def texto(self) -> str:
        return self.p.locator("body").inner_text()

    # -- evidência ---------------------------------------------------
    def registrar(self, nome: str, exigir=(), proibir=()) -> str:
        self.passo += 1
        prefixo = f"{self.rotulo}_{self.passo:02d}_{nome}"
        self.p.screenshot(path=str(SAIDA / f"{prefixo}.png"), full_page=True)
        corpo = self.texto()
        (SAIDA / f"{prefixo}.txt").write_text(corpo, encoding="utf-8")

        faltando = [t for t in exigir if t not in corpo]
        indevidos = [t for t in proibir if t in corpo]
        self.diario.append({
            "passo": self.passo, "nome": nome,
            "faltando": faltando, "indevidos": indevidos,
        })
        if faltando or indevidos:
            raise Reprovado(
                f"[{prefixo}] ausente: {faltando} | indevido: {indevidos}")
        return corpo

    # -- interação ---------------------------------------------------
    def campo(self, rotulo: str):
        """
        O `input`/`textarea`, nunca o botão de ajuda.

        `get_by_label` casa os dois — o Streamlit dá ao botão de ajuda
        um `aria-label` "Help for <rótulo>" —, e a ambiguidade derruba o
        roteiro no modo estrito.
        """
        return self.p.locator(
            f'input[aria-label="{rotulo}"], textarea[aria-label="{rotulo}"]')

    def preencher(self, rotulo: str, valor: str) -> None:
        campo = self.campo(rotulo)
        if campo.count() == 0:
            raise Reprovado(f"campo ausente na tela: {rotulo!r}")
        campo.first.fill(valor)
        campo.first.press("Tab")

    def digitar(self, rotulo: str, valor: str) -> None:
        """
        Digita tecla a tecla e confirma com Enter.

        `fill()` escreve o valor no DOM, e para os campos DENTRO de um
        `st.form` isso basta — o submit recolhe tudo. Fora do form não
        basta: medido, o botão "Entrar" continuava DESABILITADO depois
        de `fill()` + Tab, porque o Streamlit só promove o valor a
        `session_state` no rerun que a própria digitação dispara.
        Datilografar e apertar Enter é o que o servidor faz, e é o que
        o widget escuta.
        """
        campo = self.campo(rotulo)
        if campo.count() == 0:
            raise Reprovado(f"campo ausente na tela: {rotulo!r}")
        campo.first.click()
        campo.first.press_sequentially(valor, delay=25)
        campo.first.press("Enter")
        self.parar(900)

    def valor_do_campo(self, rotulo: str) -> str:
        """
        O que está DENTRO do campo.

        `inner_text()` do corpo não enxerga valor de `input` nem de
        `textarea` — a primeira versão deste roteiro conferia o objeto
        procurando o texto na página e reprovava um formulário que
        estava corretamente preenchido. Achado da ferramenta, não do
        sistema.
        """
        campo = self.campo(rotulo)
        if campo.count() == 0:
            raise Reprovado(f"campo ausente na tela: {rotulo!r}")
        return campo.first.input_value()

    def conferir_campos(self, esperados: dict) -> None:
        divergentes = {
            rotulo: (self.valor_do_campo(rotulo)[:60], str(valor)[:60])
            for rotulo, valor in esperados.items()
            if self.valor_do_campo(rotulo).strip() != str(valor).strip()
        }
        if divergentes:
            raise Reprovado(f"campos não preservaram o que foi digitado: "
                            f"{divergentes}")

    def clicar(self, nome: str, exato: bool = False) -> None:
        botao = self.p.get_by_role("button", name=nome, exact=exato)
        if botao.count() == 0:
            raise Reprovado(f"botão ausente na tela: {nome!r}")
        botao.first.click()
        self.parar()


# ---------------------------------------------------------------------------
# A planilha entra como o servidor a manda: um arquivo .xlsx
# ---------------------------------------------------------------------------
def xlsx_da_massa(itens: list[dict]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.append(["Código", "Descrição", "Unidade", "Quantidade",
                "Valor Unitário"])
    for item in itens:
        aba.append([item.get("codigo", ""), item["descricao"],
                    item["unidade"], item["quantidade"],
                    item["valor_unitario"]])
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Os passos
# ---------------------------------------------------------------------------
def entrar(r: Roteiro) -> None:
    corpo = r.texto()
    if "Primeiro acesso" in corpo:
        r.preencher("Nome completo", NOME)
        r.preencher("Login", USUARIO)
        r.preencher("Senha", SENHA)
        r.preencher("Confirmar senha", SENHA)
        r.clicar("Criar administrador")
    elif "Acesso ao sistema" in corpo:
        # O botão "Entrar" nasce DESABILITADO e só habilita quando os
        # dois valores chegam ao `session_state` — o que acontece no
        # rerun disparado por cada campo. Sem esperar entre um e outro,
        # o roteiro clica num botão desabilitado e espera 30 s por um
        # elemento que não vai habilitar sozinho.
        r.digitar("Usuário", USUARIO)
        r.digitar("Senha", SENHA)
        r.clicar("Entrar")
    r.parar(2500)
    r.registrar("painel", exigir=("Dados da Demanda",))


def preencher_demanda(r: Roteiro, cenario: dict) -> None:
    dados = cenario["dados"]
    caminho = SAIDA / f"planilha_{cenario['id']}.xlsx"
    caminho.write_bytes(xlsx_da_massa(dados["itens"]))

    # O uploader vive dentro de um expander fechado.
    for rotulo in ("Importar planilha Excel",):
        alvo = r.p.get_by_text(rotulo, exact=False)
        if alvo.count():
            alvo.first.click()
            r.parar(400)
    enviados = r.p.locator('input[type="file"]')
    enviados.last.set_input_files(str(caminho))
    r.parar(2500)

    r.preencher("Quem está pedindo *", dados["orgao"])
    r.preencher("O que vai ser comprado ou contratado *", dados["objeto"])
    r.preencher("Por que isso é necessário *", dados["justificativa"])
    if dados.get("responsavel"):
        r.preencher("Quem assina o pedido", dados["responsavel"])
    if dados.get("requisitos"):
        r.preencher("Exigências que o fornecedor precisa cumprir",
                    dados["requisitos"])
    if dados.get("riscos"):
        r.preencher("O que pode dar errado", dados["riscos"])
    if dados.get("alinhamento"):
        r.preencher("Já estava no planejamento do ano?", dados["alinhamento"])
    if dados.get("prazo"):
        r.preencher("Para quando você precisa", dados["prazo"])

    escolher_modelo(r, dados["modelo_execucao"])
    r.parar(800)
    r.registrar("formulario_preenchido", proibir=("Traceback",))
    r.conferir_campos({
        "Quem está pedindo *": dados["orgao"],
        "O que vai ser comprado ou contratado *": dados["objeto"],
        "Por que isso é necessário *": dados["justificativa"],
    })


def escolher_modelo(r: Roteiro, valor: str) -> None:
    caixa = r.campo("Como a entrega vai acontecer *")
    if caixa.count() == 0:
        raise Reprovado("selector do modelo de execução ausente")
    caixa.first.click()
    r.p.wait_for_timeout(400)
    opcao = r.p.get_by_role("option", name=valor, exact=True)
    if opcao.count() == 0:
        opcao = r.p.get_by_text(valor, exact=True)
    if opcao.count() == 0:
        raise Reprovado(f"opção {valor!r} ausente do seletor")
    opcao.first.click()
    r.parar(600)


def _contador_de_obrigatorios(corpo: str) -> str:
    for linha in corpo.splitlines():
        if "campos obrigatórios" in linha:
            return linha.strip()
    return ""


def salvar_e_iniciar(r: Roteiro, cenario: dict) -> None:
    """
    Salvar rascunho, conferir o contador e começar a elaboração.

    O contador é conferido DEPOIS do salvamento de propósito: é o
    momento em que `st.session_state.dados` passa a ter o que foi
    digitado, e portanto o momento em que ele tem de estar certo.
    """
    r.clicar("Salvar rascunho")
    r.parar(2500)
    corpo = r.registrar("rascunho_salvo", proibir=("Traceback",))
    r.diario[-1]["contador"] = _contador_de_obrigatorios(corpo)

    r.clicar("Iniciar elaboração dos documentos")
    r.parar(4000)
    r.registrar("apos_iniciar", proibir=("Traceback",))


def gerar_documento(r: Roteiro, sigla: str) -> str:
    """Clica em gerar, espera o documento aparecer e devolve o texto."""
    alvo = r.p.get_by_role("button", name=f"Gerar {sigla}", exact=False)
    if alvo.count() == 0:
        alvo = r.p.get_by_role("button", name="Gerar ", exact=False)
    if alvo.count() == 0:
        raise Reprovado(f"sem botão de geração na etapa {sigla}: "
                        f"{inventario_da_tela(r, 'sem_gerar')['botoes']}")
    alvo.first.click()

    # A geração tem overlay próprio e sobrevive a reruns; esperar só o
    # indicador do Streamlit devolveria a tela no meio do caminho.
    limite = time.time() + 240
    ultimo = ""
    while time.time() < limite:
        r.p.wait_for_timeout(1000)
        try:
            corpo = r.texto()
        except Exception:  # noqa: BLE001 — DOM trocando no meio do rerun
            continue
        ultimo = corpo
        if "sendo elaborado" in corpo:
            continue
        if any(marca in corpo for marca in
               ("Aprovar", "Gerar novamente", "Não foi possível")):
            break
    else:
        # Estourar o prazo É um achado do §15 ("indicadores de progresso
        # correspondentes a eventos reais"), não um defeito do roteiro:
        # a tela ficou sem oferecer saída por mais de quatro minutos.
        (SAIDA / f"travou_{sigla.lower()}.txt").write_text(
            ultimo, encoding="utf-8")
        raise Reprovado(
            f"{sigla}: a tela não ofereceu aprovação nem erro em 240 s")
    corpo = r.registrar(f"gerado_{sigla.lower()}", proibir=("Traceback",))
    if "Não foi possível" in corpo:
        raise Reprovado(f"{sigla}: a geração falhou na tela — "
                        "o servidor veria a mensagem genérica de erro")
    return corpo


def aprovar(r: Roteiro, sigla: str) -> None:
    alvo = r.p.get_by_role("button", name="Aprovar", exact=False)
    if alvo.count() == 0:
        raise Reprovado(
            f"{sigla}: sem botão de aprovação — "
            f"{inventario_da_tela(r, 'sem_aprovar')['botoes']}")
    alvo.first.click()
    r.parar(3000)
    r.registrar(f"aprovado_{sigla.lower()}", proibir=("Traceback",))


def percorrer_documentos(r: Roteiro, cenario: dict) -> list[str]:
    """
    Gera e aprova cada documento até a tela de conclusão.

    A lista de etapas vem da TELA, não de uma constante do roteiro: com
    `flag_mapa_riscos` ligada o fluxo tem cinco documentos, sem ela tem
    quatro, e um roteiro que soubesse a resposta de antemão deixaria de
    perceber a diferença.
    """
    percorridos: list[str] = []
    for _ in range(10):
        gerar = r.p.get_by_role("button", name="Gerar ", exact=False) \
                   .filter(has_not_text="novamente")
        aprovacao = r.p.get_by_role("button", name="Aprovar", exact=False)

        if gerar.count():
            rotulo = gerar.first.inner_text().strip()
            sigla = (rotulo.replace("Gerar ", "").replace(" com IA", "")
                     .replace("minuta do ", "").strip())
            gerar_documento(r, sigla)
        elif aprovacao.count():
            # O Mapa de Riscos gera SOZINHO ao entrar na etapa
            # (`steps.render_etapa_documento`: `automatico = doc_key ==
            # "mapa_riscos" and novo and not erro`). Um roteiro que só
            # soubesse clicar em "Gerar" pararia aqui achando que o
            # fluxo acabou — e o relatório diria "o fluxo tem dois
            # documentos", que é falso.
            sigla = _etapa_corrente(r)
        else:
            break

        aprovar(r, sigla)
        percorridos.append(sigla)
    return percorridos


def _etapa_corrente(r: Roteiro) -> str:
    """O nome da etapa pelo título da página — o stepper é a fonte."""
    titulo = r.p.locator("h1, h2, h3")
    for i in range(titulo.count()):
        texto = titulo.nth(i).inner_text().strip()
        if texto and "GovConnect" not in texto:
            return texto[:40]
    return "documento"


def exportar(r: Roteiro) -> list[str]:
    """Quais downloads a tela final oferece — e se ela chega a existir."""
    corpo = r.registrar("tela_final", proibir=("Traceback",))
    botoes = inventario_da_tela(r, "exportacao")["botoes"]
    baixaveis = [b for b in botoes
                 if any(m in b.lower() for m in ("baixar", ".docx", ".pdf",
                                                 "exportar", "dossiê"))]
    if not baixaveis:
        raise Reprovado(f"nenhuma exportação oferecida na tela final: {botoes}")
    r.diario[-1]["exportacoes"] = baixaveis
    r.diario[-1]["concluido"] = "Concluído" in corpo
    return baixaveis


def recarregar_e_reabrir(r: Roteiro, cenario: dict) -> None:
    """
    O passo que separa "salvou" de "consigo voltar".

    Recarregar a página derruba o `session_state` inteiro: o que
    sobrevive é o que o banco guardou. Reabrir pela lista de processos
    é o caminho que o servidor usa no dia seguinte.
    """
    r.p.reload(wait_until="domcontentloaded")
    r.parar(5000)
    corpo = r.registrar("apos_recarregar", proibir=("Traceback",))

    # ACHADO DO §5, medido: recarregar a página DESLOGA. A sessão vive
    # inteira no `st.session_state`, e o Streamlit a descarta quando a
    # aba recarrega — não há cookie de sessão. O servidor que aperta F5,
    # perde a rede por um instante ou reabre a aba volta para o login no
    # meio do processo.
    #
    # O roteiro segue em frente entrando de novo, porque a pergunta que
    # importa é a seguinte: o TRABALHO sobreviveu? Parar aqui reportaria
    # o incômodo e deixaria a perda de dados sem medição.
    r.diario[-1]["deslogou_no_reload"] = "Acesso ao sistema" in corpo
    if "Acesso ao sistema" in corpo:
        entrar(r)

    # A navegação lateral é um `st.radio` (ver `components.render_sidebar`),
    # não uma lista de botões: procurar por `button` devolvia zero e o
    # roteiro acusava "sem acesso à lista" num app que tinha a lista.
    aba = r.p.get_by_role("radio", name="Processos", exact=True)
    if aba.count() == 0:
        raise Reprovado(
            f"sem acesso à lista de processos depois do reload: "
            f"{inventario_da_tela(r, 'sem_processos')['botoes']}")
    aba.first.click(force=True)
    r.parar(3000)
    corpo = r.registrar("lista_de_processos", proibir=("Traceback",))

    objeto = cenario["dados"]["objeto"][:40]
    if objeto not in corpo:
        raise Reprovado(
            "o processo salvo não aparece na lista depois de recarregar — "
            "é perda de trabalho, não inconveniência")

    abrir = r.p.get_by_role("button", name="Continuar de onde parei",
                            exact=False)
    if abrir.count() == 0:
        raise Reprovado(
            f"processo listado mas sem como abrir: "
            f"{inventario_da_tela(r, 'sem_abrir')['botoes']}")
    abrir.first.click()
    r.parar(5000)
    corpo = r.registrar("processo_reaberto", proibir=("Traceback",))

    # A pergunta do §5 não é "abriu": é se o TRABALHO voltou. O processo
    # tinha cinco documentos aprovados; se a reabertura trouxesse o
    # formulário vazio, o autosalvamento não guardaria o que diz guardar
    # — e isso é perda de dados, não incômodo.
    #
    # Procurar o objeto NA TELA de conclusão não responde: ela mostra o
    # dossiê, não o formulário. Quem responde é o campo, e para chegar
    # até ele é preciso voltar à primeira etapa — que é, aliás, o
    # "avance e retorne entre as etapas" que o §5 pede.
    r.diario[-1]["reabriu_na_conclusao"] = "Emissão dos documentos" in corpo

    voltar = r.p.get_by_role("button", name="Dados da Demanda", exact=False)
    if voltar.count() == 0:
        raise Reprovado("processo reaberto sem como voltar à primeira etapa")
    voltar.first.click()
    r.parar(3000)
    r.registrar("voltou_ao_formulario", proibir=("Traceback",))
    r.conferir_campos({
        "Quem está pedindo *": cenario["dados"]["orgao"],
        "O que vai ser comprado ou contratado *": cenario["dados"]["objeto"],
        "Por que isso é necessário *": cenario["dados"]["justificativa"],
    })
    r.diario[-1]["formulario_preservado"] = True


def inventario_da_tela(r: Roteiro, nome: str) -> dict:
    """Botões e abas visíveis — para escrever o próximo passo do roteiro."""
    botoes = []
    alvo = r.p.get_by_role("button")
    for i in range(alvo.count()):
        texto = alvo.nth(i).inner_text().strip()
        if texto:
            botoes.append(texto[:60])
    inventario = {"tela": nome, "botoes": botoes}
    (SAIDA / f"inventario_{nome}.json").write_text(
        json.dumps(inventario, ensure_ascii=False, indent=2), encoding="utf-8")
    return inventario


def principal(argv: list[str] | None = None) -> int:
    from playwright.sync_api import sync_playwright

    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--cenario", default="A")
    analisador.add_argument("--largura", type=int, default=1440)
    analisador.add_argument("--altura", type=int, default=950)
    analisador.add_argument("--ate", default="fim")
    analisador.add_argument(
        "--so-reabrir", action="store_true",
        help="pula a criação e vai direto à reabertura do que já está salvo")
    argumentos = analisador.parse_args(argv)

    escolhidos = {c["id"]: c for c in massas.todos_com_g()}
    cenario = escolhidos[argumentos.cenario]

    import os

    url = os.environ["GOVDOCS_URL_APP"]
    veredito: dict = {"cenario": cenario["id"], "passos": [], "erro": ""}

    with sync_playwright() as pw:
        navegador = pw.chromium.launch(executable_path=NAVEGADOR)
        contexto = navegador.new_context(
            viewport={"width": argumentos.largura, "height": argumentos.altura})
        pagina = contexto.new_page()
        r = Roteiro(pagina, f"{cenario['id']}_{argumentos.largura}")
        try:
            pagina.goto(url, wait_until="domcontentloaded")
            r.parar(4000)
            entrar(r)
            if argumentos.so_reabrir:
                recarregar_e_reabrir(r, cenario)
            else:
                if argumentos.ate != "login":
                    preencher_demanda(r, cenario)
                if argumentos.ate not in ("login", "formulario"):
                    salvar_e_iniciar(r, cenario)
                    veredito["documentos"] = percorrer_documentos(r, cenario)
                    veredito["exportacoes"] = exportar(r)
                    recarregar_e_reabrir(r, cenario)
        except Reprovado as erro:
            veredito["erro"] = str(erro)
        finally:
            veredito["passos"] = r.diario
            veredito["erros_de_console"] = r.erros_de_console
            navegador.close()

    (SAIDA / f"veredito_{cenario['id']}.json").write_text(
        json.dumps(veredito, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(veredito, ensure_ascii=False, indent=2))
    return 1 if veredito["erro"] else 0


if __name__ == "__main__":
    raise SystemExit(principal())
