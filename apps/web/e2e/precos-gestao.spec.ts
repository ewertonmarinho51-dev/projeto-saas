import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Gestão da cotação (M10a) contra a pilha real: incluir item à mão,
 * editar, retirar, duplicar a pesquisa e arquivar a cópia. Conta própria:
 * o limite da API é por usuário.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

test("incluir, editar, pesquisar e retirar item; duplicar, revisar e arquivar", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.a1_gestao.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.a1_gestao.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.goto("/app/precos/nova");
  const nome = `Gestão E2E ${Date.now()}`;
  await page.getByLabel("Nome da pesquisa").fill(nome);
  await page.getByRole("button", { name: "Criar pesquisa" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/[0-9a-f-]{36}\?criada=1$/);
  const pesquisa = page.url().split("/app/precos/")[1].split("?")[0];

  // Incluir à mão.
  await page.getByTestId("incluir-item").locator("summary").click();
  const novo = page.getByTestId("novo-item");
  await novo.getByLabel("Descrição").fill("Caneta esferográfica azul, ponta média (E2E)");
  await novo.getByLabel("Unidade").fill("UN");
  await novo.getByLabel("Quantidade").fill("10");
  await novo.getByRole("button", { name: "Incluir item" }).click();
  await expect(page.getByText("Item incluído.")).toBeVisible();
  const linhas = page.locator("section[aria-labelledby=titulo-itens] tbody tr");
  await expect(linhas).toHaveCount(1);
  // Com item aberto, concluir a cotação fica travado e diz por quê.
  await expect(page.getByRole("button", { name: "Concluir cotação" })).toBeDisabled();
  await expect(page.getByText("Faltam 1.")).toBeVisible();

  // Editar a quantidade.
  await linhas.first().getByRole("link").click();
  const edicao = page.getByTestId("edicao-item");
  await expect(edicao).toBeVisible();
  await edicao.getByLabel("Quantidade").fill("12");
  await edicao.getByRole("button", { name: "Salvar item" }).click();
  await expect(page.getByText("Item salvo.")).toBeVisible();

  // Pesquisar preços só deste item: vai pelo worker e a página acompanha.
  await page.getByTestId("busca-item").getByRole("button", { name: "Pesquisar preços" }).click();
  await expect(page).toHaveURL(/\?busca=[0-9a-f-]{36}$/);
  await expect(page.getByText("Busca concluída")).toBeVisible({ timeout: 30_000 });

  // Retirar (sem motivo: a auditoria é automática).
  await page.getByRole("button", { name: "Retirar item" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retirar", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/precos/${pesquisa}\\?item_retirado=1$`));
  await expect(page.getByText("Item retirado da pesquisa.")).toBeVisible();
  await expect(page.locator("section[aria-labelledby=titulo-itens] tbody tr")).toHaveCount(0);

  // Duplicar e arquivar a cópia.
  await page.getByRole("button", { name: "Duplicar" }).click();
  await expect(page).toHaveURL(/\?duplicada=1$/);
  await expect(page.getByTestId("titulo-pesquisa")).toHaveText(`${nome} (cópia)`);
  await page.getByRole("button", { name: "Nova revisão" }).click();
  await page.getByRole("dialog").getByLabel("Motivo da revisão").fill("Conferência do E2E");
  await page.getByRole("dialog").getByRole("button", { name: "Criar revisão" }).click();
  await expect(page).toHaveURL(/\?revisao=1$/);
  await expect(page.getByText("Revisão criada")).toBeVisible();
  await page.getByRole("button", { name: "Arquivar" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Arquivar", exact: true }).click();
  await expect(page).toHaveURL(/\?arquivada=1$/);
  await expect(page.getByText("Pesquisa arquivada.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Arquivar" })).toHaveCount(0);
  await page.screenshot({ path: "e2e/resultados/telas/precos-gestao-1440.png", fullPage: true });
});
