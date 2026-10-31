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
