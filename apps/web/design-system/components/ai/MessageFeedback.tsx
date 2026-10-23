"use client";

import { useState } from "react";

import { Icon } from "../core/Icon";

export type FeedbackValue = "up" | "down" | null;

export interface MessageFeedbackProps {
  value?: FeedbackValue;
  onChange?: (valor: FeedbackValue) => void;
  onReport?: () => void;
}

/** Útil / não útil depois de toda resposta; o voto negativo oferece "Descrever o problema". */
export function MessageFeedback({ value, onChange, onReport }: MessageFeedbackProps) {
  const [interno, setInterno] = useState<FeedbackValue>(value ?? null);
  const atual = value === undefined ? interno : value;
  const votar = (voto: "up" | "down") => {
    const novo = atual === voto ? null : voto;
    setInterno(novo);
    onChange?.(novo);
  };
  return (
    <span className="gc-feedback">
      <button type="button" className="gc-iconbtn gc-iconbtn--sm" aria-label="Resposta útil" aria-pressed={atual === "up"} onClick={() => votar("up")}>
        <Icon name="thumbs-up" weight={atual === "up" ? "fill" : "bold"} />
      </button>
      <button
        type="button"
        className="gc-iconbtn gc-iconbtn--sm"
        aria-label="Resposta não útil"
        aria-pressed={atual === "down"}
        onClick={() => votar("down")}
      >
        <Icon name="thumbs-down" weight={atual === "down" ? "fill" : "bold"} />
      </button>
      {atual && <span className="gc-feedback__thanks">Obrigado pelo retorno.</span>}
      {atual === "down" && onReport && (
        <button type="button" className="gc-btn gc-btn--link gc-btn--sm" onClick={onReport}>
          Descrever o problema
        </button>
      )}
    </span>
  );
}
