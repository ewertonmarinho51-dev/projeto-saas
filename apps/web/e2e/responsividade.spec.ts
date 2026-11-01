import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Responsividade global: TODAS as rotas do Next, nas 4 larguras, na pilha
 * REAL e com a semente de pior caso (`semear_larguras`): nomes compridos,
 * palavra sem espaço, valor alto, tabela de 40 itens.
 *
 * Cada varredura reprova, além da rolagem lateral do documento:
 *   - rolagem lateral do `main` (`.gc-shell__content` tem `overflow-y:auto`, o
 *     que liga `overflow-x` também, e o documento continuaria sem rolar);
 *   - elemento além da janela, fora de área de rolagem interna declarada;
 *   - controle (link, botão, campo) cortado por quem esconde o excesso;
 *   - texto que estoura a própria caixa.
 *
 * Rolagem interna só é permitida em `ROLAGEM_INTERNA`: tabela extensa, etapas e
 * abas. O relatório inteiro vai para e2e/resultados/responsividade/, com uma
 * captura por rota e largura, e a prova falha só no fim, com tudo que achou.
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
  larguras: { processo: string; pesquisa: string; item: string; processo_b: string };
  editor: { processo: string; etp: string };
};
const { processo, pesquisa, item, processo_b } = estado.larguras;

const LARGURAS = [
  { largura: 390, altura: 844 },
  { largura: 768, altura: 1024 },
  { largura: 1440, altura: 900 },
  { largura: 1920, altura: 1080 },
];
const PASTA = "e2e/resultados/responsividade";
mkdirSync(PASTA, { recursive: true });

const ROLAGEM_INTERNA = ".gc-table-wrap, .gc-stepper, .gc-tabs, .gc-shell__nav, .gc-sidebar";

const PUBLICAS = [
  ["landing", "/"],
  ["sobre", "/sobre"],
  ["solucoes", "/solucoes"],
  ["solucoes-documentos", "/solucoes/documentos-ia"],
  ["solucoes-precos", "/solucoes/pesquisa-de-precos"],
  ["como-funciona", "/como-funciona"],
  ["contato", "/contato"],
  ["privacidade", "/privacidade"],
  ["entrar", "/entrar"],
  ["recuperar", "/entrar/recuperar"],
  ["vitrine", "/design-system"],
] as const;

const AUTENTICADAS = [
  ["inicio", "/app"],
  ["processos", "/app/processos"],
  ["processo", `/app/processos/${processo}`],
  ["processo-editando", `/app/processos/${processo}?editar=1`],
  ["formulario", `/app/processos/${processo}/formulario`],
  ["editor", `/app/processos/${estado.editor.processo}/documentos/${estado.editor.etp}/editar`],
  ["precos", "/app/precos"],
  ["precos-nova", "/app/precos/nova"],
  ["pesquisa", `/app/precos/${pesquisa}`],
  ["item", `/app/precos/${pesquisa}/itens/${item}`],
  ["govbot", "/app/govbot"],
  ["governanca", "/app/governanca"],
  ["instituicao", "/app/admin/instituicao"],
  ["usuarios", "/app/admin/usuarios"],
  ["base-conhecimento", "/app/admin/base-conhecimento"],
  ["senha", "/app/conta/senha"],
] as const;

type Achado = { rota: string; largura: number; tipo: string; alvo: string; detalhe?: string };
const achados: Achado[] = [];

