import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon } from "../core/Icon";

export interface TagProps {
  label?: ReactNode;
  /** Ex.: "Fonte" em "Fonte: PNCP". */
  keyLabel?: ReactNode;
  onRemove?: () => void;
  active?: boolean;
  children?: ReactNode;
}

/** Filtro aplicado, removível ("Fonte: PNCP ×"), acima da tabela filtrada. */
export function Tag({ label, keyLabel, onRemove, active, children }: TagProps) {
  return (
    <span className={cx("gc-tag", !onRemove && "gc-tag--static", active && "gc-tag--active")}>
      {keyLabel && <span className="gc-tag__key">{keyLabel}:</span>}
      {label ?? children}
      {onRemove && (
        <button
          type="button"
          className="gc-tag__remove"
          aria-label={`Remover filtro ${typeof label === "string" ? label : ""}`.trim()}
          onClick={onRemove}
        >
          <Icon name="x" size={12} />
        </button>
      )}
    </span>
  );
}
