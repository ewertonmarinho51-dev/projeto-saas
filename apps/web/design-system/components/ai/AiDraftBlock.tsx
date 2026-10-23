import type { ReactNode } from "react";

import { Icon } from "../core/Icon";

export interface AiDraftBlockProps {
  /** Destino, ex.: "ETP · Seção 4". */
  target?: ReactNode;
  title: ReactNode;
  children: ReactNode;
  meta?: ReactNode;
  status?: "pending" | "accepted" | "rejected";
  onAccept?: () => void;
  onEdit?: () => void;
  onReject?: () => void;
  onUndo?: () => void;
  acceptedNote?: ReactNode;
}

/**
 * Trecho gerado por IA com revisão humana explícita: aguardando revisão →
 * inserido (com Desfazer) ou descartado (com Restaurar). Nada entra em
 * DFD, ETP ou TR sem o clique do usuário.
 */
export function AiDraftBlock({
  target,
  title,
  children,
  meta,
  status = "pending",
  onAccept,
  onEdit,
  onReject,
  onUndo,
  acceptedNote = "Inserido no documento",
}: AiDraftBlockProps) {
  if (status === "rejected") {
    return (
      <div className="gc-draft" data-status="rejected">
        <div className="gc-draft__head">
          <Icon name="prohibit" />
          <span className="gc-draft__title">Proposta descartada</span>
          {onUndo && (
            <button type="button" className="gc-btn gc-btn--link gc-btn--sm" onClick={onUndo}>
              Restaurar
            </button>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="gc-draft" data-status={status}>
      <div className="gc-draft__head">
        <Icon name="sparkle" weight="fill" />
        <span className="gc-draft__titles">
          <span className="gc-draft__eyebrow">{target}</span>
          <span className="gc-draft__title">{title}</span>
        </span>
        {status === "pending" && (
          <span className="gc-badge gc-badge--sm gc-badge--warning">
            <Icon name="eye" />
            Aguardando revisão
          </span>
        )}
      </div>
      <div className="gc-draft__body">{children}</div>
      {status === "pending" ? (
        <div className="gc-draft__foot">
          {meta && <span className="gc-draft__meta">{meta}</span>}
          <span className="gc-draft__spacer" />
          {onReject && (
            <button type="button" className="gc-btn gc-btn--ghost gc-btn--sm" onClick={onReject}>
              Descartar
            </button>
          )}
          {onEdit && (
            <button type="button" className="gc-btn gc-btn--secondary gc-btn--sm" onClick={onEdit}>
              <Icon name="pencil-simple" />
              Editar
            </button>
          )}
          {onAccept && (
            <button type="button" className="gc-btn gc-btn--primary gc-btn--sm" onClick={onAccept}>
              <Icon name="file-arrow-down" />
              Inserir no documento
            </button>
          )}
        </div>
      ) : (
        <div className="gc-draft__done">
          <Icon name="check-circle" weight="fill" />
          <span>{acceptedNote}</span>
          {onUndo && (
            <button type="button" className="gc-btn gc-btn--link gc-btn--sm" onClick={onUndo}>
              Desfazer
            </button>
          )}
        </div>
      )}
    </div>
  );
}
