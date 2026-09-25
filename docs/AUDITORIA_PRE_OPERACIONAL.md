# GovConnect — Auditoria pré-operacional e bateria sem custo de LLM

**Data:** 22 a 24 de setembro de 2026
**Branch:** `claude/auditoria-pre-operacional`
**Critério central da rodada:** `chamadas reais às APIs de LLMs = 0`

---

## A. Ambiente e execução

### A.1 O que foi testado

| | |
|---|---|
| Repositório | `ewertonmarinho51-dev/projeto-saas` |
| Branch de trabalho | `claude/auditoria-pre-operacional` |
| Base | `main` em `8d1d954` |
| Commits desta auditoria | `916923a`, `98ee6de`, `57de426`, `09ec5eb`, `08dffde`, `52e51ca`, `20f915a`, `cad4fe8`, `e814529` |

### A.2 Os ambientes que existem, e o que cada um é

| Ambiente | URL | Banco | Tipo |
|---|---|---|---|
| VPS Hostinger | `https://govconect.com` | Supabase `nxib…` | **PRODUÇÃO** |
| Streamlit Cloud | (instalação de conferência) | Supabase `nxib…` — **o mesmo** | **PRODUÇÃO, com outra URL** |
| Homologação desta auditoria | `http://127.0.0.1:8502` | PostgreSQL local | **isolado** |

O §2.4 manda preparar ambiente isolado **ou apresentar o bloqueio**. O
bloqueio foi apresentado: **não existia ambiente de homologação**. As
duas instalações publicadas escrevem no banco de produção, e o
Streamlit Cloud, apesar do nome de "teste", é um segundo acesso a
produção — decisão registrada do operador em 19/09/2026.

Nenhum processo fictício foi criado em produção. Nenhuma migração foi
aplicada em produção. As únicas operações em produção nesta auditoria
foram **leituras** (`SELECT`) para medir o estado: contagem de
processos, de usuários, de identidades, as 37 flags de `config_app` e a
tabela `geracoes`.

### A.3 A homologação isolada, montada do zero

```
PostgreSQL local (socket unix, cluster descartável)
    ↑  25 migrações do repositório · 43 tabelas · 42 com RLS · 82 políticas
PostgREST 12.2.3          ← o MESMO servidor que o Supabase põe na frente
adaptador /rest/v1        ← tira o prefixo que o supabase-py acrescenta
Streamlit                 ← com o bloqueio de custo instalado na subida
```

Reprodutível por `scripts/homologacao_stack.py`. O `db.py` atravessa
essa pilha sem saber a diferença.

**Nenhuma credencial real entra neste caminho.** O segredo de JWT é
sorteado a cada subida e morre com ela; as chaves `anon` e
`service_role` são cunhadas contra ele. Não há chave de produção, de
projeto Supabase hospedado nem de provedor de LLM em ponto algum.

A homologação **espelha as 37 flags de produção** (lidas em 24/09/2026,
todas em `1`). Sem isso a bateria testaria um sistema que ninguém usa —
sem Mapa de Riscos no fluxo, sem GovBot, sem editor rico, sem
consolidação de demandas.

### A.4 Forma de acesso ao navegador

Chromium + Playwright, contra o Streamlit local. Roteiro em
`scripts/navegacao_auditoria.py`; medição de larguras em
`scripts/responsividade_auditoria.py`. Cada passo grava captura de tela
e o texto da página em `/tmp/auditoria/`, e **confere** o que viu — um
roteiro que só clica e fotografa não distingue "funcionou" de "abriu".

O projeto tem provas de interface com `streamlit.testing`, e elas
continuam valendo. Não substituem a navegação: rodam o script do app no
processo do pytest e não enxergam rerun que perde estado, componente que
não monta, recarregar a página nem reabrir um processo depois de fechar
a aba. **Foi exatamente aí que três achados apareceram.**

### A.5 Bloqueio das APIs pagas e configuração dos mocks

Duas peças, e a **ordem entre elas é o desenho**:

1. `scripts/sem_llm.py` — barra e **conta** toda requisição a host de
   LLM pago. Intercepta no transporte HTTP (`httpx` síncrono e
   assíncrono, `requests`) **e** no DNS, como segunda camada.
2. `scripts/bloqueio_de_custo/ia_simulada.py` — responde às conversas
   com fixture, **por fora** do bloqueio, de modo que uma chamada
   simulada nunca conta como tentativa de gasto.

O guarda entra por `sitecustomize` no `PYTHONPATH`, **antes de qualquer
import do app** — dentro do `app.py` chegaria tarde para quem já tivesse
guardado a referência do transporte. E a pilha **confere** que ele entrou,
num processo filho com o mesmo ambiente, antes de subir o Streamlit:
com `GOVDOCS_BLOQUEAR_LLM=0` a subida é **recusada**, medido.

> **Por que a fixture responde no transporte, e não em
> `llm._chamar_openai`.** Um dublê naquela função provaria que aquela
> função foi desviada. No transporte, rodam de verdade a montagem do
> prompt, o bloco do RAG, o cliente real da OpenAI, a leitura de
> `choices[0].message.content`, o `finish_reason` vazio, a troca de
> modelo, a queda entre motores e a injeção da tabela. O que se troca é
> só o texto que a rede traria.

