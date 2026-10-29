"use client";

import { useActionState } from "react";

import { criarPesquisa, type EstadoDaCriacao } from "@/app/app/precos/acoes";
import { Alert, Button, Field, Input, Textarea } from "@/design-system";

/** Nova pesquisa: o nome primeiro; os itens vêm depois, pela planilha. */
export function NovaPesquisa({ chave }: { chave: string }) {
  const [estado, acao, enviando] = useActionState<EstadoDaCriacao, FormData>(criarPesquisa, { erro: null });
  return (
    <form action={acao} className="grid max-w-2xl gap-5">
      <input type="hidden" name="chave" value={chave} />
      <Field label="Nome da pesquisa" htmlFor="nome" required>
        <Input id="nome" name="nome" required maxLength={200} autoComplete="off" placeholder="Ex.: Material de expediente 2026" />
      </Field>
      <Field label="Objeto" htmlFor="objeto" optional>
        <Textarea id="objeto" name="objeto" rows={3} maxLength={2000} />
      </Field>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Responsável" htmlFor="responsavel" optional>
          <Input id="responsavel" name="responsavel" maxLength={200} />
        </Field>
        <Field label="Data-base" htmlFor="data_base" optional>
          <Input id="data_base" name="data_base" type="date" />
        </Field>
      </div>
      <Field label="Local de referência" htmlFor="local_referencia" optional>
        <Input id="local_referencia" name="local_referencia" maxLength={200} placeholder="Ex.: Paragominas/PA" />
      </Field>
      <div aria-live="assertive">{estado.erro && <Alert variant="error" title={estado.erro} />}</div>
      <div>
        <Button type="submit" size="lg" icon="plus" loading={enviando}>
          {enviando ? "Criando" : "Criar pesquisa"}
        </Button>
      </div>
    </form>
  );
}
