"use client";

import { useActionState } from "react";

import { Alert, Button, Field, Input } from "@/design-system";

import { trocarSenha, type EstadoDaSenha } from "./acoes";

export function FormularioDeSenha() {
  const [estado, acao, enviando] = useActionState<EstadoDaSenha, FormData>(trocarSenha, { erro: null });
  return (
    <form action={acao} className="grid gap-5">
      <Field label="Nova senha" htmlFor="nova" required help="Pelo menos 12 caracteres.">
        <Input
          id="nova"
          name="nova"
          type="password"
          icon="lock-simple"
          autoComplete="new-password"
          required
          minLength={12}
          aria-describedby="nova-ajuda"
        />
      </Field>
      <Field label="Confirme a nova senha" htmlFor="confirmacao" required>
        <Input id="confirmacao" name="confirmacao" type="password" icon="lock-simple" autoComplete="new-password" required />
      </Field>
      <div aria-live="assertive">{estado.erro && <Alert variant="error" title={estado.erro} />}</div>
      <div>
        <Button type="submit" size="lg" loading={enviando}>
          {enviando ? "Salvando" : "Trocar senha"}
        </Button>
      </div>
    </form>
  );
}
