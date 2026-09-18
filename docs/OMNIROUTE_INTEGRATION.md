# OmniRoute — AI Gateway e roteamento de modelos

**18/09/2026.** O que foi construído, o que ficou de fora, e por quê.

**Estado: a camada existe, o OmniRoute não está instalado.** O
`AIProviderGateway` e a política de roteamento estão no código e valem
sozinhos; o gateway entra por `base_url` no dia em que houver onde
hospedá-lo.

---

## O que foi construído

```
Aplicação  →  src/ai_gateway.py  →  src/roteamento.py (política)
                      ↓
       [hoje]   provider direto: OpenAI · Gemini · OpenRouter
       [depois] gateway compatível com a API da OpenAI, por base_url
```

| Arquivo | Papel |
|---|---|
| `src/roteamento.py` | A política. Tabela e função pura: tipo de tarefa, grupos de modelo, quem é crítico. Sem rede, sem sessão, sem provider |
| `src/ai_gateway.py` | A única parte do sistema que sabe que um gateway existe |
| `src/llm.py` | Duas linhas: `base_url` no cliente OpenAI e o filtro de política na cascata |

Trocar provider direto por gateway é mexer em `ai_gateway.py`, e em
nenhum outro lugar.

---

## O buraco que isto fecha

A cascata de `llm.py` é irrestrita. Se a OpenAI cair no meio da geração
de um edital, a requisição desce para o motor seguinte — hoje
`gemini-2.5-flash`, e depois `gemini-1.5-flash` — **sem que ninguém
tenha homologado esses modelos para documento que vira ato
administrativo**. O edital sai, o servidor assina, e a única pista é uma
linha de registro técnico.

Com `OMNIROUTE_ROUTING_ENABLED=true`, a tarefa `edital` só pode usar
motor do grupo `PROCUREMENT_HIGH_ACCURACY`. Se a lista acabar, **falha**
— e falhar é a resposta certa: um edital gerado por modelo não
homologado é pior que um edital não gerado, porque o primeiro é assinado.

---

## Grupos e política

| `task.type` | Grupo | Motores homologados |
|---|---|---|
| `document_generation` (DFD, ETP, TR, Mapa de Riscos, edital, ARP) | `PROCUREMENT_HIGH_ACCURACY` | `openai` |
| `legal_analysis` (parecer, corretor, auditor, revisão) | `HIGH_ACCURACY` | `openai` |
| `price_research` | `HIGH_ACCURACY` | `openai` |
| `rag_answer` (GovBot) | `HIGH_ACCURACY` | `openai` |
| `classification` | `FAST` | `openai`, `gemini` |
| `background` / rótulo desconhecido | `CHEAP` | `openai`, `gemini`, `openrouter` |

Só a OpenAI é homologada para documento oficial hoje — e isso é uma
**afirmação de homologação**, não preferência técnica: é o motor com que
a suíte de documentos foi construída e conferida. Gemini e OpenRouter
entram quando passarem no conjunto de avaliação, e a entrada é decisão do
operador registrada em commit.

Rótulo desconhecido cai em `background`, o grupo mais permissivo.
Estreitar por acidente quebraria funcionalidade; a restrição só vale onde
alguém a declarou. A proteção contra esquecimento é
`test_todo_documento_oficial_e_tarefa_critica`: se um documento entrar em
`config.DOCUMENTOS` e não na política, a suíte cai.

---

## Variáveis

Todas nascem **desligadas**, e são lidas do **ambiente** — nunca de
`config_app`.

| Variável | Padrão | O que faz |
|---|---|---|
| `OMNIROUTE_ENABLED` | desligada | Manda os motores compatíveis pelo gateway |
| `OMNIROUTE_BASE_URL` | vazia | Endereço do `/v1`. Sem ela, `ENABLED` não liga nada |
| `OMNIROUTE_ROUTING_ENABLED` | desligada | Aplica a política de grupos na cascata |

`config_app` é editável pelo painel do administrador. Uma política de
roteamento que um usuário autenticado muda pela tela não é política — é
sugestão. `test_as_chaves_vem_do_ambiente_e_nao_do_banco` guarda isso.

**Nenhuma chave de API passa por aqui.** Elas continuam em
`config_app`/`secrets.toml`, como sempre.

---

## Por que o OmniRoute não foi instalado

O projeto é real: `omniroute` 3.8.50 no npm, MIT, 289 versões,
`diegosouzapw/OmniRoute`. Três fatos medidos decidiram.

**Peso.** 77 dependências diretas, **~442 MB descompactados**, incluindo
Next.js 16 e React 19 (o dashboard), express, sharp, ioredis, sql.js.
`engines: node >=22.22.2 <23 || >=24 <27`.

**Onde rodaria.** O deploy é Streamlit Cloud: instala `requirements.txt`
(Python) e `packages.txt` — que tem uma linha, `libreoffice`. Não há
runtime Node, gerenciador de processo nem sidecar. Usar OmniRoute em
produção exigiria hospedá-lo fora e apontar `base_url` para lá:
infraestrutura nova, um salto de rede na frente de **toda** geração de
documento, e um ponto único de falha novo para a função central — num
projeto que hoje não opera servidor nenhum.

**O default.** A manchete é "~1.51B Free Tokens / Month" e "352
providers, 154 catalog-marked free". Ele funciona sem chave porque vem
pré-ligado a providers **gratuitos keyless** (OpenCode Free, Felo) no
combo `auto`, e a cascata é Subscription → API Key → Cheap → **Free**.

