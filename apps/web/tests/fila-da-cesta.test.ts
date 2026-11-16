import { describe, expect, it } from "vitest";

import { AVISO_OUTRA_ABA, FilaDaCesta, type Gravacao, type Marcas } from "../components/fila-da-cesta";

/**
 * P0 de 14/11/2026 — "a referência entra na cesta e some". Servidor falso com
 * a MESMA regra da API (`apps/api/govconect_api/cesta.py`): If-Match com a
 * revisão do item; revisão diferente → 409 sem gravar; gravou → revisão + 1.
 * As gravações só terminam quando a prova manda (`soltar`), para encenar a
 * ordem exata em que o navegador recebe as respostas.
 */
class ServidorFalso {
  revisao = 1;
  cesta: Marcas;
  chamadas: { ref: string; incluir: boolean; ifMatch: number; status: number }[] = [];
  private presas: (() => void)[] = [];

  constructor(marcadas: Marcas) {
    this.cesta = { ...marcadas };
  }

  /** O que um GET da página devolveria agora. */
  pagina(): { revisao: number; marcadas: Marcas } {
    return { revisao: this.revisao, marcadas: { ...this.cesta } };
  }

  gravar = (ref: string, incluir: boolean, ifMatch: number): Promise<Gravacao> =>
    new Promise((resolver) => {
      this.presas.push(() => {
        if (ifMatch !== this.revisao) {
          this.chamadas.push({ ref, incluir, ifMatch, status: 409 });
          resolver({ ok: false, erro: "O item mudou desde a sua leitura.", conflito: true });
          return;
        }
        this.cesta[ref] = incluir;
        this.revisao += 1;
        this.chamadas.push({ ref, incluir, ifMatch, status: 200 });
        resolver({ ok: true, revisao: this.revisao, preco: `R$ ${this.revisao}` });
      });
    });

  /** Termina a gravação mais antiga em voo. */
  async soltar(): Promise<void> {
    const proxima = this.presas.shift();
    if (!proxima) throw new Error("nenhuma gravação em voo");
    proxima();
    await new Promise((r) => setTimeout(r, 0));
  }

  /** Outra aba grava direto. */
  outraAba(ref: string, incluir: boolean): void {
    this.cesta[ref] = incluir;
    this.revisao += 1;
  }
}

const tick = () => new Promise((r) => setTimeout(r, 0));
const INICIAL: Marcas = { a: false, b: false, c: false, d: false };

