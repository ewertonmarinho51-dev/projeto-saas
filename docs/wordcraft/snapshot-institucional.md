# Snapshot institucional: contrato implementado e evidência C07

Registro anterior ao código, requisitos 02/03/05. Nenhum novo cadastro, resolvedor de elegibilidade, identidade, portaria, assinatura ou aprovação será criado.

Fontes existentes:

| Responsabilidade | Autoridade atual |
| --- | --- |
| Tenant/secretaria/ator | contexto autenticado + processo autorizado no banco; o owner reconcilia JWT com perfil atual |
| Precedência visual | `contexto.resolver_identidade`: secretaria com identidade própria, depois secretaria padrão municipal, depois ausência explícita |
| Captura de identidade | `branding` e único cadastro/espelho `db.salvar_orgao` → `secretarias`; não criar outra biblioteca de logos |
| Estrutura e cláusulas reservadas | `perfis.PERFIS`, `perfis.clausulas_fixas`; equipe/assinatura é LOCKED, não escolha de LLM |
| Data do ato de equipe | `emissao.data_de_referencia`, usando criado_em do processo |
| Portaria | `portarias.resolver`, sem desempate arbitrário de portarias vigentes |
| Elegibilidade | `assinaturas.elegiveis` + `conferir_elegibilidade`; ativo, função, secretaria e vigência |
| Cópias históricas | `emissao.montar_identidade`, `montar_signatarios`, `assinaturas.montar_snapshot` |
| Renderização de assinatura | `emissao.bloco_de_assinaturas`, que lê somente cópias históricas |
| Aprovação atual | `state.aprovar_e_avancar` sobre Markdown, chama `instituicional_bridge.congelar_na_aprovacao`, depois autosave |
| Snapshots aprovados atuais | tabelas privadas `documento_identidades` e `documento_signatarios`, INSERT apenas, via helpers existentes de db |
| Exportação atual | `export.gerar_docx/gerar_pdf` aceitam branding e bloco de assinatura já congelados; não consultam cadastro vivo |

O owner WASM vincula os fatos institucionais a uma revisão nativa exata. Cada revisão registra um envelope privado derivado, com hash SHA-256, escopo do processo/tenant/secretaria e fase `draft_reference`; ele contém a linha completa da identidade resolvida (inclusive imagens e proporções), data de referência, portaria e signatários elegíveis escolhidos em `processos.dados.signatarios_escolhidos`. Todos os dados vêm de leitura autenticada do backend e das funções puras existentes. O componente não fornece nomes, cargos, números, imagens ou fase de aprovação. Ausência de identidade/portaria continua ausência explícita, nunca preenchimento inventado.

Cada revisão/artefato deve continuar ligado ao snapshot que lhe pertence. Alteração posterior do cadastro não reinterpreta a história. Checkpoints e restaurações preservam o vínculo existente; atualizar o contexto aplicado exige novo ato explícito e uma revisão nova. Históricos sem snapshot permanecem sem prova registrada, sem backfill retroativo. Na importação Markdown, o exportador canônico pode aplicar a identidade/bloco provenientes desse mesmo envelope antes de passar os bytes ao WordCraft. Um DOCX externo ou checkpoint já estruturado não pode ter seu timbrado silenciosamente substituído; nesses caminhos o envelope é referência de contexto, sem alegação de aplicação visual.

O ato nativo de aprovação vincula `document_id`, `revision`, `content_hash`, índice e snapshot em uma transação. Antes do ato, o owner relê as fontes autorizadas, recompõe o contexto institucional e exige igualdade com a referência congelada, além das validações de conteúdo, fatos, conhecimento e governança. A captura continua sendo referência de rascunho e não consentimento; somente o ato atômico registra aprovação.

Aprovação individual e emissão do pacote permanecem estados distintos. O owner de emissão relê o processo, exige o conjunto documental canônico e sua decisão de ARP, valida revisões aprovadas exatas e registra a emissão de forma independente. Não há chamada de IA necessária para o vínculo institucional.

`application=applied_by_govconnect_docx` documenta a aplicação no momento da conversão Markdown/captured_for_revision; não certifica que edições manuais posteriores mantiveram todos os blocos institucionais intactos. `reference_only` não afirma aplicação visual. A prova entre conteúdo renderizado e snapshot continua requisito de G3 e do futuro ato de emissão.

Retenção existente: as tabelas de identidade/signatários negam UPDATE/DELETE/TRUNCATE de rede, mas suas FKs para processo são ON DELETE CASCADE por decisão explícita da migration 0025; isso não equivale a retenção independente do processo. Os documentos nativos já restringem exclusão do processo por FK RESTRICT e suas revisões são append-only. Não mudar silenciosamente a política geral de exclusão de processos nesta integração. O vínculo por revisão nova deve usar essa imutabilidade existente. A retenção duradoura de bundles/artefatos e a vinculação de uma emissão aprovada continuam requisitos abertos.

A janela de prova G2 de 16 argumentos foi encerrada pelo integrador antes da mudança final. O opt-in temporário foi removido do construtor/código e a migration institucional de 18 argumentos entrou na sequência única, antes da 0027. O banco G2 preservado não é migrado silenciosamente: os ensaios desta etapa criam bancos novos. Restauração usa o snapshot histórico de sua revisão fonte quando registrado, com referência explícita à fonte; se ausente, registra somente uma referência atual, sem inventar contexto passado.

Provas executáveis: fonte somente backend, escopo de outro tenant recusado, elegibilidade/portaria reaproveitadas, alteração posterior de cabeçalho, rodapé, imagens, proporções, cargo, nome e portaria não altera um byte do snapshot registrado, retry preserva o mesmo snapshot, metadados não promovem aprovação, história antiga permanece desconhecida e leitura/exportação nunca substitui a cópia pelo cadastro atual. As migrations foram ensaiadas apenas em bancos locais descartáveis, sem laboratório vivo ou remoto.

Verificação do contrato final único de 18 argumentos: 85 provas direcionadas passaram; a combinação com índices, CAS/RLS/contenção, migrações e mecanismos institucionais existentes passou com 529 testes e 126 skips de integrações externas não configuradas, em 46,84 s. Inclui upgrade real sem backfill, fonte backend, elegibilidade, brand/cargo/portaria alterados depois da captura, retry exato, metadados privados/imutáveis, assinatura da RPC antiga ausente, rejeição de fase approved e restauração que retorna ao snapshot de uma fonte conhecida mesmo após a referência corrente mudar. A importação Markdown foi inspecionada em OOXML com cabeçalho e assinatura congelados. Motor e transporte são stubs nos testes unitários do owner; os ensaios SQL executam PostgreSQL real e não certificam fidelidade nativa visual.

Advisors oficiais do arquivo exato em banco novo descartável: exit 0, 16 avisos do schema-base e nenhum referente às tabelas/funções documentais. Não é certificação global de segurança. Evidência: `outputs/tests-wordcraft-snapshot-institucional-final-integracao.xml`. Não houve aplicação ao banco G2 preservado, ambiente remoto, produção, alteração de flags, commit ou push nesta entrega.