Isso colide com a regra deste projeto: provider gratuito não recebe
documento administrativo. Dá para configurar contra — mas configuração
que luta contra o default do produto volta ao default no primeiro upgrade
desatento.

### E o que o app já tinha

Boa parte do que o OmniRoute vende: cascata de três motores, lista de
fallback de modelo por motor, retentativa com backoff (`llm.py:342`),
timeout (`API_TIMEOUT_SEGUNDOS`), contabilidade de tokens e tradução de
erro por causa (429, timeout, cota, modelo inválido). O que faltava era
**noção de tarefa** — e é isso que esta entrega acrescenta, sem
dependência nova.

---

## O que NUNCA passa por roteamento

**Embeddings.** `src/rag.py:334` diz que o índice v2 "NÃO admite outro
provedor": os vetores foram construídos com `text-embedding-3-small`. Um
roteador que escolhesse outro provedor corromperia a busca **em
silêncio** — os resultados continuariam saindo, só que errados.
`ai_gateway` não toca no caminho de embeddings, e não deve passar a
tocar.

**O Gemini.** Tem SDK próprio e não atravessa `base_url`. Mandar o
endereço do gateway para ele não faria nada de errado — faria **nada**,
que é pior: a requisição pareceria roteada e não estaria, e a telemetria
mentiria. `test_o_gemini_nunca_recebe_base_url` guarda.

---

## Se for instalar (desenvolvimento)

```bash
node -v                        # precisa de >=22.22.2 <23 ou >=24 <27
npm install -g omniroute
omniroute                      # http://localhost:20128
.venv/bin/python scripts/omniroute_ensaio.py
```

O ensaio confere o que a integração não pode supor: o processo responde,
`/v1/models` existe, quais **aliases esta instalação realmente tem**, e a
saúde reportada. Ele descobre os prefixos em vez de acreditar em
documentação — 289 versões em sete meses é ritmo suficiente para um
alias mudar de nome entre uma leitura e um deploy.

Sem nada escutando, ele diz isso e sai com 0. É bancada, não portão.

Depois, para ligar em desenvolvimento:

```bash
export OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1
export OMNIROUTE_ENABLED=true
```

---

## Shadow, canário, produção

**Shadow.** Fora do produto, como no Headroom: rodar o mesmo prompt pelos
dois caminhos e comparar. O critério de aprovação não é "a resposta ficou
parecida" — é o mesmo do bench do Headroom: número, valor, quantidade,
data, artigo, item, especificação e identificador **idênticos**. Um
modelo não entra na rota crítica sem isso.

**Canário.** `OMNIROUTE_ENABLED` ligada só no ambiente de
desenvolvimento. Nunca por usuário, porque não há segmentação de usuário
no app.

**Produção.** Só depois de um conjunto de avaliação com casos reais e da
decisão de onde hospedar o gateway.

---

## Rollback

```bash
unset OMNIROUTE_ENABLED        # ou OMNIROUTE_ENABLED=false
```

Volta ao provider direto. Uma variável, sem deploy e sem migração.
Nenhuma funcionalidade essencial depende do gateway: com tudo desligado —
o padrão — o comportamento é **idêntico** ao de antes, e isso é medido
por `test_com_tudo_desligado_nada_muda`.

---

## Observabilidade

`ai_gateway.telemetria(rotulo, motor)` devolve `task_type`,
`routing_policy`, `critica`, `provider` e `gateway` — **sem conteúdo**.
Nada de prompt, resposta ou chave; há prova disso.

`registrar_geracao` em `llm.py` já grava motor, duração, status e
fallback por tarefa. Com o tipo de tarefa agora nomeado, dá para
responder "quanto custou gerar edital neste mês" — o que antes exigia
adivinhar pelo rótulo.

---

## Fronteira com as outras camadas

| Camada | Papel |
|---|---|
| Cartographer | Repository Intelligence |
| context7 | Documentation Intelligence |
| Claude Code Setup | Automation Intelligence |
| Headroom | Context Optimization |
| **OmniRoute / `ai_gateway`** | **Model Routing / AI Gateway** |
| RAG | Knowledge Retrieval |
| Supabase | Dados, autenticação, autorização |

Nenhuma assume o papel da outra. O OmniRoute **não** substitui
Cartographer nem Context7, e o `ai_gateway` **não** decide o que entra no
prompt — isso é RAG e Headroom, antes dele.

### Dupla compressão

O OmniRoute tem compressão própria (RTK + Caveman, 15–95%). O Headroom
também. **Não empilhe as duas sem medir**: seria compressão sobre
conteúdo já comprimido, e o bench do Headroom já mostrou o que compressão
agressiva faz com a planilha de itens — 41% de economia ao preço de 463
números e 185 códigos. Se o OmniRoute entrar, a comparação A/B/C/D é
pré-requisito, não formalidade.

---

## Troubleshooting

| Sintoma | Causa provável |
|---|---|
| `OMNIROUTE_ENABLED=true` e nada muda | Falta `OMNIROUTE_BASE_URL`. "Ligado" sem endereço não liga nada, de propósito |
| Gemini não passa pelo gateway | Correto. SDK próprio, não atravessa `base_url` |
| Documento falha com "nenhum motor" | Roteamento ligado e chave do motor homologado ausente. A política devolve a lista original em vez de vazia — se falhou, é outra coisa |
| Ensaio diz "sem resposta" | Nada escutando em 20128. `omniroute` para subir |
