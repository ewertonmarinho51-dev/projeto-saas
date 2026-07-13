"""
Fase 2 multi-tenant: contexto institucional derivado da sessão,
resolvedor hierárquico de identidade visual (secretaria > município),
shadow mode e feature flag (flag OFF = comportamento idêntico ao atual).
"""

import types
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import auth, contexto, db, rag

APP = str(Path(__file__).resolve().parent.parent / "app.py")


# PNG 1x1 válido (o export carimba a imagem de verdade no DOCX/PDF)
_PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _secretarias_exemplo() -> list[dict]:
    return [
        {"id": "sec-educacao", "nome": "Secretaria de Educação",
         "padrao": False, "ativo": True, "cabecalho_img": _PNG_1PX},
        {"id": "sec-saude", "nome": "Secretaria de Saúde",
         "padrao": False, "ativo": True},  # sem identidade própria
        {"id": "muni", "nome": "Prefeitura Municipal", "padrao": True,
         "ativo": True, "cabecalho": "PREFEITURA MUNICIPAL DE PARAGOMINAS"},
    ]


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------
def test_flag_desligada_por_padrao(monkeypatch):
    monkeypatch.setattr(db, "obter_config", lambda chave: "")
    assert db.flag_ativa("secretarias") is False


def test_flag_ligada_por_config(monkeypatch):
    monkeypatch.setattr(
        db, "obter_config",
        lambda chave: "1" if chave == "flag_secretarias" else "",
    )
    assert db.flag_ativa("secretarias") is True


# ---------------------------------------------------------------------------
# Contexto derivado da SESSÃO (nunca do formulário)
# ---------------------------------------------------------------------------
def test_contexto_vem_do_vinculo_do_usuario(monkeypatch):
    monkeypatch.setattr(
        contexto, "_usuario_sessao",
        lambda: {"id": "u1", "secretaria_id": "sec-educacao"},
    )
    ctx = contexto.contexto_institucional()
    assert ctx["secretaria_id"] == "sec-educacao"
    assert ctx["origem"] == "vinculo"
    assert ctx["tenant_id"] == db.TENANT_PADRAO


def test_contexto_sem_vinculo_usa_tenant_padrao(monkeypatch):
    monkeypatch.setattr(contexto, "_usuario_sessao", lambda: {})
    ctx = contexto.contexto_institucional()
    assert ctx["secretaria_id"] is None
    assert ctx["origem"] == "tenant_padrao"


def test_entrar_deriva_tenant_do_vinculo(monkeypatch):
    """auth.entrar registra o contexto a partir do usuário autenticado."""
    falso_st = types.SimpleNamespace(session_state=types.SimpleNamespace())
    monkeypatch.setattr(auth, "st", falso_st)
    auth.entrar({"id": "u1", "tenant_id": "t-9", "secretaria_id": "s-1"})
    assert falso_st.session_state.usuario["secretaria_id"] == "s-1"
    assert falso_st.session_state.tenant_id == "t-9"


def test_entrar_sem_tenant_nao_polui_sessao(monkeypatch):
    """Usuário anterior às migrações (sem tenant_id): sessão fica no padrão."""
    falso_st = types.SimpleNamespace(session_state=types.SimpleNamespace())
    monkeypatch.setattr(auth, "st", falso_st)
    auth.entrar({"id": "u1", "nome": "Fulano"})
    assert falso_st.session_state.usuario["id"] == "u1"
    assert not hasattr(falso_st.session_state, "tenant_id")


# ---------------------------------------------------------------------------
# Resolvedor hierárquico de identidade (secretaria > município)
# ---------------------------------------------------------------------------
def test_resolver_prefere_identidade_da_secretaria():
    identidade, origem = contexto.resolver_identidade(
        _secretarias_exemplo(), "sec-educacao"
    )
    assert origem == "secretaria"
    assert identidade["id"] == "sec-educacao"


def test_resolver_herda_do_municipio_quando_secretaria_nao_tem_propria():
    identidade, origem = contexto.resolver_identidade(
        _secretarias_exemplo(), "sec-saude"
    )
    assert origem == "municipio"
    assert identidade["id"] == "muni"


