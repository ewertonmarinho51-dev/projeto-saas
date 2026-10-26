"use client";

import { useState } from "react";

import { Button } from "../actions/Button";
import { Dialog } from "../content/Dialog";
import { Field } from "../forms/Field";
import { RadioGroup, type RadioOption } from "../forms/Radio";
import { Textarea } from "../forms/Textarea";

const MOTIVOS: RadioOption[] = [
  { value: "objeto", label: "Objeto não comparável", description: "Especificação, marca ou qualidade diferente" },
  { value: "unidade", label: "Unidade de medida divergente" },
  { value: "data", label: "Data fora do período de referência" },
  { value: "valor", label: "Valor inexequível ou excessivo" },
  { value: "outro", label: "Outro motivo" },
];

/** Justificativa mínima quando o motivo é "valor" ou "outro". */
export const JUSTIFICATIVA_MINIMA = 10;

export interface ExclusionDialogProps {
  open?: boolean;
  reference?: { title: string; value: string };
  onCancel?: () => void;
  onConfirm?: (r: { reason: string; note: string }) => void;
  reasons?: RadioOption[];
  contained?: boolean;
}

/**
 * Retirar uma referência do cálculo exige motivo registrado (e
 * justificativa para "valor" e "outro"). A decisão é do servidor e vai
 * para o relatório; nada sai do cálculo sozinho.
 */
export function ExclusionDialog({ open = true, reference, onCancel, onConfirm, reasons = MOTIVOS, contained }: ExclusionDialogProps) {
  const [motivo, setMotivo] = useState<string | null>(null);
  const [nota, setNota] = useState("");
  const pedeNota = motivo === "outro" || motivo === "valor";
  const pronto = motivo !== null && (!pedeNota || nota.trim().length >= JUSTIFICATIVA_MINIMA);
  return (
    <Dialog
      open={open}
      contained={contained}
      onClose={onCancel}
      icon="minus-circle"
      tone="warning"
      title="Retirar referência do cálculo"
      description={reference ? `${reference.title} · ${reference.value}` : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancelar
          </Button>
          <Button disabled={!pronto} onClick={() => motivo && onConfirm?.({ reason: motivo, note: nota })}>
            Retirar do cálculo
          </Button>
        </>
      }
    >
      <div className="gc-field-stack">
        <RadioGroup name="motivo-exclusao" legend="Motivo" value={motivo} onChange={setMotivo} options={reasons} />
        <Field
          label="Justificativa"
          required={pedeNota}
          optional={!pedeNota}
          help="Fica registrada no relatório da pesquisa."
          counter={`${nota.length} / 500`}
        >
          <Textarea
            rows={3}
            value={nota}
            maxLength={500}
            onChange={(e) => setNota(e.target.value)}
            placeholder="Ex.: Proposta refere-se a papel 90 g/m², gramatura superior à especificada."
          />
        </Field>
      </div>
    </Dialog>
  );
}
