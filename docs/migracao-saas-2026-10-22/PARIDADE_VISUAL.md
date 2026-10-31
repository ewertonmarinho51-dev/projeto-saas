# Paridade visual com o Claude Design — matriz por tela

Fonte da verdade visual: `apps/web/design-system/referencia/` (export de
23/10/2026), `DESIGN.md` e `apps/web/design-system/`. O UI kit do app é
**navegação simulada com dados ilustrativos**: dele vem o desenho, nunca o
comportamento nem os números. O comportamento é o do app real (API +
RLS), e nada aqui foi copiado de login simulado ou dado de demonstração.

## Como comparar

```bash
# referência, nos mesmos tamanhos (1440×900, 768×1024, 390×844)
node scripts/capturar-referencia.mjs            # em apps/web, com rede (unpkg)
# resultado, na pilha real: job web-e2e do CI → artefato "web-e2e-telas",
# pasta paridade/ (e2e/paridade.spec.ts)
```

A captura é evidência; o que reprova é a afirmação de comportamento na
spec (menu por papel, gaveta, recolher, âncora com destino, sem rolagem
lateral, movimento reduzido, sem erro de console).

## Auditoria de 31/10/2026 (Issue #152, PR D)

Esta seção substitui o que ficou desatualizado nas seções mais abaixo. Cada linha foi conferida contra o código, a referência e as capturas da pilha de CI, não contra o status de PR. Dados das capturas: sintéticos, da pilha descartável.

**Situação da paridade:** parcial. Site, login, casca, início e administração estão alinhados. Processos, preços e GovBot têm o desenho certo e lacunas funcionais declaradas abaixo. **O editor WordCraft não pode ser aprovado**: não há referência dele no Claude Design.

Legenda de fidelidade: ✅ alinhada · 🟡 parcial · ⛔ sem tela ou sem referência. Prioridade: P0 impede uso, P1 pede PR próprio, P2 melhoria, P3 opcional. `p95` é clique até o conteúdo na pilha de CI, sem a distância real: serve para comparar versões, não como promessa de produção.

