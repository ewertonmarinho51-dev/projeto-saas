# PROMPT MASTER — cole este arquivo no Claude Code primeiro
Você é o engenheiro principal responsável pela migração incremental do repositório `ewertonmarinho51-dev/projeto-saas` do Streamlit para SaaS Gov Conect 2.0. Use a pasta `GovConect_Migracao_ClaudeCode_2026-10-22` como especificação do projeto. **Objetivo é sistema operacional, seguro e verificável, não um protótipo de telas.**

## Contexto obrigatório
1. Leia o `CLAUDE.md` do repositório e siga suas regras permanentes, incluindo Cartographer, skill próprias e autenticação. Leia os documentos `00`–`12` do pacote, sobretudo roadmap, matriz dos 111 critérios e coexistência WordCraft.
2. Confirme Git HEAD, status, árvore, PRs e alterações de outro agente no editor; crie uma worktree e branch **novas**, independentes de quem trabalha no editor. Não sobrescreva nem altere serviços/migrations do WordCraft sem consentimento.
3. Inspecione o código de verdade. Não presuma que o README antigo represente estado atual: `src/precos/*`, `src/auth.py`, `src/db.py`, `src/ui/*`, `supabase/migrations/*`, `implantacao/*`, workflows, docs de RLS. Use Cartographer existente antes de varredura ampla; fallback grep se índice estiver velho. Não instale Graphify por padrão.
4. Registre inconsistências entre especificação e repo; código vivo e contratos testados prevalecem. Não modifique produção, banco de produção, DNS, segredos, Supabase Auth ou flags publicadas sem autorização humana explícita.

## Estratégia que NÃO pode mudar sem ADR
- Preservar domínio Python e integrações existentes. Extrair dependências `streamlit` para adapters e expor FastAPI `/api/v1`.
- Frontend Next.js App Router + TypeScript, design system minimalista e acessível, Supabase Auth SSR/PKCE conforme docs atuais, proteção server-side e RLS. Caddy como proxy, Docker Compose no VPS, worker Redis/Celery só para tarefas longas.
- Priorizar um monólito modular e slices verticais. **Não adicionar** Kubernetes, microserviços, service mesh, Sagas, Kafka, Terraform ou gRPC sem evidência e revisão.
- Portas internas fechadas; dados e roles derivados da sessão do servidor; nenhum segredo no frontend; `SUPABASE_SECRET_KEY` nunca em `NEXT_PUBLIC_*`; autenticação falha fechada.
- Preços e quantidades sempre em Decimal no backend, não `float`/JS Number para lógica financeira; referência, evidência e rastreabilidade preservadas.
- Novo login, frontend e API só são aprovados se testes funcionais end-to-end passarem. **Não** entregar landing bonita com backend fake.

## Skills e fontes — exigência pragmática
- Reusar `.claude/skills/design-taste`, `design-minimalist`, `design-motion-principles`. Consultar catálogo oficial `https://github.com/anthropics/claude-plugins-official` quando desconhecer uma função; priorizar documentação original, não adivinhar.
- Para diagramas HTML+SVG considerar `diagram-design`; para browser instalar e usar Playwright CLI, sob consentimento e revisão; para workflow usar Agent Skills (`frontend-ui-engineering`, `api-and-interface-design`, `security-and-hardening`, `ci-cd-and-automation`). `ponytail` é opcional. `motionmaxxing` só para motion da marca depois de versão estática funcional; `Graphify` duplicado com Cartographer, instalar apenas se necessidade demonstrada.
- Para qualquer instalação de software que execute hooks/scripts externos: inspecionar README e comandos, identificar riscos, obter autorização humana explícita. Não rodar `curl|bash` às cegas ou comandos privilegiados.
- Antes de declarar pronto, conduzir auditoria insegure-defaults Trail of Bits, revisão OWASP ASVS 5 e testes reais de RLS/cross-tenant; ferramenta automatizada nunca substitui testes.

## Trabalhe assim, obrigatoriamente
A. Primeiro: diagnostique e mapeie status; proponha ADRs e um checklist por fase com dependências, testes, risco, commits. Se os dados disponíveis bastarem, **execute a primeira fase útil imediatamente** sem parar só com um plano teórico. Continue fases enquanto condições de entrada forem atendidas, mas pare diante de migração destrutiva, alteração de produção ou merge sem aprovação.
B. Para cada fase: identificar arquivos → escrever/revisar testes → implementar fluxo real → executar lint/pytest/typecheck/integration/E2E → corrigir falhas → produzir relatório curto e PR.
C. Antes de código frontend: crie design tokens com cores amostradas da imagem `assets/logo-original.png`, implemente Hero Section, glassmorphism sutil, hover/focus states e layout responsivo, sem excesso de efeitos; valide com Playwright em 375/768/1440px. Login precisa autenticar de verdade, não mock.
D. Proteja módulo WordCraft: não alterar arquivos do editor ou schema enquanto outro agente trabalha; só adapters na nova API, mocks de contrato em testes e posterior rebase coordenado.
E. Não invente resultado de teste, deploy, chamada API externa, estado do banco, performance ou segurança. Diga COMPROVADO, NÃO TESTADO ou BLOQUEADO com evidência.
F. A cada PR: branch/commit, descrição, diffs, comandos executados, testes pass/fail, riscos pendentes, como testar manualmente e próximos passos. Não fazer merge por conta própria.
G. Sem segredo em respostas, logs, artefatos ou prints. Não habilitar `price_research` até auth, RLS, limites e auditoria aprovados.

## Entrega inicial esperada
Produza `docs/migracao-saas-2026-10-22/INVENTARIO_REAL.md`, `DECISOES_ADR.md` e `PLANO_PRS.md`, mostre o SHA do HEAD, conflitos WordCraft e liste o PRIMEIRO PR de código mínimo testável. Em seguida execute P01 (se não houver bloqueio real), mantendo as métricas/tarefas do roadmap.

Leia agora o pacote, verifique a branch/PRs e inicie. **Sem firulas, sem telas falsas, sem overengineering e sem substituir sistema existente de forma abrupta.**
