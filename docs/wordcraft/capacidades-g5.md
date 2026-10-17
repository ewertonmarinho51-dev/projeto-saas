# G5 — capacidades contextuais no owner nativo

Estado: **parcial**. Este incremento estabelece a fronteira comum das seis
capacidades, mas não encerra as trilhas A–D do corpus de aceitação.

## Fronteira implementada

`src/wordcraft_capacidades.py` é uma camada pura. Ela não consulta banco, RAG
ou LLM, não aplica patch e não persiste revisão. GovBot, auditoria e parecer
produzem `CorrecaoContextual`; o compilador deriva `documentId`, caminho e
`expectedOldHash` do relatório e do snapshot entregues pelo owner. A saída tem
o contrato de propositor de `DocumentoService.preparar_patches`. Portanto a
autenticação, o índice nativo, a política canônica, a reaplicação da auditoria,
o diff e a persistência transacional continuam em seus mecanismos existentes.

Uma sugestão é recusada quando o finding não existe, não é autocorrigível, o
caminho é ambíguo/bloqueado, o bloco não pertence ao snapshot ou a fonte
material exigida não foi vinculada. Apontamentos de parecer ambíguos,
conflitantes ou dependentes de decisão humana permanecem pendências.

Templates, evidências e montagem são projeções somente leitura:

- o snapshot de template congela a versão publicada, a identidade
  institucional e a montagem por JSON canônico e SHA-256;
- a evidência diferencia `VERIFICADA`, `INDISPONIVEL`, `NAO_VERIFICADA` e
  `PENDENTE`; resultado vazio de busca não prova ausência, e citação não
  cadastrada nunca recebe estado verificado;
- a montagem numera itens e totaliza com `Decimal`, sem arredondamento binário
  nem preenchimento de valores ausentes.

`src/ui/wordcraft_painel.py` apresenta tudo em um painel com as abas GovBot,
Auditoria, Parecer, Evidências e Histórico. Template e montagem aparecem na
auditoria porque são insumos estruturais da revisão. O painel recebe dados e
não possui callbacks de salvar, confirmar ou aprovar. Ele está montado apenas
no laboratório sintético e no novo host feature-flagged do wizard.

`src/ui/wordcraft_operacional.py` troca a superfície inteira quando
`flag_wordcraft_editor` está ligada; não monta TipTap ou `text_area` junto e
não faz fallback silencioso. A primeira abertura usa a importação Markdown
idempotente do próprio `DocumentoService`, o save confirma ACK somente depois
do commit e a aprovação exige o canvas congelado na revisão/hash exatos. O
consumidor source-aware reidrata os atos persistidos, projeta texto nativo
aprovado para o contexto da peça seguinte e libera a sequência sem consultar
`processos.aprovados`. Ao completar a sequência, a tela final exporta somente
heads nativos aprovados, com CAS de revisão/hash; os downloads legados não são
montados. O pacote ZIP auditável também é composto pelo owner a partir dessas
mesmas exportações, com manifesto de revisão, hashes, aprovação, snapshot e
build. Uma ação separada, com confirmação explícita, registra os dois pacotes
como snapshot oficial: reutiliza `governanca_publicacoes` e
`publicacao_registrada`, persiste os bytes, revalida todas as aprovações sob
lock e muda os heads para `emitido` na mesma transação. A reabertura lê os
bytes persistidos. O documento único consolidado continua pendente.

A preparação G4 de alvo único agora pode ser aceita ou rejeitada na superfície
operacional. Ao aceitar, a ponte entrega ao canvas somente o plano nativo já
compilado e selado pelo owner, vinculado à revisão/hash de origem e ao hash de
destino. O host aplica o comando na Session viva, confere os bytes resultantes,
emite um checkpoint com o mesmo `operation_id` e aguarda o commit atômico do
owner antes de ACK. Resultado divergente executa o Undo do próprio grupo e
confere a restauração da origem; nunca vira checkpoint. O recibo confirmado
entra no Histórico e a pilha nativa permanece disponível para Undo posterior.
Lotes com mais de um canvas continuam bloqueados nesta UI até haver coordenação
atômica de todos os componentes.

A Session viva também pode responder a uma solicitação explícita de seleção.
O evento fica ligado ao documento, revisão e hash limpos e é invalidado por
qualquer edição ou ACK de nova revisão. Posições e texto do navegador não
autorizam paths: a camada contextual exige que o texto seja o conteúdo integral
de exatamente um bloco da projeção backend e que exatamente um finding
autocorrigível, sem fonte material pendente, permita esse path. Seleção parcial,
duplicada, bloqueada ou stale é recusada. O usuário pode fornecer o texto
substituto ou pedir uma sugestão ao gateway GovBot existente. A resposta do
modelo continua declarativa, restrita ao único path permitido, e é recompilada
pelo mesmo owner G4; explicação, fonte ou alvo divergente não viram proposta.

