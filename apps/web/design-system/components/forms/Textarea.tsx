import type { TextareaHTMLAttributes } from "react";

import { cx } from "../../lib/cx";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

/** Texto de várias linhas (objeto, justificativa). Com limite, use o `counter` do Field. */
export function Textarea({ invalid, rows = 4, className, ...rest }: TextareaProps) {
  return <textarea rows={rows} aria-invalid={invalid || undefined} className={cx("gc-textarea", className)} {...rest} />;
}
