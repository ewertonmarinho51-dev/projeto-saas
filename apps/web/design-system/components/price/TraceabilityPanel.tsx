import type { ReactNode } from "react";

import { DataList, type DataListItem } from "../content/DataList";
import { Icon } from "../core/Icon";

export interface TraceabilityPanelProps {
  fields: DataListItem[];
  url?: string;
  urlLabel?: string;
  /** Impressão digital da coleta / id do registro. */
  hash?: string;
  status?: ReactNode;
}

/**
 * Origem de uma referência: fonte, id do registro, órgão, data, objeto,
 * link para o original e a impressão da coleta. Mostra só o que foi
 * coletado — nunca presume verificação.
 */
export function TraceabilityPanel({ fields, url, urlLabel = "Consultar registro original", hash, status }: TraceabilityPanelProps) {
  return (
    <div className="gc-trace">
      <DataList items={fields} />
      <div className="gc-trace__foot">
        {url ? (
          <a href={url} target="_blank" rel="noreferrer" className="gc-btn gc-btn--secondary gc-btn--sm">
            <Icon name="arrow-square-out" />
            {urlLabel}
          </a>
        ) : (
          <span className="gc-help">Registro sem URL pública de consulta.</span>
        )}
        <span className="gc-trace__meta">
          {hash && (
            <code className="gc-trace__hash" title="Identificador do registro coletado">
              {hash}
            </code>
          )}
          {status}
        </span>
      </div>
    </div>
  );
}
