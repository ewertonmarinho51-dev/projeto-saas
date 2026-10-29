import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ArtefatosDaGovernanca } from "@/components/governanca";
import { NovaClausula } from "@/components/governanca-acoes";
import { Alert, KpiCard, PageHead } from "@/design-system";
import { chamarApi, ErroDaApi, type ArtefatoDeGovernanca, type CentroDeGovernanca } from "@/lib/api";

export const metadata: Metadata = { title: "Governança" };

export default async function PaginaDaGovernanca({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const busca = await searchParams;
  let centro: CentroDeGovernanca;
  try {
    centro = (await chamarApi<CentroDeGovernanca>("/governanca")).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && (e.status === 404 || e.status === 403)) notFound();
    throw e;
  }

  const ativas = centro.abas.filter((a) => a.ativa);
  const aba =
    typeof busca.aba === "string" && ativas.some((a) => a.tipo === busca.aba) ? busca.aba : (ativas[0]?.tipo ?? null);
  const artefatos = aba
    ? (await chamarApi<ArtefatoDeGovernanca[]>(`/governanca/artefatos?tipo=${encodeURIComponent(aba)}`)).dados
    : [];

  return (
    <div className="grid gap-6">
      <PageHead
        title="Centro de Governança"
        desc={`O conhecimento documental do município — cláusulas, políticas, modelos e templates versionados. Seu papel: ${centro.papel.replace("_", " ")}.`}
      />
      {!centro.escrita ? (
        <Alert variant="info" compact>
          Modo leitura: a escrita do Centro na interface nova ainda não está liberada neste ambiente. Para criar, revisar ou
          publicar, use o GovDocs.
        </Alert>
      ) : centro.papel === "auditor" ? (
        <Alert variant="info" compact>
          Seu papel é de auditoria: você acompanha o Centro sem alterar nada.
        </Alert>
      ) : (
        <Alert variant="info" compact>
          Cada ato segue o seu papel: quem cria escreve e encaminha; o revisor jurídico aprova; o publicador publica e revoga.
          Políticas, modelos e templates novos ainda são montados no GovDocs.
        </Alert>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <KpiCard label="Cláusulas no catálogo" value={String(centro.resumo.clausulas)} />
        <KpiCard label="Publicadas (vigentes)" value={String(centro.resumo.publicadas)} />
        <KpiCard label="Em elaboração ou revisão" value={String(centro.resumo.em_elaboracao)} />
      </div>
      <nav aria-label="Módulos do Centro" className="gc-tabs">
        {ativas.map((a) => (
          <Link
            key={a.tipo}
            href={`/app/governanca?aba=${a.tipo}`}
            className="gc-tab"
            aria-current={a.tipo === aba ? "page" : undefined}
          >
            {a.rotulo}
          </Link>
        ))}
      </nav>
      {centro.escrita && aba === "clausula" && ["proprietario", "admin_global", "admin_municipal"].includes(centro.papel) && (
        <NovaClausula />
      )}
      {aba ? (
        <ArtefatosDaGovernanca tipo={aba} artefatos={artefatos} escrever={centro.escrita && centro.papel !== "auditor"} />
      ) : (
        <p className="text-secundario">Nenhum módulo do Centro está ligado.</p>
      )}
    </div>
  );
}
