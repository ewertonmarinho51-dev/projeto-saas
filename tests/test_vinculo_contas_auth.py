"""
Provas do `scripts/vincular_contas_auth.py`.

O que este script faz de mais importante é RECUSAR. Vincular a linha
errada à conta errada entrega o processo de um servidor a outro, e o
erro não aparece: a tela continua mostrando o nome certo enquanto o RLS
julga pelo escopo do JWT. Por isso quase toda prova aqui é de recusa, e
cada uma nomeia o estrago que evita.

Nada de rede: o cliente é um dublê que responde ao mesmo encadeamento
do supabase-py.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import vincular_contas_auth as vinc  # noqa: E402

TENANT = "11111111-1111-1111-1111-111111111111"
OUTRO_TENANT = "22222222-2222-2222-2222-222222222222"
SECRETARIA = "33333333-3333-3333-3333-333333333333"
USUARIO = "44444444-4444-4444-4444-444444444444"
CONTA = "55555555-5555-5555-5555-555555555555"
OUTRA_CONTA = "66666666-6666-6666-6666-666666666666"


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------
class Resposta:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class Consulta:
    """
    Reproduz o encadeamento do supabase-py e REGISTRA o que foi pedido.

    Registrar importa: várias provas aqui não olham o retorno, olham se
    a chamada levou o filtro `is_("auth_user_id", "null")` — que é o que
    torna a escrita idempotente.
    """

    def __init__(self, banco, tabela, diario):
        self.banco = banco
        self.tabela = tabela
        self.diario = diario
        self.filtros: list[tuple] = []
        self.operacao = "select"
        self.valores: dict | None = None
        self.contar = False

    def select(self, *_args, count=None, **_kw):
        self.operacao = "select"
        self.contar = count == "exact"
        return self

    def update(self, valores):
        self.operacao = "update"
        self.valores = valores
        return self

    def eq(self, campo, valor):
        self.filtros.append(("eq", campo, valor))
        return self

    def in_(self, campo, valores):
        self.filtros.append(("in", campo, list(valores)))
        return self

    def is_(self, campo, valor):
        self.filtros.append(("is", campo, valor))
        return self

    def _casa(self, linha) -> bool:
        for tipo, campo, valor in self.filtros:
            atual = linha.get(campo)
            if tipo == "eq" and str(atual) != str(valor):
                return False
            if tipo == "in" and str(atual) not in [str(v) for v in valor]:
                return False
            if tipo == "is" and valor == "null" and atual not in (None, ""):
                return False
        return True

    def execute(self):
        linhas = [l for l in self.banco[self.tabela] if self._casa(l)]
        self.diario.append({"tabela": self.tabela, "operacao": self.operacao,
                            "filtros": list(self.filtros),
                            "valores": self.valores})
        if self.operacao == "update":
            for linha in linhas:
                linha.update(self.valores or {})
        if self.contar:
            return Resposta([{"id": l["id"]} for l in linhas], count=len(linhas))
        return Resposta([dict(l) for l in linhas])


class Admin:
    def __init__(self, contas):
        self._contas = contas

    def list_users(self, page=1, per_page=200):
        inicio = (page - 1) * per_page
        return self._contas[inicio:inicio + per_page]


class Auth:
    def __init__(self, contas):
        self.admin = Admin(contas)


class ContaFalsa:
    def __init__(self, id, email, app_metadata):
        self.id = id
        self.email = email
        self.app_metadata = app_metadata


class ClienteFalso:
    def __init__(self, banco, contas):
        self.banco = banco
        self.auth = Auth(contas)
        self.diario: list[dict] = []

    def table(self, nome):
        return Consulta(self.banco, nome, self.diario)


def _banco(**ajustes):
    usuario = {"id": USUARIO, "nome": "Servidor", "papel": "usuario",
               "tenant_id": TENANT, "secretaria_id": SECRETARIA,
               "papel_governanca": None, "auth_user_id": None, "ativo": True}
    usuario.update(ajustes.pop("usuario", {}))
    processos = ajustes.pop("processos", [
        {"id": "p1", "usuario_id": USUARIO, "auth_user_id": None},
        {"id": "p2", "usuario_id": USUARIO, "auth_user_id": None},
    ])
    return {"usuarios": [usuario], "processos": processos}


def _conta(**ajustes):
    meta = {"papel": "usuario", "tenant_id": TENANT,
            "secretaria_id": SECRETARIA}
    meta.update(ajustes.pop("app_metadata", {}))
    return ContaFalsa(ajustes.pop("id", CONTA),
                      ajustes.pop("email", "servidor@example.org"), meta)


def _cliente(banco=None, contas=None):
    return ClienteFalso(banco or _banco(), contas or [_conta()])


def _vinculo(**ajustes):
    base = {"usuario_id": USUARIO, "auth_email": "servidor@example.org",
            "auth_uid": ""}
    base.update(ajustes)
    return base


# ---------------------------------------------------------------------------
# Leitura do mapa — recusas que não precisam de banco
# ---------------------------------------------------------------------------
def _escrever(tmp_path, conteudo):
    caminho = tmp_path / "mapa.json"
    caminho.write_text(json.dumps(conteudo), encoding="utf-8")
    return caminho


def test_mapa_ausente_e_recusado(tmp_path):
    with pytest.raises(vinc.ErroVinculo, match="não encontrado"):
        vinc.ler_mapa(tmp_path / "nao-existe.json")


def test_mapa_que_nao_e_json_e_recusado(tmp_path):
    caminho = tmp_path / "mapa.json"
    caminho.write_text("{isto não é json", encoding="utf-8")
    with pytest.raises(vinc.ErroVinculo, match="não é JSON"):
        vinc.ler_mapa(caminho)


def test_mapa_vazio_e_recusado(tmp_path):
    """Mapa vazio rodaria sem erro e sem efeito — silêncio que parece sucesso."""
    with pytest.raises(vinc.ErroVinculo, match="lista não vazia"):
        vinc.ler_mapa(_escrever(tmp_path, []))


def test_vinculo_sem_usuario_e_recusado(tmp_path):
    with pytest.raises(vinc.ErroVinculo, match="falta `usuario_id`"):
        vinc.ler_mapa(_escrever(tmp_path, [{"auth_email": "um@example.org"}]))


@pytest.mark.parametrize("item, motivo", [
    ({"usuario_id": USUARIO}, "nenhum dos dois"),
    ({"usuario_id": USUARIO, "auth_email": "um@example.org",
      "auth_uid": CONTA}, "os dois ao mesmo tempo"),
])
def test_conta_precisa_ser_apontada_por_exatamente_um_campo(tmp_path, item,
                                                           motivo):
    """
    Com os dois, qual vale seria decisão escondida no código; com
    nenhum, não há conta. Nos dois casos o script recusa — {motivo}.
    """
    with pytest.raises(vinc.ErroVinculo, match="OU"):
        vinc.ler_mapa(_escrever(tmp_path, [item]))


def test_usuario_repetido_no_mapa_e_recusado(tmp_path):
    """
    Duas linhas para o mesmo usuário fariam o resultado depender da
    ordem de aplicação — e a ordem não está declarada em lugar nenhum.
    """
    mapa = [{"usuario_id": USUARIO, "auth_email": "um@example.org"},
            {"usuario_id": USUARIO, "auth_email": "dois@example.org"}]
    with pytest.raises(vinc.ErroVinculo, match="repetido"):
        vinc.ler_mapa(_escrever(tmp_path, mapa))


def test_conta_repetida_no_mapa_e_recusada(tmp_path):
    """Uma conta para dois servidores é o próprio estrago que o script evita."""
    mapa = [{"usuario_id": USUARIO, "auth_email": "um@example.org"},
            {"usuario_id": CONTA, "auth_email": "UM@example.org"}]
    with pytest.raises(vinc.ErroVinculo, match="duas vezes"):
        vinc.ler_mapa(_escrever(tmp_path, mapa))


def test_email_e_normalizado(tmp_path):
    """Caixa e espaço não podem virar duas contas diferentes."""
    lido = vinc.ler_mapa(_escrever(
        tmp_path, [{"usuario_id": USUARIO, "auth_email": "  UM@EXAMPLE.ORG "}]))
    assert lido[0]["auth_email"] == "um@example.org"


# ---------------------------------------------------------------------------
# Conferência contra o banco
# ---------------------------------------------------------------------------
def test_conferencia_limpa_monta_o_plano():
    plano = vinc.conferir(_cliente(), [_vinculo()])
    assert plano == [{"usuario_id": USUARIO, "nome": "Servidor",
                      "email": "servidor@example.org",
                      "auth_uid": CONTA, "ja_vinculado": False,
                      "ativo": True}]


def test_conta_inexistente_e_recusada():
    with pytest.raises(vinc.ErroVinculo, match="nenhuma conta no Auth"):
        vinc.conferir(_cliente(), [_vinculo(auth_email="fantasma@example.org")])


def test_email_duplicado_no_auth_e_recusado():
    """
    Duas contas com o mesmo e-mail: escolher uma seria adivinhar qual
    servidor entra. O script para.
    """
    contas = [_conta(), _conta(id=OUTRA_CONTA)]
    with pytest.raises(vinc.ErroVinculo, match="2 contas no Auth"):
        vinc.conferir(_cliente(contas=contas), [_vinculo()])


def test_usuario_inexistente_e_recusado():
    with pytest.raises(vinc.ErroVinculo, match="não tem a linha"):
        vinc.conferir(_cliente(), [_vinculo(usuario_id=OUTRA_CONTA)])


def test_usuario_ja_vinculado_a_outra_conta_e_recusado():
    """
    Sobrescrever aqui trocaria o dono de todos os processos da pessoa
    sem deixar rastro. Desfazer vínculo é decisão administrativa.
    """
    banco = _banco(usuario={"auth_user_id": OUTRA_CONTA})
    with pytest.raises(vinc.ErroVinculo, match="já está vinculado a OUTRA"):
        vinc.conferir(_cliente(banco=banco), [_vinculo()])


def test_vinculo_ja_feito_para_a_mesma_conta_e_aceito():
    """Reexecutar não pode ser erro: a migração precisa ser retomável."""
    banco = _banco(usuario={"auth_user_id": CONTA})
    plano = vinc.conferir(_cliente(banco=banco), [_vinculo()])
    assert plano[0]["ja_vinculado"] is True


@pytest.mark.parametrize("meta, campo", [
    ({"tenant_id": OUTRO_TENANT}, "tenant_id"),
    ({"secretaria_id": OUTRA_CONTA}, "secretaria_id"),
    ({"papel": "admin"}, "papel"),
    ({"papel_governanca": "controle_interno"}, "papel_governanca"),
])
def test_escopo_divergente_e_recusado(meta, campo):
    """
    Quem julga o RLS é o `app_metadata`, não a linha. Divergência
    vincula um servidor a um escopo que a tela não mostra — inclusive
    ao município errado.
    """
    contas = [_conta(app_metadata=meta)]
    with pytest.raises(vinc.ErroVinculo, match=campo):
        vinc.conferir(_cliente(contas=contas), [_vinculo()])


def test_papel_ausente_no_app_metadata_e_recusado():
    conta = _conta()
    conta.app_metadata = {"tenant_id": TENANT, "secretaria_id": SECRETARIA}
    with pytest.raises(vinc.ErroVinculo, match="ausente no app_metadata"):
        vinc.conferir(_cliente(contas=[conta]), [_vinculo()])


def test_secretaria_ausente_dos_dois_lados_nao_e_divergencia():
    """
    `usuarios.secretaria_id` é NULLABLE desde a 0007. Conta sem a chave
    e linha sem secretaria concordam — tratar como divergência
    bloquearia o servidor sem vínculo de pasta, que existe de verdade.
    """
    banco = _banco(usuario={"secretaria_id": None})
    conta = _conta()
    conta.app_metadata = {"papel": "usuario", "tenant_id": TENANT}
    plano = vinc.conferir(ClienteFalso(banco, [conta]), [_vinculo()])
    assert plano[0]["auth_uid"] == CONTA


# ---------------------------------------------------------------------------
# Contagem e escrita
# ---------------------------------------------------------------------------
def test_conta_os_processos_que_ganhariam_dono():
    cliente = _cliente()
    plano = vinc.conferir(cliente, [_vinculo()])
    assert vinc.processos_a_preencher(cliente, plano) == {USUARIO: 2}


def test_processo_que_ja_tem_dono_nao_entra_na_conta():
    banco = _banco(processos=[
        {"id": "p1", "usuario_id": USUARIO, "auth_user_id": None},
        {"id": "p2", "usuario_id": USUARIO, "auth_user_id": OUTRA_CONTA},
    ])
    cliente = ClienteFalso(banco, [_conta()])
    plano = vinc.conferir(cliente, [_vinculo()])
    assert vinc.processos_a_preencher(cliente, plano) == {USUARIO: 1}


def test_aplicar_vincula_usuario_e_processos():
    banco = _banco()
    cliente = ClienteFalso(banco, [_conta()])
    plano = vinc.conferir(cliente, [_vinculo()])
    assert vinc.aplicar(cliente, plano) == {"usuarios": 1, "processos": 2}
    assert banco["usuarios"][0]["auth_user_id"] == CONTA
    assert {p["auth_user_id"] for p in banco["processos"]} == {CONTA}


def test_aplicar_nao_toca_processo_de_outro_dono():
    """
    O filtro `is null` é o que impede a segunda execução de reescrever
    o que já tem dono — inclusive dono posto à mão.
    """
    banco = _banco(processos=[
        {"id": "p1", "usuario_id": USUARIO, "auth_user_id": None},
        {"id": "p2", "usuario_id": USUARIO, "auth_user_id": OUTRA_CONTA},
    ])
    cliente = ClienteFalso(banco, [_conta()])
    vinc.aplicar(cliente, vinc.conferir(cliente, [_vinculo()]))
    por_id = {p["id"]: p["auth_user_id"] for p in banco["processos"]}
    assert por_id == {"p1": CONTA, "p2": OUTRA_CONTA}


def test_aplicar_duas_vezes_nao_escreve_de_novo():
    banco = _banco()
    cliente = ClienteFalso(banco, [_conta()])
    vinc.aplicar(cliente, vinc.conferir(cliente, [_vinculo()]))
    segunda = vinc.aplicar(cliente, vinc.conferir(cliente, [_vinculo()]))
    assert segunda == {"usuarios": 0, "processos": 0}


def test_a_escrita_do_usuario_e_condicionada():
    """
    Sem `is_("auth_user_id", "null")` no update, uma corrida entre duas
    execuções sobrescreveria o vínculo alheio. A prova olha a chamada,
    não só o resultado — o resultado sozinho não distingue as duas.
    """
    cliente = _cliente()
    vinc.aplicar(cliente, vinc.conferir(cliente, [_vinculo()]))
    updates = [c for c in cliente.diario
               if c["operacao"] == "update" and c["tabela"] == "usuarios"]
    assert updates, "nenhum update de usuarios foi emitido"
    assert ("is", "auth_user_id", "null") in updates[0]["filtros"]


def test_orfaos_conta_os_processos_sem_dono():
    banco = _banco(processos=[
        {"id": "p1", "usuario_id": USUARIO, "auth_user_id": None},
        {"id": "p2", "usuario_id": "outro", "auth_user_id": None},
        {"id": "p3", "usuario_id": USUARIO, "auth_user_id": CONTA},
    ])
    assert vinc.orfaos(ClienteFalso(banco, [_conta()])) == 2
