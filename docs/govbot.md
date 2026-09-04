# GovBot — arquitetura, operação e contratos de segurança

## Ativação e escopo

O GovBot é um agente contextual integrado ao wizard do GovDocs. Ele reutiliza
o motor de IA, os fatos canônicos, as decisões do motor de conhecimento, os
achados estruturados, o rastro RAG, o corretor, o aplicador de patches e o
autosave já existentes. Ele não cria endpoint, API pública, tabela, migração
ou mecanismo paralelo de persistência.

A ativação usa exclusivamente a chave `flag_govbot`, consultada por
`db.flag_ativa("govbot")`. Ausência de banco, ausência da configuração, valor
vazio ou valor falso significa **OFF**. Com a flag desligada:

- o módulo do painel e o Components v2 não são registrados;
- nenhum bucket, rascunho, histórico ou undo do GovBot é criado;
- nenhuma chamada de IA é iniciada pelo GovBot;
- o fluxo histórico do wizard permanece ativo.

Não há ativação automática nesta branch, nem alteração de configuração em
produção. O GovBot inicial foi integrado pelo PR #14. A etapa 1.1 parte da
`main` em uma nova branch e deve parar para auditoria independente, sem merge
e sem ativação. A autorização da entrega anterior não se estende à etapa 1.1.

## Bloqueio de produção

O GovBot deve permanecer desligado em produção até que uma tarefa independente
corrija e verifique as políticas anônimas amplas de `processos`, `config_app`,
`documentos_referencia` e `chunks_referencia`, e valide o fluxo completo com o
JWT do usuário sujeito a RLS. Uma credencial de servidor que atravessa Row Level
Security não prova isolamento por tenant.

Esse trabalho de autenticação/RLS está expressamente fora desta branch. Até sua
conclusão, `flag_govbot` deve permanecer ausente ou desativada em produção.

## Arquitetura

O fluxo possui três camadas internas:

```text
assets/govbot/* + govbot_component.py
  -> evento mínimo e não confiável
govbot_panel.py
  -> contexto da tela, callbacks do wizard e reruns
govbot.py
  -> contratos, allowlists, propostas, validação, aplicação e undo
```

- `src/govbot.py` é o núcleo puro. Não importa Streamlit e não acessa
  `st.session_state`; recebe mappings e callbacks explícitos.
- `src/ui/govbot_panel.py` é o único adaptador que conhece ao mesmo tempo o
  wizard e o núcleo. Ele resolve foco, monta o contexto mínimo, reidrata
  widgets, chama o motor existente e decide entre rerun do fragmento ou da
  aplicação inteira.
- `src/ui/govbot_component.py` registra um componente local com
  `st.components.v2.component(..., isolate_styles=True)` e devolve somente o
  trigger transitório `event`.
- `assets/govbot/govbot.html`, `govbot.css` e `govbot.js` implementam o painel.
  `assets/govbot/mascot.svg` é o único asset visual de runtime. Não há PNG, GIF,
  React, Next.js nem chamadas diretas do browser à IA ou ao Supabase.
- `app.py` importa e prepara o painel somente quando a flag está ativa, antes
  da criação dos widgets; depois monta o GovBot dentro de `st.fragment`.
- `state.py` continua sendo a fonte canônica de `dados`, `documentos`,
  `aprovados` e `etapa`.

O SVG foi redesenhado como vetor a partir da primeira imagem do pacote visual.
A imagem panorâmica 10 foi usada como referência para a relação entre wizard e
painel lateral; as imagens raster não entram no runtime.

## Contratos tipados

O núcleo expõe dataclasses imutáveis:

- `GovBotContext`: processo, etapa, documento, campo/bloco em foco, valor atual,
  fatos relevantes, decisões, achados e referências RAG recortadas;
- `GovBotIntent`: ação, resposta, alvo, payload e fontes validadas;
- `GovBotProposal`: id, ação, alvo, antes/depois, justificativa, fontes e hash
  da origem;
- `GovBotChange`: snapshot transacional, hash pós-aplicação, documentos
  invalidados, situação da persistência e dados de undo;
- `GovBotEvent` e `GovBotReply`: fronteiras de entrada e saída do orquestrador.

O evento do componente contém exatamente:

```json
{
  "request_id": "...",
  "event_type": "message | apply_proposal | undo",
  "text": "...",
  "focus": "campo ou editor reconhecido",
  "proposal_id": null,
  "draft": {}
}
```

Chaves desconhecidas, evento desconhecido, mensagem vazia, foco fora da tela,
`proposal_id` incompatível e identificador repetido são rejeitados. O browser
nunca escolhe uma chave interna, path de patch, finding ou operação executável.

