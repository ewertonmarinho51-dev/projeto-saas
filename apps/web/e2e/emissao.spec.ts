import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Emissão no navegador, contra a pilha real com Redis e um worker Celery de
 * verdade. A pesquisa semeada tem um item em revisão: a emissão pede
 * ciência. O que se prova: o aviso aparece antes do clique sem travar
 * nada; "Voltar e revisar" não gera nada; "Estou ciente" registra e gera;
 * o arquivo baixa pelo próprio web, com o nome que a API deu.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
  emissao: string;
};

test("emitir pede ciência, gera no worker e baixa o arquivo", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.admin_a.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.admin_a.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.goto(`/app/precos/${estado.emissao}`);
  const secao = page.getByTestId("secao-emissao");
  await expect(secao.getByTestId("aviso-emissao")).toContainText("com pendência");

  // Voltar e revisar: nada é pedido.
  await secao.getByRole("button", { name: "Memória analítica (XLSX)" }).click();
  const aviso = page.getByRole("dialog", { name: "Preços que merecem conferência" });
  await expect(aviso).toBeVisible();
  await page.screenshot({ path: "e2e/resultados/telas/emissao-ciencia-1440.png", fullPage: true });
  await aviso.getByRole("button", { name: "Voltar e revisar" }).click();
  await expect(aviso).toBeHidden();
  await expect(page).not.toHaveURL(/relatorio=/);

  // Estou ciente: registra e gera.
  await secao.getByRole("button", { name: "Memória analítica (XLSX)" }).click();
  await aviso.getByRole("button", { name: "Estou ciente, gerar relatório" }).click();
  await expect(page).toHaveURL(/\?relatorio=[0-9a-f-]{36}$/);
  const pronto = page.getByTestId("progresso-relatorio");
  await expect(pronto).toContainText("Relatório pronto", { timeout: 60_000 });

  const [arquivo] = await Promise.all([
    page.waitForEvent("download"),
    pronto.getByRole("link", { name: /^Baixar / }).click(),
  ]);
  expect(arquivo.suggestedFilename()).toMatch(/\.xlsx$/);

  // Ciência já registrada para esta versão da cesta: o próximo pedido vai direto.
  await expect(secao).toContainText("Confirmação registrada para esta versão da cesta");
  await page.screenshot({ path: "e2e/resultados/telas/emissao-pronta-1440.png", fullPage: true });
});
