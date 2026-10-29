#!/usr/bin/env node
/**
 * Captura a REFERÊNCIA do Claude Design (design-system/referencia/ui_kits)
 * nos mesmos três tamanhos que `e2e/paridade.spec.ts` usa para o app,
 * para pôr referência × resultado lado a lado.
 *
 *     node scripts/capturar-referencia.mjs [pasta-de-saida]
 *
 * Serve a pasta da referência por HTTP local (os kits carregam `.jsx` por
 * XHR, que `file://` bloqueia) e abre no Chromium do Playwright, com
 * movimento reduzido para a captura sair no estado final. Precisa de rede:
 * React, Babel e os ícones dos kits vêm do unpkg, como no export.
 *
 * O kit do app é navegação SIMULADA com dados ilustrativos: a captura
 * mostra o desenho a seguir, não o comportamento — esse vem do app real.
 */
import { createReadStream, existsSync, mkdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const REFERENCIA = fileURLToPath(new URL("../design-system/referencia", import.meta.url));
const SAIDA = process.argv[2] ?? fileURLToPath(new URL("../e2e/resultados/referencia", import.meta.url));

const TELAS = [
  { nome: "1440", width: 1440, height: 900 },
  { nome: "768", width: 768, height: 1024 },
  { nome: "390", width: 390, height: 844 },
];

const TIPOS = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".jsx": "text/babel; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
};

const servidor = createServer((req, res) => {
  const caminho = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^([/\\])+/, "");
  const arquivo = join(REFERENCIA, caminho);
  if (!arquivo.startsWith(REFERENCIA) || !existsSync(arquivo) || statSync(arquivo).isDirectory()) {
    res.writeHead(404).end();
    return;
  }
  res.writeHead(200, { "Content-Type": TIPOS[extname(arquivo)] ?? "application/octet-stream" });
  createReadStream(arquivo).pipe(res);
});
await new Promise((ok) => servidor.listen(0, "127.0.0.1", ok));
const base = `http://127.0.0.1:${servidor.address().port}`;

/** [nome, caminho, rota do kit (localStorage) ou null para a tela de login] */
const TELAS_DO_KIT = [
  ["landing", "ui_kits/landing/index.html", undefined],
  ["entrar", "ui_kits/app/index.html", null],
  ["app-inicio", "ui_kits/app/index.html", "inicio"],
  ["app-processos", "ui_kits/app/index.html", "processos"],
  ["app-novo", "ui_kits/app/index.html", "novo"],
  ["app-cotacao", "ui_kits/app/index.html", "cotacao"],
  ["app-govbot", "ui_kits/app/index.html", "govbot"],
];

mkdirSync(SAIDA, { recursive: true });
const navegador = await chromium.launch();
try {
  for (const [nome, caminho, rota] of TELAS_DO_KIT) {
    const contexto = await navegador.newContext({ reducedMotion: "reduce" });
    if (rota !== undefined) {
      await contexto.addInitScript((r) => {
        if (r) {
          localStorage.setItem("gc-kit-auth", "1");
          localStorage.setItem("gc-kit-route", r);
        } else {
          localStorage.removeItem("gc-kit-auth");
        }
      }, rota);
    }
    const page = await contexto.newPage();
    for (const t of TELAS) {
      await page.setViewportSize({ width: t.width, height: t.height });
      await page.goto(`${base}/${caminho}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(400);
      await page.screenshot({ path: join(SAIDA, `${nome}-${t.nome}.png`) });
      await page.screenshot({ path: join(SAIDA, `${nome}-${t.nome}-inteira.png`), fullPage: true });
    }
    await contexto.close();
    console.log(`referência: ${nome}`);
  }
} finally {
  await navegador.close();
  servidor.close();
}
