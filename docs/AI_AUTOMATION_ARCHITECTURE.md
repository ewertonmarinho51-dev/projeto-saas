# Arquitetura de automação de agentes

**17/09/2026.** Camada de desenvolvimento do GovDocs Wizard: o que
existe, por que existe, e o que foi deliberadamente deixado de fora.

Baseada na metodologia do plugin oficial
[`claude-code-setup@claude-plugins-official`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/claude-code-setup)
da Anthropic.

---

## A regra que governa o resto

O plugin oficial é **uma única skill somente leitura**,
`claude-automation-recommender`, e a primeira linha dela é:

> "This skill is read-only. It analyzes the codebase and outputs
> recommendations. It does NOT create or modify any files."

A regra de saída dele é **1–2 recomendações por categoria** — "don't
overwhelm". Seguimos isso, e é a razão de esta camada ter 2 MCPs, 3
skills, 2 ganchos, 1 subagente e **zero comandos**, e não as três dezenas
de peças que o pedido original listava.

Cinco arquivos de automação que ninguém lê são piores que zero: cada um
é uma afirmação sobre como o projeto trabalha, e afirmação falsa em
`.claude/` desorienta o próximo agente.

---

## A fronteira, que é o requisito mais importante

**Esta camada serve a quem desenvolve. O produto não a conhece.**

O Streamlit que gera DFD, ETP, TR e edital para um órgão público não
importa nada daqui, não lê `.claude/`, não sabe que o Cartographer
existe. Se a camada inteira sumir — plugin desinstalado, MCP fora do ar,
`.claude/` apagado —, o app funciona igual.

Isso não é promessa em documento. É `tests/test_automacao_agentes.py`:

```python
def test_o_aplicativo_nao_conhece_a_camada_de_automacao():
    # nenhum .py de src/ menciona .claude, cartographer,
    # setup-advisor ou claude-code-setup
```

A prova é por **menção**, não por import, porque o vazamento provável
não é `import setup_advisor` — é alguém montar um caminho para
`.claude/skills/...` e ler de lá em tempo de execução. Fronteira que mora
só em comentário é fronteira que a primeira pressa atravessa.

---

## As peças

### MCP servers — dois

#### `cartographer` — mapa do código

Grafo semântico do código-fonte, exposto por MCP. **Camada auxiliar,
nunca requisito.** Limites medidos neste repositório, e eles importam:

- **`impact` subestima drasticamente** — 1 dependente para `src/db.py`,
  que 40 módulos importam. Import relativo não é resolvido. Para
  dependência, `Grep`;
- o modelo de embedding é `bge-small-**en**`; este código é escrito em
  português, e consulta em linguagem natural devolve vazio. `search`
  funciona por token;
- `update-index` incremental está quebrado na v0.1.0; o script cai para
  reindexação completa.

Ordem de consulta e manutenção: seção própria no `CLAUDE.md`.

#### `context7` — documentação viva

**Problema real, não hipotético**: o `requirements.txt` fixa
`streamlit==1.64.0` porque a 1.64 mudou `at.session_state` no meio de uma
PR e quebrou uma prova no CI enquanto passava no ambiente local. O
comentário lá diz: *"o problema não foi a API ter mudado; foi a mudança
ter chegado sem ninguém decidir."*

Bibliotecas que justificam: Streamlit, TipTap 3.31, openai, google-genai,
supabase-py, psycopg 3.

Configuração idêntica à do plugin oficial — servidor HTTP remoto, sem
Node local. Funciona anonimamente; `CONTEXT7_API_KEY` só eleva o limite
de uso, e por isso entra como variável de ambiente, **nunca como valor no
arquivo versionado**.

### Skills — três

| Skill | Por quê |
|---|---|
| `setup-advisor` | A metodologia do plugin oficial + as restrições deste projeto. Somente leitura: recomenda, nunca instala |
| `revisar-migracao` | O risco recorrente nº 1. Em setembro/2026 a mesma classe de defeito apareceu três vezes (P0 do `anon`, DELETE da 0021, TRUNCATE da 0024) |
| `prova-com-dente` | Teste de mutação. Pegou quatro defeitos reais em provas que já estavam verdes |

As três convivem com `caveman`, `design-taste` e `design-minimalist`,
que já existiam.

### Ganchos — dois

