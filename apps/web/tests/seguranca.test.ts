import { describe, expect, it } from "vitest";

import { destinoSeguro, emailValido, LimiteDeTentativas } from "../lib/seguranca";

describe("destinoSeguro (redirecionamento aberto)", () => {
  it.each([
    ["/app", "/app"],
    ["/app/processos", "/app/processos"],
    ["/app/processos?cursor=abc", "/app/processos?cursor=abc"],
  ])("aceita caminho interno %s", (entrada, saida) => {
    expect(destinoSeguro(entrada)).toBe(saida);
  });

  it.each([
    "https://site-falso.example/app",
    "//site-falso.example/app",
    "/\\site-falso.example",
    "/app\\..\\..\\x",
    "javascript:alert(1)",
    "/entrar",
    "/applicativo-falso",
    "/app/../entrar",
    "/app\u0000",
    "",
    "x".repeat(600),
    null,
    42,
  ])("recusa %s e volta ao padrão", (entrada) => {
    expect(destinoSeguro(entrada)).toBe("/app");
  });
});

describe("LimiteDeTentativas", () => {
  it("barra depois do máximo e libera quando a janela passa", () => {
    let agora = 0;
    const limite = new LimiteDeTentativas(2, 1000, () => agora);
    expect(limite.consumir("ip|a@prefeitura.test")).toBe(true);
    expect(limite.consumir("ip|a@prefeitura.test")).toBe(true);
    expect(limite.consumir("ip|a@prefeitura.test")).toBe(false);
    expect(limite.consumir("ip|outro@prefeitura.test")).toBe(true);
    agora = 1001;
    expect(limite.consumir("ip|a@prefeitura.test")).toBe(true);
  });
});

describe("emailValido", () => {
  it("aceita forma comum e recusa lixo", () => {
    expect(emailValido("servidora@prefeitura.test")).toBe(true);
    expect(emailValido("sem-arroba")).toBe(false);
    expect(emailValido("a b@c.d")).toBe(false);
  });
});
