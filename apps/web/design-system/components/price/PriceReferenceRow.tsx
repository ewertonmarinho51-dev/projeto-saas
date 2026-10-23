import type { ReactNode } from "react";

import { Icon, type IconName } from "../core/Icon";
import { Badge, type BadgeVariant } from "../feedback/Badge";

export type ReferenceStatus = "compatible" | "discrepant" | "attention" | "excluded" | "pending";

const SITUACAO: Record<ReferenceStatus, { variante: BadgeVariant; icone: IconName; rotulo: string }> = {
  compatible: { variante: "success", icone: "check", rotulo: "Compatível" },
  discrepant: { variante: "error", icone: "warning", rotulo: "Revisar discrepância" },
  attention: { variante: "warning", icone: "warning-circle", rotulo: "Exige conferência" },
  excluded: { variante: "neutral", icone: "minus-circle", rotulo: "Fora do cálculo" },
  pending: { variante: "neutral", icone: "hourglass-medium", rotulo: "Não analisada" },
};

export interface PriceReferenceRowProps {
  title: ReactNode;
  source?: string;
  agency?: ReactNode;
  date?: ReactNode;
  value: ReactNode;
  unitNote?: ReactNode;
  status?: ReferenceStatus;
  statusLabel?: string;
  selected?: boolean;
  onToggle?: () => void;
  actions?: ReactNode;
}

/**
 * Uma referência coletada, na triagem: caixa de inclusão, descrição,
 * fonte, órgão, data, valor e situação com ícone. Discrepante é sinal
 * estatístico para revisão humana, nunca exclusão automática.
 */
export function PriceReferenceRow({
  title,
  source,
  agency,
  date,
  value,
  unitNote,
  status = "compatible",
  statusLabel,
  selected,
  onToggle,
  actions,
}: PriceReferenceRowProps) {
  const s = SITUACAO[status];
  return (
    <div className="gc-pref" data-status={status}>
      {onToggle ? (
        <span className="gc-check">
          <input
            type="checkbox"
            checked={!!selected}
            onChange={onToggle}
            aria-label={`Incluir ${typeof title === "string" ? title : "referência"} na cesta`}
          />
        </span>
      ) : (
        <span />
      )}
      <div className="gc-pref__main">
        <span className="gc-pref__title">{title}</span>
        <span className="gc-pref__meta">
          {source && (
            <Badge variant="brand" size="sm">
              {source}
            </Badge>
          )}
          {agency && (
            <span>
              <Icon name="buildings" /> {agency}
            </span>
          )}
          {date && (
            <span>
              <Icon name="calendar-blank" /> {date}
            </span>
          )}
        </span>
      </div>
      <div className="gc-pref__value">
        {value}
        {unitNote && <small>{unitNote}</small>}
      </div>
      <div className="gc-pref__status">
        <Badge variant={s.variante} icon={s.icone}>
          {statusLabel ?? s.rotulo}
        </Badge>
        {actions}
      </div>
    </div>
  );
}