### A.6 Chamadas reais de LLM detectadas

**Zero.**

Não é afirmação: é contagem. `sem_llm.tentativas()` é asserido em toda
prova da bateria, e o livro em `/tmp/govdocs_sem_llm.jsonl` registra
cada tentativa barrada com host, porta e **caminho** — sem a query
string, porque o Gemini manda a chave em `?key=…` e este livro vira
anexo de relatório.

Durante a bateria houve **tentativas barradas**, e elas são o achado de
custo da seção E: `/v1/embeddings`, uma por documento gerado.

### A.7 Limitações e etapas não executadas

| Limitação | Consequência |
|---|---|
| **Não há GoTrue** na homologação local. `/auth/v1` responde 501 de propósito; o login percorre o caminho legado da tabela `usuarios`. | **65 provas de isolamento por conta de usuário não foram executadas.** O isolamento está provado no SQL (157 provas contra PostgreSQL real, injetando `request.jwt.claims` como o PostgREST faz). O que segue sem prova é a **emissão** do JWT e a gravação de `app_metadata`. |
| A credencial entra pelo slot **legado** (`SUPABASE_SERVICE_KEY`), porque o atual exige o formato `sb_secret_…`, que só o Supabase emite. | A homologação roda com o aviso de descontinuação ligado — como rodaria uma instalação que ainda não trocou a chave. |
| **Verificação normativa em fonte oficial não pôde ser concluída.** `planalto.gov.br` devolveu HTTP 503 nas tentativas de 24/09/2026. | A seção D **não cita redação de artigo nem entendimento de tribunal de contas**. Os critérios ali são documentais e comportamentais. Números de dispositivo aparecem só onde já estão no mapa curado do próprio projeto, e **não foram reconferidos** nesta rodada. |
| A qualidade **redacional** dos documentos não foi avaliada. | Depende de modelo real. Vai ao portão (§21) como pendente. |
| §7, §9, §10 e §12 foram cobertos pelas **suítes existentes**, executadas e verdes — não por bateria de navegador própria. | Registrado como tal na seção C.4, sem alegação de cobertura que não houve. |

---

## B. Inventário dos testes

As massas estão em `tests/massas_auditoria.py`. Municípios inventados,
responsáveis por **função** e não por nome, preços plausíveis que **não
são cotação de contratação nenhuma**. Nenhum dado pessoal real, nenhum
cadastro de produção.

| Id | Objeto | Itens | Modelo de execução | Critério objetivo | Resultado |
|---|---|---|---|---|---|
| **A** | Materiais de expediente | 20 | Entrega parcelada | Os 20 códigos atravessam; valor global bate com a soma | ✅ |
| **B** | Equipamentos de informática | 3 | Entrega única | Garantia e especificação chegam ao TR; quantidade não muda | ✅ |
| **C** | Limpeza e conservação | 2 | Serviço continuado | Unidade `POSTO/MÊS` não convertida nem arredondada | ✅ |
| **D** | Assessoria contábil | 2 | Serviço por escopo | Estrutura se adapta a serviço | ✅ |
| **E** | Material médico-hospitalar | 4 | **SRP** | Edital traz a Ata; ARP só no SRP | ✅ |
| **F** | Uma motocicleta | 1 | Entrega única | Nada inventado para "encher" o documento | ✅ |
| **G** | Materiais de expediente | **210** | Entrega parcelada | Os 210 códigos inteiros no DOCX **e** no PDF | ✅ |
| **H** | Objeto vago, sem preço | 1 | Entrega única | Pendência apontada, nunca fato inventado | ✅ |

**Etapas percorridas** (cenário A, no navegador, ponta a ponta):
Login → Painel → Novo processo → Dados da demanda (planilha importada de
`.xlsx`) → DFD → ETP → **Mapa de Riscos** → TR → Minuta de Edital →
Exportação → Salvamento → **Recarregar a página** → Reabertura → volta à
primeira etapa.

**Documentos obtidos:** os cinco do fluxo, gerados e aprovados em
sequência, com a tela final oferecendo DOCX e PDF.

**Evidências:** `/tmp/auditoria/` — capturas, texto de cada tela,
`veredito_A.json`, `responsividade.json`, `custo.json`.

---

## C. Achados técnicos e funcionais

### C.1 P0 — Os processos atravessavam prefeituras

| | |
|---|---|
| **Gravidade** | P0 — exposição e **perda** de dados entre municípios |
| **Componentes** | `src/db.py` (`listar_processos`, `carregar_processo`, `salvar_processo`, `renomear_processo`, `excluir_processo`), `src/ui/processos_ui.py` |
| **Situação** | **Confirmado** e **corrigido** |

**Reprodução.** Duas prefeituras no banco; sessão vinculada à segunda;
abrir a aba Processos como administrador.

**Esperado.** Ver apenas os processos do próprio município.

**Observado.** `processos_ui` escolhe o filtro assim:

```python
# Administrador vê os processos do município; servidor vê os seus.
filtro = None if auth.eh_admin() else (usuario or {}).get("id")
lista = db.listar_processos(usuario_id=filtro)
```