A trilha de auditoria contextual agora também pode ser executada sem preparar
ou gravar um patch. O owner lê as heads autorizadas, reconstrói as projeções e
devolve relatório e snapshot ligados às revisões e hashes correntes. Achados de
consistência continuam pertencendo a `consistencia.py`: seu endereço textual
legado só é traduzido para uma âncora nativa quando o bloco completo possui
paridade exata com um único parágrafo editável da mesma cláusula e o achado
declara fonte material. Duplicidade, bloqueio, texto divergente, fonte ausente
ou endereço sem correspondência deixam o achado manual e sem path autorizado.
Na superfície operacional, o usuário escolhe esse achado e prepara a correção
pelo mesmo `CorrecaoContextual`, propositor e `DocumentoService.preparar_patches`
de G4. A preparação relê fontes e heads, reaudita o resultado e permanece sem
persistência até a confirmação explícita já existente.

Pareceres já ingeridos e normalizados pelo owner legado também podem ser
carregados, sob a RLS do cliente autenticado, no painel do mesmo documento.
`parecer_correcao.situar` continua responsável por classificar recomendação
objetiva, decisão administrativa, dado faltante, ambiguidade e conflito. Uma
recomendação classificada como objetiva só recebe âncora nativa quando uma
citação literal do próprio achado identifica exatamente um bloco permitido;
sem essa prova, ela permanece manual mesmo que tenha nomeado a cláusula. A
origem preserva os IDs do parecer e do achado e o painel é invalidado quando a
head muda. Este incremento é deliberadamente somente leitura: aplicação e
relatório persistente de atendimento no modelo nativo ainda são pendências,
pois não é seguro considerar a instrução jurídica como texto substituto.

A aba Evidências agora pode carregar os fatos canônicos correntes pelo mesmo
RPC privado usado pelo owner de patches. Cada item preserva ID, path, origem,
versão, hash e um trecho limitado do valor. `confirmado` só aparece como
`VERIFICADO` quando a origem existe e o hash canônico confere; `extraido`,
`disputado`, hash divergente, estado desconhecido e versão substituída mantêm
respectivamente os estados `NAO_VERIFICADO`, `REVISAO_HUMANA`, `PENDENTE` ou
`INDISPONIVEL`. A projeção não consulta a internet, não chama embeddings/LLM,
não interpreta busca vazia como inexistência e é invalidada quando a head muda.

`src/wordcraft_runtime.py` admite somente configuração de servidor, executável
absoluto e o namespace exato `static/wordcraft`. Confere pin upstream, hash do
manifesto, inventário fechado, hashes/tamanhos dos assets, cabeçalho WASM,
origem sem credenciais e os treze avisos/licenças. O status interno
`INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED` é recusado; somente um artefato
com status explícito `GOVCONNECT_WORDCRAFT_DEPLOY_APPROVED` pode montar o host.
A migration apenas registra `flag_wordcraft_editor=false`; nada foi ativado.

## Evidência automatizada deste incremento

- as três origens mutáveis compilam para o mesmo contrato G4;
- preparação integrada executa o motor nativo e a reauditoria sem chamar o RPC
  de gravação;
- finding, caminho e fonte falsos são recusados;
- a auditoria corrente é somente leitura e fica ligada às heads nativas;
- achado de consistência com paridade exata e fonte é traduzido para UUID
  nativo, corrigido pelo owner e encerrado na reauditoria sem RPC de gravação;
- paridade duplicada, bloqueada, divergente ou sem fonte falha de modo fechado;
- parecer normalizado é relido pela RLS, classificado pelo owner existente e
  ligado a uma âncora somente com citação literal única; leitura não grava;
- fatos canônicos exibem proveniência e status sem promover extraído, disputado
  ou hash divergente a evidência verificada;
- parecer ambíguo permanece pendente;
- alteração posterior de logo ou signatário não muda o snapshot capturado;
- 210 itens preservam numeração e total decimal;
- o modelo de painel reúne as seis capacidades sem expor ação de persistência.
- o host recusa patch stale, excessivo ou com hash de destino divergente,
  correlaciona exatamente operação/checkpoint/recibo e não ACKa antes do commit.

## Pendências para fechar G5

1. ampliar a prova no navegador WASM real já existente para cobrir geração
   pelo GovBot, confirmação backend, Undo posterior e stale end-to-end;
2. completar as trilhas A–D do corpus, incluindo auditoria e parecer reais;
3. consumir catálogo institucional, RAG vigente e montagem oficial pelos
   owners existentes em ensaio end-to-end;
4. provar isolamento entre tenants e o fluxo completo em sessão JWT real.

Também falta produzir e homologar o artefato com status operacional. O bundle
atual de QA não satisfaz esse requisito e não foi promovido por renomeação.

Nenhuma funcionalidade legada foi removida. G6 permanece pendente até haver
prova de substituição e autorização específica para a retirada.