Ambos em `.claude/settings.json`, ambos **falham abertos**.

#### Bloqueio de escrita em segredo (`PreToolUse`)

Este repositório tem um arquivo de credencial na **raiz**
(`contas-auth.json`). O que o protege hoje é o `.gitignore` — e
`.gitignore` impede o commit, não a escrita.

Cobre `.env*`, `.streamlit/secrets.toml*`, `contas-auth*.json`,
`credentials.json`, `*.pem`, `*.key`, `*.p12`, `secrets.y*ml`. Libera
`*.example`, `*.sample`, `*.template` — o modelo versionado existe para
ser editado, e um gancho com falso positivo é um gancho que some na
semana seguinte.

O `*` em `secrets.toml*` não é preguiça: `secrets.toml.bak` é o mesmo
segredo com outro nome, e é o que aparece quando alguém está "só fazendo
uma cópia antes de mexer".

#### Provas relacionadas (`PostToolUse`)

Roda **um** arquivo de teste, o que casa com o módulo editado. A suíte
inteira leva ~2,5 min; rodá-la a cada edição seria o gancho que bloqueia
o desenvolvimento sem justificativa.

O mapeamento é deliberadamente burro: `src/demanda/extracao.py` procura
`tests/test_demanda_extracao.py`, depois `tests/test_extracao.py`. Sem
heurística de similaridade — rodar o teste **parecido** e dizer "verde" é
pior que não rodar nada.

**Nunca reprova a edição.** Quem decide se a mudança está pronta é a
suíte inteira, no `pytest -q` e no CI. Um gancho que reprova pela metade
do sinal treina a ignorar o sinal inteiro.

### Subagente — um

`revisor-de-banco-e-seguranca`, somente leitura, escopo fechado em RLS,
grants, migrações, segredos e matriz de privilégio. Existe porque os três
achados reais do projeto estavam todos nessa área e todos eram invisíveis
na leitura do diff — e visíveis no catálogo.

### Comandos — nenhum

Skill já é invocável como `/nome`. Um `.claude/commands/revisar-migracao`
ao lado da skill `revisar-migracao` seriam duas verdades sobre a mesma
coisa, que é o que a regra de "nada de subsistema paralelo" proíbe.

### Workflow

A varredura de segredos passou a rodar **no CI, como primeiro passo**.
`scripts/varredura_segredos.py` existe desde a revisão externa e até
agora dependia de alguém lembrar de rodá-lo — scanner que depende de
memória não é controle, é intenção.

Escopo **árvore** (o estado final dos arquivos), não histórico: um portão
que acusa linhas já removidas por commits posteriores é um portão que as
pessoas aprendem a ignorar. Sem base identificável, **falha** — "não
consegui verificar" e "verifiquei e está limpo" não podem ter a mesma
cor.

---

## O roteador

| Pergunta | Ferramenta |
|---|---|
| onde está esse código? | Cartographer |
| documentação atualizada de biblioteca | context7 |
| schema, RLS, grants, dados | Supabase |
| PR, issue, CI | GitHub |
| essa migração está segura? | `revisor-de-banco-e-seguranca` |
| essa prova tem dente? | `prova-com-dente` |
| que ferramenta eu deveria usar/adicionar? | `setup-advisor` |

Uma por pergunta. Encadear três quando uma resolve gasta contexto e
produz relatório mais longo, não mais certo.

---

## Segurança

1. **Nunca** ler, imprimir, registrar, versionar ou expor `.env`,
   `secrets.toml`, `contas-auth*.json`, chave de API, token, cookie,
   senha, certificado privado ou segredo de deploy — em comando, log,
   fixture, commit ou relatório. Para dizer que um segredo existe, diga
   **onde mora**, nunca o valor.
2. **MCP com credencial de produção não entra em `.mcp.json`
   versionado.** O arquivo é do repositório; a credencial é da pessoa. É
   por isso que o Supabase MCP, que usamos para aplicar migrações,
   **não** está declarado ali: com ele versionado, qualquer pessoa com o
   repositório e um token aplica migração em produção. Se for declarar,
   declare o projeto de ensaio descartável e mantenha produção em
   configuração local.
3. Nenhuma recomendação instala nada. Instalação é decisão do operador.
4. `tests/test_automacao_agentes.py` varre `.claude/` com o mesmo scanner
   que guarda o repositório — instrução de agente fala de chave, papel e
   credencial o tempo todo, e é exatamente o tipo de arquivo onde um
   valor copiado de um `secrets.toml` real passaria despercebido.

