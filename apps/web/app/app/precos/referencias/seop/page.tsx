import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TabelaSeop } from "@/components/tabela-seop";
import { Alert, Button, Card, EmptyState, Field, Input, PageHead } from "@/design-system";
import { chamarApi, ErroDaApi, precosHabilitado, type ConsultaSeop } from "@/lib/api";

export const metadata: Metadata = { title: "Custos de engenharia (SEOP-PA)" };

function texto(v: string | string[] | undefined, max: number): string {
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

/**
 * Consulta PRÓPRIA da Planilha Padrão da SEOP-PA: custo de referência de
 * engenharia do Estado do Pará, fora da cesta de compras. Só aparece o que
 * uma pessoa conferiu e aprovou na importação do PDF. A tela só monta a
 * busca e mostra o que a API devolveu.
 */
export default async function ReferenciasSeop({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const p = await searchParams;
  const termo = texto(p.termo, 300);
  const codigo = /^\d{6}$/.test(texto(p.codigo, 6)) ? texto(p.codigo, 6) : "";

  let dados: ConsultaSeop | null = null;
  let aviso: string | null = null;
  if (termo || codigo) {
    const consulta = new URLSearchParams({ limite: "50" });
    if (termo) consulta.set("termo", termo);
    if (codigo) consulta.set("codigo", codigo);
    try {
      dados = (await chamarApi<ConsultaSeop>(`/precos/referencias/seop?${consulta}`)).dados;
    } catch (e) {
      if (e instanceof ErroDaApi && e.codigo === "MODULE_UNAVAILABLE") {
        aviso = "A consulta à SEOP-PA está desligada neste ambiente.";
      } else if (e instanceof ErroDaApi && e.status === 503) {
        aviso = "A consulta à SEOP-PA não respondeu agora. Tente de novo em instantes.";
      } else if (e instanceof ErroDaApi && e.status === 422) {
        aviso = "Confira o código (6 dígitos) e o texto da busca.";
      } else {
        throw e;
      }
    }
  }

  return (
    <>
      <PageHead
        eyebrow={
          <Button variant="link" size="sm" icon="arrow-left" href="/app/precos/referencias">
            Custos de engenharia (SINAPI)
          </Button>
        }
        title="Custos de engenharia (SEOP-PA)"
        desc="Planilha Padrão da Secretaria de Estado de Obras Públicas do Pará. É custo referencial de obra e serviço de engenharia, não preço de compra: não entra na cesta da pesquisa."
      />

      <Card divided title="Consultar a Planilha Padrão">
        <form method="get" className="grid gap-4 md:grid-cols-[3fr_1fr_auto]" data-testid="busca-seop">
          <Field label="Descrição" htmlFor="seop-termo" optional>
            <Input id="seop-termo" name="termo" defaultValue={termo} maxLength={300} />
          </Field>
          <Field label="Código" htmlFor="seop-codigo" optional help="6 dígitos">
            <Input id="seop-codigo" name="codigo" defaultValue={codigo} inputMode="numeric" maxLength={6} />
          </Field>
          <div className="flex items-end">
            <Button type="submit" icon="magnifying-glass">
              Consultar
            </Button>
          </div>
        </form>
      </Card>

      {aviso && <Alert variant="warning">{aviso}</Alert>}

      {dados && (
        <>
          {dados.referencias.length > 0 ? (
            <Card
              flush
              title={`Planilha Padrão de ${dados.referencias[0].competencia_exibicao}`}
              subtitle={`${dados.referencias.length} referência(s). Valores sem BDI.`}
            >
              <TabelaSeop referencias={dados.referencias} />
            </Card>
          ) : (
            <Card>
              <EmptyState
                icon="magnifying-glass"
                title="Nenhuma referência da SEOP-PA para esta busca."
                description="Tente outro termo ou o código de 6 dígitos. Só aparece a planilha já conferida e aprovada."
              />
            </Card>
          )}
          <Alert variant="info" title="Fundamento">
            {dados.fundamento}{" "}
            <a href={dados.pagina_oficial} rel="noopener noreferrer">
              Página oficial da SEOP-PA
            </a>
          </Alert>
        </>
      )}
    </>
  );
}
