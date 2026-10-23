import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";

import { NovaPesquisa } from "@/components/nova-pesquisa";
import { precosHabilitado } from "@/lib/api";

export const metadata: Metadata = { title: "Nova pesquisa de preços" };

export default function Nova() {
  if (!precosHabilitado()) notFound();
  return (
    <div className="grid gap-6">
      <Link href="/app/precos" className="inline-flex items-center gap-2 justify-self-start text-sm text-secundario hover:text-texto">
        <ArrowLeft size={16} weight="bold" aria-hidden />
        Pesquisas de preços
      </Link>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Nova pesquisa de preços</h1>
        <p className="mt-1 max-w-[65ch] text-sm text-secundario">
          Depois de criar, importe a planilha de itens e colete os preços.
        </p>
      </div>
      {/* Chave nova a cada renderização: o duplo clique não cria duas. */}
      <NovaPesquisa chave={`web-nova-${crypto.randomUUID()}`} />
    </div>
  );
}
