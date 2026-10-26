import type { ReactNode } from "react";

/** Seção da vitrine, com âncora por tema (o mesmo id não pode repetir nos dois painéis). */
export function Secao({
  id,
  tema,
  titulo,
  descricao,
  children,
}: {
  id: string;
  tema: string;
  titulo: string;
  descricao?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={`${tema}-${id}`} aria-labelledby={`${tema}-${id}-t`} className="grid scroll-mt-20 gap-5">
      <div className="grid gap-1">
        <h2 id={`${tema}-${id}-t`}>{titulo}</h2>
        {descricao && <p className="max-w-[70ch] text-[length:var(--gc-fs-sm)] text-secundario">{descricao}</p>}
      </div>
      {children}
    </section>
  );
}

/** Um exemplo rotulado (o nome do componente ou da variante). */
export function Exemplo({ rotulo, children, largo = false }: { rotulo: string; children: ReactNode; largo?: boolean }) {
  return (
    <div className={largo ? "grid gap-2 md:col-span-2" : "grid min-w-0 content-start gap-2"}>
      <p className="font-[number:var(--weight-semibold)] text-[length:var(--gc-fs-2xs)] uppercase tracking-[var(--gc-tracking-caps)] text-[color:var(--text-tertiary)]">
        {rotulo}
      </p>
      {children}
    </div>
  );
}

/** Grade de exemplos. */
export function Grade({ children }: { children: ReactNode }) {
  return <div className="grid gap-6 md:grid-cols-2">{children}</div>;
}

/** Linha de itens que quebra. */
export function Linha({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-3">{children}</div>;
}

/** Caixa posicionada para diálogo, menu e casca "contidos". */
export function Palco({ children, alto = false }: { children: ReactNode; alto?: boolean }) {
  return (
    <div
      className={`relative overflow-hidden rounded-[var(--gc-radius-lg)] border border-linha bg-[var(--surface-sunken)] ${
        alto ? "h-[calc(var(--space-16)*10)]" : "min-h-[calc(var(--space-16)*5)]"
      }`}
    >
      {children}
    </div>
  );
}