O comentário diz "do município". O código passa `None`, e
`listar_processos` sem `usuario_id` **não filtrava nada** — devolvia os
50 processos mais recentes de **todas** as prefeituras: objeto,
justificativa, valores, documentos gerados. E entregava os **ids**. Com
um id:

| Função | O que fazia com processo de outra prefeitura |
|---|---|
| `carregar_processo` | abria |
| `renomear_processo` | renomeava |
| `salvar_processo` | **sobrescrevia**; e a criação não carimbava `tenant_id`, então o processo novo nascia na prefeitura do *default* da coluna |
| `excluir_processo` | **apagava** |

**Causa.** `processos` ganhou `tenant_id` na migração 0006 e os acessos
em `db.py` nunca passaram a usá-lo.

**Por que o RLS não cobria** — e isto generaliza o achado: o app opera
com a credencial de **servidor**, e `service_role` tem `BYPASSRLS`. As 82
políticas do banco defendem contra chave publicável vazada; contra a
consulta do próprio app sem `where`, não há política que valha. Ali, o
`.eq("tenant_id", …)` **é** a contenção.

**Correção.** Filtro por tenant em todas as operações e carimbo do
tenant na criação.

**Novo teste.** `tests/test_achado_processos_multi_tenant.py` — seis
provas contra o **PostgREST de verdade**, com duas prefeituras semeadas
por SQL direto (semear pelo código sob suspeita faria a preparação
herdar o defeito). Vermelhas antes, verdes depois.

### C.2 P0 — A identidade visual atravessava prefeituras

| | |
|---|---|
| **Gravidade** | P0 |
| **Componente** | `src/db.py` (`listar_orgaos`, `salvar_orgao`, `excluir_orgao`) |
| **Situação** | **Confirmado** e **corrigido** |

Mesmo defeito em `config_orgaos` — a tabela do timbrado. A listagem que
alimenta o **seletor de timbrado** mostrava a identidade de todas as
prefeituras; marcar uma como padrão **limpava a marca de todas as
outras, de qualquer prefeitura** (escrita cruzando o tenant, não só
leitura); a inserção não carimbava o tenant; a exclusão apagava por id
sem conferir de quem era.

É exatamente o que o §11 manda procurar: *"a ausência de bloqueio no
backend constitui achado de segurança, mesmo que o frontend esconda a
opção"*.

**Novo teste.** `tests/test_achado_identidade_visual_multi_tenant.py` —
quatro provas, vermelhas antes, verdes depois.

### C.3 Varredura sistemática do escopo de tenant

Achar dois casos à mão não diz quantos existem.
`tests/test_escopo_de_tenant_em_db.py` percorre as migrações, junta as
**36 tabelas com `tenant_id`** e cobra o filtro em cada acesso de
`db.py`.

Restaram **13 funções sem filtro**, e elas viraram uma **lista de
exceções com motivo escrito**:

- `config_app` (2 funções): **global por desenho** — a chave primária é
  só `chave`, e uma flag vale para a instalação inteira;
- as outras 11: **escopo indireto** pelo id do pai (processo, portaria,
  secretaria, documento), que agora vem de consulta filtrada.

**Situação: parcialmente confirmado.** A ausência do filtro foi medida;
a exposição **não foi reproduzida**. É defesa em profundidade que falta,
não porta aberta. A lista tem prova de que todo nome nela ainda existe e
de que quem passar a filtrar **sai** dela.

### C.4 P0 — O Mapa de Riscos não gerava em produção

| | |
|---|---|
| **Gravidade** | P0 — processo travado no meio |
| **Componente** | `src/rag.py` (`montar_consulta`, `montar_contexto`) |
| **Situação** | **Confirmado** e **corrigido** |

**Reprodução.** Com `flag_mapa_riscos = 1` (**é o valor de produção**,
medido em 24/09/2026) e Supabase configurado, entrar na etapa do Mapa de
Riscos.

**Observado.** `KeyError: 'mapa_riscos'` em `rag.montar_consulta`.
`steps._gerar` captura `Exception` e mostra *"Não foi possível concluir
o documento"*; o log guarda só `tipo=KeyError`. O servidor vê uma falha
genérica, repetida, sem causa.

**Consequência.** Como a etapa precisa ser **aprovada** para o fluxo
andar, não era um documento a menos: era **o processo travado na
terceira etapa**, sem chegar ao TR nem ao Edital.

**Causa.** O documento entrou no fluxo (`config.SEQUENCIA_COM_MAPA`) e
nunca entrou nos dicionários do RAG. `recuperar` só desvia cedo quando
`db.disponivel()` é falso — em produção o banco existe, então a chamada
chegava inteira ao dicionário incompleto.

**Por que a suíte não pegou.** `montar_consulta` tem teste, o Mapa de
Riscos tem teste, a geração tem teste — e nenhum cruzava os dois: os
testes de geração **dublam** o RAG, e os de RAG usam os quatro
documentos anteriores à entrada do mapa no fluxo.

