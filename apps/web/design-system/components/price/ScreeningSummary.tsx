import { Icon, type IconName } from "../core/Icon";

export type ScreeningKey = "total" | "valid" | "attention" | "discrepant" | "excluded";

const CELULAS: { key: ScreeningKey; label: string; icon: IconName; tone?: "success" | "warning" | "error" }[] = [
  { key: "total", label: "Coletadas", icon: "database" },
  { key: "valid", label: "Na cesta", icon: "check-circle", tone: "success" },
  { key: "attention", label: "Para conferência", icon: "warning-circle", tone: "warning" },
  { key: "discrepant", label: "Discrepantes", icon: "warning", tone: "error" },
  { key: "excluded", label: "Fora do cálculo", icon: "minus-circle" },
];

export interface ScreeningSummaryProps {
  counts: Partial<Record<ScreeningKey, number>>;
  /** Filtro ativo. */
  active?: ScreeningKey | null;
  onFilter?: (chave: ScreeningKey | null) => void;
}

/** Contadores da triagem, que também filtram a lista: coletadas, na cesta, conferência, discrepantes, fora. */
export function ScreeningSummary({ counts, active, onFilter }: ScreeningSummaryProps) {
  return (
    <div className="gc-screen" role="group" aria-label="Resumo da triagem">
      {CELULAS.map((d) => (
        <button
          key={d.key}
          type="button"
          className="gc-screen__cell"
          data-tone={d.tone}
          aria-pressed={active === d.key}
          onClick={() => onFilter?.(active === d.key ? null : d.key)}
        >
          <span className="gc-screen__label">
            <Icon name={d.icon} weight={d.tone ? "fill" : "bold"} />
            {d.label}
          </span>
          <span className="gc-screen__value">{counts[d.key] ?? 0}</span>
        </button>
      ))}
    </div>
  );
}