describe("fila da cesta (P0: referência que entra e some)", () => {
  it("mantém um único clique confirmado quando chega uma leitura anterior à gravação", async () => {
    const srv = new ServidorFalso(INICIAL);
    const antes = srv.pagina();
    const fila = new FilaDaCesta(antes.revisao, antes.marcadas, srv.gravar);
    fila.alternar("a", false);
    expect(fila.estado()).toMatchObject({ desejado: { a: true }, confirmado: { a: false }, emVoo: "a" });
    await srv.soltar();

    expect(srv.chamadas).toEqual([{ ref: "a", incluir: true, ifMatch: 1, status: 200 }]);
    expect(fila.receberDoServidor(antes.revisao, antes.marcadas)).toBe("ignorado_velho");
    const atual = srv.pagina();
    expect(fila.receberDoServidor(atual.revisao, atual.marcadas)).toBe("confirmado");
    expect(fila.estado()).toMatchObject({ confirmado: { a: true }, revisao: 2, aviso: null });
    expect(fila.marcado("a", false)).toBe(true);
  });

  it("o modelo ANTIGO perde a seleção: provedor recriado com a página do 1º refresh", async () => {
    // reprodução do defeito: `key={item.revisao}` recriava o provedor com a
    // página que o refresh trouxe, enquanto o clique seguinte ainda gravava
    const srv = new ServidorFalso(INICIAL);
    const antiga = new FilaDaCesta(1, INICIAL, srv.gravar);
    antiga.alternar("a", false);
    await tick();
    await srv.soltar(); // A gravado → rev 2; o refresh do 1º clique parte AGORA
    const paginaDoRefresh = srv.pagina(); // lida antes de B gravar
    antiga.alternar("b", false);
    await tick();
    // a página chega com a revisão 2: o provedor nasce de novo com ela
    const recriada = new FilaDaCesta(paginaDoRefresh.revisao, paginaDoRefresh.marcadas, srv.gravar);
    expect(recriada.marcado("b", false)).toBe(false); // B "sumiu" da tela
    await srv.soltar(); // a fila antiga, desmontada, grava B → rev 3
    recriada.alternar("c", false);
    await tick();
    await srv.soltar(); // C vai com If-Match 2: 409
    expect(srv.chamadas.at(-1)).toMatchObject({ ref: "c", status: 409 });
    expect(recriada.marcado("c", false)).toBe(false); // C entrou e saiu
    expect(recriada.estado().aviso).toBeTruthy();
  });

  it("a fila NOVA reconcilia: página velha é ignorada e nenhum clique se perde", async () => {
    const srv = new ServidorFalso(INICIAL);
    const fila = new FilaDaCesta(1, INICIAL, srv.gravar);
    fila.alternar("a", false);
    await tick();
    await srv.soltar(); // rev 2
    const paginaDoRefresh = srv.pagina();
    fila.alternar("b", false);
    await tick();
    // a página do 1º refresh chega com a revisão 2 enquanto B ainda grava
    expect(fila.receberDoServidor(paginaDoRefresh.revisao, paginaDoRefresh.marcadas)).toBe("confirmado");
    expect(fila.marcado("b", false)).toBe(true); // B continua na tela
    await srv.soltar(); // B → rev 3
    expect(fila.estado().revisao).toBe(3);
    // uma página ainda mais velha (refresh atrasado) não desfaz nada
    expect(fila.receberDoServidor(2, paginaDoRefresh.marcadas)).toBe("ignorado_velho");
    fila.alternar("c", false);
    await tick();
    await srv.soltar(); // C com If-Match 3: 200
    expect(srv.chamadas.map((c) => c.status)).toEqual([200, 200, 200]);
    expect(srv.chamadas.map((c) => c.ifMatch)).toEqual([1, 2, 3]);
    for (const id of ["a", "b", "c"]) expect(fila.marcado(id, false)).toBe(true);
    expect(fila.estado().aviso).toBeNull();
    // a recarga mostra o mesmo que a tela
    expect(srv.pagina().marcadas).toMatchObject({ a: true, b: true, c: true, d: false });
    // e concluir usa a revisão realmente confirmada
    await expect(fila.aguardar()).resolves.toEqual({ revisao: 4, falhou: false });
  });

  it("cliques repetidos na mesma linha valem pelo último, sem gravação a mais", async () => {
    const srv = new ServidorFalso(INICIAL);
    const fila = new FilaDaCesta(1, INICIAL, srv.gravar);
    fila.alternar("a", false); // inclui
    await tick();
    fila.alternar("a", false); // tira (enquanto a 1ª grava)
    fila.alternar("a", false); // inclui de novo
    await srv.soltar();
    await tick();
    expect(srv.chamadas).toHaveLength(1); // o último desejo já é o confirmado
    expect(fila.marcado("a", false)).toBe(true);
    expect(srv.cesta.a).toBe(true);
  });

  it("outra aba gravou: a página nova é adotada e o clique pendente de OUTRA linha segue", async () => {
    const srv = new ServidorFalso(INICIAL);
    const fila = new FilaDaCesta(1, INICIAL, srv.gravar);
    fila.alternar("a", false);
    await tick();
    fila.alternar("b", false); // pendente atrás de A
    srv.outraAba("d", true); // rev 2, outra pessoa pôs D
    await srv.soltar(); // A com If-Match 1 → 409 (a outra aba chegou antes)
    expect(srv.chamadas.at(-1)).toMatchObject({ ref: "a", status: 409 });
    expect(fila.marcado("a", false)).toBe(false); // não finge sucesso
    expect(fila.estado().aviso).toBeTruthy();
    // o refresh traz a verdade: D na cesta, revisão 2
    expect(fila.receberDoServidor(srv.pagina().revisao, srv.pagina().marcadas)).toBe("adotado");
    expect(fila.marcado("d", false)).toBe(true);
    fila.alternar("a", false); // refaz sobre a revisão nova
    await tick();
    await srv.soltar();
    expect(srv.chamadas.at(-1)).toMatchObject({ ref: "a", ifMatch: 2, status: 200 });
  });

  it("outra aba mexeu NA MESMA referência: o clique pendente é descartado com aviso", async () => {
    const srv = new ServidorFalso(INICIAL);
    const fila = new FilaDaCesta(1, INICIAL, srv.gravar);
    fila.alternar("a", false);
    await tick();
    fila.alternar("b", false); // B pendente: incluir
    srv.outraAba("b", true); // a outra aba pôs B (rev 2)
    // a página nova chega antes de A terminar
    const r = fila.receberDoServidor(srv.pagina().revisao, srv.pagina().marcadas);
    expect(r).toBe("adotado");
    // vale o que está gravado pela outra aba, e quem clicou é avisado
    expect(fila.marcado("b", false)).toBe(true);
    expect(fila.estado().confirmado.b).toBe(true);
    expect(fila.estado().aviso).toBe(AVISO_OUTRA_ABA);
    await srv.soltar(); // A (If-Match 1) → 409
    expect(srv.chamadas.filter((c) => c.ref === "b")).toHaveLength(0); // não sobrescreveu B
  });

  it("gravação recusada (422) volta só a linha dela; rede caída não finge sucesso", async () => {
    let n = 0;
    const fila = new FilaDaCesta(1, INICIAL, async (ref) => {
      n += 1;
      if (ref === "b") return { ok: false, erro: "A regra da cesta recusou esta referência.", conflito: false };
      return { ok: true, revisao: 1 + n, preco: null };
    });
    fila.alternar("a", false);
    fila.alternar("b", false);
    fila.alternar("c", false);
    const fim = await fila.aguardar();
    expect(fim.falhou).toBe(true);
    expect(fila.marcado("a", false)).toBe(true);
    expect(fila.marcado("b", false)).toBe(false);
    expect(fila.marcado("c", false)).toBe(true);
    expect(fila.estado().aviso).toMatch(/recusou/);
  });

  it("depois de gravar, pede a página nova uma vez por esvaziamento da fila", async () => {
    const srv = new ServidorFalso(INICIAL);
    let refreshes = 0;
    const fila = new FilaDaCesta(1, INICIAL, srv.gravar, () => (refreshes += 1));
    fila.alternar("a", false);
    fila.alternar("b", false);
    await tick();
    await srv.soltar();
    await srv.soltar();
    expect(refreshes).toBe(1);
  });
});
