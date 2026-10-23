import { Input, type InputProps } from "./Input";

export interface DateFieldProps extends Omit<InputProps, "type"> {
  /** Par início/fim. */
  range?: boolean;
  startProps?: Omit<InputProps, "type">;
  endProps?: Omit<InputProps, "type">;
}

/** Data com o seletor nativo (dd/mm/aaaa em navegador pt-BR). */
export function DateField({ range = false, startProps = {}, endProps = {}, ...rest }: DateFieldProps) {
  if (!range) return <Input type="date" {...rest} />;
  return (
    <div className="gc-daterange">
      <Input type="date" aria-label="Data inicial" {...startProps} />
      <Input type="date" aria-label="Data final" {...endProps} />
    </div>
  );
}
