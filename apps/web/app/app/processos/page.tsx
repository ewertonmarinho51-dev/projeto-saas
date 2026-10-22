import type { Metadata } from "next";
import Link from "next/link";

import { FormularioDeProcesso } from "@/components/form-processo";
import { ListaDeProcessos } from "@/components/lista-processos";
import { cartao } from "@/components/ui";
import { chamarApi, type Pagina, type Processo } from "@/lib/api";

import { criarProcesso } from "./acoes";

export const metadata: Metadata = { title: "Processos" };

export default async function Processos({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const cursor = typeof params.cursor === "string" ? params.cursor : "";
  const consulta = new URLSearchParams({ limit: "20" });
  if (cursor) consulta.set("cursor", cursor);
  const { dados } = await chamarApi<Pagina<Processo>>(`/processos?${consulta}`);

  return (
    <div className="grid gap-12">
      <section className="grid gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Processos</h1>
        {dados.itens.length > 0 ? (
          <ListaDeProcessos processos={dados.itens} />
        ) : (
          <p className={`${cartao} px-6 py-10 text-center text-sm text-secundario`}>
            {cursor ? "Não há mais processos." : "Nenhum processo no seu órgão ainda."}
          </p>
        )}
        <div className="flex gap-4 text-sm">
          {cursor && (
            <Link href="/app/processos" className="text-acento underline-offset-4 hover:underline">
              Voltar ao início da lista
            </Link>
          )}
          {dados.proximo_cursor && (
            <Link
              href={`/app/processos?cursor=${encodeURIComponent(dados.proximo_cursor)}`}
              className="text-acento underline-offset-4 hover:underline"
            >
              Próxima página
            </Link>
          )}
        </div>
      </section>

      <section id="novo" aria-labelledby="titulo-novo" className={`${cartao} p-6 sm:p-8`}>
        <h2 id="titulo-novo" className="text-lg font-semibold">
          Novo processo
        </h2>
        <p className="mt-1 text-sm text-secundario">O município e a secretaria vêm da sua conta.</p>
        <div className="mt-6 max-w-xl">
          <FormularioDeProcesso
            acao={criarProcesso}
            rotuloDoBotao="Criar processo"
            ocultos={{ chave: `web-${crypto.randomUUID()}` }}
          />
        </div>
      </section>
    </div>
  );
}
