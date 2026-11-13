import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Cotação automática de ponta a ponta, na pilha real (GoTrue, PostgREST,
 * Redis e worker Celery de verdade). As fontes do CI são só o índice do
 * PNCP da pilha (GOVCONECT_FONTES_COLETA=indice), semeado com resultados no
 * formato real da API — o caminho do piloto, sem sair para a rede.
 *
 * importar e confirmar → a cotação automática começa sozinha → propostas
 * na lista, o que exige atenção primeiro → na revisão, origem, equivalência
 * e evidência na própria referência → decisão manual (tirar da cesta) e
 * complemento manual opcional ("Pesquisar preços" com o termo do servidor)
 * sem perder a decisão → "Concluir cotação" aceita as propostas aptas → PDF.
 * Reimportar a mesma planilha não duplica item.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
  planilha_cotacao: string;
};

test.describe.configure({ mode: "serial" });

const itens = (page: Page) => page.locator("section[aria-labelledby=titulo-itens] tbody tr");

async function importar(page: Page) {
  await page.getByLabel("Planilha de itens (XLSX)").setInputFiles(estado.planilha_cotacao);
  await page.getByRole("button", { name: "Conferir planilha" }).click();
  await expect(page.getByTestId("plano-importacao")).toBeVisible();
  await page.getByRole("button", { name: "Confirmar importação" }).click();
}

