# GovDocs Wizard — instruções do projeto

App Streamlit que gera documentos da fase preparatória de licitações
(Lei 14.133/2021): DFD → ETP → TR → Edital, com RAG e Supabase.

## Regras permanentes

- **Design/front-end**: SEMPRE aplicar os skills `design-taste` e
  `design-minimalist` (fonte: ewertonmarinho51-dev/Front-End-Bonito) em
  qualquer trabalho de UI/CSS/layout. Contexto: setor público —
  sobriedade, credibilidade e acessibilidade prevalecem sobre estética;
  paleta institucional azul (#1B4F8A) definida em `.streamlit/config.toml`
  e `src/ui/components.py`.
- **Comunicação**: skill `caveman` ativo (respostas curtas; código,
  comandos e erros exatos).
- **IA do produto**: OpenAI motor principal (`gpt-5-mini` padrão),
  fallback Gemini. Chaves só em `.streamlit/secrets.toml` (gitignored)
  — NUNCA commitar segredos.
- **Memória entre sessões**: consultar/atualizar
  `memorias/projeto-saas-govdocs.md` no repo
  ewertonmarinho51-dev/memoria-do-claudinho (início de sessão e a cada
  marco).
- **Testes**: `python -m pytest -q` (19+ testes, modo demo, sem rede).
  Rodar antes de qualquer push. CI: GitHub Actions em todo push.
- **Banco**: Supabase projeto `nxibohgoekphxblqtqku`; migrações
  versionadas em `supabase/migrations/` (aplicar via MCP ou SQL Editor).
- **Git**: trunk `main`; trabalho em
  `claude/procurement-docs-wizard-rhfl5o`. Usuário autorizou merge
  direto na main. Textos de commit em português.
