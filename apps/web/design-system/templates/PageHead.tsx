import type { ReactNode } from "react";

export interface PageHeadProps {
  title: ReactNode;
  desc?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}

/** Cabeçalho de página: título (h1), descrição em até 70 caracteres por linha e ações à direita. */
export function PageHead({ title, desc, actions, eyebrow }: PageHeadProps) {
  return (
    <div className="gc-page-head">
      <div className="gc-page-head__titles">
        {eyebrow}
        <h1>{title}</h1>
        {desc && <p className="gc-page-head__desc">{desc}</p>}
      </div>
      {actions && <div className="gc-page-head__actions">{actions}</div>}
    </div>
  );
}
