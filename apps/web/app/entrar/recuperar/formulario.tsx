"use client";

import { useActionState } from "react";

import { botaoPrimario, campo, rotulo } from "@/components/ui";

import { pedirRecuperacao, type EstadoDaRecuperacao } from "../acoes";

export function FormularioDeRecuperacao() {
  const [estado, acao, enviando] = useActionState<EstadoDaRecuperacao, FormData>(
    pedirRecuperacao,
    { enviado: false, erro: null },
  );

  if (estado.enviado) {
    return (
      <p role="status" className="rounded-[var(--radius-ui)] bg-ok-fundo px-4 py-3 text-sm text-ok">
        Se o e-mail estiver cadastrado, o link chega em alguns minutos.
      </p>
    );
  }

  return (
    <form action={acao} className="grid gap-5" noValidate>
      <div className="grid gap-2">
        <label htmlFor="email" className={rotulo}>
          E-mail institucional
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          aria-invalid={Boolean(estado.erro)}
          aria-describedby={estado.erro ? "erro-recuperar" : undefined}
          className={campo}
        />
      </div>
      <div aria-live="assertive">
        {estado.erro && (
          <p id="erro-recuperar" className="rounded-[var(--radius-ui)] bg-erro-fundo px-4 py-3 text-sm text-erro">
            {estado.erro}
          </p>
        )}
      </div>
      <button type="submit" className={`${botaoPrimario} w-full`} disabled={enviando}>
        {enviando ? "Enviando..." : "Enviar link"}
      </button>
    </form>
  );
}
