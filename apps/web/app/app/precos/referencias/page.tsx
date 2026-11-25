import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TabelaSinapi } from "@/components/tabela-sinapi";
import { Alert, Button, Card, EmptyState, Field, Input, PageHead, Select } from "@/design-system";
import { chamarApi, ErroDaApi, precosHabilitado, type ConsultaDeCustos } from "@/lib/api";

export const metadata: Metadata = { title: "Custos de engenharia (SINAPI)" };

const UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
  "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"];
const REGIMES = [
  { value: "sem_desoneracao", label: "Encargos sem desoneração" },
  { value: "com_desoneracao", label: "Encargos com desoneração" },
  { value: "sem_encargos", label: "Sem encargos sociais" },
];
const TIPOS = [
  { value: "", label: "Insumos e composições" },
  { value: "insumo", label: "Só insumos" },
  { value: "composicao", label: "Só composições" },
];

function texto(v: string | string[] | undefined, max: number): string {
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

/**
 * Consulta PRÓPRIA do SINAPI: custo referencial de engenharia, fora da
 * cesta de compras. A tela só monta a busca e mostra o que a API devolveu;
 * o valor, a natureza e o fundamento vêm de lá.
 */
export default async function ReferenciasDeCusto({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const p = await searchParams;
  const filtros = {
    termo: texto(p.termo, 300),
    codigo: /^\d{1,9}$/.test(texto(p.codigo, 9)) ? texto(p.codigo, 9) : "",
    uf: UFS.includes(texto(p.uf, 2).toUpperCase()) ? texto(p.uf, 2).toUpperCase() : "PA",
    regime: REGIMES.some((r) => r.value === p.regime) ? String(p.regime) : "sem_desoneracao",
    tipo: TIPOS.some((t) => t.value === p.tipo) ? String(p.tipo ?? "") : "",
  };
  const pesquisou = Boolean(filtros.termo || filtros.codigo);

  let dados: ConsultaDeCustos | null = null;
  let aviso: string | null = null;
  if (pesquisou) {
    const consulta = new URLSearchParams({ uf: filtros.uf, regime: filtros.regime, limite: "50" });
    if (filtros.termo) consulta.set("termo", filtros.termo);
    if (filtros.codigo) consulta.set("codigo", filtros.codigo);
    if (filtros.tipo) consulta.set("tipo", filtros.tipo);
    try {
      dados = (await chamarApi<ConsultaDeCustos>(`/precos/referencias/sinapi?${consulta}`)).dados;
    } catch (e) {
      if (e instanceof ErroDaApi && e.codigo === "MODULE_UNAVAILABLE") {
        aviso = "A consulta ao SINAPI está desligada neste ambiente.";
      } else if (e instanceof ErroDaApi && e.status === 503) {
        aviso = "A consulta ao SINAPI não respondeu agora. Tente de novo em instantes.";
      } else if (e instanceof ErroDaApi && e.status === 422) {
        aviso = "Confira o código (só dígitos) e o texto da busca.";
      } else {
        throw e;
      }
    }
  }

  return (
    <>
      <PageHead
        eyebrow={
          <Button variant="link" size="sm" icon="arrow-left" href="/app/precos">
            Pesquisas de preços
          </Button>
        }
        title="Custos de engenharia (SINAPI)"
        desc="Preço de insumo e custo de composição da CAIXA/IBGE, por UF e mês de referência. É custo referencial de obra e serviço de engenharia, não preço de compra: não entra na cesta da pesquisa."
        actions={
          <Button variant="secondary" icon="book-open" href="/app/precos/referencias/seop">
            Planilha da SEOP-PA
          </Button>
        }
      />

      <Card divided title="Consultar o SINAPI">
        <form method="get" className="grid gap-4 md:grid-cols-[3fr_1fr_1fr]" data-testid="busca-sinapi">
          <Field label="Descrição" htmlFor="sinapi-termo" optional>
            <Input id="sinapi-termo" name="termo" defaultValue={filtros.termo} maxLength={300} />
          </Field>
          <Field label="Código" htmlFor="sinapi-codigo" optional help="Insumo ou composição">
            <Input id="sinapi-codigo" name="codigo" defaultValue={filtros.codigo} inputMode="numeric" maxLength={9} />
          </Field>
          <Field label="UF" htmlFor="sinapi-uf">
            <Select id="sinapi-uf" name="uf" options={UFS} defaultValue={filtros.uf} />
          </Field>
          <Field label="Encargos sociais" htmlFor="sinapi-regime">
            <Select id="sinapi-regime" name="regime" options={REGIMES} defaultValue={filtros.regime} />
          </Field>
          <Field label="Tipo" htmlFor="sinapi-tipo">
            <Select id="sinapi-tipo" name="tipo" options={TIPOS} defaultValue={filtros.tipo} />
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
              title={`Mês de referência ${dados.competencia?.slice(5)}/${dados.competencia?.slice(0, 4)} · ${filtros.uf}`}
              subtitle={`${dados.referencias.length} referência(s). Valores sem BDI.`}
            >
              <TabelaSinapi referencias={dados.referencias} />
            </Card>
          ) : (
            <Card>
              <EmptyState
                icon="magnifying-glass"
                title="Nenhuma referência do SINAPI para esta busca."
                description="Tente outro termo, o código do insumo ou da composição, ou outra UF. Só as UFs já importadas respondem (o piloto é o Pará)."
              />
            </Card>
          )}
          <Alert variant="info" title="Fundamento">
            {dados.fundamento}{" "}
            <a href={dados.pagina_oficial} rel="noopener noreferrer">
              Página oficial do SINAPI
            </a>
          </Alert>
        </>
      )}
    </>
  );
}
