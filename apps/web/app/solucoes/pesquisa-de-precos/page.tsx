import Link from "next/link";

import { cabecalho, metadados, RODAPE } from "@/components/site";
import { buttonClasses, PublicFeature, PublicGrid, PublicPage, PublicSection, PublicSteps } from "@/design-system";

export const metadata = metadados("/solucoes/pesquisa-de-precos");

const ETAPAS = [
  { tag: "Itens", title: "Itens da pesquisa", text: "Itens digitados ou importados de planilha, com unidade e quantidade." },
  { tag: "Coleta", title: "Coleta nas bases públicas", text: "Busca nos dados abertos do Compras.gov.br e no PNCP, em segundo plano." },
  { tag: "Triagem", title: "Triagem das referências", text: "Conferência de unidade, data e descrição; o que fica fora tem motivo registrado." },
  { tag: "Cesta", title: "Cesta e estatísticas", text: "Média, mediana e dispersão da cesta, calculadas no servidor." },
  { tag: "Relatório", title: "Relatório da pesquisa", text: "Documento com a origem e o link de cada valor usado." },
];

export default function PesquisaDePrecos() {
  return (
    <PublicPage
      header={cabecalho("/solucoes/pesquisa-de-precos")}
      footer={RODAPE}
      parent={{ label: "Soluções", href: "/solucoes" }}
      eyebrow="Pesquisa de preços"
      title="Pesquisa de preços em que cada valor mostra de onde veio"
      lead="Referências coletadas em bases públicas, triadas com critério registrado e reunidas numa cesta que o servidor justifica — com relatório pronto para o processo, na linha do art. 23 da Lei nº 14.133/2021."
      actions={
        <Link className={buttonClasses({ size: "lg" })} href="/contato">
          Fale com a equipe
        </Link>
      }
    >
      <PublicSection eyebrow="Fluxo" title="Da lista de itens ao relatório">
        <PublicSteps steps={ETAPAS} />
      </PublicSection>

      <PublicSection muted eyebrow="Rastreabilidade" title="Evidência ao lado de cada número">
        <PublicGrid>
          <PublicFeature icon="magnifying-glass" title="Origem registrada" wide>
            Cada referência guarda a fonte, o órgão comprador, a data, a descrição original e o link do registro na
            base pública. O relatório imprime esse link, para quem conferir depois.
          </PublicFeature>
          <PublicFeature icon="funnel" title="Triagem com motivo">
            Referência retirada da cesta exige motivo, e a retirada fica no histórico do item.
          </PublicFeature>
          <PublicFeature icon="warning-circle" title="Alertas de discrepância">
            Unidade suspeita, valor muito distante da mediana e dispersão alta aparecem antes da emissão.
          </PublicFeature>
          <PublicFeature icon="database" title="Cálculo no servidor">
            Média, mediana e coeficiente de variação são calculados no servidor, com aritmética decimal — a tela só
            mostra o resultado.
          </PublicFeature>
          <PublicFeature icon="file-pdf" title="Relatório para o processo">
            O relatório reúne itens, cestas, estatísticas e fontes, com a ciência do responsável antes da emissão.
          </PublicFeature>
        </PublicGrid>
      </PublicSection>
    </PublicPage>
  );
}