A resposta do modelo deve ser um único objeto JSON completo com exatamente
`intent`, `response`, `target`, `payload` e `sources`. Cercas Markdown, texto
adicional, aliases, chaves repetidas ou campos extras falham. Há no máximo uma
segunda chamada para corrigir o formato; se ela também falhar, a resposta vira
fallback não mutável.

Hashes não são solicitados nem aceitos do modelo. `origin_hash`,
`expectedOldHash` e o hash do bundle são calculados e conferidos no servidor.
As fontes citadas pelo modelo precisam estar na lista derivada do contexto
validado; um identificador de fonte, sozinho, não autoriza valor material.

## Contexto mínimo

O adaptador envia ao núcleo/modelo somente o recorte necessário ao foco:

- o valor do campo escalar em foco; ou
- um único bloco atual de DFD, ETP ou TR, resolvido no servidor; e
- fatos canônicos relacionados, decisão de conhecimento já calculada, achados
  da versão atual e referências do trace RAG pertinente.

### GovBot 1.1 — rascunhos visíveis e busca pela pergunta

O contexto agora sobrepõe **todos** os rascunhos escalares reconhecidos da tela
à cópia temporária de `dados`. Uma chave presente com valor vazio significa
campo apagado, não retorno ao valor canônico. As pendências são calculadas
sobre essa visão. `campos_em_rascunho` identifica a procedência no prompt;
campos fora do foco têm recorte de 1.000 caracteres. O valor em foco permanece
integral para comparação e hash. A planilha continua fora da sobreposição.

Essa visão não é repassada a fatos, decisões, invalidação ou autosave. A leitura
não escreve em `dados`, não cria fatos canônicos e não muda os documentos.
O submit explícito continua descartando o draft, e a reidratação preserva
edições durante reruns, com os mesmos buckets por processo/identidade.

Somente mensagens validadas, ainda não processadas, passam pelo planejamento
local de RAG. Conversas sociais, orientação estática, melhorias de redação com
texto local, visualização, aplicar e desfazer não fazem busca. Um trace com
cobertura lexical específica da pergunta pode dispensar a recuperação; apenas
coincidir com o tema não basta. Esta seleção conservadora não é uma prova
semântica de suficiência e será avaliada com modelo/base reais na etapa 1.2.

Quando necessário, o adaptador chama `rag.buscar_referencias(...,
contextual=True)`: mesmos embeddings, RPCs, índice, contexto de tenant e piso de
relevância existentes. O modo contextual usa `consulta_textual` no fallback;
o padrão dos consumidores anteriores permanece igual. Há no máximo uma busca
e uma chamada de embeddings por mensagem. Não há cliente paralelo nem esquema
novo. A consulta, de até 500 caracteres, usa somente vocabulário controlado dos
temas jurídicos e das categorias de objeto existentes, além de referências
explícitas a artigos e identificadores internos de foco/documento. Nomes,
contatos, credenciais, prosa arbitrária, histórico e linhas da planilha não
são serializados nela. Esse filtro pode perder termos específicos do objeto;
é uma limitação deliberada de minimização, a medir na etapa 1.2.

As referências são normalizadas no servidor, deduplicadas por source ID ou
documento/ordem e limitadas a seis recortes de até 1.000 caracteres. IDs vindos
da recuperação são preservados se válidos; na ausência, derivam de chunk,
documento/ordem ou hash determinístico. Título, categoria, score/similaridade,
tema e dispositivos disponíveis são mantidos. A busca atual tem prioridade
com espaço reservado ao trace anterior, que nunca é sobrescrito nem salvo.

Falha ou ausência de referência válida produz resposta local, sem chamar o
modelo e sem mutação. Quando há fonte, o JSON continua sujeito à allowlist de
source IDs e à única tentativa de correção. A resposta fundamentada também
passa pelo guard de valores materiais: citar uma fonte sobre vigência da ata
não autoriza criar prazo de entrega, artigo ou decisão administrativa. A
aplicação ainda revalida seus próprios guards, hashes e orçamento de patch.
Logs da busca contêm apenas finalidade, duração, ação/alvo abstratos e resultado.

Os testes de integração adicionais estão em `tests/test_govbot_rag_contextual.py`;
eles usam dublês determinísticos e bloqueiam acessos a serviços reais. Isso
não valida qualidade conversacional, recall ou latência de produção.

O prompt inclui no máximo oito mensagens anteriores, com até 2.000 caracteres
por mensagem, tratadas como dados não confiáveis, nunca como autorização ou
fonte. Pendências obrigatórias e divergências entre documentos são calculadas
localmente a partir dos validadores existentes.

