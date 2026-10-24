"use client";

import { useActionState } from "react";

import { Alert, Button, Field, Input } from "@/design-system";

import { pedirRecuperacao, type EstadoDaRecuperacao } from "../acoes";

export function FormularioDeRecuperacao() {
  const [estado, acao, enviando] = useActionState<EstadoDaRecuperacao, FormData>(
    pedirRecuperacao,
    { enviado: false, erro: null },
  );

  if (estado.enviado) {
    return <Alert variant="success">Se o e-mail estiver cadastrado, o link chega em alguns minutos.</Alert>;
  }

  return (
    <form action={acao} className="gc-auth__form" noValidate>
      <Field label="E-mail institucional" htmlFor="email">
        <Input
          id="email"
          name="email"
          type="email"
          size="lg"
          icon="envelope-simple"
          autoComplete="username"
          required
          invalid={Boolean(estado.erro)}
          aria-describedby={estado.erro ? "erro-recuperar" : undefined}
        />
      </Field>
      {estado.erro && (
        <div id="erro-recuperar">
          <Alert variant="error">{estado.erro}</Alert>
        </div>
      )}
      <Button type="submit" size="lg" block loading={enviando}>
        {enviando ? "Enviando" : "Enviar link"}
      </Button>
    </form>
  );
}
