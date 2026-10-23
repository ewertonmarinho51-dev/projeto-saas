import type { IconName } from "../core/Icon";
import { Badge, type BadgeVariant } from "./Badge";

export type ProcessStatus =
  | "rascunho"
  | "em_elaboracao"
  | "em_andamento"
  | "em_revisao"
  | "pendente"
  | "concluido"
  | "aplicado"
  | "bloqueado"
  | "erro"
  | "arquivado";

/**
 * Vocabulário único de situação para processo, documento e pesquisa de
 * preços: ícone + rótulo + cor, igual em todo módulo.
 */
export const PROCESS_STATUS: Record<ProcessStatus, { label: string; variant: BadgeVariant; icon: IconName }> = {
  rascunho: { label: "Rascunho", variant: "neutral", icon: "pencil-simple-line" },
  em_elaboracao: { label: "Em elaboração", variant: "info", icon: "circle-dashed" },
  em_andamento: { label: "Em andamento", variant: "info", icon: "clock" },
  em_revisao: { label: "Em revisão", variant: "warning", icon: "eye" },
  pendente: { label: "Pendente", variant: "warning", icon: "hourglass-medium" },
  concluido: { label: "Concluído", variant: "success", icon: "check-circle" },
  aplicado: { label: "Aplicado ao processo", variant: "success", icon: "seal-check" },
  bloqueado: { label: "Bloqueado", variant: "error", icon: "prohibit" },
  erro: { label: "Falha", variant: "error", icon: "warning-octagon" },
  arquivado: { label: "Arquivado", variant: "neutral", icon: "archive" },
};

export interface StatusBadgeProps {
  status: ProcessStatus;
  /** Troca o rótulo, mantendo cor e ícone. */
  label?: string;
  size?: "sm" | "md" | "lg";
}

export function StatusBadge({ status, label, size }: StatusBadgeProps) {
  const s = PROCESS_STATUS[status] ?? PROCESS_STATUS.rascunho;
  return (
    <Badge variant={s.variant} icon={s.icon} size={size}>
      {label ?? s.label}
    </Badge>
  );
}
