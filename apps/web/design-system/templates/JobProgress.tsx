import type { HTMLAttributes, ReactNode, Ref } from "react";

import { cx } from "../lib/cx";
import { Icon } from "../components/core/Icon";
import { ProgressBar } from "../components/feedback/ProgressBar";

/**
 * `prep` = antes da primeira resposta (fila); `run` = processando;
 * `error` = parou. A conclusão não é estado do painel: nela o painel dá
 * lugar ao resumo, montado pela tela com Alert, Card e DataList.
 */
export type JobProgressState = "prep" | "run" | "error";

export interface JobProgressProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  state: JobProgressState;
  title: ReactNode;
  description?: ReactNode;
  /** Unidades processadas e total do lote. Sem total: contador "0" apagado. */
  done?: number;
  total?: number;
  /** Depois de "de N": "itens processados". */
  unitLabel?: string;
  /** Linha sob a barra, à esquerda ("Aguardando início da coleta"). */
  meta?: ReactNode;
  /** Nome acessível da barra. */
  barLabel?: string;
  /**
   * Desfecho que não é falha do lote (ex.: "3 sem referência compatível"),
   * separado do progresso por um filete.
   */
  outcome?: { title: ReactNode; detail?: ReactNode };
  /** Passos ou fontes, entre a barra e o desfecho. */
  children?: ReactNode;
  ref?: Ref<HTMLElement>;
}

/**
 * Painel de carregamento de um lote longo (coleta de preços): ocupa a área
 * de trabalho (≈ ⅔ da largura no desktop, largura útil no celular), com o
 * contador em destaque e a barra larga. Não tem botões: retomar e emitir
 * usam os controles que a tela já tem. `role="status"` e `aria-live`; na
 * falha, `role="alert"`. Estado por ícone e texto, nunca só por cor.
 */
export function JobProgress({
  state,
  title,
  description,
  done = 0,
  total = 0,
  unitLabel = "itens processados",
  meta,
  barLabel,
  outcome,
  children,
  className,
  ref,
  ...rest
}: JobProgressProps) {
  const semTotal = total <= 0;
  const pct = semTotal ? 0 : Math.round((Math.min(done, total) / total) * 100);
  const erro = state === "error";
  return (
    <section
      ref={ref}
      className={cx("gc-jobprog", className)}
      data-state={state}
      role={erro ? "alert" : "status"}
      aria-live={erro ? undefined : "polite"}
      {...rest}
    >
      <div className="gc-jobprog__head">
        <span className="gc-jobprog__ico">
          {erro ? <Icon name="warning-octagon" weight="fill" /> : <span className="gc-spinner" aria-hidden="true" />}
        </span>
        <div className="gc-jobprog__titles">
          <h2 className="gc-jobprog__title">{title}</h2>
          {description && <p className="gc-jobprog__desc">{description}</p>}
        </div>
      </div>
      <div className="gc-jobprog__count">
        <span className="gc-jobprog__num">{done}</span>
        {!semTotal && (
          <span className="gc-jobprog__of">
            de {total} <span>{unitLabel}</span>
          </span>
        )}
      </div>
      <div className="gc-jobprog__bar">
        <ProgressBar
          size="lg"
          value={semTotal ? 0 : done}
          max={semTotal ? 1 : total}
          indeterminate={state === "prep" || (state === "run" && semTotal)}
          tone={erro ? "neutral" : "accent"}
          showValue={false}
          ariaLabel={barLabel ?? (typeof title === "string" ? title : undefined)}
        />
        <div className="gc-jobprog__barmeta">
          <span>{meta}</span>
          <span>{state === "prep" || semTotal ? "—" : <b>{pct}%</b>}</span>
        </div>
      </div>
      {children}
      {outcome && (
        <div className="gc-jobprog__out">
          <span className="gc-jobprog__out-ico">
            <Icon name="warning-circle" weight="fill" />
          </span>
          <span className="gc-jobprog__out-t">
            <b>{outcome.title}</b>
            {outcome.detail && <span>{outcome.detail}</span>}
          </span>
        </div>
      )}
    </section>
  );
}
