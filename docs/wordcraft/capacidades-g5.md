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
build. Ele registra `official_emission=false`: o documento único consolidado e
a emissão oficial ainda permanecem pendentes.

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
- parecer ambíguo permanece pendente;
- alteração posterior de logo ou signatário não muda o snapshot capturado;
- 210 itens preservam numeração e total decimal;
- o modelo de painel reúne as seis capacidades sem expor ação de persistência.

## Pendências para fechar G5

1. executar seleção/contexto real do GovBot, diff, confirmação, Undo e rejeição
   stale no mesmo canvas;
2. completar as trilhas A–D do corpus, incluindo auditoria e parecer reais;
3. consumir catálogo institucional, RAG vigente e montagem oficial pelos
   owners existentes em ensaio end-to-end;
4. provar isolamento entre tenants e o fluxo completo em sessão JWT real.

Também falta produzir e homologar o artefato com status operacional. O bundle
atual de QA não satisfaz esse requisito e não foi promovido por renomeação.

Nenhuma funcionalidade legada foi removida. G6 permanece pendente até haver
prova de substituição e autorização específica para a retirada.