/** Roda no navegador: devolve o que está fora do lugar nesta tela. */
function varrer(rolagemInterna: string) {
  const janela = document.documentElement.clientWidth;
  const achou: { tipo: string; alvo: string; detalhe?: string }[] = [];
  const nome = (el: Element) => {
    const classes = typeof el.className === "string" ? el.className.trim().split(/\s+/).slice(0, 3).join(".") : "";
    const texto = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
    return `${el.tagName.toLowerCase()}${classes ? `.${classes}` : ""}${texto ? ` “${texto}”` : ""}`;
  };
  const interativo = 'a[href],button,input:not([type=hidden]):not([type=file]),select,textarea,[role=button],[role=tab],[role=menuitem]';

  const raiz = document.documentElement;
  if (raiz.scrollWidth > janela) achou.push({ tipo: "rolagem-do-documento", alvo: "html", detalhe: `${raiz.scrollWidth} > ${janela}` });
  for (const conteudo of document.querySelectorAll(".gc-shell__content")) {
    if (conteudo.scrollWidth > conteudo.clientWidth + 1) {
      achou.push({ tipo: "rolagem-do-main", alvo: nome(conteudo), detalhe: `${conteudo.scrollWidth} > ${conteudo.clientWidth}` });
    }
  }

  for (const el of document.body.querySelectorAll("*")) {
    if (el.closest("svg") && el.tagName.toLowerCase() !== "svg") continue;
    if (el.closest(".sr-only, .gc-wordcraft-editor, [aria-hidden=true], #__next-build-watcher, nextjs-portal")) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) continue;
    const estilo = getComputedStyle(el);
    if (estilo.visibility !== "visible" || estilo.display === "none") continue;

    let corte: Element | null = null;
    let area = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      if (getComputedStyle(p).position === "fixed" && !p.matches(".gc-shell__nav")) break;
      const excesso = getComputedStyle(p).overflowX;
      if (excesso === "visible") continue;
      if (p.matches(rolagemInterna)) {
        area = true;
        break;
      }
      if (p.matches(".gc-shell__content")) continue;
      if (excesso === "hidden" || excesso === "clip") corte ??= p;
    }

    if (!area && !corte && (r.right > janela + 1 || r.left < -1)) {
      achou.push({ tipo: "alem-da-janela", alvo: nome(el), detalhe: `${Math.round(r.left)}..${Math.round(r.right)} em ${janela}` });
    }
    if (!area && corte && el.matches(interativo)) {
      const c = corte.getBoundingClientRect();
      if (r.right > c.right + 1 || r.left < c.left - 1) {
        achou.push({ tipo: "controle-cortado", alvo: nome(el), detalhe: `${Math.round(r.right)} além de ${Math.round(c.right)} em ${nome(corte)}` });
      }
    }
    const folha = el.children.length === 0 && (el.textContent ?? "").trim().length > 0;
    if (!area && folha && estilo.display !== "inline" && estilo.overflowX === "visible" && el.scrollWidth > el.clientWidth + 1) {
      achou.push({ tipo: "texto-estoura", alvo: nome(el), detalhe: `${el.scrollWidth} > ${el.clientWidth}` });
    }
  }

  // Quanto a coluna de conteúdo aproveita da área que tem (não reprova: serve à leitura das capturas).
  const pagina = document.querySelector(".gc-shell__page")?.getBoundingClientRect().width ?? 0;
  const disponivel = document.querySelector(".gc-shell__content")?.getBoundingClientRect().width ?? 0;
  return { achou, ocupacao: disponivel ? Math.round((pagina / disponivel) * 100) : null };
}

const ocupacao: Record<string, number | null> = {};

async function aguardarConteudo(page: Page) {
  await page.waitForLoadState("load");
  await expect(page.locator('[data-testid="esqueleto"]')).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
}

async function examinar(page: Page, rota: string, largura: number) {
  const { achou, ocupacao: uso } = await page.evaluate(varrer, ROLAGEM_INTERNA);
  const vistos = new Set<string>();
  for (const a of achou) {
    const chave = `${a.tipo}|${a.alvo}`;
    if (vistos.has(chave)) continue;
    vistos.add(chave);
    achados.push({ rota, largura, ...a });
  }
  ocupacao[`${rota}@${largura}`] = uso;
  await page.screenshot({ path: `${PASTA}/${rota}-${largura}.png`, fullPage: true });
}

function publicarRelatorio() {
  writeFileSync(`${PASTA}/relatorio.json`, JSON.stringify({ achados, ocupacao }, null, 2));
}