**Correção.** (1) `mapa_riscos` entra em `NOMES_PARA_BUSCA`, com termos
de risco, e a leitura passa a ser `.get`; (2) `montar_contexto` passa a
honrar a própria docstring — *"nunca levanta exceção"* valia só para
`ErroRAG`. Agora o enriquecimento que falha devolve bloco vazio,
**registra incidente com correlação** e deixa a marca no rastro.

**Novo teste.** `tests/test_achado_mapa_riscos_rag.py`, **parametrizado
pela sequência do fluxo**: o próximo documento acrescentado ganha o caso
de teste sozinho e falha ali, não na tela do servidor.

**Confirmado no navegador:** o Mapa de Riscos aparece entre ETP e TR no
indicador de etapas, gera sozinho e é aprovado.

### C.5 P1 — Reabrir um processo salvo derrubava a tela

| | |
|---|---|
| **Gravidade** | P1 — o caminho de todo dia seguinte de trabalho |
| **Componentes** | `src/ui/processos_ui.py`, `app.py` (3 ocorrências), `src/ui/components.py` |
| **Situação** | **Confirmado** e **corrigido** |

**Reprodução.** Processo com os cinco documentos aprovados → recarregar
a página → entrar de novo → aba Processos → **Continuar de onde parei**.

**Observado**, na tela do servidor:

```
streamlit.errors.StreamlitWidgetAlreadyInstantiatedError:
st.session_state.pagina cannot be modified after the widget with key
pagina is instantiated.
```

**Causa.** `pagina` é a chave do `st.radio` da navegação lateral, criado
cedo em `render_sidebar`. `processos_ui._abrir` roda depois e escrevia
nela. O `app.py` tinha o mesmo defeito em três quedas para "Novo
processo".

**Correção.** `components.ir_para_pagina`, que guarda o **pedido** e o
atende na execução seguinte — antes de o radio existir.

**Novo teste.** `tests/test_achado_reabrir_processo.py`, **estrutural**:
varre `app.py` e `src/ui/*` inteiros, porque a exceção só existe quando
a barra lateral foi desenhada antes, e teste de tela isolada nunca
poderia vê-la. Quatro provas vermelhas no código antigo.

### C.6 O contador de campos obrigatórios mentia depois de salvar

| | |
|---|---|
| **Gravidade** | Média — §16: confusão e retrabalho |
| **Componente** | `src/ui/steps.py` |
| **Situação** | **Confirmado** e **corrigido** |

**Observado.** Formulário inteiro preenchido, "Salvar rascunho" clicado,
e a tela dizia, **logo acima do "Rascunho salvo."**:

> **1 de 5** campos obrigatórios preenchidos. Ainda falta: Quem está
> pedindo, O que vai ser comprado ou contratado, Por que isso é
> necessário, Como a entrega vai acontecer.

— listando exatamente os quatro campos recém-preenchidos.

**Causa.** O contador é desenhado **antes** do `st.form` e lê
`st.session_state.dados`; widget de form só chega ao estado no submit, e
o caminho do rascunho não fazia `st.rerun()`. O caminho "Iniciar
elaboração" fazia — por isso o defeito nunca aparecia ali.

**Consequência.** A saída natural para o servidor é digitar tudo de
novo.

**Correção.** Rerun após salvar, com o aviso viajando no estado para não
ser engolido.

**Depois:** `5 de 5 campos obrigatórios preenchidos. Pode avançar.`

### C.7 A tarja de ambiente mentia na instalação isolada

| | |
|---|---|
| **Gravidade** | Média — aviso que erra ensina a ser ignorado |
| **Componente** | `src/ambiente.py` |
| **Situação** | **Confirmado** e **corrigido** |

`grava_em_producao()` devolvia `True` sem condição, e a homologação
local exibia **"HOMOLOGAÇÃO — mas o banco é o de PRODUÇÃO"**.

Passou a devolver `False` **só quando dá para provar** — hoje, banco
servido em loopback. Qualquer outra coisa continua contando como
produção, **inclusive um Supabase hospedado que não seja o de
produção**: *"não consigo provar que é separado"* tem de ser lido do
lado mais sério. É o mesmo aviso que precisa ser levado a sério quando a
instalação de fato escreve em produção.

### C.8 A prosa não era conferida contra a planilha

| | |
|---|---|
| **Gravidade** | Média — §8/§14 |
| **Componente** | `src/validacao.py` |
| **Situação** | **Confirmado** e **corrigido** |

A tabela emitida já era conferida item a item. A **prosa** não era: um
DFD que escrevia *"valor global estimado de R$ 1,00"* num processo de
R$ 167.774,50 saía **sem um único achado bloqueante**, porque a tabela
ao lado estava certa e ninguém confrontava as duas.

É a classe de erro que um modelo comete com mais facilidade: o número da
tabela entra por injeção de código e está sempre certo; o número escrito
no meio do texto vem do modelo.

**Correção.** `_validar_valor_global_na_prosa` bloqueia a divergência, e
a mensagem **diz qual é o valor certo** — senão o servidor sabe que há
erro e não sabe o que corrigir. A checagem é estreita de propósito: só
dispara quando a prosa **rotula** o número como valor global/total, e
nunca dentro de linha de tabela.

