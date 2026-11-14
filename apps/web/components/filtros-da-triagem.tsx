import { Accordion, Button, Field, Input, Select } from "@/design-system";
import type { AgregadosDeReferencias } from "@/lib/api";

import { type FiltrosDaTriagem, TAMANHOS, temFiltro } from "./triagem-url";

const ORDEM_ROTULO = [
  { value: "valor_asc", label: "Menor valor primeiro" },
  { value: "valor_desc", label: "Maior valor primeiro" },
  { value: "data_desc", label: "Mais recentes primeiro" },
];

/**
 * Filtros avançados da triagem, recolhíveis (pacote de 14/11/2026, RF-07).
 * Formulário GET: o filtro vai na URL e o SERVIDOR filtra antes de paginar;
 * nada é filtrado no navegador. As opções de fonte e UF vêm do que o item
 * tem (agregados), não de lista fixa. "Limpar" volta ao conjunto inteiro.
 */
export function FiltrosDaTriagem({
  base,
  filtros,
  agregados,
}: {
  base: string;
  filtros: FiltrosDaTriagem;
  agregados: AgregadosDeReferencias | null;
}) {
  const ativo = temFiltro(filtros);
  const id = (k: string) => `filtro-${k}`;
  const conteudo = (
    <form method="get" action={base} className="grid gap-4" data-testid="filtros-da-triagem">
      {filtros.situacao && <input type="hidden" name="situacao" value={filtros.situacao} />}
      {filtros.modo === "mapa" && <input type="hidden" name="modo" value="mapa" />}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <Field label="Descrição contém" htmlFor={id("q")}>
          <Input id={id("q")} name="q" defaultValue={filtros.q ?? ""} maxLength={120} autoComplete="off" />
        </Field>
        <Field label="Fonte" htmlFor={id("fonte")}>
          <Select
            id={id("fonte")}
            name="fonte"
            defaultValue={filtros.fonte ?? ""}
            options={[
              { value: "", label: "Todas" },
              ...(agregados?.fontes ?? []).map((f) => ({ value: f.id, label: `${f.nome} (${f.quantidade})` })),
            ]}
          />
        </Field>
        <Field label="UF do órgão comprador" htmlFor={id("uf")}>
          <Select
            id={id("uf")}
            name="uf"
            defaultValue={filtros.uf ?? ""}
            options={[
              { value: "", label: "Todas" },
              ...(agregados?.ufs ?? []).map((u) => ({ value: u.uf, label: `${u.uf} (${u.quantidade})` })),
            ]}
          />
        </Field>
        <Field label="Preço unitário mínimo" htmlFor={id("preco_min")} help={agregados?.preco_min ? `Menor coletado: ${agregados.preco_min.exibicao}` : undefined}>
          <Input id={id("preco_min")} name="preco_min" inputMode="decimal" prefix="R$" defaultValue={filtros.preco_min ?? ""} />
        </Field>
        <Field label="Preço unitário máximo" htmlFor={id("preco_max")} help={agregados?.preco_max ? `Maior coletado: ${agregados.preco_max.exibicao}` : undefined}>
          <Input id={id("preco_max")} name="preco_max" inputMode="decimal" prefix="R$" defaultValue={filtros.preco_max ?? ""} />
        </Field>
        <Field label="Contratação de" htmlFor={id("desde")}>
          <Input id={id("desde")} name="desde" type="date" defaultValue={filtros.desde ?? ""} />
        </Field>
        <Field label="Contratação até" htmlFor={id("ate")}>
          <Input id={id("ate")} name="ate" type="date" defaultValue={filtros.ate ?? ""} />
        </Field>
        <Field label="Ordenar por" htmlFor={id("ordem")}>
          <Select id={id("ordem")} name="ordem" defaultValue={filtros.ordem} options={ORDEM_ROTULO} />
        </Field>
        <Field label="Por página" htmlFor={id("por_pagina")}>
          <Select
            id={id("por_pagina")}
            name="por_pagina"
            defaultValue={String(filtros.por_pagina)}
            options={TAMANHOS.map((t) => ({ value: String(t), label: String(t) }))}
          />
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" icon="funnel">
          Aplicar filtros
        </Button>
        {ativo && (
          <Button variant="link" href={base}>
            Limpar filtros
          </Button>
        )}
      </div>
    </form>
  );
  return (
    <Accordion
      items={[
        {
          title: "Filtros avançados",
          meta: ativo ? "filtro ativo" : undefined,
          icon: "funnel",
          defaultOpen: ativo,
          content: conteudo,
        },
      ]}
    />
  );
}
