"""
Preparação determinística do projeto de ENSAIO.

Cria o cenário mínimo de isolamento — cinco identidades, dois tenants,
duas secretarias, um processo do titular — usando as COLUNAS REAIS de
cada tabela.

Por que existe um módulo só para isto: a versão anterior montava as
linhas com um campo `observacao` que não existe em nenhuma tabela
filha. O PostgREST respondia PGRST204 (schema), o classificador — com
razão — chamava isso de INCONCLUSIVO, e o teste falhava por motivo
errado. Um teste de autorização que quebra no schema não mede
autorização nenhuma.

Tudo aqui roda com a credencial de SERVIDOR e só no ensaio: a guarda
de `exigir_ensaio()` é pré-condição de qualquer chamada.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_seguranca import exigir_ensaio  # noqa: E402

# Marcador desta execução: tudo que for criado leva o prefixo, e a
# limpeza remove exatamente isso — nunca por filtro amplo.
PREFIXO = "ensaio-iso"


class PreparacaoDoEnsaio(RuntimeError):
    """
    A preparação não pôde ser concluída.

    É erro, não skip. Preparação silenciosa produz um relatório verde
    sobre um cenário que não existe.
    """


# ---------------------------------------------------------------------------
# Colunas OBRIGATÓRIAS de cada tabela filha, conferidas no catálogo em
# 16/08/2026. O dicionário é o payload mínimo que o PostgREST aceita —
# e é o que separa "negado por autorização" de "recusado por schema".
# ---------------------------------------------------------------------------
def payload_da_filha(tabela: str, processo_id: str, tenant_id: str) -> dict:
    base = {"processo_id": processo_id, "tenant_id": tenant_id}
    if tabela == "geracoes":
        # documento, motor e status são NOT NULL sem default
        return {**base, "documento": "dfd", "motor": "ensaio",
                "status": "ok"}
    if tabela == "decisoes":
        return {**base, "tipo_decisao": f"{PREFIXO}-decisao"}
    if tabela == "fatos_canonicos":
        return {**base, "path": f"{PREFIXO}/campo"}
    # revisoes, qualidade_scores, pareceres, aprendizado_feedback:
    # só processo_id e tenant_id não têm default
    return base


FILHAS_DE_PROCESSO = ("revisoes", "geracoes", "decisoes", "fatos_canonicos",
                      "qualidade_scores", "pareceres", "aprendizado_feedback")


@dataclass
class Identidade:
    rotulo: str
    email: str
    senha: str
    papel: str                     # 'usuario' | 'admin'
    papel_governanca: str | None
    tenant_id: str
    secretaria_id: str | None
    auth_user_id: str = ""


@dataclass
class Cenario:
    """
    O que a preparação criou, para os testes consultarem.

    Convenção dos nomes: sem sufixo = secretaria 1 (a "A") do tenant A;
    sufixo `_b` = secretaria 2 (a "B") do MESMO tenant; sufixo
    `_outro_tenant` = tenant B. A distinção importa porque as duas
    fronteiras falham de jeitos diferentes — tenant errado é recusado
    até para admin, secretaria errada só é recusada para papel local.
    """
    tenant_a: str
    tenant_b: str
    secretaria_1: str
    secretaria_2: str
    secretaria_outro: str
    identidades: dict[str, Identidade] = field(default_factory=dict)
    processo_do_titular: str = ""
    artefato: str = ""
    artefato_b: str = ""
    artefato_outro_tenant: str = ""
    versao: str = ""
    versao_b: str = ""
    versao_outro_tenant: str = ""
    aprovacao: str = ""
    aprovacao_b: str = ""
    aprovacao_outro_tenant: str = ""
    aprovacao_de_tipo_desconhecido: str = ""
    publicacao: str = ""


# Cada identidade existe para provar UMA fronteira.
#
# `revisor_a` e `revisor_b` têm o MESMO papel de governança e diferem
# só na secretaria: é o par que separa "tem competência" de "tem
# competência AQUI". Sem os dois, um revisor sozinho no cenário prova
# apenas que o papel funciona, nunca que ele termina em algum lugar.
DESENHO = (
    # rótulo,      papel,     papel_governanca,   tenant, secretaria
    ("titular",    "usuario", None,               "a",    "1"),
    ("colega",     "usuario", None,               "a",    "1"),  # MESMA
    ("outra_sec",  "usuario", None,               "a",    "2"),
    ("outro_ten",  "usuario", None,               "b",    "outro"),
    ("admin",      "admin",   "admin_municipal",  "a",    "1"),
    ("revisor_a",  "usuario", "revisor_juridico", "a",    "1"),
    ("revisor_b",  "usuario", "revisor_juridico", "a",    "2"),
    ("publicador", "usuario", "publicador",       "a",    "1"),
    ("auditor",    "usuario", "auditor",          "a",    "1"),
)


def _admin_api(servidor):
    """Admin API do Supabase Auth — só existe com credencial de servidor."""
    try:
        return servidor.auth.admin
    except AttributeError as erro:  # noqa: BLE001
        raise PreparacaoDoEnsaio(
            "cliente sem Admin API: a credencial usada não é de servidor"
        ) from erro


def _senha_de_ensaio() -> str:
    """Senha descartável, longa e aleatória por execução."""
    return f"{PREFIXO}-{uuid.uuid4().hex}"


def preparar(servidor) -> Cenario:
    """
    Monta o cenário inteiro. Levanta `PreparacaoDoEnsaio` em qualquer
    falha — nunca devolve cenário pela metade.
    """
    exigir_ensaio()          # pré-condição, antes de qualquer escrita
    admin = _admin_api(servidor)

    try:
        cenario = _criar_organizacao(servidor)
        _criar_identidades(servidor, admin, cenario)
        _criar_conteudo(servidor, cenario)
    except PreparacaoDoEnsaio:
        raise
    except Exception as erro:  # noqa: BLE001
        raise PreparacaoDoEnsaio(
            f"falha ao preparar o ensaio: {type(erro).__name__}") from erro
    return cenario


def _criar_organizacao(servidor) -> Cenario:
    tenants = {}
    for chave, slug in (("a", f"{PREFIXO}-tenant-a"),
                        ("b", f"{PREFIXO}-tenant-b")):
        resposta = servidor.table("tenants").insert(
            {"slug": f"{slug}-{uuid.uuid4().hex[:8]}",
             "nome": f"Ensaio {chave.upper()}"}).execute()
        tenants[chave] = resposta.data[0]["id"]

    secretarias = {}
    for chave, tenant, nome in (("1", "a", "Secretaria 1"),
                                ("2", "a", "Secretaria 2"),
                                ("outro", "b", "Secretaria do outro")):
        resposta = servidor.table("secretarias").insert(
            {"tenant_id": tenants[tenant],
             "nome": f"{PREFIXO} {nome}"}).execute()
        secretarias[chave] = resposta.data[0]["id"]

    return Cenario(tenant_a=tenants["a"], tenant_b=tenants["b"],
                   secretaria_1=secretarias["1"],
                   secretaria_2=secretarias["2"],
                   secretaria_outro=secretarias["outro"])


def _criar_identidades(servidor, admin, cenario: Cenario) -> None:
    """
    Cria as contas no Auth com papel, tenant e secretaria em
    `app_metadata` — nunca em `user_metadata`, onde o próprio usuário
    se promoveria.
    """
    tenants = {"a": cenario.tenant_a, "b": cenario.tenant_b}
    secretarias = {"1": cenario.secretaria_1, "2": cenario.secretaria_2,
                   "outro": cenario.secretaria_outro}

    for rotulo, papel, papel_gov, tenant, secretaria in DESENHO:
        email = f"{PREFIXO}-{rotulo}-{uuid.uuid4().hex[:8]}@ensaio.invalid"
        senha = _senha_de_ensaio()
        metadados = {
            "papel": papel,
            "tenant_id": tenants[tenant],
            "secretaria_id": secretarias[secretaria],
        }
        if papel_gov:
            metadados["papel_governanca"] = papel_gov

        criado = admin.create_user({
            "email": email, "password": senha, "email_confirm": True,
            "app_metadata": metadados})
        auth_id = getattr(criado, "user", criado).id

        servidor.table("usuarios").insert({
            "nome": f"{PREFIXO} {rotulo}", "login": email,
            "senha_hash": "sem-uso-apos-a-0020", "papel": papel,
            "tenant_id": tenants[tenant],
            "secretaria_id": secretarias[secretaria],
            "auth_user_id": auth_id}).execute()

        cenario.identidades[rotulo] = Identidade(
            rotulo=rotulo, email=email, senha=senha, papel=papel,
            papel_governanca=papel_gov, tenant_id=tenants[tenant],
            secretaria_id=secretarias[secretaria], auth_user_id=auth_id)


def _criar_conteudo(servidor, cenario: Cenario) -> None:
    """
    Processo do TITULAR e três trilhas de governança completas —
    artefato → versão → aprovação — uma por fronteira:

      secretaria 1 do tenant A .... o caso normal
      secretaria 2 do tenant A .... a fronteira de SECRETARIA
      secretaria do tenant B ...... a fronteira de TENANT

    A aprovação não é objeto raiz: ela aponta para a versão, e é a
    versão que leva ao artefato que tem secretaria. Por isso cada
    trilha precisa existir INTEIRA — uma aprovação solta não exercita
    a resolução de escopo.
    """
    titular = cenario.identidades["titular"]
    resposta = servidor.table("processos").insert({
        "orgao": f"{PREFIXO} órgão", "objeto": f"{PREFIXO} objeto",
        "tenant_id": cenario.tenant_a,
        "secretaria_id": cenario.secretaria_1,
        "usuario_id": None,
        "auth_user_id": titular.auth_user_id}).execute()
    cenario.processo_do_titular = resposta.data[0]["id"]

    trilhas = (
        # sufixo,           tenant,            secretaria
        ("",                cenario.tenant_a,  cenario.secretaria_1),
        ("_b",              cenario.tenant_a,  cenario.secretaria_2),
        ("_outro_tenant",   cenario.tenant_b,  cenario.secretaria_outro),
    )
    for sufixo, tenant, secretaria in trilhas:
        resposta = servidor.table("governanca_artefatos").insert({
            "tenant_id": tenant, "secretaria_id": secretaria,
            "tipo_artefato": "clausula",
            "chave_estavel": f"{PREFIXO}-{uuid.uuid4().hex[:8]}"}).execute()
        artefato = resposta.data[0]["id"]
        setattr(cenario, f"artefato{sufixo}", artefato)

        resposta = servidor.table("governanca_versoes").insert({
            "artefato_id": artefato}).execute()
        versao = resposta.data[0]["id"]
        setattr(cenario, f"versao{sufixo}", versao)

        resposta = servidor.table("governanca_aprovacoes").insert({
            "tenant_id": tenant, "entidade_tipo": "versao",
            "entidade_id": versao}).execute()
        setattr(cenario, f"aprovacao{sufixo}", resposta.data[0]["id"])

    # `governanca_aprovacoes.entidade_tipo` é `text not null` — sem
    # CHECK, sem FK. A tabela aceita qualquer string, e é exatamente
    # por isso que a RPC precisa de matriz FECHADA: uma aprovação que
    # aponta para algo que a matriz não resolve não tem escopo que se
    # possa afirmar, e nem o papel de alcance de tenant deve passar.
    resposta = servidor.table("governanca_aprovacoes").insert({
        "tenant_id": cenario.tenant_a, "entidade_tipo": "processo",
        "entidade_id": cenario.processo_do_titular}).execute()
    cenario.aprovacao_de_tipo_desconhecido = resposta.data[0]["id"]

    resposta = servidor.table("governanca_publicacoes").insert({
        "tenant_id": cenario.tenant_a}).execute()
    cenario.publicacao = resposta.data[0]["id"]


def limpar(servidor, cenario: Cenario) -> None:
    """
    Remove o que a preparação criou, por id exato — nunca por filtro
    amplo. Falha de limpeza avisa e não derruba a suíte: o cenário é de
    um projeto descartável.
    """
    def _apagar(tabela: str, coluna: str, valor) -> None:
        if not valor:
            return
        try:
            servidor.table(tabela).delete().eq(coluna, valor).execute()
        except Exception:  # noqa: BLE001
            print(f"  (aviso) resto de ensaio em {tabela}: {coluna}={valor}")

    for tabela in FILHAS_DE_PROCESSO:
        _apagar(tabela, "processo_id", cenario.processo_do_titular)
    _apagar("processos", "id", cenario.processo_do_titular)

    for ident in cenario.identidades.values():
        _apagar("governanca_eventos", "ator", ident.auth_user_id)
    _apagar("governanca_publicacoes", "id", cenario.publicacao)
    # ordem inversa da criação: aprovação, versão, artefato
    _apagar("governanca_aprovacoes", "id",
            cenario.aprovacao_de_tipo_desconhecido)
    for sufixo in ("", "_b", "_outro_tenant"):
        _apagar("governanca_aprovacoes", "id",
                getattr(cenario, f"aprovacao{sufixo}"))
        _apagar("governanca_versoes", "id",
                getattr(cenario, f"versao{sufixo}"))
        _apagar("governanca_artefatos", "id",
                getattr(cenario, f"artefato{sufixo}"))

    for ident in cenario.identidades.values():
        _apagar("usuarios", "auth_user_id", ident.auth_user_id)
        try:
            servidor.auth.admin.delete_user(ident.auth_user_id)
        except Exception:  # noqa: BLE001
            print(f"  (aviso) conta de ensaio remanescente: {ident.rotulo}")

    for secretaria in (cenario.secretaria_1, cenario.secretaria_2,
                       cenario.secretaria_outro):
        _apagar("secretarias", "id", secretaria)
    for tenant in (cenario.tenant_a, cenario.tenant_b):
        _apagar("tenants", "id", tenant)


def sessao(identidade: Identidade):
    """Cliente autenticado como a identidade dada."""
    from supabase import create_client

    anon = os.environ["GOVDOCS_ENSAIO_ANON_KEY"]
    cliente = create_client(exigir_ensaio(), anon)
    cliente.auth.sign_in_with_password(
        {"email": identidade.email, "password": identidade.senha})
    return cliente