def test_resolver_sem_vinculo_usa_padrao_do_municipio():
    identidade, origem = contexto.resolver_identidade(_secretarias_exemplo(), None)
    assert origem == "municipio"
    assert identidade["id"] == "muni"


def test_resolver_sem_cadastro_devolve_nenhuma():
    identidade, origem = contexto.resolver_identidade([], None)
    assert identidade is None
    assert origem == "nenhuma"


def test_resolver_ignora_padrao_sem_identidade_visual():
    """Registro padrão sem nenhum campo visual não vira timbrado."""
    secretarias = [{"id": "muni", "nome": "Prefeitura", "padrao": True}]
    identidade, origem = contexto.resolver_identidade(secretarias, None)
    assert identidade is None
    assert origem == "nenhuma"


# ---------------------------------------------------------------------------
# Shadow mode (flag OFF) vs resolução automática (flag ON)
# ---------------------------------------------------------------------------
def test_exportacao_flag_desligada_mantem_comportamento_antigo(monkeypatch):
    """Flag OFF: devolve None (fluxo manual antigo) mesmo com tudo cadastrado."""
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "listar_secretarias",
                        lambda **kw: _secretarias_exemplo())
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    monkeypatch.setattr(contexto, "_usuario_sessao",
                        lambda: {"secretaria_id": "sec-educacao"})
    assert contexto.identidade_para_exportacao() is None


def test_exportacao_flag_ligada_resolve_pelo_vinculo(monkeypatch):
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "listar_secretarias",
                        lambda **kw: _secretarias_exemplo())
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    monkeypatch.setattr(contexto, "_usuario_sessao",
                        lambda: {"secretaria_id": "sec-educacao"})
    identidade, origem = contexto.identidade_para_exportacao()
    assert identidade["id"] == "sec-educacao"
    assert origem == "secretaria"


def test_exportacao_tolera_migracao_0007_ausente(monkeypatch):
    """Tabela secretarias inexistente → fluxo antigo, sem quebrar a tela."""
    def _explode(**kw):
        raise db.ErroBanco("relation public.secretarias does not exist")

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "listar_secretarias", _explode)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    monkeypatch.setattr(contexto, "_usuario_sessao", lambda: {})
    assert contexto.identidade_para_exportacao() is None


# ---------------------------------------------------------------------------
# Processo carrega o vínculo apenas com a flag ligada
# ---------------------------------------------------------------------------
def test_processo_recebe_secretaria_apenas_com_flag(monkeypatch):
    monkeypatch.setattr(contexto, "_usuario_sessao",
                        lambda: {"secretaria_id": "sec-educacao"})
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    assert contexto.secretaria_para_processo() is None
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    assert contexto.secretaria_para_processo() == "sec-educacao"


class _TabelaFake:
    """Query builder mínimo do supabase-py para capturar operações."""

    def __init__(self, registrador, nome):
        self._registrador = registrador
        self._nome = nome
        self._ultima_op = ""

    def insert(self, registro):
        self._ultima_op = "insert"
        self._registrador.setdefault(f"{self._nome}.insert", []).append(registro)
        return self

    def update(self, registro):
        self._ultima_op = "update"
        self._registrador.setdefault(f"{self._nome}.update", []).append(registro)
        return self

    def select(self, *campos):
        self._ultima_op = "select"
        return self

    def eq(self, campo, valor):
        self._registrador.setdefault(f"{self._nome}.eq", []).append((campo, valor))
        return self

    def neq(self, *a):
        return self

    def order(self, *a, **kw):
        return self

    def limit(self, *a):
        return self

    def execute(self):
        # selects devolvem vazio (nada cadastrado); escritas devolvem o id
        if self._ultima_op == "select":
            return types.SimpleNamespace(data=[])
        return types.SimpleNamespace(data=[{"id": f"{self._nome}-novo"}])


def _cliente_fake(registrador, tabelas_que_explodem=()):
    class _Cliente:
        def table(self, nome):
            if nome in tabelas_que_explodem:
                raise RuntimeError(f"relation {nome} does not exist")
            return _TabelaFake(registrador, nome)

    return _Cliente()