A planilha `itens` não é serializada como alvo genérico e documentos inteiros
não entram acidentalmente quando apenas um bloco está em foco. Edital e ARP
podem ser explicados, comparados ou direcionados à origem, mas não recebem
texto livre do GovBot.

## Ações permitidas

O contrato fechado possui dez ações:

| Ação | Comportamento |
|---|---|
| `explain_current` | Explica ou localiza o contexto sem alterar estado. |
| `suggest_field` | Produz comparação para um campo conhecido. |
| `replace_form_field` | Propõe/substitui um campo escalar conhecido. |
| `suggest_section_patch` | Propõe mudança para um bloco de DFD/ETP/TR. |
| `apply_section_patch` | Aplica o patch de bloco após todas as validações. |
| `explain_finding` | Explica um achado presente no relatório atual. |
| `fix_finding` | Corrige achado atual, validado e autocorrigível. |
| `undo_last_change` | Desfaz a última alteração compatível. |
| `show_missing_information` | Lista pendências sem inventar valores. |
| `compare_with_previous_document` | Compara com o documento anterior aplicável. |

As únicas ações mutáveis são substituição de campo escalar, patch de bloco
DFD/ETP/TR, correção de achado autocorrigível e undo. `itens`, Edital e ARP
ficam fora da escrita textual genérica.

Pedidos sugestivos de campo ou bloco criam uma proposta antes/depois e um
botão **Aplicar**.
“Melhore e aplique” só executa imediatamente quando o modelo retorna alvo e
valor completos e os guards determinísticos aprovam a ação. A intenção do
modelo nunca é autorização suficiente.
Perguntas, citações, condicionais e pedidos de aplicação adiada ficam apenas
como proposta. O reconhecedor é conservador: pedidos ambíguos continuam com
comparação e botão **Aplicar**, sem execução automática.
Negação explícita de aplicação bloqueia a execução imediata. Para correção
de achado, um pedido apenas sugestivo recebe orientação para confirmar com
“corrija e aplique”; a correção revalida o achado na confirmação.

## Rascunhos, processos e reruns

Conversas, propostas, cooldowns, IDs e alterações reversíveis vivem apenas na
sessão:

- até 40 mensagens por processo;
- até 20 alterações reversíveis por processo;
- até 100 identificadores processados por processo.

Um processo não salvo recebe UUID local. `obter_bucket()` somente seleciona ou
cria um bucket; `reindexar_bucket()` é a única operação que move explicitamente
o bucket local para `processo:<id>` depois do primeiro autosave bem-sucedido.
Abrir outro processo salvo não reaproveita a conversa local. Reabrir um
processo salvo na mesma sessão recupera seu bucket.
Os buckets são vinculados à identidade do usuário e ao contexto institucional.
Logout ou troca dessa identidade descarta histórico, propostas, undo, rascunhos,
widgets e cópias de contexto do GovBot; uma conta nova não herda dados da anterior.

O componente captura apenas widgets reconhecidos em `govbot_form_draft`. A
cópia soberana fica no bucket do processo; o mapping plano serve somente para
reidratar widgets antes de sua instanciação. O rascunho não é incorporado a
`dados` até um submit real ou uma aplicação explícita no alvo. Ao alterar um
bloco, outras edições não enviadas do mesmo editor são preservadas.

Mensagens comuns rerodam somente o fragmento. Aplicar e desfazer capturam o
rascunho, executam a transação e então fazem rerun completo para reidratar o
widget correto. Reiniciar o processo desassocia o bucket atual e cria novo UUID
local sem apagar buckets de processos salvos.

## Aplicação, persistência e undo

Substituição de campo:

1. confirma campo escalar e hash da origem;
2. valida valores materiais e opções fechadas;
3. altera somente o alvo;
4. chama `state.invalidar_a_partir_de("formulario")`;
5. usa o autosave existente;
6. registra snapshot, hash pós-aplicação e resultado idempotente.

Patch documental:

1. resolve o bloco/finding na versão atual;
2. reconstrói uma allowlist no servidor;
3. exige schema fechado, uma operação, documento/path coerentes, hash atual,
   fontes permitidas e orçamento de diff;
4. chama `corretor.validar_plano` e `patches.aplicar_plano`;
5. remove a aprovação do documento e invalida os posteriores;
6. salva e registra o snapshot reversível.