| Tela | Design | Rota | API | Ações reais | Gaps | E2E | p95 (CI) | Prior. |
|---|---|---|---|---|---|---|---|---|
| Hero | ✅ `ui_kits/landing` | `/` | nenhuma | links reais do site | Nenhum relevante; navegação adaptada às seções existentes | `paridade`, `site`, `sessao`, `tema` | não medido | — |
| Site institucional | 🟡 sem tela própria na referência; segue `PublicSite` | `/solucoes`, `/como-funciona`, `/sobre`, `/contato`, `/privacidade` | nenhuma | links, contato por `GOVCONECT_CONTATO_EMAIL` | E-mail comercial depende de configuração | `site`, `tema` | não medido | P2 |
| Login e sessão | ✅ `LoginScreen.jsx` | `/entrar`, `/entrar/recuperar` | Supabase Auth | entrar, recuperar, continuar, sair e trocar de conta | "Manter conectado" não entra: a sessão já persiste | `fluxo`, `sessao`, `paridade` | não medido | — |
| Casca | 🟡 `Shell.jsx` | `/app/**` | `/me` | menu por papel, recolher, gaveta, sair | Sem sino, "Salvo" global e GovBot na barra superior: não há contrato. Trilha genérica para recurso | `paridade`, `auditoria` | — | P2 |
| Início | 🟡 `HomeScreen.jsx` | `/app` | `/processos`, `/precos/pesquisas` | atalhos e listas | Conta sobre até 100 processos; sem saudação (`/me` sem nome); sem total em R$ (soma de dinheiro só no servidor). **Proposta:** `GET /painel` | `paridade`, `auditoria`, `desempenho` | casca 29, conteúdo 331 (antes 99) | P2 |
| Processos | 🟡 `ProcessesScreen.jsx` | `/app/processos` | `GET/POST /processos` (`q`, cursor), `/modulos` | buscar, criar, abrir, dados da demanda, consolidar | Sem abas por situação, filtro de secretaria, ordenação, seleção e importação. Excluir e arquivar não existem na API e não podem ser simulados (a 0020 não dá DELETE). **Proposta:** `ordem` e `secretaria_id` em `GET /processos` | `paridade`, `fluxo`, `auditoria`, `desempenho` | casca 30, conteúdo 331 (antes 137) | P1 |
| Processo e documentos | 🟡 `NewProcessScreen.jsx` | `/app/processos/[id]`, `/formulario`, `/demandas` | `/processos/{id}`, formulário, demandas, `/documentos` | editar, preencher matriz, consolidar, abrir no editor (canário) | **Geração de DFD, ETP, Mapa de Riscos e TR não existe na interface nova** (M2/M3). Stepper de documentos e `AiProcessing` dependem disso | `formulario`, `demandas`, `fluxo`, `editor-documento` | não medido | P1 |
| WordCraft | ⛔ **sem referência** | `/app/processos/[id]/documentos/[documentoId]/editar` | `documentos_nativos` | abrir, salvar por ACK, histórico, revisão, exportar | Referência própria no Claude Design é pré-requisito da aprovação. CI sem WASM aprovado: ponta a ponta só no canário de produção. Painéis de GovBot e evidências sem endpoint | `editor-documento` (sem motor real) | não medido | P1 |
| Pesquisa de preços: lista e detalhe | 🟡 `PriceResearchScreen.jsx` | `/app/precos`, `/app/precos/nova`, `/app/precos/[id]` | `/precos/pesquisas` e filhas | criar, importar, coletar, concluir, revisar, duplicar, arquivar | `Stepper` indica etapa, não navega. Sem `PriceMapTable`: falta o mapa por fonte na API | `precos`, `precos-escrita`, `precos-gestao`, `coleta`, `auditoria`, `desempenho` | 96 (antes 96) | P1 |
| Preços: item e triagem | 🟡 `PriceResearchScreen.jsx` | `/app/precos/[id]/itens/[itemId]` | referências, estatísticas, alertas, cesta | triar, pôr e tirar da cesta, ver origem, concluir | `PriceDispersion`, estatísticas e cesta já existem. Sem busca de item, abas Fontes e Comparativo e `BarChart`: gráfico exigiria posições vindas do servidor. Sem `SourcePicker`: a coleta não escolhe fonte | `paridade`, `precos`, `coleta` | não medido | P2 |
| Preços: relatório e emissão | 🟡 `PriceStages.jsx` | seção em `/app/precos/[id]` | `/emissao`, `/ciencia`, `/relatorios`, `/jobs` | conferir, dar ciência, emitir, baixar, aplicar ao processo | **`ValidationSummary` entrou nesta entrega.** Faltam seleção de conteúdo e assinatura do kit, sem contrato na API. Diálogo de ciência ainda é `<dialog>` próprio porque envia o formulário | `emissao` | não medido | P2 |
| GovBot | 🟡 `GovBotScreen.jsx` | `/app/govbot` | `POST /govbot/perguntas` | perguntar, copiar, fontes citadas | **Página cheia, composer fixo e coluna de fontes entraram nesta entrega.** Falta histórico: a conversa some no refresh porque o servidor não grava nada, e guardar pede tabela e RLS novas. `AiDraftBlock` e "Inserir no documento" dependem de M9. Sem painel na barra superior | `govbot`, `paridade`, `auditoria` | não medido | P1 |
| Governança | ✅ sem tela na referência; segue o design system | `/app/governanca` | `/governanca/*` | ler; escrita atrás de `GOVCONECT_GOVERNANCA_ESCRITA` | Escrita desligada em produção por decisão do dono | `governanca`, `tema` | não medido | — |
| Administração | ✅ sem tela na referência | `/app/admin/instituicao`, `/app/admin/usuarios` | `/admin/*` | cadastro, usuários, papéis | Sem divergência funcional | `instituicao`, `cadastro-institucional`, `usuarios`, `auditoria`, `desempenho` | Usuários 214 (antes 203), Instituição 178 (antes 195) | — |
| Base de Conhecimento | ✅ sem tela na referência | `/app/admin/base-conhecimento` | `/admin/base-conhecimento` | indexar, listar, excluir, buscar | Busca textual em produção até decidir embeddings | `base-conhecimento`, `auditoria` | não medido | P2 |
| Conta | ✅ sem tela na referência | `/app/conta/senha` | Supabase Auth | trocar a senha, com saída global | — | `auditoria` | não medido | — |
| Parecer jurídico | ⛔ item de menu sem tela na referência | sem rota | sem API | continua no legado | M5, depende de M2. Não entra no menu até existir | sem prova | — | P1 |
| Telas legadas em migração | ⛔ | `legado.govconect.com` | Streamlit | geração, parecer, exportação de documentos | Dependem de M2, M3, M5 e M9. O Streamlit fica até haver substituto | suíte do Streamlit | — | P1 |

