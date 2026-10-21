# Canário WordCraft em produção — 2026-10-21

## Escopo e estado final

O processo sintético `CANÁRIO WORDCRAFT — TESTE 2026-10-21` foi criado em
produção no tenant canário, por uma sessão autenticada, e permaneceu preservado
após o rollback. A flag global `flag_wordcraft_editor` permaneceu desligada.
Ao final do ensaio, a admissão `tenant_modulos.wordcraft_editor` do tenant foi
revertida para `habilitado=false`.

## Evidências observadas

| Verificação | Resultado | Evidência |
| --- | --- | --- |
| Criação do processo | PASS | Processo persistido, etapa 1, tenant e titular Auth preenchidos. |
| Dados sintéticos | PASS com desvio | Descrição, unidade, quantidade e fonte foram persistidas. A máscara converteu `12.34` para `1234.00`; a fonte perdeu o primeiro caractere durante a edição da grade. |
| Geração DFD pelo motor configurado | FAIL | Duas tentativas falharam em 0,2–0,3 s com HTTP 401: uma credencial OpenRouter estava configurada no caminho direto OpenAI. |
| Geração controlada sem IA | PASS | O modo demonstração preservou os dados e criou o rascunho do DFD. |
| Abertura exclusiva do WordCraft | FAIL fechado | A interface recusou montar o editor com `Configuração operacional do WordCraft incompleta.` |
| Edição, commit, reload e CAS | NÃO EXECUTADO | Dependem da admissão do runtime operacional. |
| Undo/Redo e patch | NÃO EXECUTADO | Dependem da admissão do runtime operacional. |
| Aprovação e emissão imutável | NÃO EXECUTADO | Dependem da admissão do runtime operacional. |
| DOCX, PDF e original | NÃO EXECUTADO | Nenhuma emissão WordCraft foi criada. |
| Latência | PARCIAL | Falhas do provedor foram registradas em 0,2–0,3 s; latência do editor não pôde ser medida. |
| Memória do navegador | NÃO EXECUTADO | O WASM não foi montado. |
| Rollback | PASS | A admissão do tenant foi desabilitada sem excluir o processo ou o rascunho. |

## Causa e correção de release

O release `v1.10.1` contém o gate fail-closed do WordCraft, mas a imagem não
instala Node, não monta um bundle operacional em `/app/static/wordcraft` e não
recebe as quatro variáveis `GOVDOCS_WORDCRAFT_*`. O artefato disponível no
ambiente de engenharia se declara `INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED`;
ele não pode ser promovido apenas trocando esse estado.

A correção de infraestrutura deste release instala Node, monta o bundle
externo como somente leitura e adiciona um instalador que exige SHA-256 do ZIP,
valida os hashes de todos os assets e recusa qualquer manifesto cujo estado não
seja `GOVCONNECT_WORDCRAFT_DEPLOY_APPROVED`. O canário só deve ser reativado
depois da produção legítima desse artefato e da correção da credencial ou do
roteamento do provedor de geração.
