import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Consulta própria do SIGTAP (remuneração do SUS), contra a pilha real. A
 * pilha grava uma versão publicada de 11/2026 com quatro procedimentos REAIS
 * e liga `referencia_sus_sigtap` (`pilha.semear_sigtap`).
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

const ARQUIVO =
  "ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/TabelaUnificada_202611_v2611051737.zip";

async function entrar(page: Page) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.a1_sigtap.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.a1_sigtap.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("servidor consulta a remuneração SUS de um procedimento, com SA, SH + SP e o arquivo oficial", async ({ page }) => {
  await entrar(page);
  await page.goto("/app/precos");
  await page.getByRole("link", { name: "Remuneração SUS (SIGTAP)" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/sigtap$/);
  await expect(page.getByText("não preço de compra: não entra na cesta")).toBeVisible();

  const busca = page.getByTestId("busca-sigtap");
  await busca.getByLabel("Procedimento").fill("cesariana");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("Competência 11/2026")).toBeVisible();
  const cesariana = page.locator("tbody tr").filter({ hasText: "OPERAÇÃO CESARIANA" });
  await expect(cesariana).toHaveCount(1);
  await expect(cesariana).toContainText("04.11.01.003-4");
  await expect(cesariana.getByTestId("sigtap-hospitalar")).toHaveText("R$ 545,73");
  await expect(cesariana).toContainText("SH R$ 395,68 · SP R$ 150,05");
  await expect(cesariana.getByTestId("sigtap-sa")).toHaveText("R$ 0,00");
  await expect(cesariana).toContainText("Hospitalar");
  await expect(cesariana).toContainText("tb_procedimento, linha 3526");
  await expect(cesariana.getByRole("link", { name: "Tabela Unificada 11/2026" })).toHaveAttribute("href", ARQUIVO);
  await expect(page.getByText("o total é SH + SP")).toBeVisible();

  // por código, na forma com pontos e hífen
  await busca.getByLabel("Procedimento").fill("");
  await busca.getByLabel("Código").fill("02.02.01.047-3");
  await busca.getByRole("button", { name: "Consultar" }).click();
  const glicose = page.locator("tbody tr").filter({ hasText: "DOSAGEM DE GLICOSE" });
  await expect(glicose.getByTestId("sigtap-sa")).toHaveText("R$ 1,85");
  await expect(glicose).toContainText("Ambulatorial");

  for (const [nome, width, height] of [["375", 375, 812], ["1440", 1440, 900]] as const) {
    await page.setViewportSize({ width, height });
    await page.screenshot({ path: `e2e/resultados/telas/sigtap-${nome}.png`, fullPage: true });
  }

  // a modalidade filtra: a glicose não é de atenção domiciliar
  await busca.getByLabel("Modalidade").selectOption("Atenção Domiciliar");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("Nenhum procedimento do SIGTAP para esta busca.")).toBeVisible();

  // código incompleto é recado, não erro
  await busca.getByLabel("Modalidade").selectOption("");
  await busca.getByLabel("Código").fill("0202");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("O código do procedimento tem 10 dígitos")).toBeVisible();
});
