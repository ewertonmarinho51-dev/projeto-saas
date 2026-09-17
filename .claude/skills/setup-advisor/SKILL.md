---
name: setup-advisor
description: >
  Analisa este repositório e recomenda automações de agente — MCP servers,
  skills, hooks, subagentes, workflows — com base na arquitetura REAL do
  projeto, não em catálogo. Use quando alguém perguntar que ferramenta,
  plugin, MCP, skill, hook ou agente vale a pena adicionar; quando pedir
  para "melhorar o setup"; ou antes de instalar qualquer automação nova.
  Somente leitura: recomenda, nunca instala.
---

# Setup Advisor — o que vale automatizar aqui

Camada de análise baseada na metodologia do plugin oficial
[`claude-code-setup@claude-plugins-official`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/claude-code-setup)
da Anthropic, ajustada às restrições deste projeto.

**Esta skill é somente leitura.** Ela analisa e recomenda. Não cria
arquivo, não instala MCP, não edita `settings.json`, não toca em
produção. Quem instala é o operador, depois de ler.

Se o plugin oficial estiver instalado no ambiente, prefira a skill dele
(`claude-automation-recommender`) para o levantamento genérico e use esta
para as regras que só valem aqui. Instalação (comando do operador, nunca
seu):

```
/plugin install claude-code-setup@claude-plugins-official
```

## A regra que evita a pior falha

**Poucas ferramentas de alto valor, não muitas integrações redundantes.**
O plugin oficial manda recomendar **1–2 por categoria**. Cinco arquivos
de automação que ninguém lê são piores que zero, porque cada um é uma
afirmação sobre como o projeto trabalha — e afirmação falsa em `.claude/`
desorienta o próximo agente.

Nunca recomende uma ferramenta porque ela existe. Toda recomendação
responde sete perguntas, e a primeira é a que reprova a maioria:

1. **que problema REAL deste repositório ela resolve** — com evidência,
   um arquivo, um incidente, uma medida;
2. onde exatamente será usada;
3. benefício esperado;
4. risco;
5. prioridade;
6. custo operacional;
7. exige credencial?

Sem resposta para a 1, não é recomendação — é catálogo.

## O que já existe aqui (não recomende de novo)

Medido em 17/09/2026. Confira antes de usar; se divergir, o repositório
manda.

| Camada | Estado |
|---|---|
| Cartographer | `.mcp.json` versionado. Mapa do código, **não** do produto |
| context7 | `.mcp.json`. Documentação viva das bibliotecas |
| Headroom | `.mcp.json`. Comprime saída de ferramenta. **Só para o agente** — medido: a planilha de 210 itens comprime 41% perdendo 463 números |
| Skills | `caveman`, `design-taste`, `design-minimalist`, `revisar-migracao`, `prova-com-dente`, esta |
| Hooks | `.claude/settings.json` — bloqueio de segredo (PreToolUse), provas relacionadas (PostToolUse) |
| Subagentes | `revisor-de-banco-e-seguranca` |
| Comandos | **Nenhum, de propósito.** Skill já é invocável como `/nome`; um `.claude/commands/` ao lado seria duas verdades sobre a mesma coisa |
| Revisão de código | Bot externo já comenta nas PRs |
| Varredura de segredos | `scripts/varredura_segredos.py` |
| Testes | 97 arquivos, ~2.170 provas, AppTest + ensaio PostgreSQL real + disciplina de mutação |
| CI | GitHub Actions, um job, com pgvector, LibreOffice e build do editor |

## Ordem de trabalho

### 1. Mapa antes de varredura

Se o Cartographer responder: `architecture` → `summarize` → `graph_data`
para pergunta arquitetural; `search` (token único, não frase em
português) → `file_summary` → `neighbors` para componente específico.
**Não confie no `impact` aqui** — mede 1 dependente para `src/db.py`,
que 40 módulos importam. Para dependência, `Grep`.

Se ele não responder — não instalado, sem índice, com erro —, siga com
`Glob`/`Grep`/`Read` e mencione uma vez. Ele é auxiliar, nunca requisito.