**Quatro mutações provadas:** valor certo não bloqueia; preço unitário
citado na justificativa não bloqueia; linha de tabela não é contada duas
vezes; sem planilha na sessão a checagem não opina.

**Fica de fora, como risco residual:** a **contagem de itens** afirmada
na prosa. Documentos com lotes dizem *"abrange 7 (sete) itens"*
legitimamente de um lote, e bloqueio com falso positivo é pior que a
ausência da checagem.

### C.9 Recarregar a página desloga — **não corrigido**

| | |
|---|---|
| **Gravidade** | Média — §5/§16: retrabalho |
| **Situação** | **Confirmado**, **não corrigido** (decisão humana) |

A sessão vive inteira no `st.session_state` e o Streamlit a descarta na
recarga; não há cookie de sessão. O servidor que aperta F5, perde a rede
por um instante ou reabre a aba volta ao **login no meio da tarefa**.

**O trabalho não se perde** — medido: o processo está no banco, reabre
pela lista, e voltar à primeira etapa devolve objeto, órgão e
justificativa intactos.

**Por que não corrigi.** Persistir sessão exige arquitetura de sessão
(cookie assinado, ou identidade do Supabase Auth de ponta a ponta). O
§19 pede escopo limitado e proíbe refatoração ampla. **Providência
sugerida:** decidir entre cookie de sessão e conclusão da migração para
o Supabase Auth — a segunda resolve isto e as 65 provas não executadas
da seção A.7 de uma vez.

### C.10 Responsividade — **não corrigido**

| | |
|---|---|
| **Gravidade** | Média — §16: confusão |
| **Situação** | **Confirmado**, **não corrigido** (decisão humana) |

| Largura | Clique no centro de um campo obrigatório | Controles fora da tela |
|---|---|---|
| 1920 | o próprio campo | nenhum |
| 1440 | o próprio campo | nenhum |
| **768** | `govbot-scrim` (o GovBot abre **modal**) | "Concluído" |
| **390** | o campo de pergunta do próprio GovBot | **"Mapa de Riscos", "TR", "Minuta de Edital", "Concluído"** |

Em 390 px o indicador de etapas perde **quatro dos seis passos** para
fora da tela, e a página **não rola na horizontal**: não é conteúdo
escondido atrás de rolagem, é conteúdo **recortado**. Em 768 px o
servidor precisa fechar o assistente para digitar.

**Consequência.** Em tablet e telefone o servidor deixa de enxergar em
que ponto do processo está.

**Por que não corrigi.** O indicador é `st.columns(6)`, usado em **toda
tela do wizard**. Torná-lo rolável exige trocar o contêiner, e não há
prova visual nesta suíte que pegue uma regressão de layout. A
consequência é confusão, não perda de dado.
**Providência sugerida:** envolver o indicador num contêiner com
`overflow-x: auto` abaixo de 900 px, com uma prova de geometria que
falhe se ele voltar a recortar.

### C.11 Módulos cobertos pelas suítes existentes

Executadas e **verdes** nesta rodada. Registrado como cobertura de
suíte, **não** como bateria de navegador própria:

| Seção | Módulo | Provas | Situação |
|---|---|---|---|
| §7 | Consolidação de Solicitações de Despesa | **88** | disponível; critérios do §7 cobertos (arquivo reenviado não soma duas vezes, mesmo DFD em arquivos diferentes entra uma vez, unidade incompatível não funde, nenhuma linha de entrada se perde, cada quantidade aponta para o arquivo de origem, o total é refeito pelas origens) |
| §9 | Editor visual | **11** (+ exportação do editor rico) | disponível (`flag_editor_rico`); a barra do editor — Negrito, Itálico, listas, Desfazer, Refazer, Tabela — foi **vista em tela** na etapa do Mapa de Riscos |
| §10 | GovBot | **398** | disponível; inclui `test_govbot_security.py` e `test_govbot_institucional.py` (servidor de outra prefeitura não é consultado nem selecionado; a troca passa pelo backend e não pela conversa) |
| §12 | Parecer jurídico | **67** (+ 20 do corretor) | disponível |

**Não executado por navegador:** upload real de solicitações de despesa,
edição no editor rico com copiar/colar e desfazer, conversa com o
GovBot, anexação de parecer. Vai ao portão como pendência de cobertura,
não como aprovação.

---

## D. Auditoria documental simulada — perspectiva de controle externo

> **Limite desta seção, dito antes de qualquer achado.** A verificação
> normativa em fonte oficial **não pôde ser concluída**:
> `planalto.gov.br` devolveu HTTP 503 em 24/09/2026. Portanto **nenhuma
> redação de artigo é transcrita e nenhum entendimento de tribunal de
> contas é citado**. Os critérios abaixo são **documentais e
> comportamentais**. Números de dispositivo aparecem apenas onde já
> constam do mapa curado do próprio sistema e **não foram reconferidos**.
>
> Esta seção **não emite aprovação jurídica** do sistema nem de
> contratação futura. Os documentos são simulados.

### D.1 Falhas comprovadas de funcionamento da aplicação

