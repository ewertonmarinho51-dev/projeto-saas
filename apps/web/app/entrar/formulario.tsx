"use client";

import Link from "next/link";
import { useActionState } from "react";

import { botaoPrimario, campo, rotulo } from "@/components/ui";

import { entrar, type EstadoDoLogin } from "./acoes";

export function FormularioDeEntrada({ proximo, aviso }: { proximo: string; aviso: string | null }) {
  const [estado, acao, enviando] = useActionState<EstadoDoLogin, FormData>(entrar, {
    erro: null,
    email: "",
  });
  const comErro = Boolean(estado.erro);

  return (
    <form action={acao} className="grid gap-5" noValidate>
      <input type="hidden" name="proximo" value={proximo} />

      {aviso && !comErro && (
        <p role="status" className="rounded-[var(--radius-ui)] bg-ok-fundo px-4 py-3 text-sm text-ok">
          {aviso}
        </p>
      )}

      <div className="grid gap-2">
        <label htmlFor="email" className={rotulo}>
          E-mail institucional
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          inputMode="email"
          required
          defaultValue={estado.email}
          aria-invalid={comErro}
          aria-describedby={comErro ? "erro-login" : undefined}
          className={campo}
        />
      </div>

      <div className="grid gap-2">
        <div className="flex items-baseline justify-between">
          <label htmlFor="senha" className={rotulo}>
            Senha
          </label>
          <Link
            href="/entrar/recuperar"
            className="text-sm text-acento underline-offset-4 hover:text-acento-forte hover:underline"
          >
            Esqueci minha senha
          </Link>
        </div>
        <input
          id="senha"
          name="senha"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={comErro}
          aria-describedby={comErro ? "erro-login" : undefined}
          className={campo}
        />
      </div>

      <div aria-live="assertive" className="min-h-0">
        {comErro && (
          <p
            id="erro-login"
            className="rounded-[var(--radius-ui)] bg-erro-fundo px-4 py-3 text-sm text-erro"
          >
            {estado.erro}
          </p>
        )}
      </div>

      <button type="submit" className={`${botaoPrimario} w-full`} disabled={enviando}>
        {enviando ? "Entrando..." : "Entrar"}
      </button>
    </form>
  );
}
