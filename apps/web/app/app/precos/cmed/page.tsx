import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TabelaCmed } from "@/components/tabela-cmed";
import { Alert, Button, Card, EmptyState, Field, Input, PageHead, Select } from "@/design-system";
import { chamarApi, ErroDaApi, precosHabilitado, type ConsultaCmed } from "@/lib/api";

export const metadata: Metadata = { title: "Teto de medicamentos (CMED)" };

const ALIQUOTAS = [
  ["0", "ICMS 0% (isento)"],
  ["12", "ICMS 12%"],
  ["12_alc", "ICMS 12% (ALC)"],
  ["17", "ICMS 17%"],
  ["17_alc", "ICMS 17% (ALC)"],
  ["17.5", "ICMS 17,5%"],
  ["17.5_alc", "ICMS 17,5% (ALC)"],
  ["18", "ICMS 18%"],
  ["18_alc", "ICMS 18% (ALC)"],
  ["19", "ICMS 19%"],
  ["19_alc", "ICMS 19% (ALC)"],
  ["19.5", "ICMS 19,5%"],
  ["19.5_alc", "ICMS 19,5% (ALC)"],
  ["20", "ICMS 20%"],
  ["20_alc", "ICMS 20% (ALC)"],
  ["20.5", "ICMS 20,5%"],
  ["20.5_alc", "ICMS 20,5% (ALC)"],
  ["21", "ICMS 21%"],
  ["21_alc", "ICMS 21% (ALC)"],
  ["22", "ICMS 22%"],
  ["22_alc", "ICMS 22% (ALC)"],
  ["22.5", "ICMS 22,5%"],
  ["22.5_alc", "ICMS 22,5% (ALC)"],
  ["23", "ICMS 23%"],
  ["23_alc", "ICMS 23% (ALC)"],
  ["sem_impostos", "Sem impostos"],
].map(([value, label]) => ({ value, label }));

function texto(v: string | string[] | undefined, max: number): string {
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

/**
 * Consulta PRÓPRIA da CMED: o preço máximo regulado de cada apresentação de
 * medicamento, fora da cesta de compras. A tela só monta a busca e mostra o
 * que a API devolveu; a regra do teto, a natureza e o fundamento vêm de lá.
 */
export default async function TetoCmedPagina({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const p = await searchParams;
  const digitado = texto(p.codigo, 20);
  const digitos = digitado.replace(/\D/g, "");
  const filtros = {
    termo: texto(p.termo, 300),
    codigo: /^\d{8,15}$/.test(digitos) ? digitos : "",
    codigoDigitado: digitado,
    aliquota: ALIQUOTAS.some((a) => a.value === p.aliquota) ? String(p.aliquota) : "18",
  };
  const pesquisou = Boolean(filtros.termo || filtros.codigoDigitado);

  let dados: ConsultaCmed | null = null;
  let aviso: string | null = null;
  if (pesquisou && filtros.codigoDigitado && !filtros.codigo) {
    aviso = "O código é o GGREM (15 dígitos), o registro (13) ou o EAN da embalagem (8 a 14).";
  } else if (pesquisou) {
    const consulta = new URLSearchParams({ aliquota: filtros.aliquota, limite: "50" });
    if (filtros.termo) consulta.set("termo", filtros.termo);
    if (filtros.codigo) consulta.set("codigo", filtros.codigo);
    try {
      dados = (await chamarApi<ConsultaCmed>(`/precos/referencias/cmed?${consulta}`)).dados;
    } catch (e) {
      if (e instanceof ErroDaApi && e.codigo === "MODULE_UNAVAILABLE") {
        aviso = "A consulta à CMED está desligada neste ambiente.";
      } else if (e instanceof ErroDaApi && e.status === 503) {
        aviso = "A consulta à CMED não respondeu agora. Tente de novo em instantes.";
      } else if (e instanceof ErroDaApi && e.status === 422) {
        aviso = "Confira o código e o texto da busca.";
      } else {
        throw e;
      }
    }
  }

  const lista = dados?.publicada_em?.slice(0, 10).split("-").reverse().join("/");
  const rotulo = ALIQUOTAS.find((a) => a.value === filtros.aliquota)?.label;

  return (
    <>
      <PageHead
        eyebrow={
          <Button variant="link" size="sm" icon="arrow-left" href="/app/precos">
            Pesquisas de preços
          </Button>
        }
        title="Teto de medicamentos (CMED)"
        desc="Preço Fábrica (PF) e Preço Máximo de Venda ao Governo (PMVG) de cada apresentação, pela lista vigente da CMED. É o preço máximo regulado, não preço de compra: não entra na cesta da pesquisa."
      />

      <Card divided title="Consultar a CMED">
        <form method="get" className="grid gap-4 md:grid-cols-[3fr_1fr_1fr_auto]" data-testid="busca-cmed">
          <Field label="Medicamento" htmlFor="cmed-termo" optional help="Substância, produto, apresentação ou laboratório">
            <Input id="cmed-termo" name="termo" defaultValue={filtros.termo} maxLength={300} />
          </Field>
          <Field label="Código" htmlFor="cmed-codigo" optional help="GGREM, registro ou EAN">
            <Input id="cmed-codigo" name="codigo" defaultValue={filtros.codigoDigitado} inputMode="numeric" maxLength={20} />
          </Field>
          <Field label="Alíquota de ICMS" htmlFor="cmed-aliquota" help="A do estado de destino">
            <Select id="cmed-aliquota" name="aliquota" options={ALIQUOTAS} defaultValue={filtros.aliquota} />
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
          {dados.tetos.length > 0 ? (
            <Card
              flush
              title={`Lista CMED de ${lista} · ${rotulo}`}
              subtitle={`${dados.tetos.length} apresentação(ões). Com CAP, o teto ao governo é o PMVG; sem CAP, o PF.`}
            >
              <TabelaCmed tetos={dados.tetos} />
            </Card>
          ) : (
            <Card>
              <EmptyState
                icon="magnifying-glass"
                title="Nenhuma apresentação da CMED para esta busca."
                description="Tente a substância, o nome comercial ou o código de barras (EAN) da embalagem."
              />
            </Card>
          )}
          <Alert variant="info" title="Fundamento">
            {dados.fundamento}{" "}
            <a href={dados.pagina_oficial} rel="noopener noreferrer">
              Página oficial de preços da CMED
            </a>
          </Alert>
        </>
      )}
    </>
  );
}