| # | Critério | Condição | Evidência | Causa provável | Risco | Providência | Situação |
|---|---|---|---|---|---|---|---|
| 1 | Cada município acessa apenas os próprios processos | A lista do administrador devolvia processos de todas as prefeituras, e o id abria, renomeava, sobrescrevia e apagava | 6 provas contra PostgREST real | `tenant_id` da 0006 nunca usado em `db.py`; `service_role` atravessa o RLS | Quebra de sigilo entre entes e **perda definitiva** de processo alheio | Corrigido; varredura instalada | **Confirmado — corrigido** |
| 2 | O timbrado de um município não alcança outro | Listagem, marcação de padrão, criação e exclusão cruzavam prefeituras | 4 provas contra PostgREST real | idem | Documento oficial emitido com identidade de outro ente | Corrigido | **Confirmado — corrigido** |
| 3 | Cada etapa do fluxo documental é executável | Mapa de Riscos falhava sempre, com mensagem genérica | `KeyError` reproduzido; flag medida em produção | Documento entrou no fluxo e não no RAG | **Instrução processual interrompida**: sem TR e sem Edital | Corrigido; prova parametrizada pela sequência | **Confirmado — corrigido** |
| 4 | Processo salvo é recuperável | "Continuar de onde parei" devolvia traceback | Captura `A_1440_05_processo_reaberto` | Escrita em chave de widget já instanciado | Retomada impedida; aparência de sistema quebrado | Corrigido | **Confirmado — corrigido** |
| 5 | Indicadores refletem o estado real | Contador dizia "1 de 5" com os 5 preenchidos e salvos | Captura `A_1440_03_rascunho_salvo` | Contador lê estado anterior ao submit | Retrabalho; desconfiança do salvamento | Corrigido | **Confirmado — corrigido** |
| 6 | O ambiente se identifica corretamente | Instalação isolada anunciava banco de produção | Captura `A_1440_05_gerado_dfd` | Função devolvia `True` sem condição | Aviso ignorado justamente quando for verdadeiro | Corrigido | **Confirmado — corrigido** |

### D.2 Falhas comprovadas de consistência dos documentos simulados

| # | Critério | Condição | Evidência | Risco | Providência | Situação |
|---|---|---|---|---|---|---|
| 7 | O ato não afirma número que o processo não tem | Prosa dizia "valor global de R$ 1,00" num processo de R$ 167.774,50 **sem bloqueio** | Fixture `contraditoria` | Ato com estimativa divergente da planilha | Corrigido, com 4 mutações provadas | **Confirmado — corrigido** |
| 8 | Contagem de itens afirmada na prosa | **Não verificada** pelo sistema | — | Documento pode afirmar "7 itens" num processo de 20 | Deixado fora deliberadamente: falso positivo em documento com lotes pararia ato legítimo | **Não testado — risco residual aceito** |

### D.3 Matriz de consistência entre documentos (§14)

Confronto **determinístico**, não por semelhança textual:

| Dado | Origem canônica | DFD | ETP | Mapa de Riscos | TR | Edital | Como foi conferido |
|---|---|---|---|---|---|---|---|
| Objeto | formulário | ✅ | ✅ | ✅ | ✅ | ✅ | presença literal no documento, 7 cenários |
| Órgão / unidade demandante | formulário | ✅ | ✅ | ✅ | ✅ | ✅ | idem |
| Justificativa | formulário | ✅ | ✅ | ✅ | ✅ | — | idem |
| Quantitativos | planilha | ✅ | ✅ | n/a | ✅ | ✅ | célula a célula no DOCX |
| Unidades | planilha | ✅ | ✅ | n/a | ✅ | ✅ | idem |
| Valor global | planilha | ✅ | ✅ | n/a | ✅ | ✅ | calculado **fora** do sistema |
| Marcador interno | — | ✅ ausente | ✅ | ✅ | ✅ | ✅ | busca por `[[TABELA_ITENS]]` |
| Mecânica do sistema | — | ✅ ausente | ✅ | ✅ | ✅ | ✅ | busca por "formulário matriz", "system prompt" |
| ARP quando SRP | modelo de execução | n/a | n/a | n/a | n/a | ✅ | só no cenário E |
| Solução do ETP, riscos, fiscalização, pagamento, signatários, portarias | — | — | — | — | — | — | **não confrontado**: depende de redação de modelo real |

> A última linha é a fronteira do §8: *"um mock pode comprovar que o
> sistema transporta, valida, edita e exporta o texto recebido. Ele NÃO
> comprova que uma LLM real redigirá um documento completo, correto ou
> juridicamente adequado."*

### D.4 Questões que exigem revisão humana

1. **`mapa_riscos` não tem temas jurídicos configurados** no RAG
   (`TEMAS_NUCLEO`/`TEMAS_COMPLEMENTARES`), então só a consulta geral
   roda para ele. Decidir **quais matérias sustentam um mapa de riscos**
   é escolha de conteúdo, não conserto de defeito.
2. **Verificação normativa pendente** — a seção D não pôde conferir
   redação de dispositivo em fonte oficial. Refazer com o Planalto no ar.
