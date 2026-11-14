"use client";

import { useRouter } from "next/navigation";

import { Button, Pagination, UfTileMap } from "@/design-system";
import type { AgregadosDeReferencias } from "@/lib/api";

import { type FiltrosDaTriagem, paraUrl } from "./triagem-url";

/**
 * Página da triagem pela URL (RF-06): trocar de página não toca a cesta —
 * a fila da cesta guarda as marcações por ID, em qualquer página.
 */
export function PaginacaoDaTriagem({ base, filtros, total }: { base: string; filtros: FiltrosDaTriagem; total: number }) {
  const router = useRouter();
  if (total <= filtros.por_pagina && filtros.pagina === 1) return null;
  return (
    <div data-testid="paginacao-triagem">
      <Pagination
        page={filtros.pagina}
        pageSize={filtros.por_pagina}
        total={total}
        onChange={(pagina) => router.push(paraUrl(base, filtros, { pagina }), { scroll: false })}
      />
    </div>
  );
}

/** Lista ou Mapa — o modo não mexe no filtro nem na cesta. */
export function ModoDaTriagem({ base, filtros }: { base: string; filtros: FiltrosDaTriagem }) {
  return (
    <div className="flex gap-2" role="group" aria-label="Modo de exibição">
      <Button
        size="sm"
        variant={filtros.modo === "lista" ? "primary" : "secondary"}
        icon="list"
        href={paraUrl(base, filtros, { modo: "lista" })}
        aria-pressed={filtros.modo === "lista"}
      >
        Lista
      </Button>
      <Button
        size="sm"
        variant={filtros.modo === "mapa" ? "primary" : "secondary"}
        icon="buildings"
        href={paraUrl(base, filtros, { modo: "mapa" })}
        aria-pressed={filtros.modo === "mapa"}
      >
        Mapa
      </Button>
    </div>
  );
}

/**
 * Mapa por UF (RF-08): a UF é a do órgão comprador; o número, quantas
 * referências. Escolher uma UF filtra a lista por ela (clique explícito).
 */
export function MapaDasReferencias({
  base,
  filtros,
  agregados,
}: {
  base: string;
  filtros: FiltrosDaTriagem;
  agregados: AgregadosDeReferencias;
}) {
  const router = useRouter();
  return (
    <div data-testid="mapa-referencias">
      <UfTileMap
        basis="UF do órgão comprador"
        metric="referências"
        values={agregados.ufs}
        unknown={agregados.sem_uf}
        selected={filtros.uf ?? null}
        onSelect={(uf) => router.push(paraUrl(base, filtros, { uf, modo: "lista" }))}
      />
    </div>
  );
}
