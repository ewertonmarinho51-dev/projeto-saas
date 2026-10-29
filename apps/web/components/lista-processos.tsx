import Link from "next/link";

import { Icon, ProgressBar, StatusBadge } from "@/design-system";
import type { Processo } from "@/lib/api";

import { situacaoDoProcesso } from "./situacao";

const DATA = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });

/**
 * Linhas de processo (do `HomeScreen` do ui_kit): nome, órgão e data;
 * documentos aprovados sobre os exigidos; situação. Vai dentro de um
 * `<Card flush>`. Tudo vem da API — status, etapa e progresso são do
 * domínio, não daqui.
 */
export function ListaDeProcessos({ processos }: { processos: Processo[] }) {
  return (
    <ul className="divide-y divide-linha">
      {processos.map((p) => (
        <li key={p.id}>
          <Link
            href={`/app/processos/${p.id}`}
            className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-5 gap-y-3 px-5 py-3.5 text-texto no-underline transition-colors hover:bg-[var(--surface-hover)] hover:text-texto md:grid-cols-[minmax(0,1fr)_calc(var(--space-16)*2.75)_auto_var(--space-4)]"
          >
            <span className="grid min-w-0 gap-1">
              <span className="truncate font-[number:var(--weight-medium)]">{p.nome_exibido}</span>
              <span className="truncate text-[length:var(--gc-fs-sm)] text-secundario">
                {p.orgao} · Atualizado {p.atualizado_em ? DATA.format(new Date(p.atualizado_em)) : "em data indisponível"}
              </span>
            </span>
            <span className="col-span-2 row-start-2 md:col-span-1 md:row-start-auto">
              <ProgressBar
                size="sm"
                value={p.progresso.feitos}
                max={Math.max(p.progresso.total, 1)}
                showValue={false}
                hint={`${p.progresso.feitos} de ${p.progresso.total} documentos · ${p.etapa}`}
              />
            </span>
            <StatusBadge status={situacaoDoProcesso(p.status)} label={p.status} />
            <Icon
              name="caret-right"
              className="hidden text-[color:var(--text-tertiary)] transition-transform group-hover:translate-x-0.5 md:block"
            />
          </Link>
        </li>
      ))}
    </ul>
  );
}
