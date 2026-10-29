import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * O endereço canônico do site em produção é https://govconect.com, e cada
 * página pública registrada tem caminho, título e descrição próprios. O E2E
 * (e2e/site.spec.ts) prova o que o navegador recebe; aqui, o padrão.
 */
describe("site público", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("sem GOVCONECT_SITE_URL, a canônica é https://govconect.com", async () => {
    vi.stubEnv("GOVCONECT_SITE_URL", undefined as unknown as string);
    const site = await import("../components/site");
    expect(site.SITE_URL).toBe("https://govconect.com");
    expect(site.metadados("/solucoes").alternates?.canonical).toBe("https://govconect.com/solucoes");
    expect(site.metadados("/").alternates?.canonical).toBe("https://govconect.com");
  });

  it("o ambiente troca a origem, sem barra no fim", async () => {
    vi.stubEnv("GOVCONECT_SITE_URL", "https://homologa.example/");
    const site = await import("../components/site");
    expect(site.SITE_URL).toBe("https://homologa.example");
  });

  it("caminhos, títulos e descrições são únicos, e página fora do registro é erro", async () => {
    const { PAGINAS, metadados } = await import("../components/site");
    for (const campo of ["caminho", "titulo", "descricao"] as const) {
      expect(new Set(PAGINAS.map((p) => p[campo])).size).toBe(PAGINAS.length);
    }
    expect(() => metadados("/inexistente")).toThrow();
  });
});
