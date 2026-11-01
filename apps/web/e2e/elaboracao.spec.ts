import { mkdirSync, readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Elaboração automática na pilha REAL: web + API + fila + worker + GoTrue +
 * PostgREST. Só a resposta do modelo é falsa (`tests_rls/motor_falso.py`), e
 * o worker chega nela pela URL de gateway do próprio produto. Fila, job, RLS,
 * CAS e gravação no processo são os de verdade.
 *
 * A abertura no WordCraft fica para o canário em produção: a pilha não tem o
 * runtime aprovado nem a credencial documental.
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
  elaboracao: { pronto: string; falha: string };
};
const PASTA = "e2e/resultados/telas";
mkdirSync(PASTA, { recursive: true });

async function entrar(page: Page) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.elaborador_a.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.elaborador_a.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test.describe.configure({ mode: "serial" });

test("criar processo: sem os dados obrigatórios, a próxima ação é o formulário", async ({ page }) => {
  await entrar(page);
  await page.goto("/app/processos");
  await page.getByLabel("Órgão ou secretaria").fill("Secretaria de Administração");
  await page.getByLabel("Objeto da contratação").fill(`Papel A4 E2E ${Date.now()}`);
  await page.getByRole("button", { name: "Criar processo" }).click();
  await expect(page.getByText("Processo criado.")).toBeVisible();

  const acao = page.getByTestId("proxima-acao");
  await expect(acao.getByText(/campos? obrigatórios?/)).toBeVisible();
  await expect(acao.getByRole("link", { name: "Preencher dados da demanda" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Iniciar elaboração automática" })).toHaveCount(0);
});

test("iniciar, acompanhar, recarregar no meio e receber o documento", async ({ page }) => {
  await entrar(page);
  await page.goto(`/app/processos/${estado.elaboracao.pronto}`);
  await expect(page.getByRole("list", { name: "Etapas da fase preparatória" })).toBeVisible();
  // Resumo, não formulário: ele só aparece quando pedido.
  await expect(page.getByLabel("Objeto da contratação")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Editar dados do processo" })).toBeVisible();
  await page.screenshot({
    path: `${PASTA}/elaboracao-pronta.png`,
    fullPage: true,
  });

  const acao = page.getByTestId("proxima-acao");
  const botao = acao.getByRole("button", {
    name: "Iniciar elaboração automática",
  });
  await botao.click();
  await expect(acao.getByText("Pode sair desta tela")).toBeVisible({
    timeout: 15000,
  });
  await expect(botao).toHaveCount(0);
  await page.screenshot({
    path: `${PASTA}/elaboracao-em-curso.png`,
    fullPage: true,
  });

  // Recarregar com a geração em curso volta à mesma geração, sem pedir outra.
  await page.reload();
  await expect(acao.getByText("Pode sair desta tela")).toBeVisible();

  await expect(acao.getByText("DFD pronto para revisão.", { exact: false })).toBeVisible({ timeout: 60000 });
  const lista = page.getByTestId("documentos-do-processo");
  await expect(lista.getByText("Aguardando revisão")).toHaveCount(1);
  // O que impediria a aprovação aparece antes de a pessoa tentar aprovar.
  await expect(acao.getByText(/impedem? a aprovação/)).toBeVisible();
  await expect(acao.getByText(/matrícula do responsável/)).toBeVisible();
  // Uma ação por documento: o da vez não repete o botão na lista.
  await expect(lista.getByRole("link", { name: "Abrir no editor" })).toHaveCount(0);
  await page.screenshot({
    path: `${PASTA}/elaboracao-concluida.png`,
    fullPage: true,
  });

  // O resultado está no banco: nova carga, mesmo estado, e sem gerar de novo.
  await page.reload();
  await expect(acao.getByText("DFD pronto para revisão.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Iniciar elaboração automática" })).toHaveCount(0);
});

test("motor recusou: a tela explica, preserva o processo e tenta de novo", async ({ page }) => {
  await entrar(page);
  await page.goto(`/app/processos/${estado.elaboracao.falha}`);
  const acao = page.getByTestId("proxima-acao");
  await acao.getByRole("button", { name: "Iniciar elaboração automática" }).click();
  await expect(acao.getByText("Não foi possível elaborar o DFD")).toBeVisible({
    timeout: 60000,
  });
  await expect(acao.getByText(/foi preservado/)).toBeVisible();

  await page.reload();
  await expect(acao.getByText("Não foi possível elaborar o DFD")).toBeVisible();
  await acao.getByRole("button", { name: "Tentar novamente" }).click();
  await expect(acao.getByText("DFD pronto para revisão.", { exact: false })).toBeVisible({ timeout: 60000 });
});
