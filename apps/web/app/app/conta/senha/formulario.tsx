"use client";

import { useActionState } from "react";

import { botaoPrimario, campo, rotulo } from "@/components/ui";

import { trocarSenha, type EstadoDaSenha } from "./acoes";

export function FormularioDeSenha() {
  const [estado, acao, enviando] = useActionState<EstadoDaSenha, FormData>(trocarSenha, { erro: null });
  return (
    <form action={acao} className="grid gap-5">
      <div className="grid gap-2">
        <label htmlFor="nova" className={rotulo}>
          Nova senha
        </label>
        <input
          id="nova"
          name="nova"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          aria-describedby="ajuda-senha"
          className={campo}
        />
        <p id="ajuda-senha" className="text-xs text-secundario">
          Pelo menos 12 caracteres.
        </p>
      </div>
      <div className="grid gap-2">
        <label htmlFor="confirmacao" className={rotulo}>
          Confirme a nova senha
        </label>
        <input id="confirmacao" name="confirmacao" type="password" autoComplete="new-password" required className={campo} />
      </div>
      <div aria-live="assertive">
        {estado.erro && (
          <p role="alert" className="rounded-[var(--radius-ui)] bg-erro-fundo px-4 py-3 text-sm text-erro">
            {estado.erro}
          </p>
        )}
      </div>
      <div>
        <button type="submit" className={botaoPrimario} disabled={enviando}>
          {enviando ? "Salvando..." : "Trocar senha"}
        </button>
      </div>
    </form>
  );
}
