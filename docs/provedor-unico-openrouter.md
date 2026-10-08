# OpenRouter como provedor único — o que é possível, o que não é, e por quê

*08/10/2026 · branch `claude/reducao-custo-geracao` · produção não alterada*

---

## Resumo em cinco linhas

Dá para gerar **todo o texto** pelo OpenRouter: DFD, ETP, Mapa de
Riscos, TR, auditoria, correção, GovBot, parecer, pesquisa de preços.

**Não dá** para o índice vetorial da Base de Conhecimento. Ele exige
embeddings, e o OpenRouter não serve embedding nenhum — dos 467 modelos
do catálogo em 08/10/2026, nenhum devolve vetor. A chave da OpenAI
continua necessária só para isso, e custa **4 centavos de dólar uma
vez** mais **2 centavos a cada mil processos**.

---

## 1. O que o sistema está fazendo AGORA (medido em produção)

Antes de propor mudança, o estado real. Consulta a `config_app` em
08/10/2026 — só os nomes das chaves e se estão preenchidas, nunca os
valores:

| Configuração | Estado |
|---|---|
| `OPENROUTER_API_KEY` | **configurada** |
| `OPENROUTER_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| `GOOGLE_API_KEY` | **configurada** |
| `OPENAI_API_KEY` | **vazia** |
| `IA_PROVEDOR` | não existia |

### Dois achados que isso revela

**1. A geração NÃO está indo para o OpenRouter.** A cascata é OpenAI →
Gemini → OpenRouter, filtrada por quem tem chave. Com a OpenAI vazia e
o Gemini configurado, **quem gera hoje é o Gemini**. O OpenRouter está
configurado e nunca é alcançado: ele só entraria se o Gemini falhasse.

**2. A Base de Conhecimento está em modo TEXTUAL desde 30/09.** O
índice vetorial usa `text-embedding-3-small` da OpenAI, lido de
`OPENAI_API_KEY`. Quando aquela chave foi limpa — na correção de chaves
de 30/09 — os embeddings pararam. As oito gerações com rastro de RAG em
produção registram `modo = vetorial`; a próxima registraria `textual`.

A busca textual funciona e é o fallback projetado, mas recupera pior. E
o que ela recupera é o **lastro das citações**: é o trecho recuperado
que autoriza o documento a citar um dispositivo. Precisão é a primeira
prioridade declarada deste sistema, então isto não é detalhe de
infraestrutura.

---

## 2. Por que os embeddings não vão para o OpenRouter

Duas razões independentes, e cada uma bastaria.

**O OpenRouter não tem o que oferecer.** Catálogo consultado em
08/10/2026: 467 modelos, nenhum com embedding no identificador ou no
nome, e as modalidades de saída existentes são apenas `text`, `audio` e
`image`. A rota `/api/v1/embeddings` responde 401 em vez de 404, mas não
há modelo para chamar nela, e a página de documentação de embeddings
responde 404.

**Trocar o modelo de embedding invalidaria a base.** Vetores de modelos
diferentes não são comparáveis entre si. Mudar o provedor significa
reindexar os **5.595 chunks** e, até terminar, a busca compararia
vetores incomparáveis — devolvendo referências erradas com aparência de
certas. O código já recusa isso por construção
(`EMBEDDING_V2_PROVEDOR`), e a recusa é anterior a este trabalho.

### Quanto custa manter essa única ponta na OpenAI

Medido, não estimado:

| Item | Tokens | Custo (USD 0,02/Mtok) |
|---|---:|---:|
| Consultas de embedding de **um processo** (4 documentos, 18 consultas) | 1.201 | **0,000024** |
| Mil processos | 1.201.000 | **0,024** |
| Reindexar a base inteira (5.595 chunks, 7,43M caracteres) | ~2.210.000 | **0,044** |

A contagem de tokens das consultas é medida com o tokenizador real
sobre as consultas que o código de fato monta. A da reindexação aplica a
razão medida de 3,36 caracteres por token em texto jurídico em
português. O preço de `text-embedding-3-small` é o publicado pela
OpenAI em 08/10/2026.

**Na prática:** USD 5 de crédito na OpenAI cobre a reindexação da base e
mais de duzentos mil processos. É uma recarga, uma vez, e você não volta
àquele site.

Se preferir não manter conta nenhuma lá, a alternativa existe e tem
preço: deixar a busca em modo textual permanentemente. Aí a conta fica
em um provedor só, e o lastro das citações fica menos preciso. **Essa é
sua decisão, não minha** — eu deixei as duas possíveis e o aviso na
tela diz em qual modo o sistema está.

---

## 3. O que foi alterado

### 3.1 `IA_PROVEDOR` — escolher o provedor, em vez de deduzi-lo

A cascata responde *"quem está configurado?"*. Ela não responde *"quem
eu escolhi?"* — e as duas perguntas deixaram de ter a mesma resposta no
instante em que a chave da OpenAI passou a ser necessária apenas para a
busca. Sem a escolha explícita, manter aquela chave trazia a geração de
volta para a OpenAI por efeito colateral.

Agora, no painel do administrador → Chaves de IA, há um seletor:

- **Cascata automática** (padrão, comportamento de sempre): OpenAI →
  Gemini → OpenRouter, filtrada por quem tem chave;
- **Só OpenRouter** (ou só OpenAI, ou só Gemini): a geração usa SÓ
  aquele provedor, **mesmo havendo chave dos outros**.

**A contrapartida, dita na cara:** provedor único **não tem queda para
outro provedor**. A resiliência passa a ser a lista de modelos dele — a
do OpenRouter tem quatro — e um provedor inteiro fora do ar deixa de
ter plano B. Quem preferir o plano B deixa o seletor na cascata.

### 3.2 `OPENAI_EMBEDDINGS_KEY` — a chave da busca ganhou nome próprio

Enquanto a chave do índice se chamava `OPENAI_API_KEY`, "manter a busca
funcionando" e "manter a OpenAI gerando documento" eram a mesma
decisão. Agora são duas:

- `OPENAI_EMBEDDINGS_KEY` serve **só** ao índice vetorial;
- `OPENAI_API_KEY` continua valendo como fonte do índice, atrás da
  nova, para que nenhuma instalação pare de indexar por causa desta
  mudança.

O painel ganhou uma seção própria para ela, que diz em qual modo a
busca está e por que ela não pode ir para o OpenRouter.

### 3.3 O painel passou a conhecer o OpenRouter

Ele rodava em produção **sem um único campo no painel**: nem chave, nem
modelo, nem botão de teste. E o rótulo de motor ativo só sabia dizer
"OpenAI (principal)" ou "Gemini (fallback)", de modo que o OpenRouter,
quando ativo, aparecia na tela como **"Gemini (fallback)"** — o painel
mentia sobre quem estava gerando.

Agora há campo de chave, campo de modelo, botão de teste para os três
provedores, e o rótulo diz a verdade: provedor único ou a cascata real,
com os nomes na ordem.

### 3.4 Dois defeitos que a migração expôs

**A política de modelo nunca se aplicaria ao OpenRouter.**
`politica_ia.modelos_para` recusava tudo que não fosse OpenAI
(`motor != "openai"`). Era aceitável enquanto o OpenRouter era o
terceiro da fila e a redação corria na OpenAI; virou defeito silencioso
no instante em que ele passou a ser o provedor único — a política ficava
ligada e sem efeito, e ninguém era avisado. Agora cada provedor tem sua
configuração de modelo econômico (`OPENROUTER_MODEL_ECONOMICO`,
`OPENAI_MODEL_ECONOMICO`, `GEMINI_MODEL_ECONOMICO`), porque o
identificador de um não existe no outro.

**A Nemotron não era reconhecida como modelo de raciocínio.** A detecção
casava por PREFIXO (`gpt-5`, `o1`, `o3`, `o4`), e os identificadores do
OpenRouter vêm com o fornecedor na frente —
`nvidia/nemotron-3-ultra-550b-a55b:free` nunca casaria. Consequência:
ela receberia o teto de saída sem a folga de raciocínio, gastaria o
orçamento pensando e devolveria **conteúdo vazio**. Havia ainda duas
listas de prefixos, uma em `llm` e outra em `politica_ia`; agora há uma
fonte só, e ela reconhece as duas formas de identificador. O
`reasoning_effort: low` passou a acompanhar os pedidos à Nemotron —
parâmetro que o OpenRouter documenta com a mesma semântica da OpenAI e
que os dois modelos Nemotron listam em `supported_parameters`.

---

## 4. Qual modelo usar no OpenRouter

Aqui eu preciso ser direto sobre um risco da configuração atual.

`OPENROUTER_MODEL` está em `nvidia/nemotron-3-ultra-550b-a55b:free`. O
sufixo `:free` é o endpoint gratuito, com teto de requisições, e **nunca
foi exercitado com um modelo real neste sistema** — as 168 gerações de
produção todas correram em `gpt-5-mini`. A prioridade declarada do
projeto é PRECISÃO antes de CUSTO, e um Termo de Referência é ato
administrativo.

**O ponto que resolve isso:** `openai/gpt-5-mini` está disponível pelo
OpenRouter. É possível consolidar a fatura **sem trocar de modelo** —
mesmo modelo, mesma qualidade já validada em produção, uma conta só.

Preços do catálogo do OpenRouter em 08/10/2026, por milhão de tokens:

| Modelo | Entrada | Saída | Observação |
|---|---:|---:|---|
| `openai/gpt-5-mini` | 0,25 | 2,00 | **o que a produção já usava** |
| `anthropic/claude-haiku-5.5` | 0,10 | 0,50 | mais barato que o atual |
| `google/gemini-2.5-flash` | 0,30 | 2,50 | o que está gerando hoje |
| `openai/gpt-5` | 1,25 | 10,00 | para revisão crítica |
| `nvidia/nemotron-3-ultra:free` | 0 | 0 | gratuito, com teto de requisições |

Com os números medidos depois da otimização — ~41.000 tokens de entrada
e ~24.000 de saída por processo de quatro documentos — em
`openai/gpt-5-mini` pelo OpenRouter dá cerca de **USD 0,06 por
processo**. O ciclo de auditoria e correção é que pesa: o processo mais
corrigido da produção somou 1,95M de entrada e 251k de saída, o que dá
cerca de **USD 1,00**.

Minha recomendação, e a razão dela:

1. **`OPENROUTER_MODEL = openai/gpt-5-mini`** para a redação. É o
   modelo que as 168 gerações validaram; trocar de modelo e de provedor
   ao mesmo tempo misturaria duas variáveis num documento que vira ato
   administrativo.
2. **`OPENROUTER_MODEL_ECONOMICO = anthropic/claude-haiku-5.5`** (ou um
   `:free`) para auditoria e correção, com a flag
   `politica_de_modelo` ligada. São 65 das 90 chamadas de produção, a
   saída é JSON de forma fixa, e é aí que o custo está.
3. **Deixar os `:free` na lista de fallback**, onde já estão: eles
   entram quando o pago falha, que é o lugar certo para um modelo com
   teto de requisições.

---

## 5. Como migrar (nenhum destes passos foi executado)

Nada em produção foi alterado por este trabalho. A sequência abaixo é
para você executar, ou me pedir que execute.

**1. Preservar a busca antes de qualquer outra coisa.** No painel →
Chaves de IA → Índice vetorial: informe a chave da OpenAI em
`OPENAI_EMBEDDINGS_KEY`. Hoje `OPENAI_API_KEY` está vazia, então a
busca está em modo textual — esta é a única parte da migração que
*melhora* algo que está quebrado agora.

**2. Escolher o modelo do OpenRouter.** `OPENROUTER_MODEL` =
`openai/gpt-5-mini`, pela razão da seção 4.

**3. Declarar o provedor.** Seletor "Provedor de geração de texto" →
**Só OpenRouter**. É este passo que tira o Gemini da frente.

**4. Testar antes de gerar documento.** Botão "Testar OpenRouter". Ele
faz uma chamada mínima e mostra o erro técnico exato — chave, modelo ou
cota.

**5. Gerar UM processo e conferir o registro.** A tabela `geracoes`
passa a dizer motor, modelo, tokens, custo e operação. Conferir que
`motor = openrouter`, que `rag_trace->>'modo' = vetorial` (prova de que
o passo 1 funcionou) e que o documento saiu completo.

**6. Só então limpar `GOOGLE_API_KEY` e `OPENAI_API_KEY`**, se quiser.
Com `IA_PROVEDOR = openrouter` elas já não participam da geração, então
limpá-las é arrumação, não requisito. A chave de embeddings
(`OPENAI_EMBEDDINGS_KEY`) **fica**.

**Rollback de tudo:** seletor de volta para "Cascata automática".
Nenhuma migração de banco, nenhuma reindexação, nenhuma perda.

---

## 6. Testes

| Suíte | Resultado |
|---|---|
| **Suíte completa do projeto** | **2.759 passaram, 133 puladas, 0 falhas** (6m46s, com o banco de ensaio ligado) |
| `tests/test_provedor_unico.py` (nova, 23 provas) | escolha respeitada e exclusiva; nome inválido cai na cascata; mensagem nomeia o provedor sem chave; chave de embeddings separada, com precedência e compatibilidade; índice lê a chave certa; degradação textual avisa; Nemotron reconhecida como raciocínio; detecção com fonte única; painel cobre os três provedores |
| `tests/test_llm.py` + `test_custo_de_geracao.py` | passam sem alteração de comportamento no padrão |

### O scanner de segredos barrou a primeira entrega

`docs/custo/producao.json` nomeava o projeto de produção ao explicar de
onde a telemetria vinha. A referência identifica a instância real e está
na lista de padrões que bloqueiam publicação — regra escrita na
auditoria anterior, aplicada agora contra o meu próprio texto.

Deixei passar porque não conferi o CI nos pushes anteriores da branch.
A procedência do dado não se perdeu: a frase continua dizendo que a
telemetria vem da tabela `public.geracoes` do projeto de produção, com
a data da colheita e a janela dos registros. O que saiu foi só o
identificador.

### Um defeito que a suíte pegou durante a implementação

Três provas de segurança — as que impedem a chave de aparecer na tela
quando a indexação falha — dublavam `llm.obter_openai_key` para
fornecer a chave do índice. Ao separar a chave de embeddings, elas
passaram a dublar uma função que o RAG já não chamava, e quebraram.

A correção não foi mexer nas provas: foi fazer a compatibilidade da
chave nova passar por `obter_openai_key()` em vez de ler
`OPENAI_API_KEY` uma segunda vez. Duas leituras da mesma chave
divergiriam na primeira vez que alguém mexesse em uma só — e a segunda
leitura esquecia a barra lateral, que a função já cobria.

Três provas antigas de `test_custo_de_geracao.py` foram reescritas: elas
dublavam `modelo_economico_configurado` sem argumento, e a função passou
a receber o provedor. A regra que elas guardavam — "o identificador de
um provedor não vaza para outro" — continua guardada, agora com uma
prova a mais para o OpenRouter.
