"use client";

import { useActionState } from "react";

import { criarPesquisa, type EstadoDaCriacao } from "@/app/app/precos/acoes";
import { botaoPrimario, campo, rotulo } from "@/components/ui";

/** Nova pesquisa: o nome primeiro; os itens vêm depois, pela planilha. */
export function NovaPesquisa({ chave }: { chave: string }) {
  const [estado, acao, enviando] = useActionState<EstadoDaCriacao, FormData>(criarPesquisa, { erro: null });
  return (
    <form action={acao} className="grid max-w-2xl gap-5">
      <input type="hidden" name="chave" value={chave} />
      <div className="grid gap-2">
        <label htmlFor="nome" className={rotulo}>
          Nome da pesquisa
        </label>
        <input id="nome" name="nome" required maxLength={200} className={campo} autoComplete="off" />
      </div>
      <div className="grid gap-2">
        <label htmlFor="objeto" className={rotulo}>
          Objeto
        </label>
        <textarea id="objeto" name="objeto" rows={3} maxLength={2000} className={`${campo} h-auto py-2`} />
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="grid gap-2">
          <label htmlFor="responsavel" className={rotulo}>
            Responsável
          </label>
          <input id="responsavel" name="responsavel" maxLength={200} className={campo} />
        </div>
        <div className="grid gap-2">
          <label htmlFor="data_base" className={rotulo}>
            Data-base
          </label>
          <input id="data_base" name="data_base" type="date" className={campo} />
        </div>
      </div>
      <div className="grid gap-2">
        <label htmlFor="local_referencia" className={rotulo}>
          Local de referência
        </label>
        <input id="local_referencia" name="local_referencia" maxLength={200} className={campo} />
      </div>
      <button type="submit" className={`${botaoPrimario} justify-self-start`} disabled={enviando}>
        {enviando ? "Criando..." : "Criar pesquisa"}
      </button>
      {estado.erro && (
        <p role="alert" className="rounded-[var(--radius-ui)] bg-erro-fundo px-3 py-2 text-sm text-erro">
          {estado.erro}
        </p>
      )}
    </form>
  );
}
