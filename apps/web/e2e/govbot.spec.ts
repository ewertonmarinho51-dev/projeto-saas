import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * GovBot na interface nova (M4), contra a pilha real. O CI não tem chave
 * de IA: a pergunta de pendências é respondida pela orientação local do
 * núcleo (`src/govbot.py`), sem motor — o que se prova é o caminho
 * navegador → ação do servidor → API → resposta, e que nada finge ser IA.
 *
 * Conta própria e UM login só: `/entrar` limita a 5 tentativas por IP +
 * e-mail em 15 minutos, contando as que deram certo, e a `a1` já chega
 * perto disso em `fluxo` e `precos`.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

async function entrar(page: Page, rotulo: string) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas[rotulo].email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas[rotulo].senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("perguntar ao GovBot pelo menu, receber a resposta e não abrir processo alheio", async ({ page }) => {
  await entrar(page, "a1_colega");
  await page.getByRole("navigation", { name: "Navegação principal" }).getByRole("link", { name: "GovBot", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/govbot$/);
  await expect(page.getByRole("heading", { level: 1, name: "GovBot" })).toBeVisible();
  await expect(page.getByText("Base de Conhecimento do órgão")).toBeVisible();
  // Sem função de anexar, o composer não mostra botão de anexar.
  await expect(page.getByRole("button", { name: "Anexar documento" })).toHaveCount(0);

  const caixa = page.getByRole("textbox", { name: "Mensagem para o GovBot" });
  await caixa.fill("O que está faltando?");
  await caixa.press("Enter");
  await expect(page.getByText("O que está faltando?")).toBeVisible();
  await expect(page.getByText(/Há \d+ pendência\(s\) neste contexto\./)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Resposta da orientação do sistema, sem consulta ao motor de IA.")).toBeVisible();
  await expect(caixa).toHaveValue("");
  // Sem endpoint de avaliação, a resposta não mostra polegares que não gravam nada.
  await expect(page.getByRole("button", { name: "Boa resposta" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Gerar novamente" })).toBeVisible();

  await page.screenshot({ path: "e2e/resultados/telas/govbot-1440.png", fullPage: true });

  // Processo fora do acesso no contexto é 404.
  const r = await page.goto("/app/govbot?processo=00000000-0000-4000-8000-000000000000");
  expect(r?.status()).toBe(404);
});
