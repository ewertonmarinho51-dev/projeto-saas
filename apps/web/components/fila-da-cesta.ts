/**
 * A fila da cesta de UM item, sem React (P0 de 14/11/2026).
 *
 * O defeito: a página punha `key={item.revisao}` no provedor da cesta. Cada
 * gravação trocava a revisão, o `router.refresh()` trazia a página nova e o
 * provedor NASCIA DE NOVO com o que aquela página dizia. Clicando em várias
 * referências seguidas, o refresh do 1º clique chegava com a revisão
 * intermediária: a referência do 2º clique sumia da tela, o 3º clique ia com
 * uma revisão já vencida (409, e a referência voltava para fora) e o
 * "Concluir item" usava essa mesma revisão vencida. A fila antiga ainda
 * gravava no provedor desmontado — o servidor ficava certo e a tela, não.
 *
 * Aqui a fila vive o tempo do item e RECONCILIA o que o servidor manda pela
 * revisão, em vez de ser substituída por ele:
 *
 * * instantâneo com revisão MENOR que a confirmada é velho → ignorado;
 * * instantâneo com revisão MAIOR (outra aba, outra pessoa) → vira a
 *   verdade confirmada; o clique ainda não gravado de uma referência que
 *   NÃO mudou lá continua (é a intenção de quem clicou, agora sobre a
 *   revisão nova); o de uma referência que a outra aba MUDOU é descartado
 *   com aviso — conflito explícito, nunca sobrescrita calada;
 * * revisão igual → confirma o que já sabíamos.
 *
 * Cada gravação leva a revisão que a anterior devolveu (If-Match); só a
 * linha que falhou volta; o servidor continua decidindo tudo.
 */

export type Marcas = Record<string, boolean>;

export type Gravacao =
  | { ok: true; revisao: number; preco: string | null }
  | { ok: false; erro: string; conflito: boolean };

export type Gravar = (referencia: string, incluir: boolean, revisao: number) => Promise<Gravacao>;

export type Estado = {
  desejado: Marcas;
  confirmado: Marcas;
  emVoo: string | null;
  preco: string | null;
  aviso: string | null;
  revisao: number;
};

export const AVISO_OUTRA_ABA =
  "Esta referência foi alterada em outra aba ou por outra pessoa. A tela mostra o que está gravado.";

export class FilaDaCesta {
  private desejado: Marcas;
  private confirmado: Marcas;
  private revisaoConfirmada: number;
  private emVoo: string | null = null;
  private preco: string | null = null;
  private aviso: string | null = null;
  private rodando = false;
  private falhou = false;
  private esperando: ((r: { revisao: number; falhou: boolean }) => void)[] = [];
  private ouvintes = new Set<() => void>();
  private instantaneo: Estado;

  constructor(
    revisao: number,
    marcadas: Marcas,
    private readonly gravar: Gravar,
    /** Depois que a fila esvazia com alguma gravação (a página relê o servidor). */
    private readonly aposGravar: () => void = () => {},
  ) {
    this.revisaoConfirmada = revisao;
    this.desejado = { ...marcadas };
    this.confirmado = { ...marcadas };
    this.instantaneo = this.montar();
  }

  // -- leitura (para o React: `useSyncExternalStore`) ------------------------
  estado = (): Estado => this.instantaneo;

  assinar = (ouvinte: () => void): (() => void) => {
    this.ouvintes.add(ouvinte);
    return () => this.ouvintes.delete(ouvinte);
  };

  marcado(id: string, padrao: boolean): boolean {
    return this.instantaneo.desejado[id] ?? padrao;
  }

  salvando(id: string): boolean {
    const e = this.instantaneo;
    return e.emVoo === id || (id in e.desejado && e.desejado[id] !== e.confirmado[id]);
  }

  // -- escrita ----------------------------------------------------------------
  alternar(id: string, atual: boolean): void {
    if (!(id in this.confirmado)) this.confirmado[id] = atual;
    this.desejado[id] = !(this.desejado[id] ?? atual);
    this.aviso = null;
    this.publicar();
    void this.processar();
  }