### 2. Levantar a arquitetura

Vinte pontos: linguagens, frameworks, frontend, backend, banco,
autenticação, autorização, APIs, filas/workers, RAG, LLMs, agentes
existentes, function calling, MCPs, integrações externas, CI/CD,
infraestrutura, testes, observabilidade, segurança.

Leia `requirements.txt`, `package.json` de `assets/`, `.github/workflows/`,
`.devcontainer/`, `.streamlit/config.toml`, `supabase/migrations/`,
`.mcp.json`, `CLAUDE.md`, a árvore de `src/` e `tests/`.

**Nunca leia, imprima, registre ou cite conteúdo de** `.env`,
`.streamlit/secrets.toml`, `contas-auth*.json`, chave de API, token,
cookie, senha, certificado privado ou segredo de deploy. Se precisar
dizer que um segredo existe, diga ONDE ele mora — nunca o valor.

### 3. Pesar cada candidata

| Peso | Pergunta |
|---|---|
| Impacto | quantas horas ou incidentes por mês isso evita AQUI? |
| Complexidade | quantos arquivos novos e quanta manutenção? |
| Risco | o que quebra se falhar, e o que vaza se for comprometida? |
| Dependências | exige credencial, serviço externo, dependência em `requirements.txt`? |

Descarte por escrito. A lista de **descartadas com motivo** é a parte
mais útil do relatório — é ela que impede a mesma ferramenta de voltar à
mesa daqui a três meses.

### 4. Entregar

Relatório em prosa para o humano, e o objeto abaixo quando pedirem
estruturado:

```json
{
  "project_analysis": {},
  "recommended_mcp_servers": [],
  "recommended_skills": [],
  "recommended_hooks": [],
  "recommended_agents": [],
  "recommended_commands": [],
  "recommended_workflows": [],
  "security_notes": [],
  "implementation_priority": []
}
```

Cada item traz `nome`, `problema`, `onde`, `beneficio`, `risco`,
`prioridade`, `custo`, `credenciais`. `implementation_priority` ordena
por impacto ÷ risco, não por facilidade.

## Restrições deste projeto

Elas não são negociáveis por uma recomendação:

- **Ferramenta de desenvolvimento não entra em `src/`.** O Streamlit que
  gera documento de licitação não pode importar nada desta camada. A
  regra vale para o Cartographer e vale para o Advisor. A prova
  mecânica está em `tests/test_automacao_agentes.py`.
- **Nada obrigatório.** Se esta camada sumir, o app funciona igual.
- **Nunca instalar nem alterar produção** porque uma recomendação
  apareceu. Recomendação é texto; instalação é decisão do operador.
- **Nada de subsistema paralelo.** Antes de propor um módulo novo,
  procure onde a capacidade já mora.
- **MCP com credencial de produção não entra em `.mcp.json` versionado.**
  O arquivo é do repositório; a credencial é da pessoa. Para o Supabase,
  declare o projeto de ensaio e deixe produção em configuração local.

## Fronteira com as outras camadas

As quatro camadas, sem sobreposição: **Cartographer = Repository
Intelligence**, **context7 = Documentation Intelligence**, **Headroom =
Context Optimization**, **esta skill = Tool Intelligence**. O Headroom
vem sempre DEPOIS das outras — ele comprime o que elas produziram, nunca
antes e nunca no lugar delas.

| Pergunta | Ferramenta |
|---|---|
| onde está esse código? | Cartographer |
| documentação atualizada de biblioteca | ferramenta de docs (context7, se instalada) |
| essa saída de ferramenta é grande demais | Headroom — e só ela: nunca em conteúdo que vira documento |
| schema, RLS, grants, dados | ferramenta Supabase |
| PR, issue, CI | ferramenta GitHub |
| essa migração está segura? | subagente `revisor-de-banco-e-seguranca` |
| essa prova tem dente? | skill `prova-com-dente` |
| **que ferramenta eu deveria usar/adicionar?** | **esta skill** |

Uma por pergunta. Encadear três quando uma resolve gasta contexto e
produz relatório mais longo, não mais certo.
