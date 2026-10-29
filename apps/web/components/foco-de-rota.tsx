"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Navegação no cliente não recarrega a página: o ponto de partida do Tab
 * ficaria onde estava o controle acionado (o botão "Entrar", um item do
 * menu) e o próximo Tab cairia no meio da tela nova. Na troca de rota, o
 * foco volta ao topo do documento, como num carregamento completo — e o
 * primeiro Tab é "Pular para o conteúdo". A leitura do título da página
 * nova fica com o anunciador de rota do Next.
 */
export function FocoDeRota() {
  const caminho = usePathname();
  const anterior = useRef(caminho);
  const topo = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (anterior.current === caminho) return;
    anterior.current = caminho;
    topo.current?.focus({ preventScroll: true });
  }, [caminho]);
  return <div ref={topo} tabIndex={-1} className="outline-none" />;
}
