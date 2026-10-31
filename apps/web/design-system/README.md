# Design system Gov Conect (`apps/web/design-system`)

Biblioteca de interface do `apps/web`. **Fonte da verdade dos tokens:
[`DESIGN.md`](../../../DESIGN.md) na raiz.** Vitrine com tudo, nos dois
temas: `/design-system` (em desenvolvimento; em produção só com
`GOVCONECT_VITRINE=1`).

Regras:

- Fora desta pasta, importe **só do índice**: `import { Button } from "@/design-system"`.
- Peça de interface nova (sem regra de negócio) nasce aqui, com variante e
  estado na vitrine — não na página. Tela de funcionalidade fica em
  `components/` e se monta só com peças daqui.
- Nenhum valor visual solto: hex, px e fonte vêm de token. O ESLint avisa
  no app e **recusa** aqui dentro.
- Mudou token? Mude `DESIGN.md` e `tokens/*.css` no mesmo commit:
  `tests/design-system.test.ts` reprova se divergirem.

## Estrutura

| Caminho | O que é |
|---|---|
| `index.ts` | ponto de entrada único (71 nomes do export + 4 templates) |
| `styles.css` | entrada do CSS, importada por `app/globals.css` |
| `tokens/` | `colors` (claro por padrão, escuro só por atributo), `typography`, `spacing`, `elevation`, `motion`, `layout` |
| `styles/base.css` | foco, `.gc-num`, `.gc-mono`, `.gc-sr-only`, animações, movimento reduzido (camada `base`) |
| `styles/components.css` | classes `gc-*` dos componentes (camada `components`: utilitário do Tailwind ainda vence) |
| `components/<grupo>/` | componentes React + TypeScript |
| `templates/` | composições de página |
| `lib/` | `cx` (junta classes), formato pt-BR de dinheiro e número |
| `vitrine/` | a página `/design-system` |
| `referencia/` | HTMLs originais do Claude Design, só para comparação (ver `referencia/LEIAME.md`) |

Assets da marca ficam em `apps/web/public/` (o Next só serve dali):
`logo-govconect.png` (1254 px), `logo-govconect-96.png`, `favicon-32.png`,
`padrao-geometrico.png`, `fundo-hero-claro.png` — todos transparentes, do
export.

## Mapa

Cliente = tem estado ou efeito (`"use client"`); os demais servem em
server component. Componente que recebe função (`render`, `trigger`,
`onClick`) precisa ser montado dentro de componente cliente.

