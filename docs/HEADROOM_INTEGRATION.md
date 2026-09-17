# Headroom — camada de otimização de contexto

**17/09/2026.** [Headroom](https://github.com/headroomlabs-ai/headroom)
(`headroom-ai` 0.37.0, Apache 2.0) integrado como **camada de
desenvolvimento**. Roda local, sem chave de API, sem serviço externo.

**Nota de procedência**: os metadados do PyPI ainda apontam para
`chopratejas/headroom`, a conta pessoal do autor antes da organização. O
repositório canônico é `headroomlabs-ai/headroom`, e a documentação real
mora em `headroom-docs.vercel.app`, com `docs.headroomlabs.ai`
redirecionando para lá.

---

## A medição que decidiu a arquitetura

Antes de ligar qualquer coisa, `scripts/headroom_bench.py` mediu o
Headroom sobre material **real** deste repositório. Reproduza com:

```bash
HEADROOM_BEACON=off DO_NOT_TRACK=1 .venv/bin/python scripts/headroom_bench.py
```

| Corpus | Classe | Antes | Depois | Economia | Literalidade |
|---|---|---:|---:|---:|---|
| Planilha de 210 itens (DFD/TR) | sem compressão | 16.994 | 10.002 | **41,1%** | **PERDEU 463 números e 185 códigos de item** |
| API compras.gov.br — contratações | recomendada | 4.030 | 3.224 | 20,0% | OK |
| API compras.gov.br — preços praticados | recomendada | 4.552 | 3.795 | 16,6% | OK |
| DFD extraído de PDF (2 layouts) | sem compressão | 2.237 | 2.237 | 0% | OK |
| Prosa normativa do gerador (PT-BR) | condicional | 7.214 | 7.214 | 0% | OK |
| Código-fonte Python | condicional | 14.343 | 14.343 | 0% | OK |
| SQL das migrações | condicional | 30.292 | 30.292 | 0% | OK |

Duas conclusões, e as duas são medidas, não opinião.

**1. No produto, o Headroom não tem o que fazer — e o que ele faria,
destruiria.** A prosa jurídica em português, o texto de DFD e o código
comprimem **0%**, exatamente como a documentação do próprio Headroom
avisa ("prose and already-dense output compress very little"). A única
coisa que ele de fato comprime no corpus do produto é a **planilha de
itens** — e ali ele apaga 463 números e 185 códigos, porque o
SmartCrusher resume JSON por estatística de variância, guardando bordas e
valores fora da faixa. Isso é o comportamento certo para log e o
comportamento errado para a tabela oficial de um edital, onde cada linha
é juridicamente exigível.

**2. No agente de desenvolvimento, ele rende sem perder nada.** JSON de
API real: 16–20%, sem uma perda de literalidade. É o caso de uso que o
projeto anuncia — saída de ferramenta repetitiva — e é o que esta sessão
consome o dia inteiro: GitHub, Supabase, pytest, Cartographer.

---

## O que está ligado

| Camada | Estado | Onde |
|---|---|---|
| **Headroom MCP** (agente de desenvolvimento) | **LIGADO** | `.mcp.json` |
| **SDK/wrapper no pipeline do produto** | **DESLIGADO** | não existe: `src/` não importa `headroom` |
| **Proxy HTTP** | desligado | não instalado |

`requirements.txt` **não** foi tocado. O Headroom é dependência de
desenvolvimento, instalada à mão:

```bash
.venv/bin/pip install "headroom-ai[mcp]"
```

Nada de `[all]`: arrastaria torch, transformers e datasets. O extra
`[mcp]` pede `mcp>=1.28.1,<2.0.0`, compatível com o `mcp<2` que o
Cartographer exige — conferido.

### Por que o produto ficou de fora

Além da medição acima, três razões de arquitetura:

- o pacote base puxa `litellm`, `tiktoken`, `ast-grep-cli`, `pydantic`,
  `opentelemetry-api`, `rich`, `click` e `tomlkit`. Isso entraria no
  deploy do Streamlit Cloud;
- o maior consumidor de contexto do produto é o `contexto_anterior` de
  `src/prompts.py:312` — o documento aprovado anterior, **inteiro**, na
  cadeia DFD → ETP → TR → Edital. É documento de licitação: cláusula,
  artigo, prazo e valor. Categoria "sem compressão";
- o caminho de RAG **já tem orçamento**: `MAX_CHUNKS_PROMPT = 10`
  (`rag.py:174`) e `trecho[:1_000]` (`govbot.py:828`). Dez trechos de mil
  caracteres, ~2.500 tokens. Não há o que espremer.

A ordem de prioridade declarada — precisão → segurança → qualidade →
redução de contexto → custo → velocidade — resolve o caso sozinha.

---

## As ferramentas, descobertas na versão instalada

Levantadas por handshake MCP real contra `headroom mcp serve`
(servidor `headroom` 1.30.0, protocolo `2024-11-05`), **não** copiadas da
documentação:

| Ferramenta | Parâmetros | O que faz |
|---|---|---|
| `headroom_compress` | `content*` (string) | Comprime e devolve texto, hash e economia |
| `headroom_retrieve` | `hash*` (string) | Devolve o original pelo hash |
| `headroom_stats` | — | Compressões, tokens salvos, eventos recentes |

A documentação menciona um filtro opcional em `headroom_retrieve` que a
versão instalada **não** expõe. É a razão de descobrir em vez de
hardcodar.

---

## Política de compressão

A decisão é do agente, não automática. A regra em uma linha: **comprima
saída de ferramenta; nunca comprima o que vira documento.**

### Comprimir à vontade

Saída de API em JSON, listagens, logs, resultado de busca, `git diff`
longo, saída de CI, resultado de consulta ao banco com muitas linhas
semelhantes, resultado do Cartographer.

### Não comprimir

Qualquer conteúdo que vá para dentro de um documento do processo — DFD,
ETP, TR, Mapa de Riscos, edital, contrato, ata, pesquisa de preços,
PNCP, propostas, planilhas, pareceres. E nunca a **planilha de itens**:
está medido acima o que acontece.

Preserve sempre, literalmente: números, valores, quantidades, unidades,
datas, nomes, referências legais, artigos, itens, subitens,
especificações, links, identificadores.

### Não vale a pena

Qualquer coisa abaixo de ~1.000 tokens, prosa em português, código já
denso. Medido: comprimem 0% e custam a chamada.

### Quando precisar do literal

`headroom_retrieve` com o hash. O original fica em cache local por 1h
(CCR). Se o hash expirou, leia o arquivo de novo — nunca reconstrua de
memória o que foi comprimido.

---

## Segurança

1. **Telemetria desligada na configuração versionada.** O beacon do
   Headroom é **ligado por padrão**; ele reporta ratios, IDs de modelo e
   arquitetura, e não manda prompt nem código — mas a regra desta casa é
   não mandar nada. `.mcp.json` fixa `HEADROOM_BEACON=off` e
   `DO_NOT_TRACK=1`. Não é sugestão: é a configuração.
2. **Nunca comprimir segredo.** `.env`, `secrets.toml`,
   `contas-auth*.json`, chave de API, JWT, `service_role`, senha, cookie,
   certificado privado. O CCR grava o **original em disco** por uma hora:
   mandar segredo para lá é criar uma segunda cópia fora do lugar onde
   ela deveria estar. O gancho `PreToolUse` já recusa a escrita nesses
   arquivos; a compressão é uma porta diferente, e essa é responsabilidade
   de quem chama.
3. **Roda local.** Sem chave de API, sem serviço externo, conteúdo não
   sai da máquina.

---

## Fallback — e ele é trivial de propósito

O Headroom **não pode** ser ponto único de falha, e nesta arquitetura não
tem como ser: ele é uma ferramenta MCP que o agente escolhe chamar.

| Situação | O que acontece |
|---|---|
| Não instalado | As ferramentas não aparecem. O agente lê o conteúdo como sempre leu |
| Servidor não sobe | Idem |
| `headroom_compress` falha | Use o conteúdo original, que você já tem em mãos |
| Hash expirado no `retrieve` | Releia a fonte |
| O produto | Nunca dependeu: `src/` não importa `headroom` |

Rollback completo: **apagar a entrada `headroom` do `.mcp.json`**. Uma
linha. Sem estado, sem migração, sem dado tocado.

---

## Observabilidade

`headroom_stats` na sessão; `headroom savings` e `headroom dashboard` no
terminal. `scripts/headroom_bench.py --json` produz a tabela acima em
formato de máquina, para comparar entre versões do Headroom.

O que **não** registrar: conteúdo comprimido em log, hash junto de dado
sensível, nada de prompt de usuário.

---

## Fronteira com as outras camadas

| Camada | Papel |
|---|---|
| Cartographer | Repository Intelligence — onde está o código |
| context7 | Documentation Intelligence — API atual das bibliotecas |
| **Headroom** | **Context Optimization — o que cabe no contexto** |
| Setup Advisor | Tool Intelligence — que ferramenta usar |

Headroom vem **depois** das outras: ele comprime o que elas produziram.
Nunca antes, nunca no lugar delas. Ele não substitui o RAG, não substitui
memória e não altera nada persistido.

---

## Testes

`tests/test_headroom_camada.py` guarda o que não pode mudar sem alguém
decidir:

- `src/` não importa `headroom` — a mesma prova de fronteira da camada de
  automação, pelo mesmo motivo;
- `requirements.txt` não ganhou a dependência;
- `.mcp.json` fixa a telemetria desligada;
- o bench funciona sem o Headroom instalado, e não quebra o CI.

O bench em si **não é portão de CI**: é bancada. Rode à mão quando
atualizar o Headroom, e olhe a coluna de literalidade antes da de
economia.

---

## Troubleshooting

| Sintoma | Causa provável |
|---|---|
| As ferramentas não aparecem | `headroom` fora do PATH da sessão. `headroom mcp status` |
| `Native content detection requires ONNX Runtime 1.24+` | Aviso, não erro. Cai para detecção em Python puro |
| Economia 0% e `router:protected:user_message` | O conteúdo foi passado como mensagem `user`. O Headroom protege o turno do usuário — saída de ferramenta vive em `tool`/`assistant` |
| Números somem de um JSON | Comportamento esperado do SmartCrusher em JSON tabular. **Não comprima planilha** |

---

## Se um dia o produto entrar

O que mudaria a conclusão: uma medição mostrando economia relevante em
prosa PT-BR **sem uma única perda** na coluna de literalidade. Hoje ela
mostra 0% de economia e uma perda catastrófica no único corpus que
comprime.

Se isso mudar, o caminho é curto e já está mapeado: o produto tem
**exatamente duas** chamadas de rede — `src/llm.py:347` (OpenAI) e
`src/llm.py:495` (Gemini) — com `tokens_entrada`/`tokens_saida` já
registrados. Um wrapper com flag `HEADROOM_ENABLED`, desligado em
produção, entra ali em meia hora.

O que **não** muda: a planilha de itens não passa por compressão. Nunca.
