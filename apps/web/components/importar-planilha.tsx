"use client";

import { FileXls } from "@phosphor-icons/react";
import { startTransition, useActionState, useState } from "react";

import { importarPlanilha, type EstadoDaImportacao } from "@/app/app/precos/acoes";
import { botaoPrimario, botaoSecundario, rotulo } from "@/components/ui";

const ROTULO_ACAO: Record<string, string> = { novo: "Novo", atualizar: "Atualiza", igual: "Igual" };

/**
 * Importar a planilha de itens em dois passos: conferir (nada é gravado)
 * e confirmar o plano que apareceu. O arquivo fica no estado do cliente:
 * o React 19 limpa o formulário depois de cada ação, e a confirmação
 * precisa reenviar o MESMO arquivo para o servidor refazer o plano.
 */
export function ImportarPlanilha({ pesquisa }: { pesquisa: string }) {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [estado, acao, enviando] = useActionState<EstadoDaImportacao, FormData>(importarPlanilha, {
    erro: null,
    plano: null,
  });
  const plano = estado.plano;

  function enviar(confirmar: boolean) {
    if (!arquivo) return;
    const dados = new FormData();
    dados.set("pesquisa", pesquisa);
    dados.set("planilha", arquivo);
    if (confirmar && plano) dados.set("plano", plano.plano);
    startTransition(() => acao(dados));
  }

  const mudam = plano ? plano.acoes.filter((a) => a.tipo !== "igual") : [];

  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <label htmlFor="planilha-itens" className={rotulo}>
          Planilha de itens (XLSX)
        </label>
        <p className="text-sm text-secundario">
          Colunas reconhecidas: código, descrição, unidade, quantidade (UF e lote opcionais). Reimportar a mesma planilha
          não duplica itens.
        </p>
        <input
          id="planilha-itens"
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
          className="text-sm file:mr-3 file:rounded-[var(--radius-ui)] file:border file:border-linha file:bg-superficie file:px-3 file:py-2 file:text-sm"
        />
      </div>
      <button type="button" className={`${botaoSecundario} justify-self-start`} disabled={!arquivo || enviando} onClick={() => enviar(false)}>
        <FileXls size={18} weight="bold" aria-hidden />
        {enviando && !plano ? "Conferindo..." : "Conferir planilha"}
      </button>

      {estado.erro && (
        <p role="alert" className="rounded-[var(--radius-ui)] bg-erro-fundo px-3 py-2 text-sm text-erro">
          {estado.erro}
        </p>
      )}

      {plano && (
        <div className="grid gap-3" data-testid="plano-importacao">
          {plano.erros.length > 0 ? (
            <div role="alert" className="grid gap-2 rounded-[var(--radius-ui)] bg-erro-fundo px-4 py-3 text-sm text-erro">
              <p className="font-medium">
                A planilha tem {plano.erros.length} problema(s). Nada será gravado até corrigir.
              </p>
              <ul className="grid gap-1">
                {plano.erros.slice(0, 30).map((e, i) => (
                  <li key={i}>
                    {e.linha ? `Linha ${e.linha}` : "Planilha"}, {e.campo}: {e.motivo}
                    {e.valor ? ` (${e.valor})` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm">
              <span className="font-medium">{plano.resumo.novo}</span> item(ns) novo(s),{" "}
              <span className="font-medium">{plano.resumo.atualizar}</span> atualizado(s),{" "}
              <span className="font-medium">{plano.resumo.igual}</span> igual(is).
              {plano.resumo.refaz_busca > 0 &&
                ` ${plano.resumo.refaz_busca} item(ns) mudam de descrição ou unidade e voltam para a busca: a cesta atual valia para o item antigo.`}
            </p>
          )}

          {mudam.length > 0 && (
            <div className="overflow-x-auto rounded-[var(--radius-ui)] border border-linha">
              <table className="w-full min-w-[40rem] text-sm">
                <caption className="sr-only">Itens que a importação cria ou altera</caption>
                <thead className="border-b border-linha text-left text-secundario">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">Nº</th>
                    <th scope="col" className="px-3 py-2 font-medium">Ação</th>
                    <th scope="col" className="px-3 py-2 font-medium">Descrição</th>
                    <th scope="col" className="px-3 py-2 font-medium">Unidade</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Quantidade</th>
                    <th scope="col" className="px-3 py-2 font-medium">Muda</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-linha">
                  {mudam.slice(0, 300).map((a) => (
                    <tr key={`${a.numero}-${a.descricao}`}>
                      <td className="px-3 py-2 font-mono text-secundario">{a.numero}</td>
                      <td className="px-3 py-2">{ROTULO_ACAO[a.tipo] ?? a.tipo}</td>
                      <td className="max-w-[24rem] px-3 py-2">{a.descricao}</td>
                      <td className="px-3 py-2">{a.unidade}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{a.quantidade.replace(".", ",")}</td>
                      <td className="px-3 py-2 text-secundario">{a.mudancas.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {plano.pode_importar && mudam.length > 0 && (
            <button type="button" className={`${botaoPrimario} justify-self-start`} disabled={enviando} onClick={() => enviar(true)}>
              {enviando ? "Importando..." : "Confirmar importação"}
            </button>
          )}
          {plano.pode_importar && mudam.length === 0 && (
            <p className="text-sm text-secundario">A planilha é igual ao que a pesquisa já tem.</p>
          )}
        </div>
      )}
    </div>
  );
}
