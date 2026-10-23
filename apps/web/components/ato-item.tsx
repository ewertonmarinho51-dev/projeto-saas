"use client";

import { useActionState } from "react";

import { concluirItem, reabrirItem, type EstadoDoItem } from "@/app/app/precos/acoes";
import { botaoPrimario, botaoSecundario, campo, rotulo } from "@/components/ui";

/**
 * Concluir (item em revisão) ou reabrir (item concluído). A regra é do
 * domínio: concluir com pendência de análise crítica exige justificativa;
 * reabrir exige motivo. A mensagem dele volta como veio.
 */
export function AtoNoItem({
  pesquisa,
  item,
  revisao,
  estado,
}: {
  pesquisa: string;
  item: string;
  revisao: number;
  estado: string;
}) {
  const concluir = estado === "review";
  const [situacao, acao, enviando] = useActionState<EstadoDoItem, FormData>(concluir ? concluirItem : reabrirItem, {
    erro: null,
  });
  if (!concluir && estado !== "complete") return null;
  const id = `texto-${item}`;
  return (
    <form action={acao} className="grid gap-2" data-testid="ato-item">
      <input type="hidden" name="pesquisa" value={pesquisa} />
      <input type="hidden" name="item" value={item} />
      <input type="hidden" name="revisao" value={revisao} />
      <label htmlFor={id} className={rotulo}>
        {concluir ? "Justificativa (obrigatória se o item tiver pendência de análise crítica)" : "Motivo da reabertura"}
      </label>
      <textarea id={id} name="texto" rows={2} maxLength={2000} required={!concluir} className={`${campo} h-auto py-2 text-sm`} />
      <button type="submit" className={`${concluir ? botaoPrimario : botaoSecundario} justify-self-start`} disabled={enviando}>
        {enviando ? "Enviando..." : concluir ? "Concluir item" : "Reabrir item"}
      </button>
      {situacao.erro && (
        <p role="alert" className="rounded-[var(--radius-ui)] bg-erro-fundo px-3 py-2 text-sm text-erro">
          {situacao.erro}
        </p>
      )}
    </form>
  );
}
