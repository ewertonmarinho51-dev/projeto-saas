import Link from "next/link";
import { CaretRight } from "@phosphor-icons/react/dist/ssr";

import type { Processo } from "@/lib/api";

const DATA = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });

export function ListaDeProcessos({ processos }: { processos: Processo[] }) {
  return (
    <ul className="divide-y divide-linha overflow-hidden rounded-[var(--radius-ui)] border border-linha bg-superficie">
      {processos.map((p) => (
        <li key={p.id}>
          <Link
            href={`/app/processos/${p.id}`}
            className="group grid grid-cols-[1fr_auto] items-center gap-4 px-5 py-4 transition-colors hover:bg-canvas"
          >
            <div className="min-w-0">
              <p className="truncate font-medium">{p.nome_exibido}</p>
              <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-secundario">
                <span className="text-texto">{p.status}</span>
                <span>
                  {p.progresso.feitos} de {p.progresso.total} documentos
                </span>
                <span>
                  Atualizado em {p.atualizado_em ? DATA.format(new Date(p.atualizado_em)) : "data indisponível"}
                </span>
              </p>
            </div>
            <CaretRight
              size={16}
              weight="bold"
              aria-hidden
              className="text-secundario transition-transform group-hover:translate-x-0.5"
            />
          </Link>
        </li>
      ))}
    </ul>
  );
}
