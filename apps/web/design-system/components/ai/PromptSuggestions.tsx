import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export interface PromptSuggestion {
  label: string;
  description?: string;
  icon?: IconName;
}

export interface PromptSuggestionsProps {
  items: PromptSuggestion[];
  onPick?: (item: PromptSuggestion) => void;
  /** Fichas (continuação) em vez de cartões (conversa vazia). */
  chips?: boolean;
}

/** Sugestões de pergunta ao GovBot. */
export function PromptSuggestions({ items, onPick, chips = false }: PromptSuggestionsProps) {
  return (
    <div className={cx("gc-suggestions", chips && "gc-suggestions--chips")}>
      {items.map((it, i) => (
        <button key={i} type="button" className="gc-suggestion" onClick={() => onPick?.(it)}>
          <Icon name={it.icon ?? "sparkle"} />
          <span>
            {it.label}
            {!chips && it.description && <small>{it.description}</small>}
          </span>
        </button>
      ))}
    </div>
  );
}
