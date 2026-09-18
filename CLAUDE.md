# GovDocs Wizard — instruções do projeto

App Streamlit que gera documentos da fase preparatória de licitações
(Lei 14.133/2021): DFD → ETP → TR → Edital, com RAG e Supabase.

## Regras permanentes

- **Design/front-end**: SEMPRE aplicar os skills `design-taste` e
  `design-minimalist` (fonte: ewertonmarinho51-dev/Front-End-Bonito) em
  qualquer trabalho de UI/CSS/layout. Contexto: setor público —
  sobriedade, credibilidade e acessibilidade prevalecem sobre estética;
  paleta institucional azul (#1B4F8A) definida em `.streamlit/config.toml`
  e `src/ui/components.py`.
- **Comunicação**: skill `caveman` ativo (respostas curtas; código,
  comandos e erros exatos).
- **IA do produto**: OpenAI motor principal (`gpt-5-mini` padrão),
  fallback Gemini. Chaves só em `.streamlit/secrets.toml` (gitignored)
  — NUNCA commitar segredos.
- **Memória entre sessões**: consultar/atualizar
  `memorias/projeto-saas-govdocs.md` no repo
  ewertonmarinho51-dev/memoria-do-claudinho (início de sessão e a cada
  marco).
- **Testes**: `python -m pytest -q` (19+ testes, modo demo, sem rede).
  Rodar antes de qualquer push. CI: GitHub Actions em todo push.
- **Banco**: Supabase projeto `nxibohgoekphxblqtqku`; migrações
  versionadas em `supabase/migrations/` (aplicar via MCP ou SQL Editor).
- **Git**: trunk `main`; trabalho em branch `claude/<assunto>` por
  entrega, com PR. Usuário autoriza o merge caso a caso, quando o CI
  fecha verde. Textos de commit em português.

## Camada de automação de agentes

Esta camada serve a quem DESENVOLVE. O produto não a conhece, e
`tests/test_automacao_agentes.py` prova isso mecanicamente: nenhum
módulo de `src/` menciona `.claude`, `cartographer` ou o Advisor. Se ela
sumir inteira, o app gera documento igual.

| Peça | Onde | Para quê |
|---|---|---|
| Cartographer | `.mcp.json` | mapa do código |
| context7 | `.mcp.json` | documentação viva das bibliotecas |
| Headroom | `.mcp.json` | comprime saída de ferramenta grande |
| `ai_gateway` + `roteamento` | `src/` | política de modelo por tarefa; OmniRoute pluggável, hoje desligado |
| `setup-advisor` | `.claude/skills/` | que automação vale a pena aqui |
| `revisar-migracao` | `.claude/skills/` | o ritual de migração de banco |
| `prova-com-dente` | `.claude/skills/` | teste de mutação |
| `revisor-de-banco-e-seguranca` | `.claude/agents/` | RLS, grants, segredos |
| bloqueio de segredo | `.claude/settings.json` | recusa escrita em `.env`, `secrets.toml`, `contas-auth*.json` |
| provas relacionadas | `.claude/settings.json` | roda o teste do módulo editado; nunca reprova |

Detalhes em `docs/AI_AUTOMATION_ARCHITECTURE.md`. Não há
`.claude/commands/` de propósito: skill já é invocável como `/nome`.

### Modelo por tarefa

A escolha de modelo mora em `src/roteamento.py` — **não espalhe decisão
de modelo por outros arquivos**. Documento oficial (DFD, ETP, TR, Mapa de
Riscos, edital, ARP) é `PROCUREMENT_HIGH_ACCURACY` e só usa motor
homologado; hoje, só a OpenAI. Documento novo entra em `TIPO_DO_ROTULO`
antes de ser gerado, senão cai no grupo mais barato — há prova disso.

**Nunca acrescente motor a `PROCUREMENT_HIGH_ACCURACY` sem relatório.**
Rode `scripts/homologacao_modelo.py --motor <m> --gravar`, que gera a
cadeia inteira sobre o caso real de 210 itens e reprova se um único
valor, quantidade, data, código ou artigo sair diferente do que entrou.
O relatório vai junto no commit; `tests/test_homologacao.py` recusa a
promoção sem ele.

`OMNIROUTE_ENABLED`, `OMNIROUTE_BASE_URL` e `OMNIROUTE_ROUTING_ENABLED`
vêm do AMBIENTE, nunca de `config_app`: a tabela é editável pelo painel,
e política que usuário muda pela tela não é política.

**`OMNIROUTE_ROUTING_ENABLED` está LIGADA em desenvolvimento**
(`.devcontainer/devcontainer.json`) e desligada em produção. No
Codespaces, uma falha da OpenAI ao gerar edital passa a FALHAR em vez de
cair para o Gemini — é o comportamento desejado, e se incomodar a
conversa é sobre homologar o Gemini, não sobre desligar a política. O
deploy não lê o devcontainer; ligar em produção é ato separado.

Embeddings **nunca** passam por roteamento: o índice v2 é pinado a
`text-embedding-3-small` e outro provedor corromperia a busca em
silêncio. `docs/OMNIROUTE_INTEGRATION.md` tem o resto.

### Headroom — quando comprimir

`headroom_compress` em saída de ferramenta: JSON de API, listagens, logs,
`git diff` longo, saída de CI, consulta ao banco com muitas linhas
semelhantes, resultado do Cartographer. `headroom_retrieve` com o hash
quando precisar do literal (cache local de 1h).

**Nunca comprima** o que vira documento do processo — DFD, ETP, TR, Mapa
de Riscos, edital, contrato, ata, pesquisa de preços, PNCP, propostas,
pareceres. E **nunca a planilha de itens**: medido em
`scripts/headroom_bench.py`, ela comprime 41% perdendo **463 números e
185 códigos de item**.

Não vale a pena abaixo de ~1.000 tokens, em prosa em português nem em
código — medido: 0% de economia. Nunca mande segredo para compressão: o
CCR grava o original em disco por uma hora.

`docs/HEADROOM_INTEGRATION.md` tem a tabela completa.

### Antes de adicionar ferramenta

Você tem uma camada de análise de automações baseada na metodologia do
Claude Code Setup. **Antes de acrescentar MCP, skill, hook, agente ou
workflow, analise a arquitetura e determine se a automação gera
benefício real aqui.** Prefira poucas ferramentas de alto valor a muitas
integrações redundantes — a regra do plugin oficial é 1–2 por categoria.

Para entender a estrutura do código, consulte primeiro as ferramentas de
inteligência do repositório (Cartographer). Para documentação de
biblioteca, use a ferramenta de documentação. Antes de mudança
estrutural, avalie dependências, impacto, segurança e testes.

**Nunca instale ferramenta nem altere produção automaticamente porque
uma recomendação apareceu.** Recomendação é texto; instalação é decisão
do operador.

### Roteador — uma ferramenta por pergunta

| Pergunta | Ferramenta |
|---|---|
| onde está esse código? | Cartographer |
| documentação atualizada de biblioteca | context7 |
| schema, RLS, grants, dados | Supabase |
| PR, issue, CI | GitHub |
| saída de ferramenta grande demais | Headroom (`headroom_compress`) |
| erro em produção | (não há rastreamento — ver o doc) |
| essa migração está segura? | `revisor-de-banco-e-seguranca` |
| essa prova tem dente? | `prova-com-dente` |
| que ferramenta eu deveria usar? | `setup-advisor` |

Encadear três quando uma resolve gasta contexto e produz relatório mais
longo, não mais certo.

### Segredo

Nunca leia, imprima, registre, versione ou exponha `.env`,
`.streamlit/secrets.toml`, `contas-auth*.json`, chave de API, token,
cookie, senha, certificado privado ou segredo de deploy — nem em
comando, log, fixture, commit ou relatório. O gancho de bloqueio é a
última linha, não a primeira: ele falha aberto de propósito.

MCP com credencial de produção **não** entra em `.mcp.json` versionado.
O arquivo é do repositório; a credencial é da pessoa.

## Cartographer — mapa semântico do código

Este repositório é indexado pelo [Cartographer](https://github.com/Icarus-afk/Cartographer),
que mantém um grafo do código-fonte (232 arquivos, ~5.700 nós) e o expõe
por MCP. **Ele serve a quem DESENVOLVE, não ao aplicativo**: o GovBot e
o resto do produto não sabem que ele existe, e nada em produção depende
dele.

Você tem acesso ao Cartographer, que mantém um mapa semântico do
código-fonte. Antes de pesquisar extensivamente arquivos ou fazer
alterações estruturais, consulte o Cartographer para localizar
componentes, dependências e impactos.

### Ordem de consulta

Para **pergunta arquitetural**: `architecture` → `summarize` →
`graph_data`.

Para **alterar código**:

1. `search` para achar a área — com **nome de símbolo ou palavra única**
   (`consolidacao`, `planejar`, `parecer`). Frase em português devolve
   vazio: apesar dos embeddings, a busca casa por token, não por
   sentido;
2. `file_summary` antes de pedir o arquivo inteiro (~200 tokens contra o
   arquivo todo). É a ferramenta com melhor relação custo-benefício aqui;
3. `neighbors` para ver de que aquele código depende e quem depende
   dele. Funciona bem: devolve o grafo de chamadas de verdade;
4. `path` quando precisar rastrear a ligação entre dois componentes;
5. só então abrir os arquivos que sobraram.

**Não confie no `impact` neste repositório.** Medido: `impact src/db.py`
devolve **1 dependente** quando 40 módulos importam `db`. O grafo tem 165
arestas `IMPORTS` para um projeto que usa import relativo em quase todo
arquivo (`from .. import db`) — o extrator não resolve essa forma. Para
saber quem depende de um módulo, `Grep` continua sendo a resposta certa;
`neighbors` ajuda no nível de função.

Abrir código direto continua certo quando o Cartographer indicou o
arquivo, quando a mudança é de uma linha, ou quando você já sabe onde é.
A regra existe para evitar a varredura às cegas, não para acrescentar
uma etapa a cada tarefa.

### Quando ignorar

O Cartographer é **camada auxiliar, nunca requisito**. Se ele estiver
indisponível, sem índice, com erro ou com o índice velho, trabalhe do
jeito normal — `Grep`, `Glob`, `Read`. Não pare a tarefa e não instale
nada no meio do caminho por causa disso; mencione uma vez e siga.

Sinal de índice velho: o grafo cita arquivo que não existe mais, ou não
conhece um que você acabou de criar. Conserto: `./scripts/cartographer_atualizar.sh`.

### Limites conhecidos (medidos neste repositório)

- A detecção de camadas acerta Testing, Documentation e Presentation, mas
  **subestima o domínio**: classificou "Business" com 3 entidades quando
  `govbot`, `precos`, `demanda` e `parecer_correcao` são o coração do
  sistema. Trate `architecture` como pista, não como laudo.
- `update-index` (incremental de um arquivo) está **quebrado na v0.1.0**
  — `KeyError: 'nodes'` em `graph/builder.py:238`. O script de
  atualização detecta e cai para reindexação completa, que leva ~1,5s.
- `impact` **subestima drasticamente**: 1 dependente para `src/db.py`,
  que 40 módulos importam. Import relativo não é resolvido.
- O modelo de embedding é `bge-small-**en**` — inglês. Este código é
  escrito em português, e consulta em linguagem natural devolve vazio.
  `search` funciona como busca por token, não por sentido.

### Manutenção do índice

```bash
./scripts/cartographer_atualizar.sh            # desde o último merge
./scripts/cartographer_atualizar.sh origin/main
./scripts/cartographer_atualizar.sh --completo
```

Rodar depois de merge ou de trocar de branch. **Nunca** no caminho de
uma requisição de usuário — indexação é trabalho de bancada.