---

## Fallback

Cada peça tem um caminho de degradação, e nenhuma é requisito:

| Peça indisponível | O que acontece |
|---|---|
| Cartographer | `Grep`/`Glob`/`Read`. Mencione uma vez e siga; não instale nada no meio da tarefa |
| context7 | A IA volta a usar memória de treino. Confirme versão de API antes de escrever |
| Skills / subagente | O trabalho é feito à mão, do jeito que vinha sendo |
| Ganchos | O `.gitignore`, a varredura no CI e a suíte continuam de pé. O gancho é a camada de cima, não a contenção |
| A camada inteira | O aplicativo funciona igual. Provado em `test_o_aplicativo_nao_conhece_a_camada_de_automacao` |

---

## Manutenção

- **Índice do Cartographer**: `./scripts/cartographer_atualizar.sh`
  depois de merge ou troca de branch. Nunca no caminho de uma requisição.
- **Skills**: quando o ritual mudar na prática, mude o arquivo. Skill que
  descreve um processo que ninguém segue mais é pior que skill nenhuma.
- **Ganchos**: se um começar a atrapalhar, conserte o padrão ou remova.
  Não conviva com falso positivo — é assim que a proteção inteira perde
  credibilidade.
- **Antes de adicionar peça nova**: `setup-advisor`, e a pergunta que
  reprova a maioria — *que problema real deste repositório ela resolve,
  com evidência?*

---

## O que foi descartado, e por quê

Esta é a seção mais útil do documento: é ela que impede a mesma
ferramenta de voltar à mesa daqui a três meses.

| Ferramenta | Motivo |
|---|---|
| **Playwright MCP** | Streamlit renderiza no servidor, e a estratégia do projeto é `AppTest`, que exercita o script real sem navegador — ~2.170 provas assim. A única superfície de navegador é o editor TipTap, já testado com `node --test` + jsdom. Seria uma **terceira** pilha de teste para um bundle. Reconsiderar só para regressão visual do editor |
| **Vercel MCP** | A plataforma não consegue servir este app — o check é vermelho em toda PR. Aprofundar a integração é investir no que deve ser desligado |
| **GitHub MCP no `.mcp.json`** | Já funciona na sessão; declarar não acrescenta capacidade |
| **Supabase MCP no `.mcp.json`** | Carrega credencial de produção. Ver Segurança, item 2 |
| **Sentry / observabilidade** | O problema é real — três provedores de LLM em cascata e a única evidência de falha é `logging` que ninguém lê. Mas a solução entra em `requirements.txt` e no processo de produção. É decisão do operador, não recomendação automática |
| **Subagente `code-reviewer`** | Um bot de revisão já comenta nas PRs. Dois revisores na mesma linha produzem ruído |
| **Subagentes de arquitetura / frontend / backend / testes** | Sobrepõem, respectivamente, o Cartographer, as skills de design, uma camada que não existe (não há backend separado) e a skill `prova-com-dente` |
| **Gancho de formatação automática** | Não há formatador configurado. Ligar um agora reescreveria 35.100 linhas e destruiria o `git blame` de um código cujo valor está muito nos comentários |
| **`.claude/commands/`** | Redundante com as skills |

---

## Pendências conhecidas

- **O check da Vercel segue vermelho em toda PR.** Não é falha técnica; é
  falha de sinal — treina a ignorar vermelho. A integração deveria ser
  removida do repositório, e isso é ação no painel da Vercel, não em
  código.
- **Sem rastreamento de erro em produção.** Ver a linha do Sentry acima.
- **Sem lint, formatação ou checagem de tipo.** Não há `ruff.toml`,
  `pyproject.toml`, `mypy.ini`. Um `ruff check` em job não bloqueante
  seria o primeiro passo barato; adotar formatação é decisão maior, pelo
  motivo do `git blame`.
- **O plugin oficial não está instalado.** O comando é do operador:
  `/plugin install claude-code-setup@claude-plugins-official`. Esta
  camada não depende dele — reimplementá-lo aqui seria o subsistema
  paralelo que a regra da casa proíbe; o que existe aqui é a parte que
  ele não tem: as regras deste projeto.