function reprovarSeAchou(prefixos: readonly string[]) {
  publicarRelatorio();
  const meus = achados.filter((a) => prefixos.includes(a.rota));
  if (meus.length) console.log("RESPONSIVIDADE", JSON.stringify(meus));
  expect(meus.map((a) => `${a.rota}@${a.largura} ${a.tipo}: ${a.alvo} (${a.detalhe ?? ""})`)).toEqual([]);
}

async function entrar(page: Page, conta: Conta) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test("site público e entrada nas 4 larguras", async ({ page }) => {
  test.setTimeout(240_000);
  for (const [nome, rota] of PUBLICAS) {
    for (const { largura, altura } of LARGURAS) {
      await page.setViewportSize({ width: largura, height: altura });
      const resposta = await page.goto(rota);
      expect(resposta?.status(), rota).toBe(200);
      await aguardarConteudo(page);
      await examinar(page, nome, largura);
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/nao-existe");
  await examinar(page, "nao-encontrada", 390);
  reprovarSeAchou([...PUBLICAS.map(([n]) => n), "nao-encontrada"]);
});

test("área autenticada nas 4 larguras", async ({ page }) => {
  test.setTimeout(240_000);
  await entrar(page, estado.contas.admin_larguras);
  // Uma carga por rota: o limite de 120 pedidos por minuto vale para a conta.
  for (const [nome, rota] of AUTENTICADAS) {
    await page.setViewportSize({ width: LARGURAS[0].largura, height: LARGURAS[0].altura });
    const resposta = await page.goto(rota);
    expect(resposta?.status(), rota).toBe(200);
    await aguardarConteudo(page);
    for (const { largura, altura } of LARGURAS) {
      await page.setViewportSize({ width: largura, height: altura });
      await examinar(page, nome, largura);
    }
  }
  reprovarSeAchou(AUTENTICADAS.map(([n]) => n));
});

test("Consolidar Demandas nas 4 larguras", async ({ page }) => {
  await entrar(page, estado.contas.larguras_b);
  await page.goto(`/app/processos/${processo_b}/demandas`);
  await aguardarConteudo(page);
  for (const { largura, altura } of LARGURAS) {
    await page.setViewportSize({ width: largura, height: altura });
    await examinar(page, "demandas", largura);
  }
  reprovarSeAchou(["demandas"]);
});

test("gaveta, menu de linha e diálogo cabem no celular com os controles alcançáveis", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await entrar(page, estado.contas.admin_larguras);

  const menu = page.getByRole("navigation", { name: "Navegação principal" });
  await page.getByRole("button", { name: "Abrir menu" }).click();
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("link", { name: "Processos", exact: true })).toBeInViewport({ ratio: 1 });
  await examinar(page, "gaveta", 390);
  await menu.getByRole("link", { name: "Processos", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/processos$/);
  await aguardarConteudo(page);

  const acoes = page.getByRole("table", { name: "Processos do órgão" }).getByRole("button", { name: /^Mais ações/ }).first();
  await acoes.scrollIntoViewIfNeeded();
  await acoes.click();
  const opcao = page.getByRole("menuitem").first();
  await expect(opcao).toBeInViewport({ ratio: 1 });
  await examinar(page, "menu-de-linha", 390);
  await page.keyboard.press("Escape");

  await page.goto(`/app/precos/${pesquisa}/itens/${item}`);
  await aguardarConteudo(page);
  await page.getByRole("button", { name: "Ver origem" }).first().click();
  const dialogo = page.getByRole("dialog");
  await expect(dialogo).toBeVisible();
  await expect(dialogo.getByRole("button", { name: "Fechar", exact: true }).first()).toBeInViewport({ ratio: 1 });
  await expect(dialogo).toBeInViewport({ ratio: 1 });
  await examinar(page, "dialogo", 390);
  await dialogo.getByRole("button", { name: "Fechar", exact: true }).last().click();
  reprovarSeAchou(["gaveta", "menu-de-linha", "dialogo"]);
});
