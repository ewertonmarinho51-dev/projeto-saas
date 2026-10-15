# Proveniência do motor por revisão

Inventário e decisão anterior à implementação da extensão G2. Responsável único continua `DocumentoService`; bytes, CAS, escopo JWT e RLS continuam nas tabelas e funções documentais existentes. Não cria motor, autenticação ou storage paralelos.

Cada revisão nova registra `engine_build_sha256`, o SHA-256 do manifest configurado no servidor e verificado pelo worker nativo antes do commit. O manifest contém os hashes de JS/WASM e a referência upstream. O componente e claims do usuário não fornecem esse campo. A revisão também expõe `validation_provenance`, calculada pelo banco a partir da presença do hash.

Revisões anteriores à migration permanecem com hash nulo e `legacy_unrecorded`: reabrir e validar hoje não prova qual bundle as validou no passado. A migration não inventa nem retroatribui esse dado. Um CHECK `NOT VALID` preserva essas linhas e exige hash válido em toda inserção futura. A tabela já nega UPDATE/DELETE/TRUNCATE ao papel de servidor; a coluna gerada não admite atribuição pelo chamador.

A RPC interna recebe o hash como argumento obrigatório, continua `SECURITY INVOKER` com EXECUTE somente para `service_role`, e retorna o hash/proveniência do registro confirmado. A assinatura anterior de oito argumentos é removida na mesma transação: não permanece um caminho de escrita que omite o build. A identidade idempotente inclui o build; repetir a operação com outro build retorna conflito e preserva o registro original.

Abrir um documento devolve a proveniência persistida separada da validação executada pelo runtime atual. Exportar devolve hash/revisão da fonte, build/proveniência que validaram essa revisão e build do runtime exportador. Esses metadados acompanham os bytes, mas ainda não constituem armazenamento imutável do artefato nem emissão/aprovação institucional.

Arquivo novo: migration gerada com `supabase migration new documentos_editor_proveniencia`; a migration documental já aplicada não será editada. Consumidores alterados: `src/documentos_editor.py`, contratos unitários/SQL e inventário de argumentos do ensaio HTTP. A sequência descartável aplica a nova migration após a primeira documental e mantém 0027 por último. Nenhuma aplicação remota ou no laboratório vivo `wordcraft_qa_ready` faz parte desta alteração.

Verificação necessária: migração real sobre revisão legada, hash obrigatório em novas linhas, retry exato, retry com build divergente, concorrência CAS, histórico imutável, RLS, assinatura antiga ausente e grants das funções. A adição de coluna gerada armazenada pode reescrever a tabela e adquirir lock: planejar janela e medir antes de qualquer futura aplicação autorizada em ambiente compartilhado.

Verificação executada em PostgreSQL 16.15 portátil, somente em bancos novos descartáveis do loopback: 45 testes do owner/proveniência passaram; a combinação com contenção SQL e histórico passou com 349 testes e 126 skips de integrações externas não configuradas. O ensaio de upgrade criou uma revisão pela RPC antiga, aplicou o arquivo novo exato e comprovou preservação dos bytes/hash/operação e hash de build nulo. A próxima revisão registra o build; retry que tentaria atribuir build à antiga conflita. A suíte também executou dois escritores reais concorrentes, escopos de tenant e revogação de perfil.

Advisors oficiais executados sobre um terceiro banco descartável depois do schema completo: saída 0, 16 avisos já pertencentes ao schema-base (13 `auth_rls_initplan`, dois `extension_in_public`, um `multiple_permissive_policies`); nenhum aviso identifica as tabelas/funções documentais. Isso não é uma certificação global de segurança. Os bancos próprios foram descartados pelo harness. Não foi aplicada a migration no laboratório já existente ou remotamente.

Limite: o hash do manifest identifica exatamente a configuração validada, mas a retenção duradoura dos manifests e bundles de cada build continua necessária para reproduzir versões históricas. Não transformar esse identificador em alegação de que os binários históricos já estão arquivados com política definitiva.
