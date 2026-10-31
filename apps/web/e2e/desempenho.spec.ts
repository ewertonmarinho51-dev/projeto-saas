import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Tempo de clique até o conteúdo, no build de produção (Issue #152, PR C).
 *
 * Mede, não julga: a pilha do CI não tem a distância real entre o usuário, a
 * VPS e o Supabase, então o número aqui serve para comparar duas versões, não
 * para prometer tempo em produção. O que reprova é comportamento: a tela tem de
 * chegar, e prefetch não pode multiplicar a carga no servidor.
 *
 * `primeiro_retorno`: até aparecer o `h1` da tela nova.
 * `conteudo`: até o seletor que só existe com os dados carregados.
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
};
const conta = estado.contas.admin_desempenho;

const ROTAS = [
  { nome: "Início", menu: "Início", url: /\/app$/, titulo: "Início", dados: "Processos recentes" },
  { nome: "Processos", menu: "Processos", url: /\/app\/processos$/, titulo: "Processos", dados: "Buscar processos" },
  { nome: "Preços", menu: "Preços", url: /\/app\/precos$/, titulo: "Pesquisas de preços", dados: null },
  { nome: "Usuários", menu: "Usuários", url: /\/app\/admin\/usuarios$/, titulo: "Usuários", dados: null },
  { nome: "Instituição", menu: "Instituição", url: /\/app\/admin\/instituicao/, titulo: null, dados: null },
];
const RODADAS = 6;
const PASTA = "e2e/resultados/desempenho";
mkdirSync(PASTA, { recursive: true });

function percentil(valores: number[], q: number): number {
  const ordenados = [...valores].sort((a, b) => a - b);
  return ordenados[Math.min(ordenados.length - 1, Math.floor(ordenados.length * q))];
}

async function esperarTela(page: Page, rota: (typeof ROTAS)[number]) {
  await page.waitForURL(rota.url);
  const titulo = rota.titulo
    ? page.getByRole("heading", { level: 1, name: rota.titulo, exact: true })
    : page.getByRole("heading", { level: 1 });
  await expect(titulo).toBeVisible();
}

test("o clique responde na hora, mesmo com a página seguinte demorando", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  // Atrasa a página seguinte: sem a barra, nada mudaria na tela neste tempo.
  await page.route(/\/app\/admin\/usuarios/, async (rota) => {
    await new Promise((r) => setTimeout(r, 1500));
    await rota.continue();
  });
  const barra = page.getByRole("progressbar", { name: "Carregando a página" });
  await page.getByRole("navigation", { name: "Navegação principal" }).getByRole("link", { name: "Usuários", exact: true }).click();
  await expect(barra).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Usuários", exact: true })).toBeVisible();
  await expect(barra).toHaveCount(0);

  // Clicar na página em que já se está não promete navegação nenhuma.
  await page.unroute(/\/app\/admin\/usuarios/);
  await page.getByRole("navigation", { name: "Navegação principal" }).getByRole("link", { name: "Usuários", exact: true }).click();
  await expect(barra).toHaveCount(0);
});

test("clique até o conteúdo nas telas principais", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  let prefetches = 0;
  let navegacoes = 0;
  page.on("request", (r) => {
    const cabecalhos = r.headers();
    if (!cabecalhos.rsc) return;
    if (cabecalhos["next-router-prefetch"]) prefetches += 1;
    else navegacoes += 1;
  });

  const menu = page.getByRole("navigation", { name: "Navegação principal" });
  const tempos = new Map<string, { retorno: number[]; conteudo: number[] }>();
  for (let rodada = 0; rodada < RODADAS; rodada++) {
    for (const rota of ROTAS) {
      const inicio = Date.now();
      await menu.getByRole("link", { name: rota.menu, exact: true }).click();
      await esperarTela(page, rota);
      const retorno = Date.now() - inicio;
      if (rota.dados) await expect(page.getByText(rota.dados, { exact: true }).first()).toBeVisible();
      const conteudo = Date.now() - inicio;
      // A primeira rodada carrega código: fica fora, como o aquecimento.
      if (rodada === 0) continue;
      const linha = tempos.get(rota.nome) ?? { retorno: [], conteudo: [] };
      linha.retorno.push(retorno);
      linha.conteudo.push(conteudo);
      tempos.set(rota.nome, linha);
    }
  }

  const medido = [...tempos].map(([rota, t]) => ({
    rota,
    amostras: t.conteudo.length,
    primeiro_retorno_p50: percentil(t.retorno, 0.5),
    primeiro_retorno_p95: percentil(t.retorno, 0.95),
    conteudo_p50: percentil(t.conteudo, 0.5),
    conteudo_p95: percentil(t.conteudo, 0.95),
  }));
  const relatorio = { rodadas: RODADAS, navegacoes, prefetches, medido };
  writeFileSync(`${PASTA}/medicao.json`, JSON.stringify(relatorio, null, 2));
  console.log("MEDICAO_NAVEGACAO", JSON.stringify(relatorio));
});