| Grupo | Componente | Para quê | Cliente |
|---|---|---|---|
| core | `Icon` | glifo Phosphor de registro fechado (`IconName`) | |
| core | `Logo` | marca oficial, PNG transparente, nome opcional | |
| core | `Avatar` | foto ou iniciais | |
| core | `Tooltip` | dica curta no hover/foco | |
| actions | `Button` (+ `buttonClasses`) | ação; 7 variantes, 3 tamanhos, carregando, link | |
| actions | `IconButton` | botão só de ícone, rótulo obrigatório | |
| actions | `Menu` | menu de ações; fecha fora e no Esc | sim |
| actions | `Toolbar`, `ToolbarSeparator`, `ToolbarSpacer` | barra de ações | |
| forms | `Field` | rótulo + controle + ajuda/erro/contador | |
| forms | `Input` | texto; ícone, prefixo/sufixo, inválido, só leitura, limpar | |
| forms | `SearchField` | busca com limpar e atalho | sim |
| forms | `Textarea` | texto longo | |
| forms | `Select` | select nativo estilizado | |
| forms | `DateField` | data, ou intervalo | |
| forms | `Checkbox` | marcação, com estado misto | sim |
| forms | `Radio`, `RadioGroup` | escolha única | sim |
| forms | `Switch` | liga/desliga imediato | |
| forms | `FileUpload` | arrastar/clicar + lista com progresso | sim |
| navigation | `Sidebar`, `NavItem`, `UserCard` | barra lateral do app | |
| navigation | `Topbar` | barra superior de 64 px | |
| navigation | `Breadcrumbs` | trilha | |
| navigation | `Tabs` | abas linha ou segmentadas; setas do teclado | sim |
| navigation | `Stepper` | etapas (fase preparatória, pesquisa) | |
| content | `Card` | superfície base | |
| content | `DataList` | chave–valor | |
| content | `Accordion` | detalhe que abre/fecha | |
| content | `Dialog` | modal; Esc e clique fora fecham | sim |
| content | `DocumentViewer` | prévia de documento em papel | |
| feedback | `Alert` | mensagem em linha (info, success, warning, error, neutral) | |
| feedback | `Toast`, `ToastStack` | confirmação passageira | |
| feedback | `Badge` | selo de status, contagem, fonte | |
| feedback | `StatusBadge`, `PROCESS_STATUS` | vocabulário único de situação | |
| feedback | `Tag` | filtro removível | |
| feedback | `EmptyState` | lista vazia / primeiro uso | |
| feedback | `Skeleton`, `SkeletonText` | marcador de carregamento | |
| feedback | `Spinner` | carregando sem total | |
| feedback | `ProgressBar` | progresso linear | |
| data | `KpiCard` | indicador com tendência | |
| data | `DataTable`, `TableContainer` | tabela ordenável e selecionável | sim |
| data | `Pagination` | paginação | |
| data | `BarChart` | barras horizontais rotuladas | |
| ai | `ChatMessage`, `Cite` | turno do GovBot, citação numerada | |
| ai | `ChatComposer` | caixa de pergunta | sim |
| ai | `PromptSuggestions` | sugestões de pergunta | |
| ai | `AiProcessing` | etapas de geração | |
| ai | `SourceList` | fontes da resposta | |
| ai | `ConversationList` | histórico de conversas | |
| ai | `ContextBar` | o que o GovBot pode usar | |
| ai | `AiDraftBlock` | texto gerado com revisão humana | |
| ai | `MessageFeedback` | útil / não útil | sim |
| price | `PriceReferenceRow` | referência na triagem | |
| price | `PriceBasket` | cesta de preços | |
| price | `PriceStats` | estatística do item | |
| price | `TraceabilityPanel` | origem da referência | |
| price | `SourcePicker` | fontes consultadas | |
| price | `PriceItemNav` | navegador de itens | |
| price | `PriceDispersion` | dispersão no eixo de preço | |
| price | `ScreeningSummary` | contadores/filtros da triagem | |
| price | `ValidationSummary` | conferência antes da emissão | |
| price | `PriceMapTable` | mapa de preços | |
| price | `ExclusionDialog` | retirar referência com motivo | sim |
| templates | `PageHead` | cabeçalho de página | |
| templates | `AppShell` | casca do app (barra lateral + superior); `workspace` = modo de trabalho do editor (tela inteira, barra recolhida) | sim |
| templates | `DocumentWorkspace` | espaço de trabalho do editor de documento: barra (voltar, sigla, título, selos, salvamento anunciado, ações), área do editor sem cartão e painel opcional; modo foco cobre a tela sem recriar a área | |
| templates | `AuthLayout` | entrada dividida marca/formulário; sempre no tema claro (usado em `/entrar` e `/entrar/recuperar`) | |
| templates | `LandingHero` | Hero da landing pública (`/`): cabeçalho de vidro, fluxo DFD → ETP → TR → Preços em SVG, painéis ilustrativos; CSS em `styles/landing.css`, sem JavaScript | |

## Integração com o resto do app

- `app/globals.css` importa `styles.css` e mapeia os nomes do Tailwind que
  o app já usava (`bg-canvas`, `text-secundario`, `border-linha`,
  `bg-acento`…) para os tokens semânticos, com `@theme inline`. Um valor,
  um lugar; o tema escuro vem junto.
- `components/ui.ts`: `botaoPrimario`, `botaoSecundario` e `cartao` agora
  são as classes `gc-btn`/`gc-card`. `components/marca.tsx` usa o `Logo`
  daqui.
- Tipografia de elemento (h1, h2, link) do design system só vale dentro de
  `.gc-base`; o `body` do app segue em 16 px até a migração das páginas.
