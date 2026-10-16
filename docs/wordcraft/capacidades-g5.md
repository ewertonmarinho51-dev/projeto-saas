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
no laboratório sintético enquanto não existe host WordCraft operacional no
wizard.

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

1. ligar o host WordCraft ao fluxo operacional autenticado do wizard;
2. executar seleção/contexto real do GovBot, diff, confirmação, Undo e rejeição
   stale no mesmo canvas;
3. completar as trilhas A–D do corpus, incluindo auditoria e parecer reais;
4. consumir catálogo institucional, RAG vigente e montagem oficial pelos
   owners existentes em ensaio end-to-end;
5. provar isolamento entre tenants e o fluxo completo em sessão JWT real.

Nenhuma funcionalidade legada foi removida. G6 permanece pendente até haver
prova de substituição e autorização específica para a retirada.
