# Landing pública — Hero (escopo restrito)

Somente a Hero da landing pública e ajustes pontuais no Login. Nenhuma outra tela foi recriada (shell, processos, preços, GovBot etc. permanecem como estavam).

## Arquivos
- `index.html` — Hero responsiva em HTML/CSS puro sobre `styles.css` (classes `gc-*`). Sem imagens rasterizadas de fundo: o fundo é feito com gradientes e uma malha de pontos em CSS. As PNGs de referência não são usadas como asset.
- Logo: `assets/logo-govconect-96.png` (símbolo oficial transparente, sem transformação). O `logo_original.png` desta rodada tem fundo branco opaco, por isso não foi usado direto.

## Estados e motion
| Momento | O que acontece |
|---|---|
| 0–450 ms | Selo, título, subtítulo, CTAs e fatos entram por opacity + translateY 10px, com 90 ms entre cada um |
| 450–1400 ms | A linha SVG DFD → ETP → TR → Preços é revelada (stroke-dashoffset) |
| 500–1750 ms | Os nós entram em sequência (opacity + scale 0,98 → 1) |
| 700–1700 ms | Os 2 painéis de vidro entram (opacity + scale 0,98 → 1) |
| Depois | Só o painel "Pesquisa de preços" flutua 3 px num ciclo de 6 s |

- **Hover (CTAs):** sobem 1px, ganham sombra média e a seta desliza 2px. O secundário ganha borda azul-300.
- **Hover (nós e painéis):** sobem 2px, a borda fica azul e a sombra aumenta.
- **Foco:** o foco por teclado é o contorno global de 2px azul, independente do hover.
- **Vidro:** `rgba(255,255,255,.64)` com blur de 12px, borda de 1px e sombra suave.
  - Aplicado só no header flutuante e nos 2 painéis decorativos; nunca em formulários.
  - Fundo sólido quando não há suporte a `backdrop-filter` ou com `prefers-reduced-transparency`.
- **Movimento reduzido (`prefers-reduced-motion`):** tudo já aparece visível, sem linha animada, sem flutuação e sem deslocamento no hover.
- **Apenas visual:** os painéis e nós são ilustrações com dados de exemplo (marcadas "Exemplo ilustrativo"), não resultados reais. Os links "Conhecer a plataforma" e "Falar com a equipe" são âncoras sem destino. "Acessar sistema" leva ao UI kit do app.

## Login (preservado)
A tela e o fluxo foram mantidos. A única adição foi o estado de **falha de autenticação**: um Alert de erro, que pode ser fechado e entra com fade-up, aparece quando o e-mail não é `.gov.br` (simulação visual). Os estados de foco, erro de campo e carregando já existiam. Nada foi feito em autenticação real, rotas ou validação; isso fica com o Claude Code.

## Checklist
- [x] 1440px: duas colunas, sem overflow.
- [x] 768px: coluna única, ilustração abaixo do texto; `scrollWidth` 753 ≤ viewport.
- [x] 375px: nós em grade 2×2, sem a linha SVG, painéis empilhados e CTAs em largura total; `scrollWidth` 360 ≤ viewport.
- [x] Movimento reduzido: conteúdo integral e estático.
- [x] Animações só com transform/opacity/stroke-dashoffset, sem layout shift.
- [x] Logo original estática, sem distorção.
