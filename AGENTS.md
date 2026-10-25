# AGENTS.md

As instruções completas deste repositório estão em [`CLAUDE.md`](CLAUDE.md)
— leia antes de mudar qualquer coisa (testes, segredos, banco, git, modelo
por tarefa). Este arquivo existe para agentes que procuram `AGENTS.md`, e
não repete aquele.

Interface nova (`apps/web`):

- [`DESIGN.md`](DESIGN.md) é a fonte da verdade dos tokens visuais.
- Peças de interface vêm de `@/design-system` (`apps/web/design-system/`,
  mapa no `README.md` de lá); peça nova nasce ali. Tela de funcionalidade
  (com action de servidor e regra de negócio) fica em `apps/web/components/`
  e se monta só com essas peças.
- Nenhum hex, px ou fonte solto: use token.
- Validar: `npm run lint && npm run typecheck && npm test && npm run build`
  dentro de `apps/web`.
