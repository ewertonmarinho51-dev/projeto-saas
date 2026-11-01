import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Fluxo real ponta a ponta: login no GoTrue, sessão por cookie, API
 * verificando o token, RLS no Postgres. Contas e senhas de TESTE vêm do
 * estado gravado por `apps/api/tests_rls/pilha.py`.
 */
type Conta = { email: string; senha: string; tenant_id: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
};
const conta = (rotulo: string) => estado.contas[rotulo];

const TELAS = [
  { nome: "375", width: 375, height: 812 },
  { nome: "768", width: 768, height: 1024 },
  { nome: "1440", width: 1440, height: 900 },
];

async function capturar(page: Page, nome: string) {
  for (const t of TELAS) {
    await page.setViewportSize({ width: t.width, height: t.height });
    await page.screenshot({ path: `e2e/resultados/telas/${nome}-${t.nome}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

async function entrar(page: Page, rotulo: string) {
  await page.getByLabel("E-mail institucional").fill(conta(rotulo).email);
  await page.getByLabel("Senha", { exact: true }).fill(conta(rotulo).senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
}

function vigiarConsole(page: Page) {
  const erros: string[] = [];
  page.on("console", (m) => m.type() === "error" && erros.push(m.text()));
  page.on("pageerror", (e) => erros.push(e.message));
  return erros;
}

test.describe.configure({ mode: "serial" });

test("página pública: CSP com nonce, sem erro de console", async ({ page }) => {
  const erros = vigiarConsole(page);
  const resposta = await page.goto("/");
  expect(resposta?.status()).toBe(200);
  const csp = resposta?.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("script-src 'self' 'nonce-");
  expect(csp).toContain("frame-ancestors 'none'");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Planejamento público, com método");
  await capturar(page, "inicio");
  await page.goto("/entrar");
  await capturar(page, "entrar");
  expect(erros).toEqual([]);
});

test("link profundo sem sessão vai ao login e volta ao destino", async ({ page }) => {
  await page.goto("/app/processos");
  await expect(page).toHaveURL(/\/entrar\?proximo=%2Fapp%2Fprocessos/);
  await entrar(page, "a1");
  await expect(page).toHaveURL(/\/app\/processos$/);
  await expect(page.getByTestId("usuario-email")).toHaveText(conta("a1").email);
});

test("senha errada mostra mensagem neutra e não entra", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta("a2").email);
  await page.getByLabel("Senha", { exact: true }).fill("senha-errada-de-proposito");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.getByText("E-mail ou senha incorretos.")).toBeVisible();
  await expect(page).toHaveURL(/\/entrar/);
});

test("redirecionamento para fora do site é ignorado", async ({ page }) => {
  await page.goto("/entrar?proximo=https://site-falso.example/app");
  await entrar(page, "a2");
  await expect(page).toHaveURL(/localhost:\d+\/app$/);
});

test("criar, reabrir, editar e conflito de versão", async ({ browser }) => {
  const contexto = await browser.newContext();
  const page = await contexto.newPage();
  await page.goto("/entrar");
  await entrar(page, "a1");
  await page.waitForURL(/\/app$/);

  const resposta = await page.goto("/app/processos");
  expect(resposta?.headers()["cache-control"]).toContain("no-store");
  const objeto = `Aquisição de luvas E2E ${Date.now()}`;
  await page.getByLabel("Órgão ou secretaria").fill("Secretaria de Saúde");
  await page.getByLabel("Objeto da contratação").fill(objeto);
  await page.getByRole("button", { name: "Criar processo" }).click();
  await expect(page.getByText("Processo criado.")).toBeVisible();
  const urlDoProcesso = page.url().split("?")[0];
  await capturar(page, "processo");

  // Duas abas na versão atual; a segunda salva primeiro.
  // O formulário só aparece quando pedido; o normal é o resumo.
  await expect(page.getByLabel("Objeto da contratação")).toHaveCount(0);
  await page.getByRole("link", { name: "Editar dados do processo" }).click();
  await expect(page.getByLabel("Objeto da contratação")).toBeVisible();
  const urlDeEdicao = page.url();
  const aba2 = await contexto.newPage();
  await aba2.goto(urlDeEdicao);
  await page.goto(urlDeEdicao);
  await aba2.getByLabel("Objeto da contratação").fill(`${objeto} (revisado)`);
  await aba2.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(aba2.getByText("Alterações salvas.")).toBeVisible();

  await page.getByLabel("Objeto da contratação").fill(`${objeto} (versão velha)`);
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByText("Outra pessoa alterou este processo")).toBeVisible();

  // Reabrir em sessão nova traz o que foi salvo, não o rascunho perdido.
  await page.goto("/app");
  await capturar(page, "app");
  await page.goto(urlDeEdicao);
  await expect(page.getByLabel("Objeto da contratação")).toHaveValue(`${objeto} (revisado)`);

  // Outro município não vê pelo id.
  const outro = await browser.newContext();
  const pageB = await outro.newPage();
  await pageB.goto("/entrar");
  await entrar(pageB, "b1");
  await pageB.waitForURL(/\/app$/);
  await pageB.goto(urlDoProcesso);
  await expect(pageB.getByText(objeto)).toHaveCount(0);
  await expect(pageB.getByText(/could not be found|não encontrad/i)).toBeVisible();
  await outro.close();
  await contexto.close();
});

test("conta desativada entra no Auth mas não acessa o órgão", async ({ page }) => {
  await page.goto("/entrar");
  await entrar(page, "a1_revogado");
  await expect(page.getByText("sem vínculo ativo")).toBeVisible();
});

test("sair encerra a sessão", async ({ page }) => {
  await page.goto("/entrar");
  await entrar(page, "a2");
  await page.waitForURL(/\/app$/);
  await page.getByRole("button", { name: "Sair" }).click();
  await expect(page).toHaveURL(/\/entrar\?saiu=1/);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/entrar\?proximo=%2Fapp/);
});
