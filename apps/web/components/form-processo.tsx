"use client";

import { useActionState } from "react";

import { botaoPrimario, campo, rotulo } from "@/components/ui";
import type { EstadoDoFormulario } from "@/app/app/processos/acoes";

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
      <div className="grid gap-2">
        <label htmlFor="nome" className={rotulo}>
          Nome do processo <span className="font-normal text-secundario">(opcional)</span>
        </label>
        <input id="nome" name="nome" maxLength={120} defaultValue={inicial.nome} className={campo} />
      </div>
      <div className="grid gap-2">
        <label htmlFor="orgao" className={rotulo}>
          Órgão ou secretaria
        </label>
        <input id="orgao" name="orgao" required maxLength={200} defaultValue={inicial.orgao} className={campo} />
      </div>
      <div className="grid gap-2">
        <label htmlFor="objeto" className={rotulo}>
          Objeto da contratação
        </label>
        <textarea
          id="objeto"
          name="objeto"
          required
          maxLength={2000}
          rows={3}
          defaultValue={inicial.objeto}
          className={`${campo} h-auto py-2.5`}
        />
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
          {enviando ? "Salvando..." : rotuloDoBotao}
        </button>
      </div>
    </form>
  );
}