def test_salvar_processo_grava_secretaria(monkeypatch):
    capturas = {}
    monkeypatch.setattr(db, "_cliente", lambda: _cliente_fake(capturas))
    pid = db.salvar_processo(
        None, {"orgao": "X", "objeto": "Y"}, {}, set(), 0,
        usuario_id="u1", secretaria_id="sec-educacao",
    )
    assert pid == "processos-novo"
    registro = capturas["processos.insert"][0]
    assert registro["secretaria_id"] == "sec-educacao"
    assert registro["usuario_id"] == "u1"


def test_salvar_processo_sem_vinculo_nao_menciona_coluna_nova(monkeypatch):
    """Compat: flag OFF/None → registro idêntico ao formato antigo."""
    capturas = {}
    monkeypatch.setattr(db, "_cliente", lambda: _cliente_fake(capturas))
    db.salvar_processo(None, {"orgao": "X", "objeto": "Y"}, {}, set(), 0,
                       usuario_id="u1", secretaria_id=None)
    assert "secretaria_id" not in capturas["processos.insert"][0]


# ---------------------------------------------------------------------------
# Isolamento por tenant nas consultas de secretaria
# ---------------------------------------------------------------------------
def test_listar_secretarias_filtra_pelo_tenant_da_sessao(monkeypatch):
    capturas = {}
    monkeypatch.setattr(db, "_cliente", lambda: _cliente_fake(capturas))
    db.listar_secretarias()
    filtros = capturas["secretarias.eq"]
    assert ("tenant_id", db.TENANT_PADRAO) in filtros
    assert ("ativo", True) in filtros


def test_salvar_secretaria_atribui_tenant_da_sessao(monkeypatch):
    capturas = {}
    monkeypatch.setattr(db, "_cliente", lambda: _cliente_fake(capturas))
    db.salvar_secretaria({"nome": "Secretaria de Obras"})
    registro = capturas["secretarias.insert"][0]
    assert registro["tenant_id"] == db.TENANT_PADRAO


# ---------------------------------------------------------------------------
# Espelhamento config_orgaos -> secretarias (dupla escrita best-effort)
# ---------------------------------------------------------------------------
def test_salvar_orgao_espelha_em_secretarias(monkeypatch):
    capturas = {}
    monkeypatch.setattr(db, "_cliente", lambda: _cliente_fake(capturas))
    db.salvar_orgao({"orgao": "Prefeitura Municipal",
                     "cabecalho_img": "iVBOR", "padrao": False})
    # gravou no legado e espelhou na tabela nova com rastreio de origem
    assert capturas["config_orgaos.insert"]
    espelho = capturas["secretarias.insert"][0]
    assert espelho["nome"] == "Prefeitura Municipal"
    assert espelho["cabecalho_img"] == "iVBOR"
    assert espelho["origem_orgao_id"] == "config_orgaos-novo"


def test_salvar_orgao_sobrevive_sem_tabela_secretarias(monkeypatch):
    """Migração 0007 não aplicada: o fluxo antigo não pode quebrar."""
    capturas = {}
    monkeypatch.setattr(
        db, "_cliente",
        lambda: _cliente_fake(capturas, tabelas_que_explodem=("secretarias",)),
    )
    db.salvar_orgao({"orgao": "Prefeitura", "cabecalho": "PMX"})  # não levanta
    assert capturas["config_orgaos.insert"]


# ---------------------------------------------------------------------------
# RAG restrito ao tenant (com fallback para a assinatura antiga)
# ---------------------------------------------------------------------------
class _RPCFake:
    def __init__(self, chamadas, funcao, params, migracao_aplicada):
        self._chamadas = chamadas
        self._funcao = funcao
        self._params = params
        self._migracao = migracao_aplicada

    def execute(self):
        if "tenant" in self._params and not self._migracao:
            raise RuntimeError(
                "Could not find the function "
                f"public.{self._funcao}(consulta, qtd, tenant) in the schema cache"
            )
        return types.SimpleNamespace(data=[{"conteudo": "trecho", "titulo": "Lei"}])


def _cliente_rpc(chamadas, migracao_aplicada):
    class _Cliente:
        def rpc(self, funcao, params):
            chamadas.append((funcao, dict(params)))
            return _RPCFake(chamadas, funcao, params, migracao_aplicada)

    return _Cliente()


