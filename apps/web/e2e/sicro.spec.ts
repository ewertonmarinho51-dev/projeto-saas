import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Consulta própria do SICRO (custo de obra de transportes), contra a pilha
 * real. A pilha grava uma versão publicada do Pará, julho/2026, com cinco
 * referências REAIS e liga `referencia_custos_sicro` (`pilha.semear_sicro`).
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

const ARQUIVO =
  "https://www.gov.br/dnit/pt-br/assuntos/planejamento-e-pesquisa/custos-referenciais/sistemas-de-custos/sicro/relatorios/relatorios-sicro/norte/para/2026/julho/pa-07-2026.7z";

async function entrar(page: Page) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.a1_sicro.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.a1_sicro.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("servidor consulta composição, insumo e equipamento do SICRO, com o arquivo oficial", async ({ page }) => {
  await entrar(page);
  await page.goto("/app/precos");
  await page.getByRole("link", { name: "Custos de transportes (SICRO)" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/sicro$/);
  await expect(page.getByText("não preço de compra: não entra na cesta")).toBeVisible();

  const busca = page.getByTestId("busca-sicro");
  await busca.getByLabel("Descrição").fill("concreto usinado");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("Mês de referência 07/2026 · PA")).toBeVisible();
  const composicao = page.locator("tbody tr").filter({ hasText: "1106050" });
  await expect(composicao.getByTestId("custo-sicro")).toHaveText("R$ 65,12");
  await expect(composicao).toContainText("Composição");
  await expect(composicao).toContainText("m³");
  await expect(composicao).toContainText("Relatório Sintético de Composições de Custos, linha 1693");
  await expect(composicao.getByRole("link", { name: /Arquivo oficial 07\/2026/ })).toHaveAttribute("href", ARQUIVO);
  await expect(page.getByText("art. 23, § 2º, I")).toBeVisible();

  // mão de obra: o valor muda com o regime, com as quatro casas do DNIT
  await busca.getByLabel("Descrição").fill("ajudante");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.locator("tbody tr").filter({ hasText: "P9801" }).getByTestId("custo-sicro")).toHaveText("R$ 24,8197");
  await busca.getByLabel("Encargos sociais").selectOption("com_desoneracao");
  await busca.getByRole("button", { name: "Consultar" }).click();
  const comDesoneracao = page.locator("tbody tr").filter({ hasText: "P9801" });
  await expect(comDesoneracao.getByTestId("custo-sicro")).toHaveText("R$ 23,6691");
  await expect(comDesoneracao).toContainText("origem: salário de fontes secundárias de dados públicos (SDP)");

  // equipamento: produtivo e improdutivo
  await busca.getByLabel("Descrição").fill("");
  await busca.getByLabel("Encargos sociais").selectOption("sem_desoneracao");
  await busca.getByLabel("Código").fill("E9009");
  await busca.getByRole("button", { name: "Consultar" }).click();
  const equipamento = page.locator("tbody tr").filter({ hasText: "E9009" });
  await expect(equipamento.getByTestId("custo-sicro")).toHaveText("R$ 489,8398");
  await expect(equipamento.getByTestId("improdutivo-sicro")).toContainText("R$ 149,9339");

  for (const [nome, width, height] of [["375", 375, 812], ["1440", 1440, 900]] as const) {
    await page.setViewportSize({ width, height });
    await page.screenshot({ path: `e2e/resultados/telas/sicro-${nome}.png`, fullPage: true });
  }

  // composição só existe sem desoneração: com desoneração, nada encontrado
  await busca.getByLabel("Código").fill("1106050");
  await busca.getByLabel("Encargos sociais").selectOption("com_desoneracao");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("Nenhuma referência do SICRO para esta busca.")).toBeVisible();

  // código fora da forma é recado, não erro
  await busca.getByLabel("Código").fill("110605");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("O código do SICRO tem 7 dígitos")).toBeVisible();
});
