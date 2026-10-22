import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";

import { FormularioDeProcesso } from "@/components/form-processo";
import { cartao } from "@/components/ui";
import { chamarApi, ErroDaApi, type Processo } from "@/lib/api";

import { editarProcesso } from "../acoes";

export const metadata: Metadata = { title: "Processo" };

const DATA = new Intl.DateTimeFormat("pt-BR", { dateStyle: "long", timeStyle: "short", timeZone: "America/Sao_Paulo" });

export default async function DetalheDoProcesso({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const avisos = await searchParams;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();

  let p: Processo;
  try {
    p = (await chamarApi<Processo>(`/processos/${id}`)).dados;
  } catch (e) {
    // 404 também para processo de outro município: não confirma que existe.
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }

  const aviso = avisos.criado ? "Processo criado." : avisos.salvo ? "Alterações salvas." : null;

  return (
    <div className="grid gap-8">
      <Link
        href="/app/processos"
        className="inline-flex items-center gap-2 justify-self-start text-sm text-secundario hover:text-texto"
      >
        <ArrowLeft size={16} weight="bold" aria-hidden />
        Processos
      </Link>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="titulo-processo">
          {p.nome_exibido}
        </h1>
        <dl className="mt-4 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-secundario">Situação</dt>
            <dd className="font-medium">{p.status}</dd>
          </div>
          <div>
            <dt className="text-secundario">Etapa</dt>
            <dd className="font-medium">{p.etapa}</dd>
          </div>
          <div>
            <dt className="text-secundario">Documentos aprovados</dt>
            <dd className="font-medium">
              {p.progresso.feitos} de {p.progresso.total}
            </dd>
          </div>
        </dl>
        <p className="mt-3 text-xs text-secundario">
          Atualizado em {p.atualizado_em ? DATA.format(new Date(p.atualizado_em)) : "data indisponível"}
        </p>
      </div>

      {aviso && (
        <p role="status" className="rounded-[var(--radius-ui)] bg-ok-fundo px-4 py-3 text-sm text-ok">
          {aviso}
        </p>
      )}

      <section aria-labelledby="titulo-editar" className={`${cartao} p-6 sm:p-8`}>
        <h2 id="titulo-editar" className="text-lg font-semibold">
          Dados do processo
        </h2>
        <div className="mt-6 max-w-xl">
          <FormularioDeProcesso
            acao={editarProcesso}
            rotuloDoBotao="Salvar alterações"
            ocultos={{ id: p.id, versao: p.versao }}
            inicial={{ nome: p.nome, orgao: p.orgao, objeto: p.objeto }}
          />
        </div>
      </section>
    </div>
  );
}