def test_busca_rag_envia_tenant_do_contexto(monkeypatch):
    chamadas = []
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente",
                        lambda: _cliente_rpc(chamadas, migracao_aplicada=True))
    monkeypatch.setattr(rag, "_gerar_embeddings", lambda *a, **kw: [])
    resultado = rag.buscar_referencias("materiais de expediente")
    assert resultado and resultado[0]["conteudo"] == "trecho"
    funcao, params = chamadas[0]
    assert funcao == "buscar_chunks_textual"
    assert params["tenant"] == db.TENANT_PADRAO


def test_busca_rag_cai_para_assinatura_antiga_sem_migracao(monkeypatch):
    """Antes da 0007: erro citando `tenant` → repete sem o parâmetro."""
    chamadas = []
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente",
                        lambda: _cliente_rpc(chamadas, migracao_aplicada=False))
    monkeypatch.setattr(rag, "_gerar_embeddings", lambda *a, **kw: [])
    resultado = rag.buscar_referencias("materiais de expediente")
    assert resultado and len(chamadas) == 2
    assert "tenant" in chamadas[0][1]
    assert "tenant" not in chamadas[1][1]


# ---------------------------------------------------------------------------
# Fluxo real (AppTest): app dirigido de ponta a ponta com a flag ligada
# ---------------------------------------------------------------------------
def _app_logado_com_flag(monkeypatch, papel: str = "usuario") -> AppTest:
    """
    Sobe o app real com banco simulado, flag da Fase 2 LIGADA e usuário
    vinculado à Secretaria de Educação (que tem identidade própria).
    """
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == "secretarias")
    monkeypatch.setattr(db, "listar_secretarias",
                        lambda **kw: _secretarias_exemplo())
    monkeypatch.setattr(db, "listar_processos", lambda **kw: [])
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["usuario"] = {
        "id": "u1", "nome": "Servidor Teste", "login": "servidor",
        "papel": papel, "ativo": True, "secretaria_id": "sec-educacao",
        "tenant_id": db.TENANT_PADRAO,
    }
    return at

_DOC_LIMPO = (
    "## 1. IDENTIFICAÇÃO\n\n1.1. Documento aprovado para teste.\n\n"
    "## 2. CONTEÚDO\n\n2.1. Texto sem pendências.\n"
)


def test_tela_final_aplica_identidade_automaticamente(monkeypatch):
    """Flag ON: sem seleção manual de timbrado; identidade vem do vínculo."""
    at = _app_logado_com_flag(monkeypatch)
    at.session_state["dados"] = {"orgao": "Prefeitura", "objeto": "Compra"}
    at.session_state["documentos"] = {
        k: _DOC_LIMPO for k in ("dfd", "etp", "tr", "edital")
    }
    at.session_state["aprovados"] = {"dfd", "etp", "tr", "edital"}
    at.session_state["etapa"] = 5
    at.run()
    assert not at.exception
    rotulos_select = [s.label or "" for s in at.selectbox]
    assert not any("Identidade visual" in r for r in rotulos_select), (
        "com a flag ligada o servidor não escolhe timbrado"
    )
    legendas = " ".join(c.value for c in at.caption)
    assert "aplicada automaticamente" in legendas
    assert "Secretaria de Educação" in legendas


def test_admin_aba_secretarias_renderiza(monkeypatch):
    """Aba Secretarias: flag, cadastro e vínculos aparecem para o admin."""
    at = _app_logado_com_flag(monkeypatch, papel="admin")
    monkeypatch.setattr(
        auth, "listar_usuarios",
        lambda: [{"id": "u1", "nome": "Servidor Teste", "login": "servidor",
                  "papel": "usuario", "ativo": True,
                  "secretaria_id": "sec-educacao"}],
    )
    at.session_state["pagina"] = "Administração"
    at.run()
    assert not at.exception
    rotulos_toggle = [t.label or "" for t in at.toggle]
    assert any("Resolução automática" in r for r in rotulos_toggle)
    vinculos = [s for s in at.selectbox if (s.key or "").startswith("vinculo_")]
    assert vinculos and vinculos[0].value == "sec-educacao"
