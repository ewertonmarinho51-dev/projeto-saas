import { defineConfig, devices } from "@playwright/test";

/**
 * E2E contra a pilha REAL (job `web-e2e` do CI): web em `next start`,
 * API FastAPI e GoTrue + PostgREST + Postgres descartáveis. Nada de mock:
 * se a pilha não estiver de pé, os testes falham.
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.resultados/artefatos",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "./e2e/.resultados/relatorio", open: "never" }]],
  use: {
    baseURL: process.env.GOVCONECT_E2E_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
