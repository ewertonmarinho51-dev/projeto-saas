// Copia o host nativo do WordCraft (assets/wordcraft_editor/host.mjs, do
// Codex) para o estático do web, com o hash no nome, e atualiza a URL que a
// tela importa. Rode depois de qualquer mudança no host:
//   node scripts/sincronizar-wordcraft-host.mjs
// `tests/wordcraft-host.test.ts` reprova se a cópia divergir do original.
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const ORIGEM = join(WEB, "..", "..", "assets", "wordcraft_editor", "host.mjs");
const PASTA = join(WEB, "public", "app", "wordcraft-host");

// Hash do texto canônico (LF): o checkout no Windows pode trazer CRLF.
const texto = readFileSync(ORIGEM, "utf8").replace(/\r\n/g, "\n");
const hash = createHash("sha256").update(texto).digest("hex");
const nome = `host.${hash.slice(0, 16)}.mjs`;

mkdirSync(PASTA, { recursive: true });
for (const antigo of readdirSync(PASTA)) rmSync(join(PASTA, antigo));
writeFileSync(join(PASTA, nome), texto);
writeFileSync(
  join(WEB, "lib", "wordcraft", "host.ts"),
  `// Gerado por scripts/sincronizar-wordcraft-host.mjs — não edite à mão.\n` +
    `export const HOST_URL = "/app/wordcraft-host/${nome}";\n` +
    `export const HOST_SHA256 = "${hash}";\n`,
);
console.log(`host WordCraft: ${nome}`);
