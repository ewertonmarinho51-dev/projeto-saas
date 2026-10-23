"use client";

import { useActionState, useState } from "react";

import { aplicarAoProcesso, type EstadoDaAplicacao } from "@/app/app/precos/acoes";
import { botaoPrimario } from "@/components/ui";
import type { PreviaDaAplicacao } from "@/lib/api";

/**
 * §26: o diff vem ANTES, sempre. O preço de cada item antes e depois, o
 * que a pesquisa NÃO cobre e a lista nominal dos documentos que serão
 * descartados. Nada é gravado sem o clique — e, havendo documento, sem a
 * confirmação do descarte.
 */
export function AplicarAoProcesso({ pesquisa, previa }: { pesquisa: string; previa: PreviaDaAplicacao }) {
  const [estado, acao, enviando] = useActionState<EstadoDaAplicacao, FormData>(aplicarAoProcesso, { erro: null });
  const [confirmado, setConfirmado] = useState(false);
  const descarta = previa.documentos_a_descartar;

  if (previa.impedimento) {
    return <p className="rounded-[var(--radius-ui)] bg-canvas px-4 py-3 text-sm text-secundario">{previa.impedimento}</p>;
  }

  return (
    <form action={acao} className="grid gap-4" data-testid="aplicacao">
      <input type="hidden" name="pesquisa" value={pesquisa} />
      <input type="hidden" name="versao" value={previa.versao_processo} />
      <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-secundario">Itens a atualizar</dt>
          <dd className="font-medium">{previa.mudancas.length}</dd>
        </div>
        <div>
          <dt className="text-secundario">Valor global atual</dt>
          <dd className="font-medium tabular-nums">{previa.valor_atual?.exibicao ?? "Não informado"}</dd>
        </div>
        <div>
          <dt className="text-secundario">Valor global depois</dt>
          <dd className="font-medium tabular-nums" data-testid="valor-depois">
            {previa.valor_novo?.exibicao ?? ""}
          </dd>
        </div>
      </dl>

      <div className="overflow-x-auto rounded-[var(--radius-ui)] border border-linha">
        <table className="w-full min-w-[40rem] text-sm">
          <caption className="sr-only">Preço de cada item antes e depois da aplicação</caption>
          <thead className="border-b border-linha text-left text-secundario">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Item</th>
              <th scope="col" className="px-3 py-2 font-medium">Descrição</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Atual</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Novo</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-linha">
            {previa.mudancas.map((m) => (
              <tr key={m.posicao}>
                <td className="px-3 py-2 font-mono text-secundario">{String(m.posicao).padStart(2, "0")}</td>
                <td className="max-w-[26rem] px-3 py-2">
                  {m.descricao}
                  {m.avisos.map((a, i) => (
                    <span key={i} className="mt-0.5 block text-xs text-secundario">
                      {a}
                    </span>
                  ))}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{m.unitario_atual?.exibicao ?? ""}</td>
                <td className="px-3 py-2 text-right tabular-nums font-medium">{m.unitario_novo?.exibicao ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {previa.recusas.length > 0 && (
        <div className="grid gap-1 text-sm">
          <p className="font-medium">{previa.recusas.length} item(ns) da planilha não serão alterados:</p>
          <ul className="grid gap-1 text-secundario">
            {previa.recusas.slice(0, 50).map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {descarta.length > 0 ? (
        <div className="grid gap-2 rounded-[var(--radius-ui)] bg-erro-fundo px-4 py-3 text-sm text-erro">
          <p>
            Aplicar altera a planilha do Formulário Matriz. Os documentos gerados a partir dela ficam desatualizados e serão
            descartados para nova geração: <span className="font-medium">{descarta.map((d) => d.nome).join(", ")}</span>.
          </p>
          <label className="flex items-start gap-2 text-texto">
            <input
              type="checkbox"
              name="confirmo"
              value="1"
              checked={confirmado}
              onChange={(e) => setConfirmado(e.target.checked)}
              className="mt-1"
            />
            Entendi que esses documentos serão descartados e precisarão ser gerados novamente.
          </label>
        </div>
      ) : (
        <p className="text-sm text-secundario">Nenhum documento gerado ainda: nada será descartado.</p>
      )}

      <button
        type="submit"
        className={`${botaoPrimario} justify-self-start`}
        disabled={enviando || (descarta.length > 0 && !confirmado)}
      >
        {enviando ? "Aplicando..." : "Aplicar preços ao processo"}
      </button>
      {estado.erro && (
        <p role="alert" className="rounded-[var(--radius-ui)] bg-erro-fundo px-3 py-2 text-sm text-erro">
          {estado.erro}
        </p>
      )}
    </form>
  );
}
