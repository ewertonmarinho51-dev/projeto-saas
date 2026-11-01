"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useLayoutEffect, useState } from "react";

import { NavigationProgress } from "@/design-system";

/** Navegação que não terminou neste tempo deixa de ser anunciada: a barra não fica presa. */
const DESISTIR_MS = 20_000;
/** Até aqui a tela antiga fica: em navegação rápida, o esqueleto só piscaria. */
const ESQUELETO_MS = 120;

type Saida = { de: string; outraTela: boolean };

/** O clique leva a outra página deste site, na mesma aba? */
function saidaDoClique(evento: MouseEvent): Saida | null {
  if (evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return null;
  const link = (evento.target as Element | null)?.closest?.("a[href]");
  if (!(link instanceof HTMLAnchorElement) || link.hasAttribute("download")) return null;
  if (link.target && link.target !== "_self") return null;
  const destino = new URL(link.href, location.href);
  const outraTela = destino.pathname !== location.pathname;
  if (destino.origin !== location.origin || (!outraTela && destino.search === location.search)) return null;
  return { de: `${location.pathname}?${location.search.slice(1)}`, outraTela };
}

/**
 * Mostra a barra do clique até a rota mudar, e o esqueleto da casca quando a
 * troca é de tela (filtro e paginação mantêm a tela à vista). Guarda em que
 * endereço a navegação começou: a URL mudou, ela some sozinha, sem efeito para
 * limpar.
 */
export function ProgressoDeNavegacao() {
  const caminho = usePathname();
  const busca = useSearchParams();
  const aqui = `${caminho}?${busca}`;
  const [saida, setSaida] = useState<Saida | null>(null);

  useEffect(() => {
    const aoClicar = (evento: MouseEvent) => {
      const nova = saidaDoClique(evento);
      if (nova) setSaida(nova);
    };
    document.addEventListener("click", aoClicar);
    return () => document.removeEventListener("click", aoClicar);
  }, []);

  const carregando = saida?.de === aqui;
  useEffect(() => {
    if (!carregando) return;
    const prazo = setTimeout(() => setSaida(null), DESISTIR_MS);
    return () => clearTimeout(prazo);
  }, [carregando]);

  const trocandoDeTela = carregando && saida?.outraTela === true;
  // Layout, não efeito comum: a limpeza roda antes de o Next medir a tela nova
  // para voltar a rolagem ao topo, e com a tela escondida ele desistiria.
  useLayoutEffect(() => {
    if (!trocandoDeTela) return;
    const raiz = document.documentElement;
    const atraso = setTimeout(() => raiz.setAttribute("data-navegando", ""), ESQUELETO_MS);
    return () => {
      clearTimeout(atraso);
      raiz.removeAttribute("data-navegando");
    };
  }, [trocandoDeTela]);

  return carregando ? <NavigationProgress /> : null;
}
