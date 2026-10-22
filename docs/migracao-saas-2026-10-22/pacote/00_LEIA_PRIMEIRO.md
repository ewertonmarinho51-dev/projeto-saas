# GOV CONECT — pacote de migração Streamlit → SaaS 2.0
**Data-base:** 2026-10-22. **Repositório:** https://github.com/ewertonmarinho51-dev/projeto-saas (`main`, verificar SHA antes de agir).

## Executar na ordem
1. Ler `01_DIAGNOSTICO.md`, `02_ARQUITETURA.md`, `03_ROADMAP_GATES.md`, `05_SEGURANCA.md`, `06_FRONTEND.md`, `07_SKILLS.md`, `08_CONTRATOS_API.md`, `09_QUALIDADE.md`, `10_DEPLOY.md` e `11_CONCORRENCIA_EDITOR.md`.
2. Copiar todo o pacote para `docs/migracao-saas-2026-10-22/` ou mantê-lo em diretório de trabalho separado. **Não sobrepor `CLAUDE.md` existente.** Fornecer ao Claude Code o arquivo `prompts/P00_MASTER.md` primeiro.
3. Depois, enviar um prompt por fase (`P01` a `P07`) após as condições de entrada de cada um serem verdadeiras. Anexar `assets/logo-original.png` ao repositório na branch de frontend antes de executar `P04`.
4. Para cada fase, exigir branch/PR isolados, relatório do que mudou, testes e bloqueios; nunca fazer merge, aplicar migração em produção ou realizar deploy irreversível sem aprovação humana explícita.

## Meta real
Frontend Next.js com hero, login, aplicação funcional; motor Python preservado; API FastAPI; tarefas pesadas assíncronas; Supabase Auth/RLS auditado; Docker/Caddy; CI e operação observável. **Não é uma ordem para implementar os 111 padrões imediatamente.** Classificação está em `04_MATRIZ_111.md`.

## Estado de honestidade
Este pacote foi produzido por análise da branch `main` via GitHub em 22/10/2026, não executou implementação, testes, instâncias nem migrações. A situação das migrações aplicadas no banco e a eficácia real de autenticação/RLS permanecem **a verificar**. Exemplos de rotas/configuração são contratos-alvo, não alegações de código já funcional.

## Primeiro resultado esperado do Claude
Inventário dos módulos reais + mapa de dependências + conflito com agente WordCraft + branch isolada + plano de commits + primeiro PR útil. Nada de substituir o Streamlit antes do caminho crítico estar integralmente reproduzido e validado.
