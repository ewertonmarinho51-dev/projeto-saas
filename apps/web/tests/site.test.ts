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

  it("mantém os títulos editoriais e inclui a entrada no sitemap público", async () => {
    const { PAGINAS, metadados } = await import("../components/site");
    const esperados = new Map([
      ["/", "Gov Conect — IA para Licitações e Pesquisa de Preços"],
      ["/entrar", "Entrar — Gov Conect"],
      ["/solucoes", "Soluções — Gov Conect"],
      ["/solucoes/documentos-ia", "Documentos com Inteligência Artificial"],
      ["/solucoes/pesquisa-de-precos", "Pesquisa de Preços"],
      ["/como-funciona", "Como Funciona"],
      ["/sobre", "Sobre a Gov Conect"],
      ["/contato", "Contato"],
      ["/privacidade", "Privacidade"],
    ]);
    expect(new Map(PAGINAS.map((pagina) => [pagina.caminho, pagina.titulo]))).toEqual(esperados);
    expect(metadados("/entrar").openGraph).toMatchObject({
      url: "https://govconect.com/entrar",
      title: "Entrar — Gov Conect",
    });
  });
});
