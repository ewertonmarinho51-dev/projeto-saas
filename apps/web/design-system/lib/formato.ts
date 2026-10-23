/** R$ 4.250,00 — formato pt-BR, como em todo o produto. */
export function formatarReais(n: number): string {
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/** 1.234 — milhar com ponto. */
export function formatarNumero(n: number): string {
  return n.toLocaleString("pt-BR");
}
