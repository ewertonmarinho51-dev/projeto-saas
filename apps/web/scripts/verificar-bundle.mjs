#!/usr/bin/env node
/**
 * Depois do `next build`: nada de segredo no que vai ao navegador.
 *
 * Varre `.next/static` (o que o navegador baixa) atrás de formatos de
 * chave de servidor e de nomes de variável que só o servidor conhece.
 * Achou, reprova o build. `NEXT_PUBLIC_*` é público por desenho e não
 * conta; o que conta é segredo vazando por import errado num componente
 * de cliente.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const RAIZ = new URL("../.next/static", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

const PROIBIDOS = [
  [/sb_secret_[A-Za-z0-9_-]{8,}/, "chave secreta do Supabase"],
  [/SUPABASE_SECRET_KEY|SUPABASE_SERVICE_KEY|SUPABASE_JWT_SECRET/, "nome de variável de servidor"],
  [/GOVCONECT_API_URL/, "URL interna da API"],
  [/"role"\s*:\s*"service_role"/, "JWT de service_role"],
];

function* arquivos(dir) {
  for (const nome of readdirSync(dir)) {
    const caminho = join(dir, nome);
    if (statSync(caminho).isDirectory()) yield* arquivos(caminho);
    else if (/\.(js|css|json|html|txt|map)$/.test(nome)) yield caminho;
  }
}

let achados = 0;
let total = 0;
for (const arquivo of arquivos(RAIZ)) {
  total += 1;
  const texto = readFileSync(arquivo, "utf8");
  for (const [padrao, descricao] of PROIBIDOS) {
    if (padrao.test(texto)) {
      console.error(`SEGREDO NO BUNDLE: ${descricao} em ${arquivo}`);
      achados += 1;
    }
  }
}
if (total === 0) {
  console.error("Nenhum arquivo em .next/static: rode `next build` antes.");
  process.exit(2);
}
console.log(`${total} arquivos do navegador varridos, ${achados} achado(s).`);
process.exit(achados ? 1 : 0);
