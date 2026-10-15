# Snapshot institucional: inventário e elo documental

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

O elo que falta no owner WASM é vincular os fatos institucionais a uma revisão nativa exata. Proposta: registrar na revisão um envelope privado derivado, com hash forte, escopo do processo/tenant/secretaria e fase `draft_reference`; conter identidade resolvida, data de referência, portaria e signatários elegíveis escolhidos em `processos.dados.signatarios_escolhidos`. Todos os dados vêm de SELECT do cliente autenticado e das funções puras existentes. O componente não fornece nomes, cargos, números, imagens ou fase de aprovação. Ausência de identidade/portaria continua ausência explícita, nunca preenchimento inventado.

Cada revisão/artefato deve continuar ligado ao snapshot que lhe pertence. Alteração posterior do cadastro não reinterpreta a história. Checkpoints e restaurações preservam o vínculo existente; atualizar o contexto aplicado exige novo ato explícito e uma revisão nova. Históricos sem snapshot permanecem sem prova registrada, sem backfill retroativo. Na importação Markdown, o exportador canônico pode aplicar a identidade/bloco provenientes desse mesmo envelope antes de passar os bytes ao WordCraft. Um DOCX externo ou checkpoint já estruturado não pode ter seu timbrado silenciosamente substituído; nesses caminhos o envelope é referência de contexto, sem alegação de aplicação visual.

Impedimento concreto da aprovação: `processos.aprovados` não identifica document_id/revision/content_hash nativos. O botão atual aprova Markdown e seu congelamento é best-effort; ele não prova que uma revisão WASM editada foi aprovada. O owner não pode marcar nativo como aprovado com base apenas nesse conjunto ou em ter capturado um snapshot. É necessário adaptar o ato canônico para vincular a revisão exata e seu snapshot, mantendo elegibilidade, validação e auditoria. Até isso existir, a fase capturada é referência de rascunho e não emissão/assinatura/ato aprovado.

Plano para o ato único posterior: `state.aprovar_e_avancar` deve encaminhar o vínculo nativo confirmado ao mesmo owner, em vez de escrever um segundo indicador independente. O vínculo inclui documento/revisão/hash, índice e snapshot; buffer dirty ou revisão obsoleta bloqueiam. O owner revalida elegibilidade e conteúdo e registra o ato atomicamente, sem inferir consentimento da captura. Aprovação individual e emissão do pacote continuam estados distintos: o gate final de `ui.steps` exige fatos/conhecimento, `qualidade.avaliar_gate`, revalidação atual e `ui.revisao.emissao_liberada` para o bundle exato. Este último hoje calcula `blocos.hash_bundle` sobre Markdown; adaptar a evidência de revisão ao conteúdo nativo exige o adaptador estruturado e não pode ser substituído por um APPROVED antigo. Não há chamada de IA necessária para esse vínculo.

`application=applied_by_govconnect_docx` documenta a aplicação no momento da conversão Markdown/captured_for_revision; não certifica que edições manuais posteriores mantiveram todos os blocos institucionais intactos. `reference_only` não afirma aplicação visual. A prova entre conteúdo renderizado e snapshot continua requisito de G3 e do futuro ato de emissão.

Retenção existente: as tabelas de identidade/signatários negam UPDATE/DELETE/TRUNCATE de rede, mas suas FKs para processo são ON DELETE CASCADE por decisão explícita da migration 0025; isso não equivale a retenção independente do processo. Os documentos nativos já restringem exclusão do processo por FK RESTRICT e suas revisões são append-only. Não mudar silenciosamente a política geral de exclusão de processos nesta integração. O vínculo por revisão nova deve usar essa imutabilidade existente. A retenção duradoura de bundles/artefatos e a vinculação de uma emissão aprovada continuam requisitos abertos.

A janela de prova G2 de 16 argumentos foi encerrada pelo integrador antes da mudança final. O opt-in temporário foi removido do construtor/código e a migration institucional de 18 argumentos entrou na sequência única, antes da 0027. O banco G2 preservado não é migrado silenciosamente: os ensaios desta etapa criam bancos novos. Restauração usa o snapshot histórico de sua revisão fonte quando registrado, com referência explícita à fonte; se ausente, registra somente uma referência atual, sem inventar contexto passado.

Provas planejadas: fonte somente backend, escopo de outro tenant recusado, elegibilidade/portaria reaproveitadas, alteração posterior de logo/cargo/portaria não altera snapshot registrado, retry preserva o mesmo snapshot, metadados não promovem aprovação, história antiga permanece desconhecida e leitura/exportação nunca substitui a cópia por cadastro atual. Novas migrations somente via CLI e ensaiadas em bancos novos descartáveis, sem laboratório vivo ou remoto.

Verificação do contrato final único de 18 argumentos: 85 provas direcionadas passaram; a combinação com índices, CAS/RLS/contenção, migrações e mecanismos institucionais existentes passou com 529 testes e 126 skips de integrações externas não configuradas, em 46,84 s. Inclui upgrade real sem backfill, fonte backend, elegibilidade, brand/cargo/portaria alterados depois da captura, retry exato, metadados privados/imutáveis, assinatura da RPC antiga ausente, rejeição de fase approved e restauração que retorna ao snapshot de uma fonte conhecida mesmo após a referência corrente mudar. A importação Markdown foi inspecionada em OOXML com cabeçalho e assinatura congelados. Motor e transporte são stubs nos testes unitários do owner; os ensaios SQL executam PostgreSQL real e não certificam fidelidade nativa visual.

Advisors oficiais do arquivo exato em banco novo descartável: exit 0, 16 avisos do schema-base e nenhum referente às tabelas/funções documentais. Não é certificação global de segurança. Evidência: `outputs/tests-wordcraft-snapshot-institucional-final-integracao.xml`. Não houve aplicação ao banco G2 preservado, ambiente remoto, produção, alteração de flags, commit ou push nesta entrega.
