import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TabelaSicro } from "@/components/tabela-sicro";
import { Alert, Button, Card, EmptyState, Field, Input, PageHead, Select } from "@/design-system";
import { chamarApi, ErroDaApi, precosHabilitado, type ConsultaSicro } from "@/lib/api";

export const metadata: Metadata = { title: "Custos de transportes (SICRO)" };

const UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
  "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"];
const REGIMES = [
  { value: "sem_desoneracao", label: "Encargos sem desoneração" },
  { value: "com_desoneracao", label: "Encargos com desoneração" },
];
const TIPOS = [
  { value: "", label: "Todos" },
  { value: "composicao", label: "Composições" },
  { value: "material", label: "Materiais" },
  { value: "mao_de_obra", label: "Mão de obra" },
  { value: "equipamento", label: "Equipamentos" },
];

function texto(v: string | string[] | undefined, max: number): string {
  return typeof v === "string" ? v.trim().slice(0, max) : "";
}

/**
 * Consulta PRÓPRIA do SICRO: custo referencial de obras de infraestrutura de
 * transportes, fora da cesta de compras. A tela só monta a busca e mostra o
 * que a API devolveu; o valor, a natureza e o fundamento vêm de lá.
 */
export default async function CustosSicro({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const p = await searchParams;
  const codigo = texto(p.codigo, 7).toUpperCase();
  const filtros = {
    termo: texto(p.termo, 300),
    codigo: /^(\d{7}|[MPEA]\d{4})$/.test(codigo) ? codigo : "",
    codigoDigitado: codigo,
    uf: UFS.includes(texto(p.uf, 2).toUpperCase()) ? texto(p.uf, 2).toUpperCase() : "PA",
    regime: REGIMES.some((r) => r.value === p.regime) ? String(p.regime) : "sem_desoneracao",
    tipo: TIPOS.some((t) => t.value === p.tipo) ? String(p.tipo ?? "") : "",
  };
  const pesquisou = Boolean(filtros.termo || filtros.codigoDigitado);

  let dados: ConsultaSicro | null = null;
  let aviso: string | null = null;
  if (pesquisou && filtros.codigoDigitado && !filtros.codigo) {
    aviso = "O código do SICRO tem 7 dígitos (composição) ou uma letra e 4 dígitos (insumo, ex.: M0004).";
  } else if (pesquisou) {
    const consulta = new URLSearchParams({ uf: filtros.uf, regime: filtros.regime, limite: "50" });
    if (filtros.termo) consulta.set("termo", filtros.termo);
    if (filtros.codigo) consulta.set("codigo", filtros.codigo);
    if (filtros.tipo) consulta.set("tipo", filtros.tipo);
    try {
      dados = (await chamarApi<ConsultaSicro>(`/precos/referencias/sicro?${consulta}`)).dados;
    } catch (e) {
      if (e instanceof ErroDaApi && e.codigo === "MODULE_UNAVAILABLE") {
        aviso = "A consulta ao SICRO está desligada neste ambiente.";
      } else if (e instanceof ErroDaApi && e.status === 503) {
        aviso = "A consulta ao SICRO não respondeu agora. Tente de novo em instantes.";
      } else if (e instanceof ErroDaApi && e.status === 422) {
        aviso = "Confira o código e o texto da busca.";
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
        title="Custos de transportes (SICRO)"
        desc="Custo de composição, material, mão de obra e equipamento do DNIT, por UF e trimestre. É custo referencial de obra de infraestrutura de transportes, não preço de compra: não entra na cesta da pesquisa."
      />

      <Card divided title="Consultar o SICRO">
        <form method="get" className="grid gap-4 md:grid-cols-[3fr_1fr_1fr]" data-testid="busca-sicro">
          <Field label="Descrição" htmlFor="sicro-termo" optional>
            <Input id="sicro-termo" name="termo" defaultValue={filtros.termo} maxLength={300} />
          </Field>
          <Field label="Código" htmlFor="sicro-codigo" optional help="Ex.: 1106050 ou M0004">
            <Input id="sicro-codigo" name="codigo" defaultValue={filtros.codigoDigitado} maxLength={7} />
          </Field>
          <Field label="UF" htmlFor="sicro-uf">
            <Select id="sicro-uf" name="uf" options={UFS} defaultValue={filtros.uf} />
          </Field>
          <Field label="Encargos sociais" htmlFor="sicro-regime">
            <Select id="sicro-regime" name="regime" options={REGIMES} defaultValue={filtros.regime} />
          </Field>
          <Field label="Tipo" htmlFor="sicro-tipo">
            <Select id="sicro-tipo" name="tipo" options={TIPOS} defaultValue={filtros.tipo} />
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
              <TabelaSicro referencias={dados.referencias} />
            </Card>
          ) : (
            <Card>
              <EmptyState
                icon="magnifying-glass"
                title="Nenhuma referência do SICRO para esta busca."
                description="Tente outro termo, o código, outro tipo ou outra UF. Só as UFs já importadas respondem (o piloto é o Pará). Composição só existe sem desoneração."
              />
            </Card>
          )}
          <Alert variant="info" title="Fundamento">
            {dados.fundamento}{" "}
            <a href={dados.pagina_oficial} rel="noopener noreferrer">
              Relatórios oficiais do SICRO
            </a>
          </Alert>
        </>
      )}
    </>
  );
}
