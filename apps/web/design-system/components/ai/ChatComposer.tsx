"use client";

import { useState } from "react";

import { Icon } from "../core/Icon";

export interface ChatComposerProps {
  placeholder?: string;
  hint?: string;
  onSend?: (texto: string) => void;
  busy?: boolean;
  value?: string;
  onChange?: (valor: string) => void;
  /** Sem a função, o botão não aparece: nada de botão que não faz nada. */
  onAttach?: () => void;
  onKnowledge?: () => void;
}

/** Caixa de pergunta ao GovBot: Enter envia, Shift+Enter quebra linha. */
export function ChatComposer({
  placeholder = "Pergunte ao GovBot sobre o processo, a lei ou os documentos…",
  hint = "O GovBot pode errar. Confira as fontes.",
  onSend,
  busy = false,
  value,
  onChange,
  onAttach,
  onKnowledge,
}: ChatComposerProps) {
  const [interno, setInterno] = useState("");
  const atual = value ?? interno;
  const enviar = () => {
    if (!atual.trim() || busy) return;
    onSend?.(atual.trim());
    if (value === undefined) setInterno("");
  };
  return (
    <div className="gc-composer">
      <textarea
        rows={2}
        value={atual}
        placeholder={placeholder}
        aria-label="Mensagem para o GovBot"
        onChange={(e) => {
          setInterno(e.target.value);
          onChange?.(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            enviar();
          }
        }}
      />
      <div className="gc-composer__bar">
        {onAttach && (
          <button type="button" className="gc-iconbtn gc-iconbtn--sm" aria-label="Anexar documento" onClick={onAttach}>
            <Icon name="paperclip" />
          </button>
        )}
        {onKnowledge && (
          <button type="button" className="gc-iconbtn gc-iconbtn--sm" aria-label="Usar base de conhecimento" onClick={onKnowledge}>
            <Icon name="books" />
          </button>
        )}
        <span className="gc-composer__hint">{hint}</span>
        <button
          type="button"
          className="gc-iconbtn gc-iconbtn--sm gc-iconbtn--primary"
          aria-label="Enviar"
          disabled={!atual.trim() || busy}
          onClick={enviar}
        >
          {busy ? <span className="gc-spinner gc-spinner--sm" /> : <Icon name="arrow-up" />}
        </button>
      </div>
    </div>
  );
}
