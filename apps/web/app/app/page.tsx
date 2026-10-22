import type { Metadata } from "next";
import Link from "next/link";
import { Plus } from "@phosphor-icons/react/dist/ssr";

import { ListaDeProcessos } from "@/components/lista-processos";
import { botaoPrimario, cartao } from "@/components/ui";
import { chamarApi, type Pagina, type Processo } from "@/lib/api";

export const metadata: Metadata = { title: "Início" };

export default async function Inicio() {
  const { dados } = await chamarApi<Pagina<Processo>>("/processos?limit=5");

  return (
    <div className="grid gap-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Processos recentes</h1>
          <p className="mt-1 text-sm text-secundario">Os últimos atualizados no seu órgão.</p>
        </div>
        <Link href="/app/processos#novo" className={botaoPrimario}>
          <Plus size={18} weight="bold" aria-hidden />
          Novo processo
        </Link>
      </div>

      {dados.itens.length > 0 ? (
        <div className="grid gap-3">
          <ListaDeProcessos processos={dados.itens} />
          <Link
            href="/app/processos"
            className="justify-self-start text-sm text-acento underline-offset-4 hover:text-acento-forte hover:underline"
          >
            Ver todos os processos
          </Link>
        </div>
      ) : (
        <div className={`${cartao} px-6 py-12 text-center`}>
          <p className="font-medium">Nenhum processo ainda</p>
          <p className="mx-auto mt-2 max-w-[44ch] text-sm text-secundario">
            Comece registrando o órgão e o objeto da contratação. Os documentos vêm depois.
          </p>
        </div>
      )}
    </div>
  );
}