### Correções desta auditoria

- **GovBot não está sem tela:** a linha antiga dizia "sem tela/sem API". Tela e API existem e estão em produção.
- **Dispersão não está ausente:** `PriceDispersion` e `precos_estatisticas.py` estão em uso. A lacuna real é a dos gráficos por fonte.
- **`/` já é a Hero em produção**, e o legado responde em `legado.govconect.com`.
- **Ainda fogem do design system:** `acao-cesta`, `aplicar-processo`, `ato-item`, `coleta`, `emissao` e `importar-planilha` usam `components/ui.ts`. Funcionam com tokens, mas devem migrar para os componentes.

### Defeitos encontrados e corrigidos

| Defeito | Onde | Correção |
|---|---|---|
| 404 preta em aparelho no escuro | página padrão do Next | PR A, páginas próprias |
| Ações do cartão fora da tela e título esmagado em 390 px | detalhe do processo | PR D, cabeçalho do cartão quebra linha, com prova |
| Token renovado não chegava ao servidor | `lib/supabase/proxy.ts` | PR B |

### Em aberto

- Numa captura de 1440 px feita depois da gaveta do celular, o rodapé da barra lateral apareceu só com o avatar. Não foi reproduzido em uso normal. P3.
- A navegação por `PriceItemNav` usa `router.push`, então não aciona a barra de progresso. P3.

### Capturas comparativas

`docs/migracao-saas-2026-10-22/capturas-paridade/`: referência ao lado da tela real, em 1440×900, 768×1024 e 390×844, para Hero, login, início, processos, processo, item de preços e GovBot. Para refazer, rode `scripts/capturar-referencia.mjs` e depois `scripts/montar-comparativo.mjs`, com a pasta `paridade/` do artefato `web-e2e-telas`.

| Tela | 1440×900 | 768×1024 | 390×844 |
|---|---|---|---|
| Hero | [ver](capturas-paridade/hero-1440.jpg) | [ver](capturas-paridade/hero-768.jpg) | [ver](capturas-paridade/hero-390.jpg) |
| Login | [ver](capturas-paridade/login-1440.jpg) | [ver](capturas-paridade/login-768.jpg) | [ver](capturas-paridade/login-390.jpg) |
| Início | [ver](capturas-paridade/inicio-1440.jpg) | [ver](capturas-paridade/inicio-768.jpg) | [ver](capturas-paridade/inicio-390.jpg) |
| Processos | [ver](capturas-paridade/processos-1440.jpg) | [ver](capturas-paridade/processos-768.jpg) | [ver](capturas-paridade/processos-390.jpg) |
| Processo | [ver](capturas-paridade/processo-1440.jpg) | [ver](capturas-paridade/processo-768.jpg) | [ver](capturas-paridade/processo-390.jpg) |
| Preços: item | [ver](capturas-paridade/precos-item-1440.jpg) | [ver](capturas-paridade/precos-item-768.jpg) | [ver](capturas-paridade/precos-item-390.jpg) |
| GovBot | [ver](capturas-paridade/govbot-1440.jpg) | [ver](capturas-paridade/govbot-768.jpg) | [ver](capturas-paridade/govbot-390.jpg) |

## Matriz histórica (entregas 1 a 5, até 29/10)

Registro do que cada entrega fez. Onde divergir da auditoria acima, vale a auditoria.

Legenda: ✅ alinhada · 🟡 parcial (estrutura no design system, falta
fidelidade de tela) · ⛔ sem tela/sem API — **não simulada**.

