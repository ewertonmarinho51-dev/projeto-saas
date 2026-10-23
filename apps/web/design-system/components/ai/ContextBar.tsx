import { Icon, type IconName } from "../core/Icon";

export interface ContextItem {
  label: string;
  icon?: IconName;
  kind?: "process" | "document" | "knowledge" | "law";
  onRemove?: () => void;
}

export interface ContextBarProps {
  items: ContextItem[];
  onAdd?: () => void;
  label?: string;
}

/**
 * O que o GovBot pode usar para responder (processo vinculado, documentos,
 * base de conhecimento, lei). A resposta só usa o que está listado aqui.
 */
export function ContextBar({ items, onAdd, label = "Contexto" }: ContextBarProps) {
  return (
    <div className="gc-ctxbar" aria-label="Contexto do GovBot">
      <span className="gc-ctxbar__label">{label}</span>
      {items.map((it, i) => (
        <span key={i} className="gc-ctxchip" data-kind={it.kind}>
          <Icon name={it.icon ?? "file-text"} />
          <span className="gc-ctxchip__text">{it.label}</span>
          {it.onRemove && (
            <button type="button" className="gc-tag__remove" aria-label={`Remover ${it.label} do contexto`} onClick={it.onRemove}>
              <Icon name="x" size={11} />
            </button>
          )}
        </span>
      ))}
      {onAdd && (
        <button type="button" className="gc-btn gc-btn--ghost gc-btn--sm" onClick={onAdd}>
          <Icon name="plus" />
          Adicionar
        </button>
      )}
    </div>
  );
}
