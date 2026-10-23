export interface PriceSource {
  id: string;
  name: string;
  description?: string;
  disabled?: boolean;
}

export interface SourcePickerProps {
  sources: PriceSource[];
  value: string[];
  onChange?: (ids: string[]) => void;
}

/** Quais fontes oficiais a busca consulta (PNCP, Compras.gov.br, Painel de Preços, pesquisa direta…). */
export function SourcePicker({ sources, value, onChange }: SourcePickerProps) {
  const alternar = (id: string) => onChange?.(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);
  return (
    <fieldset className="gc-srcpick">
      {sources.map((s) => (
        <label key={s.id} className="gc-srcopt">
          <span className="gc-check">
            <input type="checkbox" checked={value.includes(s.id)} disabled={s.disabled} onChange={() => alternar(s.id)} />
          </span>
          <span className="gc-srcopt__body">
            <span className="gc-srcopt__name">{s.name}</span>
            {s.description && <span className="gc-srcopt__desc">{s.description}</span>}
          </span>
        </label>
      ))}
    </fieldset>
  );
}
