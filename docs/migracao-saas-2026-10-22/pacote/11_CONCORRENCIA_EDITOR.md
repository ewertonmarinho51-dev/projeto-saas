# Política de convivência: outro agente altera editor/WordCraft
**Proibição inicial:** não modificar `src/documentos_editor.py`, `src/wordcraft_*.py`, `integrations/wordcraft/**`, migrations `20261015*`–`20261018*` ou workflows `wordcraft-*` sem acordo formal entre frentes. Conferir novos paths pelos diffs PR atuais.

1. Criar `git worktree add ../govconect-web -b claude/migracao-nextjs-api origin/main` (se branch já existe, escolher slug novo); não dar `git checkout` na pasta usada pelo outro agente.
2. Executar `git status`, `git log -5`, `git branch -a`, listar PRs e capturar HEAD; identificar alterações de editor pendentes, conflitos em `src/db.py`, `src/auth.py`, migrations e CI.
3. Criar interfaces/adapters na API em área nova e adicionar **contract tests** com mocks mínimos e verificação da estrutura real. Não copiar código do editor nem gerar novo editor rico.
4. Não assumir schema definitivo: ler migrations e serviço de persistência WordCraft, implementar feature flag `documents_next_ui` off até adapter bater teste de integração.
5. Após PR do outro agente aprovado: atualizar worktree pelo `main`, mapear modificações, rodar `pytest` e workflows WordCraft + testes de contrato. Se conflito, abrir documento de compatibilidade; não forçar `git reset --hard` nem descartar alterações de terceiros.
6. Separar PRs: F1 API, F2 login/shell, F3 preços, F4 editor adapter; **nunca** merge automático.

## Contrato provisório do editor
Input: `process_id`, `document_id`, `expected_version`, `patches` válidos e identidade server-side. Output: `document_id`, `version`, `content_revision`, status de aprovação, `updated_at` e `audit_ref`. Reusar modelo canônico WordCraft real; **não** impor JSON arbitrário até mapear o domínio e migrações atuais.
