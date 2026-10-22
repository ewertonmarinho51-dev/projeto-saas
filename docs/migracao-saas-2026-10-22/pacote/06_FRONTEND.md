# Direção de produto e design — Gov Conect
## Brief
Sistema SaaS para planejamento de contratações públicas. Públicos: servidores, gestores e equipes de pesquisa de preços. Promessa: eficiência com rastreabilidade, revisão humana e conformidade; jamais 'IA faz toda a licitação sem revisão'.

## Identidade
- Logo oficial no pacote `assets/logo-original.png` (ícone azul de documento/checks, fundo branco). Preservar proporção; evitar redesenho por IA, distorção, efeito neon ou inventar marca/slogan.
- Cores iniciais: azul do logo, azul profundo, branco/off-white e cinza-neutro; amostrar os HEX da **própria imagem** antes de fixar tokens. O legado usa `#1B4F8A`, mas não forçar se conflitar com logo; harmonizar tokens.
- Tipografia moderna legível (p.ex. Inter ou Geist) sem título grotesco; escala modular e leitura confortável. Acessibilidade WCAG 2.2 AA.
- Glassmorphism **contido** no hero/login ou cards de contexto (transparência leve, borda sutil, blur baixo), nunca em tabelas, densos relatórios nem textos longos. Contraste validado.
- Hover states reais (botões, linhas, navegação, cards), focus-visible de teclado, reduced-motion; nada que dependa apenas de hover no mobile.

## Páginas prioritárias
1. `/`: hero público com logo, headline direta, 2 CTAs ('Conhecer a plataforma' e 'Entrar'), visualização editorial do fluxo DFD→ETP→TR→Pesquisa de Preços→Documento/Relatório, seção produto, confiança e FAQ. **Sem promessas não verificadas ou números falsos.**
2. `/entrar`: layout responsivo em dois painéis desktop: painel marca/motion sutil + formulário acessível. Login Supabase Auth real; erros genéricos, feedback, recuperar acesso, loading, bloqueio de brute force; link para política de privacidade. Sem auto-cadastro de administrações públicas sem fluxo definido.
3. `/app`: dashboard funcional com processos recentes, pesquisa de preços, documentos em elaboração, tarefas pendentes e status de jobs.
4. `/app/processos`: lista/pesquisa/criação/abertura/retomada; sidebar compacta.
5. `/app/precos`: seleção de itens, filtros de fonte, coleta assíncrona, triagem da cesta, estimativa, evidência verificável e emissão; sem esperar UI por consulta externa.
6. `/app/documentos`: integrar o editor já desenvolvido, sem recriar WordCraft.
7. `/app/configuracoes`: perfil, tenant, usuários permissões, fonte de dados e consumo (por papéis).

## Comportamentos
- Cargas de 210 itens: virtualização ou paginação, salvamento incremental e estados claros, sem re-render integral ao retirar item.
- Design system: tokens CSS, primitives (Button, Input, Table, Badge somente quando semântico, Dialog, Skeleton, Toast), componentes que mostram empty/loading/error/success, RSC quando possível e client components isolados.
- Branding animation: `motionmaxxing` é para **gerar um MP4/WebM da logo**, não para animar formulário ou autenticação com vídeo obrigatório. MP4/WebM decorativo em seção marca/login com poster estático, autoplay muted loop playsInline; pause/reduced-motion; nada de vídeo bloqueando TTI/LCP nem peso de vários MB. Revisar licenças/asset original.
- Diagramas na landing em **HTML+SVG responsivos e acessíveis**, usando `diagram-design`; cards como conteúdo real e clicável apenas quando fazem algo.

## Gate visual com Playwright
Viewport 375×812, 768×1024, 1440×900 e 1920×1080. Screenshot hero, login, dashboard, preços; revisar console errors, requests quebradas, layout shift, navegação teclado, contraste, alvos de toque, focus-visible e conexão de fluxo real com API. Não aceitar só screenshot bonita: cliques reais devem funcionar.
