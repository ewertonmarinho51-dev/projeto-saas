import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TabelaSigtap } from "@/components/tabela-sigtap";
import { Alert, Button, Card, EmptyState, Field, Input, PageHead, Select } from "@/design-system";
import { chamarApi, ErroDaApi, precosHabilitado, type ConsultaSigtap } from "@/lib/api";

export const metadata: Metadata = { title: "Remuneração SUS (SIGTAP)" };

const MODALIDADES = [
  { value: "", label: "Todas" },
  { value: "Ambulatorial", label: "Ambulatorial" },
  { value: "Hospitalar", label: "Hospitalar" },
  { value: "Hospital Dia", label: "Hospital Dia" },
  { value: "Atenção Domiciliar", label: "Atenção Domiciliar" },
];

function texto(v: string | string[] | undefined, max: number): string {
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

/**
 * Consulta PRÓPRIA do SIGTAP: o valor que o SUS remunera por procedimento,
 * fora da cesta de compras. A tela só monta a busca e mostra o que a API
 * devolveu; valores, natureza e fundamento vêm de lá.
 */
export default async function RemuneracaoSus({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const p = await searchParams;
  // o código aceita a forma com pontos e hífen (04.11.01.003-4)
  const digitos = texto(p.codigo, 20).replace(/\D/g, "");
  const filtros = {
    termo: texto(p.termo, 300),
    codigo: /^\d{10}$/.test(digitos) ? digitos : "",
    codigoDigitado: texto(p.codigo, 20),
    modalidade: MODALIDADES.some((m) => m.value === p.modalidade) ? String(p.modalidade ?? "") : "",
  };
  const pesquisou = Boolean(filtros.termo || filtros.codigoDigitado);

  let dados: ConsultaSigtap | null = null;
  let aviso: string | null = null;
  if (pesquisou && filtros.codigoDigitado && !filtros.codigo) {
    aviso = "O código do procedimento tem 10 dígitos (ex.: 04.11.01.003-4).";
  } else if (pesquisou) {
    const consulta = new URLSearchParams({ limite: "50" });
    if (filtros.termo) consulta.set("termo", filtros.termo);
    if (filtros.codigo) consulta.set("codigo", filtros.codigo);
    if (filtros.modalidade) consulta.set("modalidade", filtros.modalidade);
    try {
      dados = (await chamarApi<ConsultaSigtap>(`/precos/referencias/sigtap?${consulta}`)).dados;
    } catch (e) {
      if (e instanceof ErroDaApi && e.codigo === "MODULE_UNAVAILABLE") {
        aviso = "A consulta ao SIGTAP está desligada neste ambiente.";
      } else if (e instanceof ErroDaApi && e.status === 503) {
        aviso = "A consulta ao SIGTAP não respondeu agora. Tente de novo em instantes.";
      } else if (e instanceof ErroDaApi && e.status === 422) {
        aviso = "Confira o código (10 dígitos) e o texto da busca.";
      } else {
        throw e;
      }
    }
  }

  const competencia = dados?.procedimentos[0]?.competencia_exibicao;

  return (
    <>
      <PageHead
        eyebrow={
          <Button variant="link" size="sm" icon="arrow-left" href="/app/precos">
            Pesquisas de preços
          </Button>
        }
        title="Remuneração SUS (SIGTAP)"
        desc="Valores da Tabela Unificada de Procedimentos do SUS (DATASUS), por competência. É o que o SUS remunera ao prestador, não preço de compra: não entra na cesta da pesquisa."
      />

      <Card divided title="Consultar o SIGTAP">
        <form method="get" className="grid gap-4 md:grid-cols-[3fr_1fr_1fr_auto]" data-testid="busca-sigtap">
          <Field label="Procedimento" htmlFor="sigtap-termo" optional>
            <Input id="sigtap-termo" name="termo" defaultValue={filtros.termo} maxLength={300} />
          </Field>
          <Field label="Código" htmlFor="sigtap-codigo" optional help="10 dígitos">
            <Input
              id="sigtap-codigo"
              name="codigo"
              defaultValue={filtros.codigoDigitado}
              inputMode="numeric"
              maxLength={20}
            />
          </Field>
          <Field label="Modalidade" htmlFor="sigtap-modalidade">
            <Select id="sigtap-modalidade" name="modalidade" options={MODALIDADES} defaultValue={filtros.modalidade} />
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
          {dados.procedimentos.length > 0 ? (
            <Card
              flush
              title={`Competência ${competencia}`}
              subtitle={`${dados.procedimentos.length} procedimento(s). Remuneração do SUS, não preço de mercado.`}
            >
              <TabelaSigtap procedimentos={dados.procedimentos} />
            </Card>
          ) : (
            <Card>
              <EmptyState
                icon="magnifying-glass"
                title="Nenhum procedimento do SIGTAP para esta busca."
                description="Tente outro termo, o código de 10 dígitos ou outra modalidade. Só as competências já importadas respondem."
              />
            </Card>
          )}
          <Alert variant="info" title="Fundamento">
            {dados.fundamento}{" "}
            <a href={dados.pagina_oficial} rel="noopener noreferrer">
              Página oficial do SIGTAP
            </a>
          </Alert>
        </>
      )}
    </>
  );
}
