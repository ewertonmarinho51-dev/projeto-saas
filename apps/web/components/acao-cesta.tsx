"use client";

import { useActionState } from "react";

import { alterarCesta, type EstadoDaCesta } from "@/app/app/precos/acoes";
import { botaoPrimario, botaoSecundario, campo, rotulo } from "@/components/ui";

/**
 * Pôr ou tirar uma referência da cesta.
 *
 * Tirar: um clique, sem justificativa (regra do domínio, pacote Jev
 * RF-02 — a trilha registra quem e quando). Pôr: pede o motivo, que vai
 * para a memória de cálculo. A revisão do item segue no formulário; se
 * outra aba mexeu antes, a API devolve 409 e nada é gravado.
 */
export function AcaoNaCesta({
  pesquisa,
  item,
  referencia,
  revisao,
  naCesta,
}: {
  pesquisa: string;
  item: string;
  referencia: string;
  revisao: number;
  naCesta: boolean;
}) {
  const [estado, acao, enviando] = useActionState<EstadoDaCesta, FormData>(alterarCesta, { erro: null });
  const ocultos = (
    <>
      <input type="hidden" name="pesquisa" value={pesquisa} />
      <input type="hidden" name="item" value={item} />
      <input type="hidden" name="referencia" value={referencia} />
      <input type="hidden" name="revisao" value={revisao} />
    </>
  );
  const erro = estado.erro && (
    <p role="alert" className="mt-2 rounded-[var(--radius-ui)] bg-erro-fundo px-3 py-2 text-xs text-erro">
      {estado.erro}
    </p>
  );

  if (naCesta) {
    return (
      <form action={acao}>
        {ocultos}
        <input type="hidden" name="incluir" value="0" />
        <button type="submit" className={`${botaoSecundario} h-9 px-3 text-sm`} disabled={enviando}>
          {enviando ? "Retirando..." : "Tirar da cesta"}
        </button>
        {erro}
      </form>
    );
  }

  const idMotivo = `motivo-${referencia}`;
  return (
    <details className="group">
      <summary className={`${botaoSecundario} h-9 cursor-pointer list-none px-3 text-sm`}>Pôr na cesta</summary>
      <form action={acao} className="mt-3 grid gap-2">
        {ocultos}
        <input type="hidden" name="incluir" value="1" />
        <label htmlFor={idMotivo} className={rotulo}>
          Motivo da inclusão
        </label>
        <textarea id={idMotivo} name="motivo" rows={2} maxLength={1000} required className={`${campo} h-auto py-2 text-sm`} />
        <button type="submit" className={`${botaoPrimario} h-9 px-3 text-sm`} disabled={enviando}>
          {enviando ? "Incluindo..." : "Confirmar inclusão"}
        </button>
        {erro}
      </form>
    </details>
  );
}
