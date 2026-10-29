import Link from "next/link";

import { cabecalho, metadados, RODAPE } from "@/components/site";
import { buttonClasses, PublicFeature, PublicGrid, PublicPage, PublicSection } from "@/design-system";

export const metadata = metadados("/sobre");

export default function Sobre() {
  return (
    <PublicPage
      header={cabecalho("/sobre")}
      footer={RODAPE}
      eyebrow="Sobre"
      title="Planejamento público com método, e com a responsabilidade onde ela está"
      lead="O Gov Conect nasceu da rotina de quem prepara contratações em prefeituras: documentos longos, prazos curtos e a obrigação de justificar cada número."
      actions={
        <Link className={buttonClasses({ size: "lg" })} href="/contato">
          Fale com a equipe
        </Link>
      }
    >
      <PublicSection eyebrow="Propósito" title="Por que a plataforma existe" narrow>
        <p>
          A Lei nº 14.133/2021 deu à fase preparatória o peso que ela merece: a contratação começa bem quando a
          demanda, o estudo, os riscos, o termo de referência e os preços estão coerentes entre si e bem
          fundamentados.
        </p>
        <p>
          O Gov Conect organiza esse trabalho na ordem da lei, aproveita o que cada etapa já registrou e usa
          inteligência artificial para o que ela faz bem — redigir e conferir — deixando a decisão com o servidor.
        </p>
      </PublicSection>

      <PublicSection muted eyebrow="Princípios" title="O que não negociamos">
        <PublicGrid>
          <PublicFeature icon="seal-check" title="Revisão humana">
            Nenhum documento segue para o processo sem a aprovação de um servidor identificado.
          </PublicFeature>
          <PublicFeature icon="magnifying-glass" title="Evidência em cada valor">
            Preço sem origem não entra na cesta; a origem acompanha o valor até o relatório.
          </PublicFeature>
          <PublicFeature icon="lock-simple" title="Dados do órgão são do órgão">
            Isolamento por município no banco de dados, e nenhum dado de um órgão alimenta a resposta de outro.
          </PublicFeature>
        </PublicGrid>
      </PublicSection>
    </PublicPage>
  );
}
