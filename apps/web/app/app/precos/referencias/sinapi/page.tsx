import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CustosSinapi } from "@/components/custos-sinapi";
import { Alert, Button, Card, EmptyState, Field, Input, PageHead, Select } from "@/design-system";
import { chamarApi, ErroDaApi, precosHabilitado, type ConsultaSinapi } from "@/lib/api";

export const metadata: Metadata = { title: "Custos de engenharia (SINAPI)" };

const TIPOS = [
  { value: "", label: "Insumos e composições" },
  { value: "insumo", label: "Insumos" },
  { value: "composicao", label: "Composições" },
];
const REGIMES = [
  { value: "sem_desoneracao", label: "Sem desoneração" },
  { value: "com_desoneracao", label: "Com desoneração" },
  { value: "sem_encargos", label: "Sem encargos sociais" },
];
const COMPETENCIA = /^\d{4}-(0[1-9]|1[0-2])$/;

function texto(valor: string | string[] | undefined, max: number): string {
  return (typeof valor === "string" ? valor : "").trim().slice(0, max);
}

/**
 * Consulta própria do SINAPI: custo de referência de obra e serviço de
 * engenharia (Lei 14.133, art. 23, § 2º, I). Fica fora da pesquisa de preços
 * de compras de propósito — nada daqui entra na cesta. Formulário GET: a
 * consulta é a URL, e funciona sem JavaScript.
 */
export default async function ConsultaSinapiPagina({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const params = await searchParams;
  const termo = texto(params.termo, 200);
  const codigo = texto(params.codigo, 12).replace(/\D/g, "");
  const tipo = TIPOS.some((t) => t.value === params.tipo) ? String(params.tipo ?? "") : "";
  const regime = REGIMES.some((r) => r.value === params.regime) ? String(params.regime) : "sem_desoneracao";
  const competencia = COMPETENCIA.test(texto(params.competencia, 7)) ? texto(params.competencia, 7) : "";
  const pediu = Boolean(termo || codigo);

  let dados: ConsultaSinapi | null = null;
  let fechada = false;
  let erro: string | null = null;
  if (pediu) {
    const consulta = new URLSearchParams({ uf: "PA", regime, limite: "50" });
    if (termo) consulta.set("termo", termo);
    if (codigo) consulta.set("codigo", codigo);
    if (tipo) consulta.set("tipo", tipo);
    if (competencia) consulta.set("competencia", competencia);
    try {
      dados = (await chamarApi<ConsultaSinapi>(`/precos/referencias/sinapi?${consulta}`)).dados;
    } catch (e) {
      if (e instanceof ErroDaApi && e.status === 404) fechada = true;
      else if (e instanceof ErroDaApi && e.status === 422) erro = e.mensagem || "Confira os filtros da consulta.";
      else erro = "O índice do SINAPI não respondeu agora. Tente de novo em instantes.";
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
        desc="Custo de referência de obras e serviços de engenharia publicado pela CAIXA, no Pará. Não é preço de compra e não entra na cesta da pesquisa de preços."
      />

      <Card>
        <form method="get" className="grid gap-4 md:grid-cols-[2fr_1fr_1fr_1fr]" data-testid="consulta-sinapi">
          <Field label="Descrição" htmlFor="sinapi-termo" help="Palavras do insumo ou da composição">
            <Input id="sinapi-termo" name="termo" defaultValue={termo} maxLength={200} />
          </Field>
          <Field label="Código" htmlFor="sinapi-codigo" optional>
            <Input id="sinapi-codigo" name="codigo" defaultValue={codigo} maxLength={12} inputMode="numeric" />
          </Field>
          <Field label="Tipo" htmlFor="sinapi-tipo">
            <Select id="sinapi-tipo" name="tipo" options={TIPOS} defaultValue={tipo} />
          </Field>
          <Field label="Regime" htmlFor="sinapi-regime">
            <Select id="sinapi-regime" name="regime" options={REGIMES} defaultValue={regime} />
          </Field>
          <Field label="Competência" htmlFor="sinapi-competencia" optional help="AAAA-MM; vazio = a mais recente">
            <Input id="sinapi-competencia" name="competencia" defaultValue={competencia} maxLength={7} placeholder="2026-10" />
          </Field>
          <div className="flex items-end md:col-span-3">
            <Button type="submit" icon="magnifying-glass">
              Consultar
            </Button>
          </div>
        </form>
      </Card>

      {fechada && (
        <Alert variant="neutral" title="Consulta ao SINAPI ainda não habilitada">
          A importação e a consulta estão prontas, mas a liberação depende da decisão sobre o uso da publicação da CAIXA.
        </Alert>
      )}
      {erro && <Alert variant="error">{erro}</Alert>}
      {dados && <Alert variant="info">{dados.aviso}</Alert>}
      {dados &&
        (dados.itens.length > 0 ? (
          <Card flush>
            <CustosSinapi itens={dados.itens} />
          </Card>
        ) : (
          <EmptyState
            icon="magnifying-glass"
            title="Nada encontrado nesta competência."
            description="Tente outras palavras, o código do insumo ou da composição, ou outro regime."
          />
        ))}
    </>
  );
}
