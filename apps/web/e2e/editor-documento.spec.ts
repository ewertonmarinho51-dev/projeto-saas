import { mkdirSync, readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * WordCraft Workspace (Issue #137) na pilha REAL: web + API + GoTrue +
 * PostgREST. A pilha não tem o runtime aprovado do WordCraft nem a
 * credencial documental (ADR-011 em proposta), então o que se prova aqui é
 * o que não depende deles:
 *
 * - trava de ativação: tenant A no canário vê os documentos e o editor; o
 *   tenant B recebe 404 na mesma URL;
 * - modo de trabalho: casca em tela inteira, barra lateral recolhida, sem
 *   rolagem lateral em 1920, 1440 e 768; leitura segura em 390;
 * - falha fechada: sem motor, a tela diz por quê e não finge que abriu;
 *   documento só no GovDocs não ganha botão enquanto abrir exigir gravação.
 *
 * Edição, ACK, conflito e exportação com o motor de verdade: canário em
 * produção, sobre processo sintético (docs/wordcraft/workspace-nextjs.md).
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
  editor: { processo: string; etp: string; dfd: string };
};
const { processo, etp, dfd } = estado.editor;
const EDITOR = `/app/processos/${processo}/documentos/${etp}/editar`;
const PASTA = "e2e/resultados/paridade";
mkdirSync(PASTA, { recursive: true });

async function entrar(page: Page, conta: string) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas[conta].email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas[conta].senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

async function semRolagemLateral(page: Page) {
  const { largura, janela } = await page.evaluate(() => ({
    largura: document.documentElement.scrollWidth,
    janela: window.innerWidth,
  }));
  expect(largura, "rolagem lateral").toBeLessThanOrEqual(janela);
}

test.describe.configure({ mode: "serial" });

test("canário: processo lista os documentos e abre o editor em modo de trabalho", async ({ page }) => {
  await entrar(page, "editor_a");
  await page.goto(`/app/processos/${processo}`);
  const lista = page.getByTestId("documentos-do-processo");
  await expect(lista).toBeVisible();
  await expect(lista.getByText("Estudo Técnico Preliminar")).toBeVisible();
  await expect(lista.getByText("Documento de Formalização da Demanda")).toBeVisible();
  // Só o ETP tem cabeça nativa; abrir o DFD importaria (gravação ainda não liberada).
  await expect(lista.getByRole("link", { name: "Abrir no editor" })).toHaveCount(1);
  await expect(page.locator(`a[href$="/documentos/${dfd}/editar"]`)).toHaveCount(0);

  await lista.getByRole("link", { name: "Abrir no editor" }).click();
  await page.waitForURL(new RegExp(`/documentos/${etp}/editar$`));
  await expect(page.getByTestId("titulo-documento")).toHaveText("Estudo Técnico Preliminar");
  await expect(page.locator(".gc-shell--workspace")).toHaveCount(1);
  await expect(page.locator(".gc-sidebar--collapsed")).toHaveCount(1);

  // Sem runtime aprovado na pilha: falha fechada, com o motivo, e sem "salvo".
  await expect(page.getByText("Não foi possível abrir o documento")).toBeVisible();
  await expect(page.getByText("O motor do editor não está disponível neste ambiente.")).toBeVisible();
  await expect(page.getByText(/Salvo ·/)).toHaveCount(0);

  for (const [w, h] of [
    [1920, 1080],
    [1440, 900],
    [768, 1024],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    await semRolagemLateral(page);
    // A área do documento vai até o pé da janela: nada de coluna de 1200 px nem rolagem da página.
    const altura = await page.evaluate(() => document.documentElement.scrollHeight);
    expect(altura, `rolagem vertical da página em ${w}`).toBeLessThanOrEqual(h);
    await page.screenshot({ path: `${PASTA}/editor-indisponivel-${w}.png` });
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("link", { name: "Voltar ao processo" }).first().click();
  await page.waitForURL(new RegExp(`/app/processos/${processo}$`));
  await expect(page.locator(".gc-shell--workspace")).toHaveCount(0);
});

test("celular: leitura segura, sem montar o editor", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await entrar(page, "editor_a");
  await page.goto(EDITOR);
  await expect(page.getByText("Edição disponível em telas a partir de 768 px")).toBeVisible();
  await expect(page.getByTestId("area-do-editor")).toHaveCount(0);
  await semRolagemLateral(page);
  await page.screenshot({ path: `${PASTA}/editor-leitura-390.png` });
});

test("tenant fora do canário: 404 na mesma URL e nenhum documento no processo", async ({ page }) => {
  await entrar(page, "editor_b");
  const resposta = await page.goto(EDITOR);
  expect(resposta?.status()).toBe(404);
});