  /** Resolve quando não há nada por gravar; `falhou` = alguma gravação recusada. */
  aguardar(): Promise<{ revisao: number; falhou: boolean }> {
    if (!this.rodando && this.pendentes().length === 0) {
      return Promise.resolve({ revisao: this.revisaoConfirmada, falhou: false });
    }
    const promessa = new Promise<{ revisao: number; falhou: boolean }>((r) => this.esperando.push(r));
    void this.processar();
    return promessa;
  }

  /**
   * O que a página do servidor trouxe. Devolve o que foi feito, para a prova
   * e para o diagnóstico (sem dado de pessoa: só a decisão).
   */
  receberDoServidor(revisao: number, marcadas: Marcas): "ignorado_velho" | "confirmado" | "adotado" {
    if (revisao < this.revisaoConfirmada) return "ignorado_velho";
    if (revisao === this.revisaoConfirmada) {
      // a mesma revisão: o servidor e nós concordamos sobre o confirmado
      for (const [id, v] of Object.entries(marcadas)) {
        if (!(id in this.confirmado)) {
          this.confirmado[id] = v;
          if (!(id in this.desejado)) this.desejado[id] = v;
        }
      }
      this.publicar();
      return "confirmado";
    }
    // revisão mais nova que a nossa: outra aba/pessoa gravou
    let descartou = false;
    for (const [id, v] of Object.entries(marcadas)) {
      const pendente = id in this.desejado && this.desejado[id] !== this.confirmado[id] && this.emVoo !== id;
      if (pendente && this.confirmado[id] !== undefined && this.confirmado[id] !== v) {
        // a outra aba mexeu NESTA referência: vale o que está gravado
        this.desejado[id] = v;
        descartou = true;
      } else if (!pendente && this.emVoo !== id) {
        this.desejado[id] = v;
      }
      if (this.emVoo !== id) this.confirmado[id] = v;
    }
    this.revisaoConfirmada = revisao;
    if (descartou) this.aviso = AVISO_OUTRA_ABA;
    this.publicar();
    return "adotado";
  }

  // -- interno ----------------------------------------------------------------
  private pendentes(): [string, boolean][] {
    return Object.entries(this.desejado).filter(([id, v]) => this.confirmado[id] !== v);
  }

  private montar(): Estado {
    return {
      desejado: { ...this.desejado },
      confirmado: { ...this.confirmado },
      emVoo: this.emVoo,
      preco: this.preco,
      aviso: this.aviso,
      revisao: this.revisaoConfirmada,
    };
  }

  private publicar(): void {
    this.instantaneo = this.montar();
    this.ouvintes.forEach((o) => o());
  }

  private async processar(): Promise<void> {
    if (this.rodando) return;
    this.rodando = true;
    this.falhou = false;
    let gravou = false;
    try {
      for (;;) {
        const proxima = this.pendentes()[0];
        if (!proxima) break;
        const [id, incluir] = proxima;
        this.emVoo = id;
        this.publicar();
        const r = await this.gravar(id, incluir, this.revisaoConfirmada);
        this.emVoo = null;
        if (r.ok) {
          this.confirmado[id] = incluir;
          this.revisaoConfirmada = Math.max(this.revisaoConfirmada, r.revisao);
          this.preco = r.preco;
          gravou = true;
        } else {
          // só esta linha volta; as outras marcações seguem na fila
          this.falhou = true;
          this.desejado[id] = this.confirmado[id] ?? false;
          this.aviso = r.erro;
          if (r.conflito) {
            // revisão vencida: descarta o que falta e espera a página nova
            this.desejado = { ...this.confirmado };
          }
        }
        this.publicar();
        if (!r.ok && r.conflito) break;
      }
    } finally {
      this.rodando = false;
      this.emVoo = null;
      this.publicar();
      const resultado = { revisao: this.revisaoConfirmada, falhou: this.falhou };
      this.esperando.splice(0).forEach((f) => f(resultado));
      if (gravou || this.falhou) this.aposGravar();
    }
  }
}
