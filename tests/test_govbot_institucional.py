"""
§36 e §37: o GovBot no cadastro institucional, e o portão que o segura.

OS NOVE CRITÉRIOS DE ACEITE DO ESCOPO, UM A UM

1. membros da equipe → só os da portaria aplicável
2. portaria → número e data de publicação cadastrados
3. servidor elegível pode ser sugerido
4. servidor fora da equipe NÃO entra por comando ao robô
5. servidor de outra prefeitura não é consultado nem selecionado
6. portaria revogada/futura/fora da vigência não autoriza
7. ausência ou conflito gera PENDÊNCIA, não escolha
8. troca passa pelo backend, e não só pela conversa
9. o robô não altera portaria, função ou vínculo para validar o pedido

O CRITÉRIO 8 É O QUE DECIDE A ARQUITETURA

"Não basta o GovBot recusar o pedido em linguagem natural: uma chamada
direta ao mecanismo de alteração deve estar sujeita às mesmas regras."

Por isso as provas do portão chamam `instituicional_bridge.guardar_escolhas`
DIRETO, sem passar por conversa nenhuma. Se a verificação vivesse no
prompt, todas elas passariam — e o sistema estaria aberto.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from src import assinaturas, govbot_institucional as gbi, portarias

HOJE = _dt.date(2026, 3, 10)

ANTONIO = {"id": "s-a", "nome": "Antonio Ewerton Marinho", "ativo": True,
           "cargo": "Agente Administrativo"}
MARIA = {"id": "s-m", "nome": "Maria Silva Souza", "ativo": True,
         "cargo": "Técnica em Contabilidade"}
JOAO = {"id": "s-j", "nome": "João Pereira Lima", "ativo": True,
        "cargo": "Assistente"}
INATIVO = {"id": "s-x", "nome": "Carlos Antigo", "ativo": False}

PORTARIA = {"id": "p-1", "secretaria_id": "sec-1", "numero": "003",
            "ano": 2026, "tipo": "EQUIPE_PLANEJAMENTO", "status": "ATIVA",
            "data_publicacao": "2026-01-15",
            "data_inicio_vigencia": "2026-01-15", "data_fim_vigencia": None}

MEMBROS = [
    {"portaria_id": "p-1", "servidor_id": "s-a",
     "funcao": "EQUIPE_PLANEJAMENTO", "ativo": True, "ordem": 1},
    {"portaria_id": "p-1", "servidor_id": "s-m",
     "funcao": "COORDENADOR_EQUIPE_PLANEJAMENTO", "ativo": True, "ordem": 2},
]


def panorama(**ajustes) -> gbi.Panorama:
    base = dict(secretaria_id="sec-1", data_referencia=HOJE,
                servidores=[ANTONIO, MARIA, JOAO], funcoes_do_servidor=[],
                portaria=PORTARIA, membros=MEMBROS, aviso="")
    base.update(ajustes)
    return gbi.Panorama(**base)


# ---------------------------------------------------------------------------
# 1) Membros da equipe: só os da portaria aplicável
# ---------------------------------------------------------------------------
def test_membros_vem_so_da_portaria_aplicavel():
    resposta = gbi.responder_membros(panorama())
    assert "Antonio Ewerton Marinho" in resposta
    assert "Maria Silva Souza" in resposta
    assert "João" not in resposta, (
        "João está no cadastro do município e NÃO na portaria — listá-lo "
        "seria inventar designação")


def test_membros_de_outra_portaria_nao_entram():
    """`portaria_id` diferente é outra equipe, de outra secretaria."""
    intrusos = MEMBROS + [{"portaria_id": "p-OUTRA", "servidor_id": "s-j",
                           "funcao": "EQUIPE_PLANEJAMENTO", "ativo": True}]
    assert "João" not in gbi.responder_membros(panorama(membros=intrusos))


# ---------------------------------------------------------------------------
# 2) Portaria: número e data de publicação CADASTRADOS
# ---------------------------------------------------------------------------
def test_a_portaria_sai_com_numero_e_data_do_cadastro():
    resposta = gbi.responder_portaria(panorama())
    assert "003/2026" in resposta
    assert "15 de janeiro de 2026" in resposta


def test_sem_portaria_o_robo_nao_inventa_numero():
    import re
    resposta = gbi.responder_portaria(panorama(portaria=None, membros=[]))
    assert not re.search(r"n[ºo°]\s*\d", resposta), (
        f"apareceu número de portaria numa resposta de ausência: {resposta}")
    assert "não inventa" in resposta or "pendência" in resposta


# ---------------------------------------------------------------------------
# 3) Servidor elegível PODE ser sugerido
# ---------------------------------------------------------------------------
def test_servidor_da_portaria_e_aprovado_para_a_funcao():
    veredito = gbi.avaliar_troca(panorama(), nome="Maria",
                                 funcao="COORDENADOR_EQUIPE_PLANEJAMENTO")
    assert veredito["permitida"] is True
    assert veredito["servidor"]["id"] == "s-m"


def test_o_coordenador_tambem_conta_como_integrante():
    """A portaria publicada não separa os dois — a lista não pode separar."""
    veredito = gbi.avaliar_troca(panorama(), nome="Maria",
                                 funcao="EQUIPE_PLANEJAMENTO")
    assert veredito["permitida"] is True


# ---------------------------------------------------------------------------
# 4) Servidor fora da equipe NÃO entra por comando
# ---------------------------------------------------------------------------
def test_joao_nao_entra_como_integrante_por_pedido_ao_robo():
    """O exemplo literal do §37."""
    veredito = gbi.avaliar_troca(panorama(), nome="João",
                                 funcao="EQUIPE_PLANEJAMENTO")
    assert veredito["permitida"] is False
    assert "não integra a Equipe de Planejamento" in veredito["mensagem"]
    assert "003/2026" in veredito["mensagem"], (
        "a recusa precisa nomear a portaria aplicável, senão o servidor "
        "não sabe onde conferir")


def test_a_recusa_nomeia_o_ato_que_falta_e_nao_so_diz_nao():
    """Cada causa se conserta num lugar diferente."""
    sem_portaria = gbi.avaliar_troca(
        panorama(portaria=None, membros=[]), nome="João",
        funcao="EQUIPE_PLANEJAMENTO")
    assert "não tem Portaria" in sem_portaria["mensagem"]

    inativo = gbi.avaliar_troca(
        panorama(servidores=[ANTONIO, MARIA, JOAO, INATIVO]),
        nome="Carlos Antigo", funcao="EQUIPE_PLANEJAMENTO")
    assert "inativo" in inativo["mensagem"]


def test_funcao_sem_portaria_e_verificada_pelo_ato_dela(caplog):
    """
    §37, parágrafo final: não exigir portaria de Equipe de Planejamento
    para função que tem outra forma válida de designação.

    Um secretário municipal assina como secretário pelo ato dele — se o
    sistema exigisse que ele estivesse na equipe de planejamento, a
    assinatura mais comum do processo ficaria impossível.
    """
    designacao = [{"servidor_id": "s-j", "funcao": "SECRETARIO",
                   "secretaria_id": "sec-1", "ativo": True,
                   "data_inicio": "2026-01-01", "data_fim": None}]
    veredito = gbi.avaliar_troca(
        panorama(funcoes_do_servidor=designacao, portaria=None, membros=[]),
        nome="João", funcao="SECRETARIO")
    assert veredito["permitida"] is True, (
        "a aptidão de secretário foi negada por falta de portaria de "
        "equipe — exatamente o que o §37 proíbe")


# ---------------------------------------------------------------------------
# 5) Servidor de OUTRA prefeitura
# ---------------------------------------------------------------------------
def test_servidor_fora_do_cadastro_da_prefeitura_nao_e_encontrado():
    """
    O panorama é montado com `db.listar_servidores()`, que filtra pelo
    tenant da sessão e passa pela RLS. Quem não está na lista não tem
    caminho para entrar: não há busca alternativa neste módulo.
    """
    with pytest.raises(gbi.PendenciaInstitucional) as erro:
        gbi.localizar_servidor(panorama(), "Fulano de Outra Cidade")
    assert "não encontrei" in str(erro.value).lower()


def test_o_robo_nao_tem_um_segundo_caminho_para_buscar_servidor():
    """
    Guarda estrutural: se alguém acrescentar uma consulta que ignore o
    panorama, o isolamento por tenant deixa de valer para o robô sem que
    nenhuma outra prova caia.
    """
    from pathlib import Path

    fonte = (Path(__file__).resolve().parent.parent / "src" /
             "govbot_institucional.py").read_text(encoding="utf-8")
    corpo = fonte.split("def localizar_servidor", 1)[1].split("\ndef ", 1)[0]
    assert "db." not in corpo, (
        "localizar_servidor passou a consultar o banco por fora do "
        "panorama — o filtro por tenant deixa de ser garantido")


# ---------------------------------------------------------------------------
# 6) Portaria revogada, futura ou fora da vigência
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ajuste", [
    {"status": "REVOGADA"},
    {"data_inicio_vigencia": "2026-06-01"},                    # futura
    {"data_fim_vigencia": "2026-02-01"},                       # expirada
])
def test_portaria_fora_de_vigencia_nao_autoriza(ajuste):
    """
    A resolução é a mesma da tela (`portarias.resolver`): status
    declarado E janela de vigência, na DATA DO PROCESSO.
    """
    fora = {**PORTARIA, **ajuste}
    assert portarias.resolver([fora], secretaria_id="sec-1",
                              data_referencia=HOJE) is None

    veredito = gbi.avaliar_troca(panorama(portaria=None, membros=[]),
                                 nome="Antonio",
                                 funcao="EQUIPE_PLANEJAMENTO")
    assert veredito["permitida"] is False


def test_a_data_e_a_do_processo_e_nao_a_de_hoje():
    """
    §24 vale para o robô também: perguntar em dezembro sobre um processo
    de janeiro tem que devolver a portaria de janeiro.
    """
    antiga = {**PORTARIA, "data_fim_vigencia": "2026-04-30"}
    em_marco = panorama(portaria=portarias.resolver(
        [antiga], secretaria_id="sec-1", data_referencia=HOJE))
    assert em_marco.portaria is not None

    assert portarias.resolver([antiga], secretaria_id="sec-1",
                              data_referencia=_dt.date(2026, 12, 1)) is None


# ---------------------------------------------------------------------------
# 7) Ausência ou conflito gera PENDÊNCIA, não escolha
# ---------------------------------------------------------------------------
def test_conflito_de_portarias_nao_vira_escolha():
    conflito = panorama(
        aviso="Há mais de uma portaria vigente do tipo EQUIPE_PLANEJAMENTO")
    for resposta in (gbi.responder_portaria(conflito),
                     gbi.responder_membros(conflito),
                     gbi.responder_quem_pode_assinar(
                         conflito, "EQUIPE_PLANEJAMENTO")):
        assert "mais de uma portaria" in resposta

    veredito = gbi.avaliar_troca(conflito, nome="Antonio",
                                 funcao="EQUIPE_PLANEJAMENTO")
    assert veredito["permitida"] is False, (
        "com duas portarias vigentes o robô escolheu uma — é o arbítrio "
        "que o §23 proíbe")


def test_nome_ambiguo_vira_pendencia_e_nao_o_primeiro_da_lista():
    """Duas "Maria" e o robô escolhendo produziria assinatura da errada."""
    outra = {"id": "s-m2", "nome": "Maria Souza Lima", "ativo": True}
    with pytest.raises(gbi.PendenciaInstitucional) as erro:
        gbi.localizar_servidor(panorama(servidores=[MARIA, outra]), "Maria")
    assert "mais de um servidor" in str(erro.value)


def test_alertas_nomeiam_o_que_conserta_cada_caso():
    sem = gbi.alertas(panorama(portaria=None, membros=[]))
    assert any("marcador de pendência" in a for a in sem)

    vazia = gbi.alertas(panorama(membros=[]))
    assert any("não designa nenhum membro" in a for a in vazia)


# ---------------------------------------------------------------------------
# 8) O PORTÃO DO BACKEND — chamada DIRETA, sem conversa
# ---------------------------------------------------------------------------
def test_o_portao_recusa_escolha_nova_inelegivel():
    with pytest.raises(assinaturas.ErroAssinatura):
        gbi.conferir_escolhas(
            [{"servidor_id": "s-j", "funcao": "EQUIPE_PLANEJAMENTO"}],
            [], panorama())


def test_o_portao_aceita_escolha_nova_elegivel():
    gbi.conferir_escolhas(
        [{"servidor_id": "s-a", "funcao": "EQUIPE_PLANEJAMENTO"}],
        [], panorama())


def test_o_portao_deixa_remover_escolha_que_ficou_invalida():
    """
    Se a portaria for revogada depois da escolha, o servidor ainda
    precisa conseguir REMOVER a linha. Conferir tudo a cada gravação
    tornaria impossível desfazer o problema — uma prisão, não um portão.
    """
    antes = [{"servidor_id": "s-a", "funcao": "EQUIPE_PLANEJAMENTO"},
             {"servidor_id": "s-m", "funcao": "COORDENADOR_EQUIPE_PLANEJAMENTO"}]
    gbi.conferir_escolhas(antes[:1], antes,
                          panorama(portaria=None, membros=[]))


def test_o_portao_deixa_reordenar():
    antes = [{"servidor_id": "s-a", "funcao": "EQUIPE_PLANEJAMENTO"},
             {"servidor_id": "s-m", "funcao": "COORDENADOR_EQUIPE_PLANEJAMENTO"}]
    gbi.conferir_escolhas(list(reversed(antes)), antes, panorama())


def test_conflito_bloqueia_qualquer_escolha_nova():
    with pytest.raises(assinaturas.ErroAssinatura) as erro:
        gbi.conferir_escolhas(
            [{"servidor_id": "s-a", "funcao": "EQUIPE_PLANEJAMENTO"}],
            [], panorama(aviso="Há mais de uma portaria vigente"))
    assert "mais de uma portaria" in str(erro.value)


def test_a_gravacao_passa_pelo_portao_sem_nenhuma_conversa(monkeypatch):
    """
    O CRITÉRIO 8, literal: chamada DIRETA a `guardar_escolhas`, sem
    GovBot nenhum no caminho. Se a verificação vivesse no prompt, esta
    prova passaria e o sistema estaria aberto.
    """
    from src import instituicional_bridge as ponte

    sessao: dict = {"dados": {}}
    monkeypatch.setattr(ponte.st, "session_state", sessao)
    monkeypatch.setattr(ponte, "ativo", lambda: True)
    monkeypatch.setattr(gbi, "montar_panorama", lambda *a, **k: panorama())

    with pytest.raises(assinaturas.ErroAssinatura):
        ponte.guardar_escolhas(
            "edital", [{"servidor_id": "s-j",
                        "funcao": "EQUIPE_PLANEJAMENTO"}])

    assert not sessao["dados"].get("signatarios_escolhidos"), (
        "a escolha inelegível foi GRAVADA apesar da recusa")


def test_cadastro_ilegivel_recusa_em_vez_de_deixar_passar(monkeypatch):
    """
    Não conferir é diferente de aprovar. Se o panorama não pode ser
    montado, a escolha NOVA não entra — o caminho de exceção não pode
    virar a porta larga.
    """
    from src import instituicional_bridge as ponte

    sessao: dict = {"dados": {}}
    monkeypatch.setattr(ponte.st, "session_state", sessao)
    monkeypatch.setattr(ponte, "ativo", lambda: True)

    def cair(*_a, **_k):
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(gbi, "montar_panorama", cair)

    with pytest.raises(assinaturas.ErroAssinatura):
        ponte.guardar_escolhas(
            "edital", [{"servidor_id": "s-a",
                        "funcao": "EQUIPE_PLANEJAMENTO"}])


# ---------------------------------------------------------------------------
# 9) O robô não altera cadastro para validar o pedido
# ---------------------------------------------------------------------------
def test_o_modulo_nao_escreve_no_cadastro_institucional():
    """
    Guarda estrutural, e é a mais importante deste arquivo.

    §37: o GovBot não pode "criar uma portaria fictícia, presumir uma
    designação ou modificar o cadastro administrativo para atender ao
    pedido". A forma de garantir isso não é revisar intenção — é não
    existir caminho: nenhuma chamada de escrita neste módulo.
    """
    from pathlib import Path

    fonte = (Path(__file__).resolve().parent.parent / "src" /
             "govbot_institucional.py").read_text(encoding="utf-8")
    proibidas = ("salvar_portaria", "salvar_membro_de_portaria",
                 "salvar_servidor", "salvar_modulo", "gravar_signatarios",
                 "salvar_dados_do_tenant", ".insert(", ".upsert(",
                 ".update(", ".delete(")
    for nome in proibidas:
        assert nome not in fonte, (
            f"{nome!r} aparece em govbot_institucional.py — o robô ganhou "
            "um caminho para alterar o cadastro e tornar o pedido válido")


def test_o_modulo_so_le_o_cadastro():
    """
    As únicas funções de banco usadas são de leitura.

    O padrão exige o PARÊNTESE — `db.nome(` —, e a primeira versão não
    exigia: ela casava `src/db.py` escrito na prosa da docstring e
    reprovava o módulo por ele DOCUMENTAR o que reusa. É a mesma
    família do inventário que leu comentário como comando, e a correção
    é a mesma: medir chamada, não menção.
    """
    from pathlib import Path
    import re

    fonte = (Path(__file__).resolve().parent.parent / "src" /
             "govbot_institucional.py").read_text(encoding="utf-8")
    chamadas = set(re.findall(r"\bdb\.(\w+)\s*\(", fonte))
    assert chamadas, "nenhuma chamada ao banco encontrada — o padrão quebrou"
    for chamada in sorted(chamadas):
        assert chamada.startswith("listar_"), (
            f"db.{chamada}() não é leitura — este módulo só consulta")