| Tela da referência | Rota real | Entrega | Situação | Peças usadas | O que falta / divergência |
|---|---|---|---|---|---|
| Hero (`ui_kits/landing`) | `/` | 1 | ✅ | `LandingHero` (novo template), `Logo`, `buttonClasses`, `Icon` | Links do cabeçalho apontam às seções reais (Plataforma, Revisão e segurança, Perguntas) em vez de Documentos/Pesquisa de preços/Segurança, que não têm seção; "Falar com a equipe" virou "Como obter acesso" → FAQ (não há canal de contato publicado). Entre 600 e 1180 px o menu do celular aparece (na referência a navegação some sem substituto). |
| Login (`LoginScreen.jsx`) | `/entrar` | 1 | ✅ | `AuthLayout`, `Field`, `Input`, `Button`, `Alert` | Sem "Manter conectado": a sessão do Supabase já persiste, e a caixa não teria efeito (botão sem ação). |
| Casca (`Shell.jsx`) | `/app/**` | 1 | ✅ | `AppShell`, `Sidebar`, `NavItem`, `UserCard`, `Topbar`, `Breadcrumbs`, `Avatar`, `Badge`, `IconButton` | Menu só com o que existe e a pessoa pode ver (papel e flags do servidor). Sem GovBot, sino, "Salvo" nem Parecer jurídico: não há API. Até 768 px a barra vira gaveta (a referência não define celular). Trilha genérica para recurso ("Processo", "Pesquisa"): o layout não conhece o nome. |
| Início (`HomeScreen.jsx`) | `/app` | 1 | ✅ | `PageHead`, `KpiCard`, `Alert`, `Card`, `ProgressBar`, `StatusBadge`, `EmptyState`, `Button` | Indicadores contados sobre os até 100 processos mais recentes que o RLS deixa ver (a nota do cartão diz o escopo). Sem "Cotações concluídas R$": somar dinheiro no navegador é proibido; mostra as pesquisas recentes com a `exibicao` da API. Sem saudação por nome: `/me` não devolve nome. **Proposta**: `GET /api/v1/painel` com as contagens no servidor, quando um órgão passar de 100 processos. |
| Processos (`ProcessesScreen.jsx`) | `/app/processos` | 2 | ✅ | `PageHead`, `DataTable`, `TableContainer`, `StatusBadge`, `Menu`, `IconButton`, `Card`, `EmptyState`, `Field`/`Input`/`Textarea` | Sem abas, busca, filtros, ordenação nem seleção: a API lista por cursor sem filtro, e filtrar/ordenar só a página visível fingiria uma busca que o servidor não fez (**proposta**: `q` e `status` em `GET /processos`). Menu de linha só com ações reais (abrir, dados da demanda, consolidar); sem Excluir/Arquivar/Renomear/Duplicar — a API não tem. Paginação por cursor (Próxima página / Voltar ao início), não por número. |
| Novo processo / DFD (`NewProcessScreen.jsx`) | `/app/processos#novo`, `/app/processos/[id]`, `/formulario` | 2 | 🟡 | `PageHead` (situação no sobretítulo), `DataList`, `ProgressBar`, `Card`, `Alert`, formulário em `Field`/`Input`/`Textarea`/`Button` | Detalhe e formulário alinhados. Geração por IA e visualizador do DFD dependem do WordCraft (M2/M3) — fora desta frente. A trilha própria das subpáginas virou link de volta com o nome do processo (a trilha da barra superior não conhece o nome). |
| Consolidar demandas | `/app/processos/[id]/demandas` | 2 | ✅ | `PageHead`, `Alert`, `FileUpload`, `DataTable` | — |
| Nova pesquisa de preços | `/app/precos/nova` | 4 | ✅ | `PageHead`, `Card`, `Field`, `Input`, `Textarea`, `Button`, `Alert` | — |
| Cotação — triagem (`PriceResearchScreen.jsx`) | `/app/precos`, `/app/precos/[id]`, `/itens/[itemId]` | 3 | ✅ | `PageHead`, `DataList`, `Stepper`, `StatusBadge`, tabela `gc-table`, `PriceItemNav`, `ScreeningSummary` (filtra de verdade), `PriceReferenceRow`, `Dialog` + `TraceabilityPanel`, `PriceBasket`, `PriceStats`, `Alert` | Etapas são indicador lido do estado da API, não navegação (cada etapa é uma seção da página). Sem `PriceDispersion`, `BarChart` e média/mediana/CV: exigiriam converter dinheiro em número no navegador (proibido) — **proposta**: a API devolver estatísticas e posições já calculadas. Sem `SourcePicker`: a coleta não escolhe fonte pela tela hoje. `ExclusionDialog` não usado: tirar da cesta não pede motivo (regra RF-02); pôr pede, no `AcaoNaCesta` existente. Cesta, cálculo, conclusão e reabertura continuam no servidor. |
| Mapa e relatório (`PriceStages.jsx`) | `/app/precos/[id]` (itens, emissão, aplicação) | 3 | 🟡 | seções em `gc-card`, `Alert` | A tabela de itens faz o papel do mapa; emissão e aplicação mantêm os componentes atuais (ciência, bloqueio, job), agora dentro de cartões. `PriceMapTable` e `ValidationSummary` ficam para quando a API devolver o mapa por fonte e as pendências no formato deles. |
| GovBot (`GovBotScreen.jsx`, `GovBotPanel.jsx`) | — | 4 | ⛔ | — | Não há endpoint de conversa na API v1 (só `POST /admin/base-conhecimento/busca`, de admin). Não entra no menu até existir; quando existir: `ChatMessage`, `Cite`, `SourceList`, `AiDraftBlock`, `MessageFeedback`, `PromptSuggestions`, `ConversationList`, `ContextBar`, `ChatComposer`. |
| Base de conhecimento | `/app/admin/base-conhecimento` | 4 | ✅ | `PageHead`, `FileUpload`, `DataTable`, `Dialog` (já portados em M6) | Na casca nova; a busca por trechos (RAG) é a única leitura do índice exposta pela API, e só a admin. |
| Governança | `/app/governanca` | 4 | ✅ | `PageHead`, `KpiCard`, `Card`, `Badge`, `EmptyState`, `Alert`, `Field`/`Input`/`Select`/`Textarea` (M8a/M8b) | Escrita continua atrás de `GOVCONECT_GOVERNANCA_ESCRITA`, desligada por padrão; sem `loading.tsx` para o 404 de quem não tem acesso continuar 404. |
| Administração: Instituição, Usuários | `/app/admin/instituicao`, `/app/admin/usuarios` | 4 | ✅ | `PageHead`, `Card`, `Tabs`, `DataTable`, `Dialog`, `DateField`, `Field`/`Input`/`Select`/`Switch` (M7a–c) | Na casca nova, no grupo Gestão do menu, só para admin. |
| Conta / Senha | `/app/conta/senha` | 4 | ✅ | `PageHead`, `Card`, `Field`, `Input`, `Alert`, `Button` | — |
| Editor de documento (WordCraft Workspace, Issue #137) | `/app/processos/[id]/documentos/[documentoId]/editar` | WC-1 | 🟡 | `AppShell workspace`, `DocumentWorkspace` (novo), `Badge`, `Button`, `IconButton`, `Menu`, `DataList`, `Dialog`, `Alert`, `EmptyState`, `Spinner` | **Não há tela de editor no export do Claude Design** (Etapa A da issue não entregue): desenho feito a partir do brief da issue e do design system. Ver seção abaixo. |

## Auditoria global (entrega 5)

`e2e/auditoria.spec.ts` (conta própria `admin_auditoria`) passa por todas as telas autenticadas — início, processos, processo, preços, nova pesquisa, pesquisa, item, instituição, usuários, base de conhecimento, senha — e reprova se alguma: não responder 200, sair da casca (`main#conteudo`, trilha), tiver mais ou menos de um `h1`, rolar para o lado em 1440 ou 390 px, tiver imagem sem `alt` ou botão sem nome, ou registrar erro no console. O primeiro Tab tem de cair em "Pular para o conteúdo". Capturas em `e2e/resultados/auditoria/`.

## Peças do design system ainda sem uso no app

`Tooltip`, `Menu`, `Toolbar*`, `Radio*`, `SearchField`, `Stepper`,
`Accordion`, `DataList`, `DocumentViewer`, `Spinner`, `Tag`,
`Toast`/`ToastStack`, `BarChart`, `Pagination`, toda a família `ai/` e
toda a família `price/`. As de preço e as de lista entram nas entregas 2
e 3; as de IA esperam a API do GovBot.

## Peças adaptadas nesta entrega

- `AppShell`: gaveta até 768 px (botão de menu, fundo, Esc, fecha ao
  navegar), barra lateral presa à altura da tela, `id` por `useId`.
- `UserCard.name` aceita nó (o e-mail leva o `data-testid` do E2E).
- `Icon`: `sign-in`, `clipboard-text`, `list`, `users-three`.
- `LandingHero` (template novo) + `styles/landing.css`, só com tokens
  (as transparências do export viraram `color-mix` sobre o token).

## Ciclo de 29/10 (histórico; pendências atualizadas na auditoria de 31/10)

Resolvido:

- **Foco depois de navegar** (entrega 5): na troca de rota no cliente (login, menu) o foco volta ao topo e o primeiro Tab é "Pular para o conteúdo" (`components/foco-de-rota.tsx`).
- **Trilha da barra superior no celular**: só a página atual, com reticências até 768 px — a trilha inteira estourava 7 px na Base de Conhecimento.
- **Site institucional** (PR do site): `/solucoes`, `/solucoes/documentos-ia`, `/solucoes/pesquisa-de-precos`, `/como-funciona`, `/sobre`, `/contato` e `/privacidade` com `PublicPage`; o cabeçalho de vidro da Hero virou `PublicHeader`. Divergência "Falar com a equipe → Como obter acesso" resolvida: o botão leva a `/contato`.
- **Busca de processos** (PR da busca): `q=` na API, filtrada pelo banco sobre todos os processos visíveis.

Ainda aberto:

| Item | Bloqueio | Classe |
|---|---|---|
| `/` com a Hero em produção | o `/` é do Streamlit; falta um endereço para o legado (subdomínio no DNS) — subcaminho quebraria `/app/static` do WordCraft | P1 |
| Contato comercial | não há e-mail comercial no repositório; a página lê `GOVCONECT_CONTATO_EMAIL` | P1 |
| GovBot | API v1 sem endpoint de conversa | P1 |
| Dispersão e estatísticas da pesquisa | conta em dinheiro só no servidor; falta endpoint de estatística por item | P2 |
| Filtro de processos por situação | situação é derivada em Python; filtrar exigiria ler a base inteira | P3 |

## WordCraft Workspace: diferenças em relação ao brief (30/10)

A Etapa A da Issue #137 pedia um "Editor Workspace" no Claude Design (1440×900,
1920×1080, 768×1024, 390×844, todos os estados). **Ele não está no repositório**
(`design-system/referencia/` não tem tela de editor). A implementação seguiu o
brief textual da issue e as peças existentes; quando o desenho chegar, esta
seção vira a matriz de comparação. Capturas da pilha de CI:
`e2e/resultados/paridade/editor-*.png` (artefato `web-e2e-telas`).

