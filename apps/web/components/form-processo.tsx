"use client";

import { useActionState } from "react";

import type { EstadoDoFormulario } from "@/app/app/processos/acoes";
import { Alert, Button, Field, Input, Textarea } from "@/design-system";

type Acao = (estado: EstadoDoFormulario, form: FormData) => Promise<EstadoDoFormulario>;

/**
 * Formulário único para criar e editar: os mesmos três campos, a mesma
 * validação. Os campos ocultos (chave de idempotência, id, versão) vêm do
 * servidor junto com a página.
 */
export function FormularioDeProcesso({
  acao,
  rotuloDoBotao,
  ocultos,
  inicial = { nome: "", orgao: "", objeto: "" },
}: {
  acao: Acao;
  rotuloDoBotao: string;
  ocultos: Record<string, string>;
  inicial?: { nome: string; orgao: string; objeto: string };
}) {
  const [estado, executar, enviando] = useActionState<EstadoDoFormulario, FormData>(acao, { erro: null });
  return (
    <form action={executar} className="grid gap-5">
      {Object.entries(ocultos).map(([nome, valor]) => (
        <input key={nome} type="hidden" name={nome} value={valor} />
      ))}
      <Field label="Nome do processo" htmlFor="nome" optional help="Sem nome, a lista mostra órgão e objeto.">
        <Input id="nome" name="nome" maxLength={120} defaultValue={inicial.nome} />
      </Field>
      <Field label="Órgão ou secretaria" htmlFor="orgao" required>
        <Input
          id="orgao"
          name="orgao"
          required
          maxLength={200}
          defaultValue={inicial.orgao}
          placeholder="Ex.: Secretaria Municipal de Saúde"
        />
      </Field>
      <Field label="Objeto da contratação" htmlFor="objeto" required>
        <Textarea
          id="objeto"
          name="objeto"
          required
          maxLength={2000}
          rows={3}
          defaultValue={inicial.objeto}
          placeholder="Ex.: Aquisição de luvas de procedimento para as unidades de saúde"
        />
      </Field>
      <div aria-live="assertive">{estado.erro && <Alert variant="error" title={estado.erro} />}</div>
      <div>
        <Button type="submit" size="lg" loading={enviando}>
          {enviando ? "Salvando" : rotuloDoBotao}
        </Button>
      </div>
    </form>
  );
}
