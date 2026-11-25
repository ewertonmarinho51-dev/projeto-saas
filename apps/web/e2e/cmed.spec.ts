import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Consulta própria da CMED (teto de medicamentos), contra a pilha real. A
 * pilha grava a lista PMVG de 09/11/2026 como vigente, com onze
 * apresentações REAIS, e liga `referencia_teto_cmed` (`pilha.semear_cmed`).
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

const LISTA =
  "https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/lista_pmvg_20261109_111901662.xlsx/@@download/file";

async function entrar(page: Page) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.a1_cmed.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.a1_cmed.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("servidor consulta o teto CMED: PMVG com CAP, PF sem CAP, por alíquota", async ({ page }) => {
  await entrar(page);
  await page.goto("/app/precos");
  await page.getByRole("link", { name: "Teto de medicamentos (CMED)" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/cmed$/);
  await expect(page.getByText("não preço de compra: não entra na cesta")).toBeVisible();

  const busca = page.getByTestId("busca-cmed");
  await busca.getByLabel("Medicamento").fill("orencia");
  await busca.getByLabel("Alíquota de ICMS").selectOption("18");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("Lista CMED de 09/11/2026 · ICMS 18%")).toBeVisible();

  // no CAP: o teto ao governo é o PMVG; isenta de ICMS mostra também a coluna 0%
  const cap = page.locator("tbody tr").filter({ hasText: "125 MG/ML SOL INJ SC" });
  await expect(cap.getByTestId("teto-cmed")).toHaveText("R$ 6.596,70");
  await expect(cap).toContainText("PMVG (CAP aplicado ao PF)");
  await expect(cap).toContainText("R$ 8.224,28");                 // o PF, ao lado
  await expect(cap.getByTestId("teto-isento-cmed")).toContainText("R$ 5.409,29");
  await expect(cap).toContainText("Isento de ICMS");
  await expect(cap.getByRole("link", { name: "Lista CMED de 09/11/2026" })).toHaveAttribute("href", LISTA);
  await expect(cap).toContainText("linha 4");

  // fora do CAP: o teto é o PF, não o PMVG que a planilha também traz
  await busca.getByLabel("Medicamento").fill("");
  await busca.getByLabel("Código").fill("7891106000956");
  await busca.getByRole("button", { name: "Consultar" }).click();
  const semCap = page.locator("tbody tr").filter({ hasText: "BAYCUTEN N" });
  await expect(semCap.getByTestId("teto-cmed")).toHaveText("R$ 37,48");
  await expect(semCap).toContainText("PF (fora do CAP)");
  await expect(semCap).toContainText("R$ 30,06");                 // o PMVG, que não vale

  // a alíquota muda o valor
  await busca.getByLabel("Alíquota de ICMS").selectOption("0");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.locator("tbody tr").filter({ hasText: "BAYCUTEN N" }).getByTestId("teto-cmed")).toHaveText("R$ 30,73");

  for (const [nome, width, height] of [["375", 375, 812], ["1440", 1440, 900]] as const) {
    await page.setViewportSize({ width, height });
    await page.screenshot({ path: `e2e/resultados/telas/cmed-${nome}.png`, fullPage: true });
  }

  // nada encontrado é um estado; código fora da forma é recado
  await busca.getByLabel("Código").fill("78911060009560");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("Nenhuma apresentação da CMED para esta busca.")).toBeVisible();
  await busca.getByLabel("Código").fill("1234");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("O código é o GGREM (15 dígitos)")).toBeVisible();
});