3. **Persistência de sessão** (C.9) — decidir entre cookie assinado e
   conclusão da migração para o Supabase Auth.
4. **Recorte do indicador de etapas em tela pequena** (C.10).

### D.5 Avaliações que dependem de LLM real

- Completude e adequação jurídica da redação de cada peça;
- Coerência argumentativa entre ETP e TR (solução escolhida →
  operacionalização);
- Qualidade das análises de risco do Mapa de Riscos;
- Comportamento do GovBot diante de pedido ambíguo;
- Aplicação de parecer jurídico com recomendações conflitantes.

---

## E. Controle de custos da próxima rodada

Medido com orçamento zero (`scripts/custo_da_proxima_rodada.py`), com a
pilha de homologação de pé.

### E.1 Por processo completo

O fluxo de produção tem cinco documentos. **Edital e ARP não passam por
modelo nenhum** — são montados do catálogo versionado de cláusulas —,
então quatro consomem IA.

| Cenário | Conversas | Chamadas de embedding | Caracteres de prompt |
|---|---|---|---|
| F (1 item) | 4 | 4 | 72 279 |
| A (20 itens) | 4 | 4 | 77 181 |
| **G (210 itens)** | 4 | 4 | **135 915** |

### E.2 Os três achados de custo

**1. Os embeddings não aparecem em nenhuma conta.** São **uma chamada
paga por documento**, toda vez, e ninguém os menciona ao pensar no preço
da geração. Na bateria eles apareceram como **2 requisições** cada,
porque o cliente do RAG é criado com `max_retries=1` e o bloqueio fez a
primeira falhar — na rodada operacional, com chave válida, a conta é de
**1 por documento**.

**2. O encadeamento infla o prompt.** O prompt do ETP no cenário de 210
itens tem **52 941 caracteres** porque carrega o documento anterior
inteiro. Cada regeneração reenvia tudo.

**3. O caminho de falha multiplica.** Uma única ação do servidor que não
obtém resposta dispara **3 requisições no mesmo modelo**
(`API_TENTATIVAS = 3`, com espera de 2 s e 4 s), antes de trocar de
modelo e, depois, de motor. Medido: **3 requisições para uma ação que
falhou**, com um motor configurado. Com três motores e lista de modelos
alternativos, o pior caso é bem maior.

### E.3 Onde a próxima rodada desperdiçaria

| Caminho | Desperdício | Oportunidade |
|---|---|---|
| Embedding por documento | 4 chamadas por processo, sempre as mesmas consultas para o mesmo objeto | **Cache por (objeto, doc_key)**: o texto de busca é determinístico |
| Regeneração de documento | reenvia o prompt inteiro, incluindo a cadeia aprendida | Orçamento máximo por documento; confirmação antes de regenerar |
| Retentativa em erro não transitório | até 3 por modelo | `_trocar_de_modelo` já aborta em erro de chave/cota — **conferir a classificação antes da rodada** |
| Botão "testar conexão" do painel | é chamada paga disfarçada de diagnóstico | Medido: **não gasta** com o bloqueio; na rodada operacional, gasta |
| Correção automática e GovBot | disparam por evento de interface | Medido: a correção automática falhou **com segurança** ao ser barrada |

### E.4 Orçamento proposto para a bateria operacional

> Proposta para decisão do proprietário. **Nenhuma API real foi usada
> para produzi-la.**

| Limite | Valor sugerido | Razão |
|---|---|---|
| Cenários com LLM real | **2** (F e A) | G serve ao estresse de exportação, já provado sem custo |
| Documentos por cenário | 4 | Edital e ARP não consomem |
| Teto de conversas | **12** (4 por cenário + 4 de folga para regeneração) | |
| Teto de embeddings | **8** | |
| `API_TENTATIVAS` durante a rodada | **1** | a retentativa serve à produção, não à medição |
| Motores habilitados | **1** (OpenAI) | a queda entre motores multiplica a conta sem acrescentar informação |
| Corte automático | interromper ao atingir o teto de requisições | o contador de `sem_llm` já existe e serve, invertido |

---

## F. Evidências de refinamento

### F.1 Commits

| Commit | Conteúdo |
|---|---|
| `916923a` | Homologação isolada com PostgREST local |
| `98ee6de` | **P0** — Mapa de Riscos não gerava |
| `57de426` | §17 — 265 provas de contenção deixam de ser puladas |
| `09ec5eb` | §4 e §8 — massas A–H e o achado do valor global na prosa |
| `08dffde` | §5 — navegação no navegador e três achados |
| `52e51ca` | §13 — exportação aberta e conferida |
| `20f915a` | §16 — responsividade por consequência |
| `cad4fe8` | **P0** — processos e timbrado atravessavam prefeituras |
| `e814529` | §15 e §20-E — custo da próxima rodada |

### F.2 Testes criados

