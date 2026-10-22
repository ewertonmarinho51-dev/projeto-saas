/**
 * Regras pequenas de segurança, puras e testadas (tests/seguranca.test.ts).
 */

/**
 * Destino de redirecionamento depois do login.
 *
 * `?proximo=` vem da URL, e URL qualquer um monta. Sem esta função,
 * `/entrar?proximo=https://site-falso` levaria o servidor recém-logado
 * para fora do Gov Conect — o redirecionamento aberto clássico, usado
 * para phishing com o domínio verdadeiro na frente.
 *
 * Só caminho interno de `/app`: começa com uma barra e não duas, sem
 * barra invertida (que alguns navegadores tratam como `//`), sem esquema.
 */
export function destinoSeguro(valor: unknown, padrao = "/app"): string {
  if (typeof valor !== "string" || valor.length > 512) return padrao;
  if (!valor.startsWith("/app")) return padrao;
  if (valor.startsWith("//") || valor.includes("\\")) return padrao;
  if (/[\u0000-\u001f]/.test(valor)) return padrao;
  try {
    const url = new URL(valor, "https://interno.invalid");
    if (url.origin !== "https://interno.invalid") return padrao;
    if (url.pathname !== "/app" && !url.pathname.startsWith("/app/")) return padrao;
    return url.pathname + url.search;
  } catch {
    return padrao;
  }
}

/**
 * Limite de tentativas de login, por chave (IP + e-mail), em memória.
 *
 * É a camada do NOSSO servidor; o Supabase Auth tem a dele. Vale enquanto
 * o web roda num processo só (ADR-007). Janela deslizante.
 */
export class LimiteDeTentativas {
  private eventos = new Map<string, number[]>();

  constructor(
    private readonly maximo: number,
    private readonly janelaMs: number,
    private readonly agora: () => number = () => Date.now(),
  ) {}

  /** true se a tentativa pode seguir; registra a tentativa. */
  consumir(chave: string): boolean {
    const t = this.agora();
    const lista = (this.eventos.get(chave) ?? []).filter((x) => x > t - this.janelaMs);
    if (lista.length >= this.maximo) {
      this.eventos.set(chave, lista);
      return false;
    }
    lista.push(t);
    this.eventos.set(chave, lista);
    if (this.eventos.size > 10_000) this.varrer(t);
    return true;
  }

  private varrer(t: number) {
    for (const [chave, lista] of this.eventos) {
      if (!lista.some((x) => x > t - this.janelaMs)) this.eventos.delete(chave);
    }
  }
}

/** E-mail plausível; a validade real é do Supabase Auth. */
export function emailValido(valor: string): boolean {
  return valor.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(valor);
}
