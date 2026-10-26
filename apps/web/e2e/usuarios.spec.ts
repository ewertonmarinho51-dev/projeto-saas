import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Usuários (M7c) contra a pilha real, como administrador. A pilha não tem
 * a chave da Admin API (ADR-010): a tela avisa, e o que não depende dela
 * — desativar e reativar, pelo JWT do admin — funciona. Convidar e trocar
 * papel têm prova na API (`test_usuarios_admin.py`).
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

test("administrador desativa e reativa um usuário; não se altera", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.admin_inst.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.admin_inst.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.getByRole("link", { name: "Usuários", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Usuários", level: 1 })).toBeVisible();
  await expect(page.getByText("A chave da Admin API não está configurada")).toBeVisible();

  const lista = page.getByTestId("lista-usuarios");
  const alvo = lista.getByRole("row").filter({ hasText: estado.contas.a1_alternavel.email });
  await alvo.getByRole("switch").click();
  await expect(page.getByText("Usuário desativado")).toBeVisible();
  await expect(alvo.getByText("Desativado")).toBeVisible();
  await alvo.getByRole("switch").click();
  await expect(page.getByText("Usuário reativado.")).toBeVisible();

  // A própria linha: o interruptor fica travado.
  const eu = lista.getByRole("row").filter({ hasText: estado.contas.admin_inst.email });
  await expect(eu.getByRole("switch")).toBeDisabled();
  await page.screenshot({ path: "e2e/resultados/telas/usuarios-1440.png", fullPage: true });
});
