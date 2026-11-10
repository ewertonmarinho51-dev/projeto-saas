import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Vitest só nas provas de unidade; `e2e/` é do Playwright, contra a pilha real.
// O `@/` espelha o `paths` do tsconfig: sem ele, componente que importa
// `@/design-system` não pode ser renderizado numa prova.
export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: { include: ["tests/**/*.test.ts"] },
});