| Arquivo | Provas | Cobre |
|---|---|---|
| `tests/test_achado_mapa_riscos_rag.py` | 7 | C.4 |
| `tests/test_achado_reabrir_processo.py` | 20 | C.5 |
| `tests/test_achado_processos_multi_tenant.py` | 6 | C.1 |
| `tests/test_achado_identidade_visual_multi_tenant.py` | 4 | C.2 |
| `tests/test_escopo_de_tenant_em_db.py` | 28 | C.3 |
| `tests/test_bateria_auditoria.py` | 32 | §8, §14 |
| `tests/test_bateria_exportacao.py` | 15 | §13 |
| `tests/test_sem_llm.py` | 17 | §3 |
| `tests/massas_auditoria.py` | — | §4 |

Acrescidas provas em `test_validacao.py` (C.8),
`test_formulario_leigo.py` (C.6) e `test_ambiente_e_promocao.py` (C.7).

### F.3 Antes e depois

| Medida | Antes | Depois |
|---|---|---|
| Suíte completa | 2 317 ✅ / 316 ⏭ | **2 467 ✅ / 289 ⏭** |
| Provas de contenção executadas (§17) | 217 ✅ / 119 ⏭ | **265 ✅ / 65 ⏭** |
| Provas de RLS contra PostgreSQL real | 0 (puladas) | **157 ✅** |
| Provas de PDF institucional | puladas | **executadas** (LibreOffice instalado) |
| Chamadas pagas de LLM | — | **0** |

### F.4 Problemas ainda abertos

1. **C.9** — recarregar desloga (decisão humana)
2. **C.10** — indicador de etapas recortado em tela pequena
3. **C.3** — 11 funções com escopo de tenant apenas indireto
4. **65 provas de isolamento por conta** não executadas (sem GoTrue)
5. **D.4.1** — `mapa_riscos` sem temas jurídicos no RAG
6. **Verificação normativa** pendente (Planalto 503)
7. §7, §9, §10 e §12 **sem bateria de navegador própria**

### F.5 Homologação, rollout e rollback

- **Homologar** com `scripts/homologacao_stack.py --recriar-banco`,
  que espelha as flags de produção.
- **Rollout:** as correções de `db.py` são aditivas (acrescentam
  `where`). Produção tem **um único tenant** e todas as linhas no mesmo
  `tenant_id` — medido em 24/09/2026 —, então **nada muda para quem está
  lá hoje**.
- **Rollback:** reverter os commits. Não há migração nova; o banco não
  muda.
- **Ordem sugerida:** `98ee6de` (Mapa de Riscos) e `cad4fe8`
  (multi-tenant) primeiro — são os dois P0.

---

## §21. Portão para a próxima bateria

**As APIs reais não foram ativadas.** Conclusão fundamentada sobre os
requisitos de entrada:

| Pergunta do §21 | Resposta | Fundamento |
|---|---|---|
| Os fluxos essenciais foram testados? | **Sim, com ressalva.** | Ponta a ponta no navegador, cenário A. §7, §9, §10 e §12 cobertos por suíte, **não** por navegador. |
| Há falhas que provocam perda ou corrupção de dados? | **Havia duas, corrigidas.** | C.1 (apagar processo alheio) e C.2 (apagar timbrado alheio). Nenhuma aberta. |
| Os cálculos e vínculos institucionais foram validados? | **Cálculos, sim.** Vínculos, **parcialmente.** | Aritmética conferida fora do sistema em 7 cenários. Isolamento provado no SQL e no PostgREST; **emissão de JWT não**. |
| Os documentos simulados preservam os fatos do processo? | **Sim.** | Matriz D.3: objeto, órgão, justificativa, quantitativos, unidades e valor global atravessam os cinco documentos. |
| A exportação está íntegra? | **Sim.** | 210 códigos inteiros no DOCX **e** no PDF; cabeçalho repetindo entre páginas; mais de uma página; dossiê na ordem. |
| O isolamento entre prefeituras está funcionando? | **Agora sim, no que foi medido.** | Era o P0 da rodada. 10 provas contra PostgREST real. Restam 11 funções com escopo indireto (C.3). |
| Existem chamadas duplicadas ou desnecessárias? | **Sim, e estão medidas.** | E.2: embeddings por documento, prompt encadeado, 3 requisições por ação que falha. |
| O mecanismo de limitação de gastos está preparado? | **Existe e foi provado — mas é de auditoria, não de produção.** | `sem_llm` barra e conta, e a pilha recusa subir sem ele. **Não há teto de gasto no app.** |
| Quais pontos ainda exigem modelos reais? | D.5. | |

### Recomendação

**A rodada operacional pode ocorrer**, em ambiente controlado, **desde
que**:

1. os limites da seção **E.4** sejam adotados — em especial
   `API_TENTATIVAS = 1` e **um único motor**;
2. a rodada use a **homologação isolada**, nunca produção;
3. haja **corte automático** ao atingir o teto de requisições;
4. o resultado da seção **C.3** (escopo indireto) seja decidido antes de
   uma segunda prefeitura ser cadastrada — a porta está fechada nas duas
   tabelas críticas, e o resto é defesa em profundidade que falta.

**Não recomendo** ativar as APIs antes de decidir **C.9** (persistência
de sessão), porque o retrabalho de re-login no meio de uma geração paga
tem custo direto: o servidor reautentica e regenera.

> Nada nesta auditoria autoriza merge ou deploy. A próxima bateria
> depende de **autorização expressa do proprietário**.
