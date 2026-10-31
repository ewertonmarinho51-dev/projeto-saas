#!/usr/bin/env node
/**
 * Junta referência × tela real, lado a lado, nos três tamanhos.
 *
 *     node scripts/montar-comparativo.mjs <pasta-referencia> <pasta-real> <saida>
 *
 * `pasta-referencia` sai de `capturar-referencia.mjs`; `pasta-real` é a pasta
 * `paridade/` do artefato `web-e2e-telas` do CI, com dados sintéticos da pilha
 * descartável. Nada aqui vem de produção.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "@playwright/test";

const [referencia, real, saida] = process.argv.slice(2);
if (!referencia || !real || !saida) {
  console.error("uso: montar-comparativo.mjs <pasta-referencia> <pasta-real> <saida>");
  process.exit(2);
}

/** [nome do comparativo, captura da referência, captura real] */
const PARES = [
  ["hero", "landing", "landing"],
  ["login", "entrar", "entrar"],
  ["inicio", "app-inicio", "app-inicio"],
  ["processos", "app-processos", "app-processos"],
  ["processo", "app-novo", "app-processo"],
  ["precos-item", "app-cotacao", "app-item"],
  ["govbot", "app-govbot", "app-govbot"],
];
const TAMANHOS = [
  { nome: "1440", largura: 1000, altura: 625 },
  { nome: "768", largura: 640, altura: 853 },
  { nome: "390", largura: 390, altura: 844 },
];

const imagem = (caminho) => `data:image/png;base64,${readFileSync(caminho).toString("base64")}`;

function pagina(titulo, esquerda, direita, largura, altura) {
  const coluna = (rotulo, src) => `
    <figure><figcaption>${rotulo}</figcaption>
      <img src="${src}" width="${largura}" height="${altura}" alt=""></figure>`;
  return `<!doctype html><meta charset="utf-8"><style>
    body{margin:0;padding:16px;background:#F6F8FC;color:#17243A;font:14px system-ui,sans-serif}
    h1{margin:0 0 12px;font-size:16px}
    main{display:flex;gap:16px;align-items:flex-start}
    figure{margin:0}
    figcaption{margin-bottom:6px;font-weight:600}
    img{display:block;border:1px solid #D7DEE8}
  </style><h1>${titulo}</h1><main>${coluna("Referência (Claude Design, dados ilustrativos)", esquerda)}${coluna("Gov Conect real (pilha de CI, dados sintéticos)", direita)}</main>`;
}

mkdirSync(saida, { recursive: true });
const navegador = await chromium.launch();
const faltando = [];
try {
  for (const [nome, ref, app] of PARES) {
    for (const t of TAMANHOS) {
      const a = join(referencia, `${ref}-${t.nome}.png`);
      const b = join(real, `${app}-${t.nome}.png`);
      if (!existsSync(a) || !existsSync(b)) {
        faltando.push(`${nome}-${t.nome}`);
        continue;
      }
      const page = await navegador.newPage({ viewport: { width: t.largura * 2 + 66, height: t.altura + 100 } });
      await page.setContent(pagina(`${nome} · ${t.nome} px`, imagem(a), imagem(b), t.largura, t.altura));
      await page.screenshot({ path: join(saida, `${nome}-${t.nome}.jpg`), type: "jpeg", quality: 68, fullPage: true });
      await page.close();
      console.log(`comparativo: ${nome}-${t.nome}`);
    }
  }
} finally {
  await navegador.close();
}
writeFileSync(join(saida, "faltando.txt"), faltando.join("\n"));
if (faltando.length) console.error(`sem captura: ${faltando.join(", ")}`);