| Pedido no brief | Como ficou | Divergência / motivo |
|---|---|---|
| Logo oficial, "Voltar ao processo", nome/tipo documental | Logo na barra lateral recolhida; barra do documento com voltar, sigla (sobretítulo) e título | Logo não se repete na barra do documento: a casca já o mostra. |
| Estado real de salvamento e revisão | Selo de situação + "Revisão N"; indicador anunciado (`role=status`): abrindo, revisão aberta, alterações não salvas, salvando, salvo · revisão N (só com ACK da API), falha, gravação indisponível, conflito, bloqueado, sessão encerrada | "Exportando" não tem estado próprio: o download é do navegador. |
| Ações somente funcionais | Histórico, Revisão, Exportar (DOCX/PDF da revisão salva), Modo foco | Sem GovBot, evidências, auditoria, pareceres e templates: a API v1 não os expõe ainda (continuam no Streamlit). |
| Área central ampla, sem cartão em volta do canvas | Área ocupa toda a altura/largura útil; sem cartão | — |
| Sidebar recolhida ao entrar | Recolhida (68 px) ao entrar; a pessoa pode abrir | — |
| Painéis colapsáveis (Estrutura, Revisão/GovBot/Evidências/Histórico) | Revisão e aprovação; Histórico de revisões; um por vez, à direita (≤ 768 px: folha inferior) | Estrutura e Evidências ficam para quando houver endpoint. |
| Modo foco | Cobre a tela (casca e painel somem), Esc ou botão para sair; a área não é recriada | — |
| Não duplicar a toolbar nativa | Nenhuma barra de formatação no Next; formatação é do WordCraft | — |
| Estados: abertura, ACK, editando, salvando, erro, conflito, somente leitura/aprovado, congelando, exportando | Todos menos "exportando" (ver acima); "somente leitura" aparece quando a gravação não está liberada no ambiente | Editar um documento já aprovado: o canvas não trava sozinho; o que o banco faz com o novo checkpoint (CAS/status) não foi verificado nesta entrega — conferir no canário. |
| 390×844 | Leitura segura (aviso + exportação), sem montar o editor | Edição por toque não comprovada (issue: "mobile de edição só se usabilidade nativa for comprovada"). |
