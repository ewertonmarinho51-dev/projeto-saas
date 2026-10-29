import Link from "next/link";

import { cabecalho, metadados, RODAPE } from "@/components/site";
import { buttonClasses, PublicFeature, PublicGrid, PublicPage, PublicSection } from "@/design-system";

export const metadata = metadados("/solucoes");

export default function Solucoes() {
  return (
    <PublicPage
      header={cabecalho("/solucoes")}
      footer={RODAPE}
      eyebrow="Soluções"
      title="Uma plataforma para a fase preparatória da contratação"
      lead="Da demanda ao Termo de Referência, com documentos redigidos a partir dos dados do processo, preços de fonte pública e a decisão sempre com um servidor."
      actions={
        <>
          <Link className={buttonClasses({ size: "lg" })} href="/contato">
            Fale com a equipe
          </Link>
          <Link className={buttonClasses({ variant: "secondary", size: "lg" })} href="/como-funciona">
            Como funciona
          </Link>
        </>
      }
    >
      <PublicSection eyebrow="Módulos" title="O que a plataforma faz">
        <PublicGrid columns={2}>
          <PublicFeature icon="file-text" title="Documentos com IA" href="/solucoes/documentos-ia" linkLabel="Conhecer os documentos">
            DFD, ETP, Mapa de Riscos e Termo de Referência redigidos a partir do que o processo já registrou,
            com a fundamentação na Lei nº 14.133/2021 e aprovação de um servidor.
          </PublicFeature>
          <PublicFeature
            icon="currency-circle-dollar"
            title="Pesquisa de preços"
            href="/solucoes/pesquisa-de-precos"
            linkLabel="Conhecer a pesquisa"
          >
            Coleta em bases públicas, triagem das referências, cesta justificada e relatório com a origem de cada
            valor — os cálculos são feitos no servidor, não na tela.
          </PublicFeature>
        </PublicGrid>
      </PublicSection>

      <PublicSection muted eyebrow="Para o órgão" title="O que acompanha cada módulo">
        <PublicGrid>
          <PublicFeature icon="folder-open" title="Processos">
            Cada contratação é um processo, com situação, demandas das secretarias consolidadas e os documentos
            de cada etapa.
          </PublicFeature>
          <PublicFeature icon="books" title="Base de conhecimento">
            O administrador do órgão envia normas, decretos e modelos próprios, que passam a orientar a redação.
          </PublicFeature>
          <PublicFeature icon="shield-check" title="Governança">
            Cláusulas padronizadas com autoria, revisão jurídica e publicação separadas, e histórico de versões.
          </PublicFeature>
          <PublicFeature icon="users-three" title="Usuários e papéis">
            Contas criadas pelo administrador, vinculadas ao órgão e à secretaria, com papel de usuário ou
            administrador.
          </PublicFeature>
          <PublicFeature icon="buildings" title="Isolamento entre órgãos">
            Regras de acesso aplicadas no banco de dados: um município não alcança os dados de outro.
          </PublicFeature>
          <PublicFeature icon="clipboard-text" title="Registro das decisões">
            Aprovações, exclusões de referência e ciências ficam registradas com autor e data.
          </PublicFeature>
        </PublicGrid>
      </PublicSection>
    </PublicPage>
  );
}
