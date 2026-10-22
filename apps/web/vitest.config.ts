import { defineConfig } from "vitest/config";

// Vitest só nas provas de unidade; `e2e/` é do Playwright, contra a pilha real.
export default defineConfig({
  test: { include: ["tests/**/*.test.ts"] },
});