`fix_finding` volta a gerar e validar o relatório atual; somente findings
autocorrigíveis de DFD/ETP/TR podem chegar ao aplicador. O plano deve conter
uma única operação `replace`, `add` ou `remove` permitida pelo próprio finding.

Toda aplicação é idempotente pelo identificador. Undo só restaura o snapshot
se o estado atual ainda tiver o hash pós-aplicação; qualquer edição posterior
gera conflito e bloqueia a restauração.
Edições ainda não enviadas no alvo também bloqueiam o undo. Quando o valor
anterior existia somente no formulário, desfazer restaura esse rascunho sem
incorporá-lo aos dados canônicos. Hidratação antiga nunca substitui o valor
mais recente recebido em um submit real do formulário.

O retorno distingue explicitamente “aplicado e salvo” de “aplicado somente
nesta sessão”. Falha de autosave não é apresentada como persistência concluída.

## Valores materiais e modo offline

Números, prazos, identificações, quantidades e decisões administrativas só
podem ser introduzidos quando já aparecem no pedido do usuário, no valor
anterior, em fatos canônicos ou no trecho de uma fonte RAG validada. Campos
integralmente materiais, como órgão, responsável, prazo e modelo de execução,
exigem o novo valor na evidência. O modelo não pode inventá-los.
Na correção de achados, caminhos internos e diagnósticos estruturais não são
fontes de quantidades. A numeração do título é validada como estrutura do alvo,
sem autorizar esse número no corpo. Mensagens legais determinísticas mantêm
o lastro do dispositivo indicado pelo mapa canônico.
A validação distingue unidades, números por extenso, separadores brasileiros
e afirmações administrativas positivas/negativas; reutiliza também as
decisões estruturadas do verificador de consistência.
Fatos precisam de proveniência e metadados válidos: usa-se a versão vigente
mais recente, excluindo fatos disputados, substituídos ou inativos. Inferências
não confirmadas e métricas internas de classificação não autorizam valores
materiais; uma inferência administrativa exige confirmação explícita.

Microfrases e orientações de campo são locais e determinísticas, com intervalo
mínimo de 90 segundos e uma intervenção por campo/versão. Sem motor de IA,
orientação, localização, pendências, comparação determinística e undo (botão
ou pedido explícito) continuam funcionando;
perguntas abertas informam de forma explícita que a assistência por IA está
indisponível.

## Interface e acessibilidade

- Desktop acima de 1024 px: painel fixo de 300 px e reserva de espaço no
  conteúdo quando aberto.
- Entre 801 e 1024 px: drawer lateral com scrim.
- Até 800 px: botão flutuante e bottom sheet.
- Primeira visita: painel aberto; a preferência fica na sessão da aba.
- `Alt+G`: abrir e focar o chat; `Esc`: fechar; `Enter`: enviar;
  `Shift+Enter`: nova linha.
- Regiões `aria-live`, log acessível, foco visível e contraste AA.
- Nenhum foco é roubado na abertura automática.

O mascote implementa `IDLE`, `HOVER`, `LISTENING`, `THINKING`, `WORKING`,
`SUGGESTION`, `APPLYING`, `SUCCESS`, `ATTENTION`, `CELEBRATE` e `ERROR`, com
olhos independentes. Timers e movimentos pausam quando a aba está oculta, o
mascote sai da viewport ou `prefers-reduced-motion` está ativo. O renderer é
reentrante e remove listeners, observers, timers e o marcador global ao
desmontar.

## Segurança e telemetria

- Conteúdo dinâmico é inserido com `textContent`, nunca como HTML não
  confiável. Não há `innerHTML`, `document.write`, `eval` ou código do modelo.
- O browser não usa `fetch`, WebSocket, SDK de IA ou SDK do Supabase.
- Chaves, tokens, secrets, conversa, documentos e rascunhos não entram nos
  logs do GovBot.
- A telemetria registra apenas finalidade, duração, identificador abstrato do
  modelo, tipo da ação, alvo abstrato, resultado e situação da persistência.
- Entrada adulterada, hash obsoleto, fonte forjada, diff excessivo ou falha do
  executor termina sem mutação parcial.

Conversas e undo são perdidos ao encerrar a sessão do navegador. Apenas as
alterações canônicas continuam usando a persistência já existente do GovDocs.

## Validação

Testes focados:

```text
python -m pytest -q \
  tests/test_govbot.py \
  tests/test_govbot_panel.py \
  tests/test_govbot_component.py \
  tests/test_govbot_security.py \
  tests/test_govbot_regressoes.py
```

A entrega também exige a suíte completa, `git diff --check`, prova visual nos
três breakpoints e Codex Security diff scan da branch contra o commit-base.
