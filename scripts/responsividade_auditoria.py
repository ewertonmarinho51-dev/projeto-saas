#!/usr/bin/env python3
"""
§16 da auditoria: as larguras de tela, e o que cada problema CUSTA.

    python scripts/homologacao_stack.py --executar \
        ".venv/bin/python scripts/responsividade_auditoria.py"

O §16 pede classificação pela consequência concreta para o servidor —
confusão, retrabalho, perda de informação, operação incorreta ou
impedimento de uso —, e não avaliação estética. Por isso o roteiro não
mede "ficou bonito": mede COISAS QUE ACONTECEM.

  * `elementoDePonto`: qual elemento recebe o clique no centro de um
    campo do formulário. Se não for o campo, alguma coisa está por cima
    dele e o servidor não consegue usar — impedimento de uso;
  * `rolagemHorizontal`: a página rola para o lado? Tabela larga que
    força rolagem lateral esconde coluna, e coluna escondida é
    quantidade que ninguém confere;
  * `cortados`: campos e botões que saem da largura da janela.

As capturas ficam em /tmp/auditoria para conferência humana. O roteiro
não substitui olhar: ele aponta onde olhar.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from navegacao_auditoria import (  # noqa: E402
    NAVEGADOR, NOME, SAIDA, SENHA, USUARIO, Roteiro,
)

# Desktop comum, notebook estreito, tablet em pé e telefone. O telefone
# entra porque o §16 manda incluir dispositivos móveis "quando
# pertinente", e um servidor conferindo um processo fora da repartição é
# um caso real — ainda que não seja o de elaborar.
LARGURAS = (
    ("desktop", 1920, 1080),
    ("notebook", 1440, 900),
    ("tablet", 768, 1024),
    ("telefone", 390, 844),
)


def _entrar(r: Roteiro) -> None:
    corpo = r.texto()
    if "Primeiro acesso" in corpo:
        r.preencher("Nome completo", NOME)
        r.preencher("Login", USUARIO)
        r.preencher("Senha", SENHA)
        r.preencher("Confirmar senha", SENHA)
        r.clicar("Criar administrador")
    elif "Acesso ao sistema" in corpo:
        r.digitar("Usuário", USUARIO)
        r.digitar("Senha", SENHA)
        r.clicar("Entrar")
    r.parar(2500)


def _elemento_no_centro_do_campo(pagina) -> str:
    """
    O que REALMENTE está no ponto — atravessando o shadow DOM.

    `document.elementFromPoint` devolve o HOST quando o alvo está dentro
    de um shadow root, e foi por isso que a primeira medição acusou
    "stBidiComponentIsolated" sem dizer o quê: o host do GovBot tem 0×0
    e `pointer-events: none`. Quem intercepta é um descendente dele, e a
    diferença entre o painel aberto e o lançador importa — um o servidor
    fecha, o outro não.
    """
    return pagina.evaluate(
        """() => {
            const campo = document.querySelector(
                'textarea[aria-label^="O que vai ser comprado"], '
                + 'input[aria-label^="Quem está pedindo"]');
            if (!campo) return "campo ausente";
            const r = campo.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            if (y < 0 || y > window.innerHeight) return "fora da janela";
            let alvo = document.elementFromPoint(x, y);
            while (alvo && alvo.shadowRoot) {
                const dentro = alvo.shadowRoot.elementFromPoint(x, y);
                if (!dentro || dentro === alvo) break;
                alvo = dentro;
            }
            if (!alvo) return "nada";
            if (alvo === campo || campo.contains(alvo)) return "o proprio campo";
            return (alvo.className && String(alvo.className).slice(0, 40))
                || alvo.getAttribute('data-testid') || alvo.tagName;
        }"""
    )


def fechar_govbot(pagina) -> bool:
    """Fecha o assistente, se houver o que fechar. Devolve se fechou."""
    for seletor in (".govbot-close", '[aria-label*="Fechar"]',
                    ".govbot-scrim"):
        alvo = pagina.locator(seletor)
        if alvo.count() and alvo.first.is_visible():
            alvo.first.click(force=True)
            pagina.wait_for_timeout(900)
            return True
    return False


def medir(pagina, rotulo: str) -> dict:
    """O que acontece nesta largura, em fatos verificáveis."""
    rolagem = pagina.evaluate(
        "() => document.documentElement.scrollWidth - "
        "document.documentElement.clientWidth")

    # Quem recebe o clique no centro de um campo obrigatório do
    # formulário. Se não for o próprio campo, há algo por cima — e a
    # medição é feita DUAS vezes, com o assistente como ele abre e
    # depois de fechado, porque a diferença entre "atrapalha até você
    # fechar" e "impede de usar" é a própria classificação do §16.
    quem_recebe = _elemento_no_centro_do_campo(pagina)
    fechou = fechar_govbot(pagina)
    quem_recebe_sem_govbot = (_elemento_no_centro_do_campo(pagina)
                              if fechou else quem_recebe)

    # Nomeados, e não contados: "16 elementos cortados" não diz se são
    # dezesseis campos do formulário ou dezesseis itens de uma barra
    # lateral que está deliberadamente fora da tela. O §16 pede a
    # consequência concreta, e ela depende de QUEM ficou de fora.
    cortados = pagina.evaluate(
        """() => {
            const largura = document.documentElement.clientWidth;
            const alvos = [...document.querySelectorAll(
                'button, input, textarea, [data-testid="stDataFrame"]')];
            return alvos.filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && (r.right > largura + 2 || r.left < -2);
            }).map(el => ({
                rotulo: (el.getAttribute('aria-label')
                         || (el.innerText || '').trim().slice(0, 30)
                         || el.tagName),
                dentroDaBarraLateral: !!el.closest(
                    'section[data-testid="stSidebar"]'),
            })).slice(0, 25);
        }"""
    )
    return {"tela": rotulo, "rolagem_horizontal_px": rolagem,
            "clique_no_campo_chega_em": quem_recebe,
            "govbot_fechavel": fechou,
            "clique_apos_fechar_govbot": quem_recebe_sem_govbot,
            "cortados_no_conteudo": [c["rotulo"] for c in cortados
                                     if not c["dentroDaBarraLateral"]],
            "cortados_na_barra_lateral": sum(
                1 for c in cortados if c["dentroDaBarraLateral"])}


def principal() -> int:
    from playwright.sync_api import sync_playwright

    url = os.environ["GOVDOCS_URL_APP"]
    medidas = []

    with sync_playwright() as pw:
        navegador = pw.chromium.launch(executable_path=NAVEGADOR)
        for rotulo, largura, altura in LARGURAS:
            contexto = navegador.new_context(
                viewport={"width": largura, "height": altura})
            pagina = contexto.new_page()
            r = Roteiro(pagina, f"resp_{rotulo}")
            pagina.goto(url, wait_until="domcontentloaded")
            r.parar(4000)
            _entrar(r)
            r.registrar(f"formulario_{largura}px")
            medida = medir(pagina, rotulo)
            medida["largura"] = largura
            medida["erros_de_console"] = r.erros_de_console[:5]
            medidas.append(medida)
            contexto.close()
        navegador.close()

    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / "responsividade.json").write_text(
        json.dumps(medidas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(medidas, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
