import { mkdirSync, readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Layout das duas telas corrigidas em 11/11/2026, na pilha REAL e nas larguras
 * que o dono usa (1920 × 1080 e 1366 × 768) mais o celular:
 *
 * - Pesquisa de Preços (página do item, semente `semear_larguras`, com um item
 *   de descrição sem espaço): Itens | busca e triagem | Cesta no desktop, em
 *   sequência no estreito; cada linha do navegador contida no cartão Itens;
 *   Termo, Período e UF alinhados pela base, e o seletor mostrando cada
 *   período por inteiro; Contratação similar no PNCP numa linha própria, com
 *   as ações abaixo; sem rolagem lateral.
 * - WordCraft (editor sem motor na pilha): faixa do documento numa linha só,
 *   sem a barra superior da casca, e a área do documento ocupando o resto da
 *   altura. Alternar painéis com o motor de verdade é prova da vitrine
 *   (design-system.spec) e do canário em produção.
 *
 * Capturas em e2e/resultados/layout/ (artefato `web-e2e-telas`).
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
  larguras: { pesquisa: string; item: string };
  editor: { processo: string; etp: string };
};
const ITEM = `/app/precos/${estado.larguras.pesquisa}/itens/${estado.larguras.item}`;
const EDITOR = `/app/processos/${estado.editor.processo}/documentos/${estado.editor.etp}/editar`;
const PASTA = "e2e/resultados/layout";
mkdirSync(PASTA, { recursive: true });

const DESKTOP = [
  { nome: "1920", width: 1920, height: 1080 },
  { nome: "1366", width: 1366, height: 768 },
];

async function entrar(page: Page, conta: Conta) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

async function semRolagemLateral(page: Page) {
  const r = await page.evaluate(() => {
    const main = document.querySelector(".gc-shell__content")!;
    return {
      documento: document.documentElement.scrollWidth,
      janela: window.innerWidth,
      main: main.scrollWidth - main.clientWidth,
    };
  });
  expect(r.documento, "rolagem lateral da página").toBeLessThanOrEqual(r.janela);
  expect(r.main, "rolagem lateral do conteúdo").toBeLessThanOrEqual(1);
}

/** Navegador de itens: linha, ícone e texto dentro do cartão; item atual à vista. */
async function itensContidos(page: Page) {
  const m = await page.getByTestId("cartao-itens").evaluate((cartao) => {
    const r = (e: Element) => e.getBoundingClientRect();
    const limite = r(cartao);
    const lista = cartao.querySelector("ul")!;
    const botoes = [...cartao.querySelectorAll(".gc-itemnav__btn")];
    const atual = cartao.querySelector('[aria-current="true"]')!;
    return {
      linhas: botoes.length,
      linhasFora: botoes.filter((b) => r(b).right > limite.right + 0.5 || r(b).left < limite.left - 0.5).length,
      iconesFora: botoes.filter((b) => r(b.querySelector(".gc-itemnav__status")!).right > r(b).right + 0.5).length,
      textoFora: [...cartao.querySelectorAll(".gc-itemnav__title")].filter((t) => t.scrollWidth > t.clientWidth + 1).length,
      atualVisivel: r(atual).top >= r(lista).top - 0.5 && r(atual).bottom <= r(lista).bottom + 0.5,
    };
  });
  expect(m.linhas).toBeGreaterThan(1);
  expect(m.linhasFora, "linha do navegador além do cartão Itens").toBe(0);
  expect(m.iconesFora, "ícone de situação além da linha").toBe(0);
  expect(m.textoFora, "descrição estourando a própria caixa").toBe(0);
  expect(m.atualVisivel, "item atual fora da vista").toBe(true);
}

/** Cada período cabe inteiro no seletor ("Último ano" incluído). */
async function periodoLegivel(page: Page) {
  const sobra = await page.locator("#busca-janela").evaluate((sel: HTMLSelectElement) => {
    const estilo = getComputedStyle(sel);
    const ctx = document.createElement("canvas").getContext("2d")!;
    ctx.font = estilo.font;
    const livre = sel.clientWidth - parseFloat(estilo.paddingLeft) - parseFloat(estilo.paddingRight);
    return Math.min(...[...sel.options].map((o) => livre - ctx.measureText(o.text).width));
  });
  expect(sobra, "período cortado no seletor").toBeGreaterThanOrEqual(0);
  await expect(page.locator("#busca-janela")).toHaveValue("365");
  await expect(page.locator("#busca-janela option:checked")).toHaveText("Último ano");
}

test.describe.configure({ mode: "serial" });

