import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Coleta assíncrona no navegador, contra a pilha real com Redis e um
 * worker Celery de verdade (sem fontes externas — GOVCONECT_FONTES_COLETA=
 * indice: só o índice do PNCP da pilha, recusado em produção). O que se prova: o clique responde na
 * hora, a página acompanha o job até o fim e os itens saem de "Pendente".
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
  coleta: string;
};

test("coletar preços acompanha o job até o fim, inclusive após recarregar", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.a1.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.a1.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.goto(`/app/precos/${estado.coleta}`);
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await expect(page.locator("tbody")).toContainText("Pendente");

  await page.getByRole("button", { name: "Coletar preços" }).click();
  await expect(page).toHaveURL(/\?job=[0-9a-f-]{36}$/);
  const lote = new URL(page.url()).searchParams.get("job");
  const progresso = page.getByTestId("progresso-coleta");
  // O painel aparece onde a pessoa está olhando, e com o foco.
  await expect(progresso).toBeInViewport();
  await expect(progresso).toBeFocused();
  // Refresh no meio: o job vem da URL, o acompanhamento continua no MESMO lote.
  await page.reload();
  expect(new URL(page.url()).searchParams.get("job")).toBe(lote);
  await expect(progresso).toBeInViewport();
  // Na conclusão o painel dá lugar ao resumo, e o destaque vai para ele.
  await expect(progresso).toHaveAttribute("data-job", "succeeded", { timeout: 60_000 });
  await expect(progresso).toContainText("Coleta concluída");
  await expect(progresso).toContainText("2 de 2 itens processados");
  await expect(progresso).toBeFocused();
  await expect(page.getByRole("button", { name: "Coletar preços" })).toBeEnabled();
  await expect(page.locator("tbody")).not.toContainText("Pendente");
  await page.screenshot({ path: "e2e/resultados/telas/coleta-1440.png", fullPage: true });
});
