# Cartographer — instalação e uso

O [Cartographer](https://github.com/Icarus-afk/Cartographer) mantém um
grafo semântico do código-fonte deste repositório e o expõe por MCP para
o assistente de desenvolvimento.

## O que ele é, e o que não é

**É** ferramenta de quem desenvolve. Serve para achar onde algo está,
entender de que um módulo depende e medir o impacto de uma mudança antes
de fazê-la — sem ler doze arquivos para descobrir.

**Não é** parte do produto. O GovBot, o wizard, a pesquisa de preços e a
consolidação de demandas não sabem que ele existe. Nenhuma dependência
dele entrou no `requirements.txt`, e derrubá-lo não afeta o aplicativo em
nada.

Essa separação foi deliberada. O assistente do app serve servidores
públicos elaborando licitações; um mapa do código-fonte do próprio
sistema não tem valor para eles, e expô-lo pelo chat seria superfície de
vazamento em vez de funcionalidade. Acrescentar as ferramentas do
Cartographer a `govbot.ACOES_PERMITIDAS` também alargaria justamente a
fronteira de segurança sobre a qual o desenho do GovBot se apoia.

## Instalação

O Cartographer vive **fora** deste repositório e **fora** do `.venv` do
projeto — ele não pode entrar como dependência do aplicativo.

```bash
git clone https://github.com/Icarus-afk/Cartographer.git ~/Cartographer
cd ~/Cartographer
python3 -m venv ~/.venvs/cartographer
~/.venvs/cartographer/bin/pip install -e .
# Obrigatório: o Cartographer declara `mcp>=1.0.0` sem teto, e o `mcp`
# 2.x renomeou FastMCP para MCPServer — sem este pin, `cartographer-mcp`
# nem sobe.
~/.venvs/cartographer/bin/pip install "mcp<2"
```

Para o MCP encontrar o executável, deixe-o no `PATH`:

```bash
export PATH="$HOME/.venvs/cartographer/bin:$PATH"   # no seu .bashrc/.zshrc
cartographer version
```

## Índice

O índice é **local ao projeto**, não global:

```bash
cd /caminho/para/projeto-saas
cartographer index .
cartographer status      # deve apontar para .cartographer/index.db
```

Quem garante isso é o `.cartographer/config.json`, que é versionado. Sem
ele, o Cartographer usa `~/.cartographer/`, que mistura este repositório
com qualquer outro da máquina — e a busca passa a devolver resultado de
outro projeto.

O banco `.cartographer/index.db` **não** é versionado: é derivado do
código, pesa megabytes e recriá-lo custa segundos.

## MCP

O `.mcp.json` na raiz registra o servidor para o Claude Code:

```json
{ "mcpServers": { "cartographer": { "command": "cartographer-mcp", "args": [] } } }
```

Para o Claude Desktop, o mesmo bloco vai no
`claude_desktop_config.json`. O servidor resolve o banco a partir do
diretório de trabalho, então abra o assistente com a raiz do projeto
como CWD.

## Segurança

O Cartographer respeita o `.gitignore`, e o `.cartographerignore` deste
repositório reforça: segredos, `contas-auth*.json` (e-mails e UIDs
reais), ambiente virtual e caches ficam fora.

Depois da primeira indexação, isto foi conferido no próprio banco: 245
caminhos no grafo, nenhum arquivo de segredo, e o único alarme de
credencial era o teste do varredor de segredos — cujo JWT de exemplo
termina em `assinaturafalsa`.

Vale repetir a conferência se alguém afrouxar o `.gitignore`:

```bash
python3 - <<'EOF'
import sqlite3, re
con = sqlite3.connect('.cartographer/index.db')
alvo = re.compile(r'secrets\.toml$|contas-auth|\.env|\.pem$|\.key$')
maus = [c for (c,) in con.execute(
    'select distinct file_path from nodes where file_path is not null')
    if alvo.search(c or '')]
print(maus or 'nenhum arquivo sensível no índice')
EOF
```

## Atualização

```bash
./scripts/cartographer_atualizar.sh            # desde o último merge
./scripts/cartographer_atualizar.sh origin/main
./scripts/cartographer_atualizar.sh --completo
```

Rodar depois de merge ou de trocar de branch — nunca no caminho de uma
requisição de usuário.

Sem o Cartographer instalado o script sai com código 0 e uma mensagem:
ele é opcional, e quem não o tem continua desenvolvendo normalmente.

## Limites conhecidos, medidos aqui

Tudo abaixo foi medido neste repositório, não suposto.

| Observação | Consequência |
|---|---|
| **`mcp>=1.0.0` sem teto no `pyproject.toml` do Cartographer.** O pip instala o `mcp` 2.x, onde `FastMCP` virou `MCPServer`, e o `cartographer-mcp` não sobe: `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | Instale com `pip install "mcp<2"` depois do `pip install -e .`. Sem isso o servidor MCP não funciona numa instalação limpa |
| **`impact` subestima drasticamente**: devolve 1 dependente para `src/db.py`, que 40 módulos importam. Só há 165 arestas `IMPORTS` num projeto que usa import relativo em quase todo arquivo | Não use `impact` para decidir o alcance de uma mudança aqui. `Grep` continua certo para "quem importa X"; `neighbors` serve no nível de função |
| **`search` é por token, não por sentido**, mesmo com embeddings — e o modelo (`bge-small-en`) é inglês, num código escrito em português | Consulte com nome de símbolo (`consolidacao`, `planejar`), não com frase |
| `update-index` quebra na v0.1.0: `KeyError: 'nodes'` em `graph/builder.py:238` (passa `stats={}` e incrementa `stats["nodes"]`) | O script detecta e cai para reindexação completa (~1,5s). Vale abrir issue |
| `architecture --detect` classificou "Business" com 3 entidades | Subestima o domínio (`govbot`, `precos`, `demanda`, `parecer_correcao`). Pista, não laudo |

**O que funciona bem:** `file_summary` (resumo compacto e correto),
`neighbors` (grafo de chamadas real), `summarize`, `context` e `status`.
