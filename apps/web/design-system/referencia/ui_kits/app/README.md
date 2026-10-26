# UI kit — Gov Conect web app

Click-through recreation of the Next.js app (`apps/web`) shell plus the modules seen in the Streamlit screenshots, composed entirely from the design-system components.

- `index.html` — entry; login state + route persisted in localStorage (`gc-kit-auth`, `gc-kit-route`).
- `Shell.jsx` — `AppShell` (Sidebar + Topbar + optional GovBot panel), `PageHead`.
- `LoginScreen.jsx` — split brand panel / form (from `app/entrar/page.tsx`).
- `HomeScreen.jsx` — KPIs, alert, recent processes list (from `app/app/page.tsx`, `lista-processos.tsx`).
- `ProcessesScreen.jsx` — tabs, search/filters, sortable selectable table, row menu, delete dialog.
- `NewProcessScreen.jsx` — Dados da demanda form → AI generation progress → DFD document viewer.
- `PriceResearchScreen.jsx` — cotação, stage 3 Triagem: item nav, screening counters/filters, dispersion plot, reference rows with justified exclusion dialog, sources, comparison chart, cesta, stats, traceability dialog (from `app/app/precos/[id]/page.tsx` + screenshots).
- `PriceStages.jsx` — stage 4 Mapa de preços (matrix) and stage 5 Relatório (validation summary with blocking vs warning, report options, emission progress). Stepper: click completed steps to go back.
- `GovBotScreen.jsx` — full-page GovBot: conversation history, context bar, cited answer with AI draft → insert/discard review, feedback, sources panel, new-conversation suggestions.
- `GovBotPanel.jsx` — side conversation with suggestions, citations and sources.

Data is illustrative. Not built: Base de conhecimento, Governança, Administração, Parecer jurídico screens (visible in screenshots, compose from the same parts).
