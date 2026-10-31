"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { NavigationProgress } from "@/design-system";

/** Navegação que não terminou neste tempo deixa de ser anunciada: a barra não fica presa. */
const DESISTIR_MS = 20_000;

/** O clique leva a outra página deste site, na mesma aba? */
function levaAOutraPagina(evento: MouseEvent): boolean {
  if (evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return false;
  const link = (evento.target as Element | null)?.closest?.("a[href]");
  if (!(link instanceof HTMLAnchorElement) || link.hasAttribute("download")) return false;
  if (link.target && link.target !== "_self") return false;
  const destino = new URL(link.href, location.href);
  return destino.origin === location.origin && (destino.pathname !== location.pathname || destino.search !== location.search);
}

/**
 * Mostra a barra do clique até a rota mudar. Guarda em que endereço a
 * navegação começou: a URL mudou, ela some sozinha, sem efeito para limpar.
 */
export function ProgressoDeNavegacao() {
  const caminho = usePathname();
  const busca = useSearchParams();
  const aqui = `${caminho}?${busca}`;
  const [saindoDe, setSaindoDe] = useState<string | null>(null);

  useEffect(() => {
    const aoClicar = (evento: MouseEvent) => {
      if (levaAOutraPagina(evento)) setSaindoDe(`${location.pathname}?${location.search.slice(1)}`);
    };
    document.addEventListener("click", aoClicar);
    return () => document.removeEventListener("click", aoClicar);
  }, []);

  const carregando = saindoDe === aqui;
  useEffect(() => {
    if (!carregando) return;
    const prazo = setTimeout(() => setSaindoDe(null), DESISTIR_MS);
    return () => clearTimeout(prazo);
  }, [carregando]);

  return carregando ? <NavigationProgress /> : null;
}