test("Pesquisa de Preços: três colunas no desktop, linhas contidas, busca alinhada", async ({ page }) => {
  await entrar(page, estado.contas.admin_larguras);
  for (const tela of DESKTOP) {
    await page.setViewportSize({ width: tela.width, height: tela.height });
    await page.goto(ITEM);
    await expect(page.getByTestId("busca-item")).toBeVisible();

    const caixa = async (seletor: string) => (await page.locator(seletor).first().boundingBox())!;
    const itens = await caixa('[data-testid="cartao-itens"]');
    const cartaoBusca = await caixa('section.gc-card:has([data-testid="busca-item"])');
    const busca = await caixa('[data-testid="busca-item"]');
    const cesta = await caixa('[data-testid="cartao-cesta"]');
    expect(itens.x + itens.width, `${tela.nome}: Itens invade a busca`).toBeLessThanOrEqual(cartaoBusca.x);
    expect(cartaoBusca.x + cartaoBusca.width, `${tela.nome}: busca invade a Cesta`).toBeLessThanOrEqual(cesta.x);
    // A triagem vem logo abaixo da busca, na mesma coluna.
    const triagem = await caixa("h2#triagem");
    expect(triagem.y).toBeGreaterThan(cartaoBusca.y + cartaoBusca.height - 1);
    expect(Math.abs(triagem.x - cartaoBusca.x)).toBeLessThanOrEqual(1);

    // Termo, Período e UF: base comum, mesmo quando quebram em duas linhas.
    const base = await Promise.all(
      ["#busca-termo", "#busca-janela", "#busca-uf"].map(async (s) => {
        const b = (await page.locator(s).boundingBox())!;
        return { y: b.y, fundo: b.y + b.height };
      }),
    );
    // A largura que decide é a do cartão (container query): ≥ 42rem, uma linha;
    // ≥ 24rem, termo em cima e período e UF juntos embaixo.
    const rem = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
    if (busca.width >= 42 * rem) {
      expect(Math.max(...base.map((b) => b.fundo)) - Math.min(...base.map((b) => b.fundo)), "linha da busca desalinhada").toBeLessThanOrEqual(1);
    } else {
      expect(busca.width, `${tela.nome}: cartão da busca estreito demais`).toBeGreaterThanOrEqual(24 * rem);
      expect(Math.abs(base[1].fundo - base[2].fundo), "período e UF desalinhados").toBeLessThanOrEqual(1);
      expect(base[1].y, "período ao lado do termo sem caber").toBeGreaterThan(base[0].fundo);
    }
    const pncp = (await page.locator("#busca-pncp").boundingBox())!;
    expect(pncp.y, "PNCP numa linha própria, abaixo dos campos").toBeGreaterThan(Math.max(...base.map((b) => b.fundo)));
    const acao = (await page.getByRole("button", { name: "Pesquisar preços" }).boundingBox())!;
    expect(acao.y, "ações abaixo do PNCP").toBeGreaterThan(pncp.y + pncp.height);

    await periodoLegivel(page);
    await itensContidos(page);
    await semRolagemLateral(page);
    await page.screenshot({ path: `${PASTA}/precos-item-${tela.nome}.png` });
  }
});

test("Pesquisa de Preços no celular: blocos em sequência, seletor aberto", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await entrar(page, estado.contas.admin_larguras);
  await page.goto(ITEM);
  await expect(page.getByTestId("busca-item")).toBeVisible();

  const topo = async (seletor: string) => (await page.locator(seletor).first().boundingBox())!;
  const itens = await topo('[data-testid="cartao-itens"]');
  const busca = await topo('[data-testid="busca-item"]');
  const triagem = await topo("h2#triagem");
  const cesta = await topo('[data-testid="cartao-cesta"]');
  expect(busca.y).toBeGreaterThan(itens.y + itens.height - 1);
  expect(triagem.y).toBeGreaterThan(busca.y);
  expect(cesta.y).toBeGreaterThan(triagem.y);
  for (const b of [itens, busca, cesta]) expect(b.x + b.width).toBeLessThanOrEqual(390);

  await itensContidos(page);
  await semRolagemLateral(page);
  // Seletor aberto: o celular desenha a lista por cima; o campo não muda de lugar.
  const antes = await topo("#busca-janela");
  await page.locator("#busca-janela").scrollIntoViewIfNeeded();
  await page.locator("#busca-janela").focus();
  await page.keyboard.press("Alt+ArrowDown");
  await periodoLegivel(page);
  await semRolagemLateral(page);
  const depois = await topo("#busca-janela");
  expect(depois.width).toBe(antes.width);
  await page.screenshot({ path: `${PASTA}/precos-item-390-seletor.png` });
  await page.keyboard.press("Escape");
  await page.screenshot({ path: `${PASTA}/precos-item-390.png`, fullPage: true });
});

test("WordCraft: faixa compacta, sem barra superior, documento com a altura da tela", async ({ page }) => {
  await entrar(page, estado.contas.editor_a);
  for (const tela of DESKTOP) {
    await page.setViewportSize({ width: tela.width, height: tela.height });
    await page.goto(EDITOR);
    await expect(page.getByTestId("titulo-documento")).toBeVisible();
    // A trilha da casca repetia o "Voltar ao processo": no editor ela sai.
    await expect(page.locator(".gc-topbar")).toBeHidden();
    await expect(page.getByRole("button", { name: "Voltar ao processo" }).or(page.getByRole("link", { name: "Voltar ao processo" })).first()).toBeVisible();
    // Situação só uma vez: a revisão mora no indicador de salvamento.
    const selos = await page.evaluate(() => document.querySelector(".gc-workspace__meta")?.textContent ?? "");
    expect(selos).not.toMatch(/Revisão \d/);

    const m = await page.evaluate(() => {
      const r = (s: string) => document.querySelector(s)!.getBoundingClientRect();
      return {
        faixa: r(".gc-workspace__bar").height,
        controle: parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--control-lg")),
        corpoFundo: r(".gc-workspace__body").bottom,
        corpoAltura: r(".gc-workspace__body").height,
        pagina: document.documentElement.scrollHeight,
        janela: window.innerHeight,
      };
    });
    expect(m.faixa, `${tela.nome}: faixa do documento em mais de uma linha`).toBeLessThan(m.controle * 1.5);
    expect(m.corpoFundo, `${tela.nome}: documento não vai até o pé da janela`).toBeGreaterThanOrEqual(m.janela - 1);
    // Sem barra superior e com a faixa numa linha, o documento fica com quase toda a altura.
    expect(m.corpoAltura, `${tela.nome}: altura do documento`).toBeGreaterThanOrEqual(m.janela - m.controle * 3);
    expect(m.pagina, `${tela.nome}: a página rola em vez do documento`).toBeLessThanOrEqual(m.janela);
    await semRolagemLateral(page);
    await page.screenshot({ path: `${PASTA}/editor-${tela.nome}.png` });
  }
});