test("importar → cotação automática → revisar → aceitar → PDF", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.cotador_a.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.cotador_a.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.goto("/app/precos");
  await page.getByRole("link", { name: "Nova pesquisa" }).click();
  await page.getByLabel("Nome da pesquisa").fill("Combustível e papel (E2E automática)");
  await page.getByLabel("Objeto").fill("Gasolina e papel para as secretarias.");
  await page.getByRole("button", { name: "Criar pesquisa" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/[0-9a-f-]{36}\?criada=1$/);
  const pesquisa = page.url().split("/app/precos/")[1].split("?")[0];

  // 1. Confirmar a importação já inicia a cotação automática.
  await importar(page);
  await expect(page).toHaveURL(/\?importada=1&job=[0-9a-f-]{36}$/);
  const primeiroJob = new URL(page.url()).searchParams.get("job");
  await expect(page.getByText("A cotação automática dos itens pendentes começou")).toBeVisible();
  const progresso = page.getByTestId("progresso-coleta");
  await expect(progresso).toHaveAttribute("data-job", "succeeded", { timeout: 90_000 });
  await expect(progresso).toContainText("2 de 2 itens processados");
  await expect(page.getByTestId("resumo-do-lote")).toContainText(/Pronto para revisão\s*2/);
  await page.reload();
  await expect(itens(page)).toHaveCount(2);
  await expect(page.getByTestId("situacao-item").first()).toContainText("Proposta apta");
  await expect(page.getByTestId("aptas")).toContainText("2 proposta(s) apta(s)");
  await page.screenshot({ path: "e2e/resultados/telas/cotacao-automatica-lista-1440.png", fullPage: true });

  // 2. Reimportar a mesma planilha: o plano diz que é igual, não há o que
  // confirmar, e nenhum item é duplicado (a repetição da MESMA confirmação
  // cai na mesma execução pela chave do plano — prova da API e da action).
  await page.getByLabel("Planilha de itens (XLSX)").setInputFiles(estado.planilha_cotacao);
  await page.getByRole("button", { name: "Conferir planilha" }).click();
  await expect(page.getByText("A planilha é igual ao que a pesquisa já tem.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmar importação" })).toHaveCount(0);
  await page.goto(`/app/precos/${pesquisa}`);
  await expect(itens(page)).toHaveCount(2);
  await expect(page.getByTestId("aptas")).toContainText("2 proposta(s) apta(s)");
  expect(primeiroJob).toBeTruthy();

  // 3. Revisão do papel: equivalente comprovado, origem e evidência na referência.
  await page.goto(`/app/precos/${pesquisa}`);
  await itens(page).filter({ hasText: "PAPEL SULFITE" }).getByRole("link").click();
  const referencias = page.getByTestId("referencia");
  await expect(referencias).toHaveCount(4);
  // o cartão fica limpo (natureza do valor); o resto está na rastreabilidade
  await expect(referencias.first().getByTestId("natureza")).toHaveText("Homologado");
  await referencias.first().getByRole("button", { name: "Ver origem" }).click();
  const dialogo = page.getByRole("dialog");
  await expect(dialogo).toContainText("equivalente comprovado");
  await expect(dialogo).toContainText("Licitanet");
  await expect(dialogo).toContainText("Coleta via PNCP");
  await page.keyboard.press("Escape");
  // e o registro original, com o link de origem no PNCP
  await referencias.first().getByTestId("consultar-registro").click();
  await expect(page.getByTestId("registro-original")).toBeVisible();
  await expect(page.getByTestId("registro-original").getByRole("link").first()).toHaveAttribute(
    "href",
    /^https:\/\/pncp\.gov\.br\//,
  );
  await page.keyboard.press("Escape");

  // 4. Decisão de pessoa: tirar uma referência da cesta, em um clique.
  await referencias.first().getByRole("button", { name: "Retirar da cesta" }).click();
  await expect(referencias.first()).toHaveAttribute("data-na-cesta", "0");
  // a gravação é em segundo plano: espera o servidor confirmar antes de recarregar
  await expect(referencias.first().getByTestId("controle-cesta")).not.toHaveAttribute("aria-busy", "true");
  await page.reload();
  await expect(page.getByTestId("referencia").filter({ hasText: "Excluída" })).toHaveCount(1);

  // 5. Complemento manual opcional: o termo do servidor orienta a busca.
  const busca = page.getByTestId("busca-item");
  await busca.getByLabel("Termo da busca").fill("papel para impressao a4");
  await busca.getByRole("button", { name: "Pesquisar preços" }).click();
  await expect(page).toHaveURL(/\?busca=[0-9a-f-]{36}&termo=/);
  await expect(page.getByText("Busca concluída")).toBeVisible({ timeout: 60_000 });
  // a decisão de pessoa continua de pé depois da busca
  await page.reload();
  await expect(page.getByTestId("referencia").filter({ hasText: "Excluída" })).toHaveCount(1);
  await page.screenshot({ path: "e2e/resultados/telas/cotacao-automatica-revisao-1440.png", fullPage: true });

  // 6. Aceite: "Concluir cotação" conclui as propostas aptas e a cotação.
  await page.goto(`/app/precos/${pesquisa}`);
  await page.getByTestId("fechamento-pesquisa").getByRole("button", { name: "Concluir cotação" }).click();
  await expect(page).toHaveURL(/\?concluida=1$/, { timeout: 30_000 });
  await expect(page.locator("section[aria-labelledby=titulo-itens] tbody")).not.toContainText("Em revisão");

  // 7. PDF do relatório de cotação.
  await page.reload();
  const secao = page.getByTestId("secao-emissao");
  await secao.getByRole("button", { name: "Relatório de Cotação (PDF)" }).click();
  const aviso = page.getByRole("dialog", { name: "Preços que merecem conferência" });
  if (await aviso.isVisible().catch(() => false)) {
    await aviso.getByRole("button", { name: "Estou ciente, gerar relatório" }).click();
  }
  await expect(page).toHaveURL(/\?relatorio=[0-9a-f-]{36}$/);
  const pronto = page.getByTestId("progresso-relatorio");
  await expect(pronto).toContainText("Relatório pronto", { timeout: 120_000 });
  const [arquivo] = await Promise.all([
    page.waitForEvent("download"),
    pronto.getByRole("link", { name: /^Baixar / }).click(),
  ]);
  expect(arquivo.suggestedFilename()).toMatch(/\.pdf$/);
  await page.screenshot({ path: "e2e/resultados/telas/cotacao-automatica-pdf-1440.png", fullPage: true });
});
