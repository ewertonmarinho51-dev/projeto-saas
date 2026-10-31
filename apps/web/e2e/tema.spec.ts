import { mkdirSync, readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Tema claro em aparelho configurado no escuro (Issue #152, PR A).
 *
 * O navegador daqui inteiro pede escuro (`colorScheme: "dark"`). Toda tela
 * tem de sair clara na primeira visita e no refresh, sem depender de
 * JavaScript: a cor é lida com a página recém-carregada, e `erros` pega a
 * divergência de hidratação, que o React acusa no console.
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
};
const conta = estado.contas.admin_tema;

const CLARO = {
  fundo: "rgb(246, 248, 252)", // --bg-app
  superficie: "rgb(255, 255, 255)", // --surface-card
  texto: "rgb(23, 36, 58)", // --text-primary
  acento: "rgb(0, 89, 214)", // --accent, o #0059D6 oficial
};

const PASTA = "e2e/resultados/tema";
mkdirSync(PASTA, { recursive: true });

test.use({ colorScheme: "dark" });
test.describe.configure({ mode: "serial" });

function vigiarConsole(page: Page) {
  const erros: string[] = [];
  page.on("console", (m) => m.type() === "error" && erros.push(m.text()));
  page.on("pageerror", (e) => erros.push(e.message));
  return erros;
}

/** Lê os tokens e as cores pintadas; `--bg-app` escuro aqui é a falha. */
async function exigirClaro(page: Page) {
  const lido = await page.evaluate(() => {
    const raiz = getComputedStyle(document.documentElement);
    const sonda = document.createElement("div");
    document.body.append(sonda);
    const ler = (cor: string) => {
      sonda.style.color = `var(${cor})`;
      return getComputedStyle(sonda).color;
    };
    const cores = {
      fundo: getComputedStyle(document.body).backgroundColor,
      superficie: ler("--surface-card"),
      texto: ler("--text-primary"),
      acento: ler("--accent"),
    };
    sonda.remove();
    return {
      ...cores,
      tema: document.documentElement.dataset.theme,
      esquema: raiz.colorScheme,
      sistemaEscuro: matchMedia("(prefers-color-scheme: dark)").matches,
    };
  });
  // Sem isto a prova não prova nada: o aparelho precisa estar no escuro.
  expect(lido.sistemaEscuro).toBe(true);
  expect(lido.tema).toBe("light");
  // O navegador serializa `only light` nesta ordem.
  expect(lido.esquema).toBe("light only");
  expect({ fundo: lido.fundo, superficie: lido.superficie, texto: lido.texto, acento: lido.acento }).toEqual(CLARO);
}

async function capturar(page: Page, nome: string) {
  for (const t of [
    { nome: "1440", width: 1440, height: 900 },
    { nome: "390", width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: t.width, height: t.height });
    await page.screenshot({ path: `${PASTA}/${nome}-${t.nome}.png` });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test("site público e login saem claros na primeira visita e no refresh", async ({ page }) => {
  const erros = vigiarConsole(page);
  for (const [rota, nome] of [
    ["/", "inicio"],
    ["/entrar", "entrar"],
    ["/solucoes", "solucoes"],
    ["/contato", "contato"],
    ["/privacidade", "privacidade"],
  ] as const) {
    await page.goto(rota);
    await exigirClaro(page);
    await page.reload();
    await exigirClaro(page);
    await capturar(page, nome);
  }
  expect(erros).toEqual([]);
});

test("404 sai clara: a página padrão do Next obedece ao tema do aparelho", async ({ page }) => {
  const resposta = await page.goto("/pagina-que-nao-existe");
  expect(resposta?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Página não encontrada" })).toBeVisible();
  await exigirClaro(page);
  await capturar(page, "nao-encontrada");
});

test("HTML cru já sai claro: nada depende de JavaScript", async ({ request }) => {
  const html = await (await request.get("/")).text();
  expect(html).toMatch(/<html[^>]*data-theme="light"/);
  expect(html).toContain('<meta name="color-scheme" content="only light"');
});

test("área autenticada, tabela, menu e diálogo saem claros", async ({ page }) => {
  const erros = vigiarConsole(page);
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
  await exigirClaro(page);
  await capturar(page, "painel");

  // Toda tela do menu desta conta: Processos, Preços, GovBot, administração...
  const menu = page.getByRole("navigation", { name: "Navegação principal" });
  const rotas = await menu.getByRole("link").evaluateAll((links) => links.map((a) => a.getAttribute("href") ?? ""));
  expect(rotas.length).toBeGreaterThanOrEqual(8);
  for (const rota of rotas) {
    await page.goto(rota);
    await exigirClaro(page);
    await page.reload();
    await exigirClaro(page);
    await capturar(page, `tela${rota.replaceAll("/", "-")}`);
  }

  // 404 dentro da casca, com o status certo: nada de 200 mascarando.
  const ausente = await page.goto("/app/processos/00000000-0000-4000-8000-000000000000");
  expect(ausente?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Página não encontrada" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Navegação principal" })).toBeVisible();
  await exigirClaro(page);
  erros.length = 0; // O 404 acima loga no console, e é o esperado.

  // Sobreposição: a gaveta do celular, por cima do conteúdo.
  await page.goto("/app/processos");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("Abrir menu").click();
  await expect(page.locator(".gc-shell__scrim")).toBeVisible();
  await exigirClaro(page);
  await page.screenshot({ path: `${PASTA}/gaveta-390.png` });
  expect(erros).toEqual([]);
});
