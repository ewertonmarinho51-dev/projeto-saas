import { expect, test } from "@playwright/test";

/**
 * Layout que só o navegador mede. Em 31/10/2026 o nome de um parecer da Base,
 * sem espaço, alargou a conversa do GovBot em produção: o texto ficou atrás do
 * painel de fontes. A vitrine traz o mesmo caso, sem depender de IA nem de
 * dado semeado (`GOVCONECT_VITRINE=1` no job `web-e2e`).
 */
const TELAS = [
  { nome: "1440", width: 1440, height: 900 },
  { nome: "768", width: 768, height: 1024 },
  { nome: "390", width: 390, height: 844 },
];

for (const tela of TELAS) {
  test(`fonte de nome longo não alarga a conversa em ${tela.nome}`, async ({ page }) => {
    await page.setViewportSize({ width: tela.width, height: tela.height });
    await page.goto("/design-system");

    const conversa = page.locator('[data-prova="conversa-nome-longo"]').first();
    await conversa.scrollIntoViewIfNeeded();
    await expect(conversa.locator(".gc-source__title").first()).toBeVisible();

    const medida = await conversa.evaluate((caixa) => {
      const direita = (e: Element) => e.getBoundingClientRect().right;
      const conteudo = caixa.querySelectorAll(".gc-source__title, .gc-source__excerpt, .gc-msg__content, .gc-msg__bubble");
      return {
        limite: direita(caixa.parentElement!),
        maior: Math.max(...[...conteudo].map(direita)),
        janela: window.innerWidth,
      };
    });

    expect(medida.maior, "conteúdo além da conversa").toBeLessThanOrEqual(medida.limite);
    expect(medida.limite, "conversa além da janela").toBeLessThanOrEqual(medida.janela);
  });
}

/**
 * Pesquisa de Preços: com 383 itens, o destaque do item atual e os ícones de
 * situação avançavam sobre o formulário vizinho. A vitrine põe 383 itens, com
 * descrição sem espaço e número de três algarismos, no cartão de 256 px.
 */
const TELAS_DO_DONO = [
  { nome: "1920", width: 1920, height: 1080 },
  { nome: "1366", width: 1366, height: 768 },
  { nome: "390", width: 390, height: 844 },
];

for (const tela of TELAS_DO_DONO) {
  test(`navegador de itens: cada linha fica no cartão Itens em ${tela.nome}`, async ({ page }) => {
    await page.setViewportSize({ width: tela.width, height: tela.height });
    await page.goto("/design-system");

    const caixa = page.locator('[data-prova="itemnav-estreito"]').first();
    await caixa.scrollIntoViewIfNeeded();
    await expect(caixa.locator(".gc-itemnav__btn")).toHaveCount(383);

    const medida = await caixa.evaluate((el) => {
      const r = (e: Element) => e.getBoundingClientRect();
      const cartao = r(el.querySelector(".gc-card")!);
      const lista = el.querySelector("ul")!;
      const botoes = [...el.querySelectorAll(".gc-itemnav__btn")];
      const atual = el.querySelector('[aria-current="true"]')!;
      return {
        linhasFora: botoes.filter((b) => r(b).right > cartao.right + 0.5 || r(b).left < cartao.left - 0.5).length,
        iconesFora: botoes.filter((b) => r(b.querySelector(".gc-itemnav__status")!).right > r(b).right + 0.5).length,
        textoFora: [...el.querySelectorAll(".gc-itemnav__title, .gc-itemnav__meta")].filter((t) => t.scrollWidth > t.clientWidth + 1).length,
        rolaDentro: lista.scrollHeight > lista.clientHeight,
        atualVisivel: r(atual).top >= r(lista).top - 0.5 && r(atual).bottom <= r(lista).bottom + 0.5,
        documento: document.documentElement.scrollWidth,
        janela: window.innerWidth,
      };
    });
    expect(medida.linhasFora, "linha além do cartão").toBe(0);
    expect(medida.iconesFora, "ícone de situação além da linha").toBe(0);
    expect(medida.textoFora, "descrição estourando a própria caixa").toBe(0);
    expect(medida.rolaDentro, "a lista longa rola dentro do cartão").toBe(true);
    expect(medida.atualVisivel, "o item atual abre à vista").toBe(true);
    expect(medida.documento, "rolagem lateral").toBeLessThanOrEqual(medida.janela);
  });
}

/**
 * WordCraft: as ferramentas saíram da faixa do topo para o trilho lateral. Um
 * painel por vez; abrir e fechar não recria a área do documento — o texto em
 * edição e a posição de leitura continuam onde estavam.
 */
for (const tela of TELAS_DO_DONO.slice(0, 2)) {
  test(`espaço de trabalho: trilho alterna painéis sem recriar o documento em ${tela.nome}`, async ({ page }) => {
    await page.setViewportSize({ width: tela.width, height: tela.height });
    await page.goto("/design-system");

    const caixa = page.locator('[data-prova="workspace-trilho"]').first();
    await caixa.scrollIntoViewIfNeeded();
    const trilho = caixa.getByRole("navigation", { name: "Painéis do documento" });
    await expect(trilho.getByRole("button")).toHaveText(["Estrutura", "Evidências", "Histórico", "Revisão"]);

    // Edição de verdade: digitar no fim do documento, depois rolar a leitura.
    const area = caixa.getByRole("textbox", { name: "Área do documento" });
    await area.click();
    await page.keyboard.press("Control+End");
    await page.keyboard.type(" Trecho digitado durante a prova");
    await area.evaluate((t: HTMLTextAreaElement & { __prova?: string }) => {
      t.__prova = "mesmo-no";
      t.scrollTop = 400;
    });

    const estado = () =>
      area.evaluate((t: HTMLTextAreaElement & { __prova?: string }) => ({
        mesmo: t.__prova === "mesmo-no",
        texto: t.value.endsWith("Trecho digitado durante a prova"),
        rolagem: t.scrollTop,
        largura: Math.round(t.getBoundingClientRect().width),
      }));

    // A vitrine abre com Revisão: fechar devolve a largura ao documento.
    const comPainel = await estado();
    await trilho.getByRole("button", { name: "Revisão" }).click();
    await expect(caixa.locator(".gc-workspace__panel")).toHaveCount(0);
    const semPainel = await estado();
    expect(semPainel.largura, "documento ocupa o espaço sem painel").toBeGreaterThan(comPainel.largura);

    for (const nome of ["Estrutura", "Evidências", "Histórico", "Revisão"]) {
      await trilho.getByRole("button", { name: nome }).click();
      await expect(caixa.locator(".gc-workspace__panel")).toHaveCount(1);
      await expect(caixa.locator(".gc-workspace__panel-title")).toHaveText(nome);
      await expect(trilho.getByRole("button", { pressed: true })).toHaveText([nome]);
      const agora = await estado();
      expect(agora.mesmo, `${nome}: documento recriado`).toBe(true);
      expect(agora.texto, `${nome}: texto em edição perdido`).toBe(true);
      expect(agora.rolagem, `${nome}: posição de leitura perdida`).toBe(400);
    }
    await caixa.getByRole("button", { name: "Fechar painel" }).click();
    await expect(caixa.locator(".gc-workspace__panel")).toHaveCount(0);
    expect(await estado()).toMatchObject({ mesmo: true, texto: true, rolagem: 400 });
  });
}
