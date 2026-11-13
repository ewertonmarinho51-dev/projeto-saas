import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Pesquisa de preços, leitura (P04a), contra a pilha real. A pesquisa foi
 * gravada direto no banco por `pilha.py` (como o Streamlit grava hoje):
 * valor global que não cabe em float, item ativo, item retirado e uma
 * referência do PNCP.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
  precos: { pesquisa: string; item: string };
};

async function entrar(page: Page, rotulo: string) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas[rotulo].email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas[rotulo].senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test.describe.configure({ mode: "serial" });

test("dono vê a pesquisa com dinheiro exato e evidência verificável", async ({ page }) => {
  await entrar(page, "a1");
  await page.getByRole("link", { name: "Preços", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/precos$/);
  // A pilha semeia DUAS pesquisas com o mesmo valor; a conferência é na linha da certa.
  const linhaDaPesquisa = page.getByRole("listitem").filter({ hasText: "Luvas E2E" });
  await expect(linhaDaPesquisa).toContainText("Valor global R$ 12.345.678.901.234,57");

  await page.getByRole("link", { name: /Luvas E2E/ }).click();
  await expect(page.getByTestId("valor-global")).toHaveText("R$ 12.345.678.901.234,57");
  const linhas = page.locator("tbody tr");
  await expect(linhas).toHaveCount(1);                       // o retirado não aparece
  await expect(page.getByText("Item retirado")).toHaveCount(0);
  await expect(linhas.first()).toContainText("1.500");
  await expect(linhas.first()).toContainText("R$ 2,35");
  await expect(linhas.first()).toContainText("R$ 3.517,50");

  for (const [nome, width, height] of [["375", 375, 812], ["768", 768, 1024], ["1440", 1440, 900]] as const) {
    await page.setViewportSize({ width, height });
    await page.screenshot({ path: `e2e/resultados/telas/precos-${nome}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.getByRole("link", { name: "Luva nitrílica" }).click();
  const referencia = page.getByTestId("referencia");
  await expect(referencia).toHaveCount(1);
  await expect(referencia).toContainText("R$ 2,35");
  // o link oficial mora em "Consultar registro original", não no cartão
  await referencia.getByTestId("consultar-registro").click();
  const link = page.getByTestId("registro-original").getByRole("link", { name: /PNCP/ });
  await expect(link).toHaveAttribute("href", "https://pncp.gov.br/app/editais/12345678000190/2025/123");
  await expect(link).toHaveAttribute("rel", /noopener/);
  await page.keyboard.press("Escape");

  // Análise da série: números do servidor, um preço só não inventa dispersão.
  await page.getByRole("tab", { name: "Análise da série" }).click();
  await expect(page).toHaveURL(/aba=analise/);
  const analise = page.getByTestId("analise-da-serie");
  await expect(analise).toContainText("Poucos preços para medir");
  await expect(analise).toContainText("R$ 2,35");
  await expect(analise.locator(".gc-disp__plot")).toHaveAttribute("aria-label", /R\$ 2,35 — Na cesta/);
  await expect(analise.locator(".gc-disp__ticks > span").first()).toContainText("R$");
  await expect(analise.getByRole("img", { name: /Preços por fonte/ })).toContainText("PNCP");
  await analise.getByText("Números por fonte").click();
  await expect(analise.getByRole("table", { name: "Preços por fonte" })).toContainText("PNCP");
  await analise.getByText("Números por UF").click();
  await expect(analise.getByRole("table", { name: "Preços por UF" })).toBeVisible();
  await page.getByRole("tab", { name: /Triagem/ }).click();
});

test("cesta em um clique: tira, põe de volta, grava em segundo plano e persiste", async ({ page }) => {
  await entrar(page, "a1");
  const url = `/app/precos/${estado.precos.pesquisa}/itens/${estado.precos.item}`;
  await page.goto(url);
  const referencia = page.getByTestId("referencia").first();
  await expect(referencia).toHaveAttribute("data-na-cesta", "1");
  const contagem = page.getByTestId("cartao-cesta").getByTestId("contagem-cesta");
  const antes = Number(await contagem.textContent());

  // Retirar: um clique, sem justificativa nem modal; marca e conta na hora.
  await referencia.getByRole("button", { name: "Retirar da cesta" }).click();
  await expect(referencia).toHaveAttribute("data-na-cesta", "0");
  await expect(contagem).toHaveText(String(antes - 1));
  await expect(referencia.getByRole("button", { name: "Incluir na cesta" })).toBeVisible();
  // o valor recalculado chega quando o servidor confirma; a URL não muda
  await expect(page.getByTestId("preco-do-item")).not.toHaveText("R$ 2,35");
  await expect(page).toHaveURL(new RegExp(`${url}$`));
  // persiste ao recarregar
  await page.reload();
  await expect(page.getByTestId("referencia").first()).toHaveAttribute("data-na-cesta", "0");

  // Incluir de volta: também um clique, sem justificativa.
  await page.getByTestId("referencia").first().getByRole("button", { name: "Incluir na cesta" }).click();
  await expect(page.getByTestId("referencia").first()).toHaveAttribute("data-na-cesta", "1");
  await page.reload();
  await expect(page.getByTestId("referencia").first()).toHaveAttribute("data-na-cesta", "1");
  await page.screenshot({ path: "e2e/resultados/telas/cesta-1440.png", fullPage: true });
});

test("outro município não abre a pesquisa nem as referências", async ({ page }) => {
  await entrar(page, "b1");
  await page.goto(`/app/precos/${estado.precos.pesquisa}`);
  await expect(page.getByText(/could not be found|não encontrad/i)).toBeVisible();
  await expect(page.getByText("Luvas E2E")).toHaveCount(0);
  await page.goto(`/app/precos/${estado.precos.pesquisa}/itens/${estado.precos.item}`);
  await expect(page.getByText(/could not be found|não encontrad/i)).toBeVisible();
});
