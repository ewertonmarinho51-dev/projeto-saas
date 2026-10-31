import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Hero, login e sessão (Issue #152, PR B), na pilha REAL.
 *
 * `/` é sempre a Hero; `/entrar` com sessão válida pergunta, em vez de
 * redirecionar em silêncio; `/app` continua exigindo sessão e vínculo. Cada
 * conta faz um login só por teste: `/entrar` limita 5 por IP + e-mail.
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
};
const A = estado.contas.a1_sessao;
const B = estado.contas.b1_sessao;
const REVOGADA = estado.contas.a1_sessao_revogada;

async function entrar(page: Page, conta: Conta) {
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
}

function vigiarConsole(page: Page) {
  const erros: string[] = [];
  page.on("console", (m) => m.type() === "error" && erros.push(m.text()));
  page.on("pageerror", (e) => erros.push(e.message));
  return erros;
}

test.describe.configure({ mode: "serial" });

test("com sessão: a Hero continua sendo o início, e /entrar pergunta", async ({ page }) => {
  const erros = vigiarConsole(page);
  await page.goto("/entrar");
  await entrar(page, A);
  await page.waitForURL(/\/app$/);

  // A Hero não some nem redireciona.
  const inicio = await page.goto("/");
  expect(inicio?.status()).toBe(200);
  expect(new URL(page.url()).pathname).toBe("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Planejamento público, com método");

  // /entrar fica em /entrar: nem formulário, nem redirecionamento silencioso.
  await page.getByRole("link", { name: "Entrar", exact: true }).first().click();
  await expect(page).toHaveURL(/\/entrar$/);
  await expect(page.getByRole("heading", { level: 1, name: "Você já está conectado" })).toBeVisible();
  await expect(page.getByTestId("sessao-email")).toHaveText(A.email);
  await expect(page.getByLabel("Senha", { exact: true })).toHaveCount(0);

  await page.getByRole("link", { name: "Continuar no aplicativo" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByTestId("usuario-email")).toHaveText(A.email);

  // Refresh mantém a sessão: nada de pedir a senha a cada navegação.
  await page.reload();
  await expect(page.getByTestId("usuario-email")).toHaveText(A.email);
  expect(erros).toEqual([]);
});

test("link profundo com sessão: /entrar preserva o destino validado", async ({ page }) => {
  await page.goto("/entrar");
  await entrar(page, B);
  await page.waitForURL(/\/app$/);

  await page.goto("/entrar?proximo=/app/processos");
  await page.getByRole("link", { name: "Continuar no aplicativo" }).click();
  await expect(page).toHaveURL(/\/app\/processos$/);

  // Destino de fora do site não vira link.
  await page.goto("/entrar?proximo=https://site-falso.example/app");
  await expect(page.getByRole("link", { name: "Continuar no aplicativo" })).toHaveAttribute("href", "/app");
});

test("sair e trocar de conta: sessão encerrada, nada privado volta", async ({ page }) => {
  await page.goto("/entrar?proximo=/app/processos");
  await entrar(page, A);
  await page.waitForURL(/\/app\/processos$/);

  await page.goto("/entrar?proximo=/app/processos");
  await page.getByRole("button", { name: "Sair / trocar de conta" }).click();
  await expect(page).toHaveURL(/\/entrar\?saiu=1&proximo=%2Fapp%2Fprocessos$/);
  await expect(page.getByText("Sessão encerrada.")).toBeVisible();

  // Voltar no navegador não mostra a página privada, nem por cache.
  await page.goBack();
  await expect(page.getByTestId("usuario-email")).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/\/entrar/);
  await expect(page.getByTestId("usuario-email")).toHaveCount(0);

  // A área privada exige login de novo; o outro usuário entra no destino.
  await page.goto("/app/processos");
  await expect(page).toHaveURL(/\/entrar\?proximo=%2Fapp%2Fprocessos/);
  await entrar(page, B);
  await page.waitForURL(/\/app\/processos$/);
  await expect(page.getByTestId("usuario-email")).toHaveText(B.email);
  await expect(page.getByText(A.email)).toHaveCount(0);
});

test("sessão apagada no navegador: /entrar volta ao formulário, /app barra", async ({ page, context }) => {
  await page.goto("/entrar");
  await entrar(page, A);
  await page.waitForURL(/\/app$/);

  // Cookie adulterado é o mesmo que nenhum: assinatura não confere.
  const cookies = await context.cookies();
  const sessao = cookies.filter((c) => c.name.includes("auth-token"));
  expect(sessao.length).toBeGreaterThan(0);
  await context.clearCookies();
  await context.addCookies(sessao.map((c) => ({ ...c, value: "base64-e30" })));

  await page.goto("/entrar");
  await expect(page.getByRole("button", { name: "Entrar", exact: true })).toBeVisible();
  await page.goto("/app/processos");
  await expect(page).toHaveURL(/\/entrar\?proximo=%2Fapp%2Fprocessos/);
});

test("conta sem vínculo: sessão existe, mas /app não abre o órgão", async ({ page }) => {
  await page.goto("/entrar");
  await entrar(page, REVOGADA);
  await expect(page.getByText("sem vínculo ativo")).toBeVisible();

  // /entrar não prende a pessoa: dá para sair e entrar com outra conta.
  await page.goto("/entrar");
  await expect(page.getByTestId("sessao-email")).toHaveText(REVOGADA.email);
  await page.getByRole("button", { name: "Sair / trocar de conta" }).click();
  await expect(page.getByRole("button", { name: "Entrar", exact: true })).toBeVisible();
});
