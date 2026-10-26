"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { Alert, Button, Field, Icon, Input } from "@/design-system";

import { entrar, type EstadoDoLogin } from "./acoes";

export function FormularioDeEntrada({ proximo, aviso }: { proximo: string; aviso: string | null }) {
  const [estado, acao, enviando] = useActionState<EstadoDoLogin, FormData>(entrar, {
    erro: null,
    email: "",
  });
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const comErro = Boolean(estado.erro);

  return (
    <form action={acao} className="gc-auth__form" noValidate>
      <input type="hidden" name="proximo" value={proximo} />

      {aviso && !comErro && (
        <Alert variant="success" compact>
          {aviso}
        </Alert>
      )}

      <Field label="E-mail institucional" htmlFor="email">
        <Input
          id="email"
          name="email"
          type="email"
          size="lg"
          icon="envelope-simple"
          autoComplete="username"
          inputMode="email"
          required
          defaultValue={estado.email}
          invalid={comErro}
          aria-describedby={comErro ? "erro-login" : undefined}
        />
      </Field>

      <Field label="Senha" htmlFor="senha">
        <Input
          id="senha"
          name="senha"
          type={mostrarSenha ? "text" : "password"}
          size="lg"
          icon="lock-simple"
          autoComplete="current-password"
          required
          invalid={comErro}
          aria-describedby={comErro ? "erro-login" : undefined}
          suffix={
            <button
              type="button"
              className="gc-input__clear"
              aria-label={mostrarSenha ? "Ocultar senha" : "Mostrar senha"}
              aria-pressed={mostrarSenha}
              onClick={() => setMostrarSenha((m) => !m)}
            >
              <Icon name={mostrarSenha ? "eye-slash" : "eye"} />
            </button>
          }
        />
      </Field>

      <div className="gc-auth__row">
        <Link href="/entrar/recuperar" className="gc-auth__link">
          Esqueci a senha
        </Link>
      </div>

      {comErro && (
        <div id="erro-login">
          <Alert variant="error" title="Não foi possível entrar">
            {estado.erro}
          </Alert>
        </div>
      )}

      <Button type="submit" size="lg" block loading={enviando}>
        {enviando ? "Entrando" : "Entrar"}
      </Button>
    </form>
  );
}
