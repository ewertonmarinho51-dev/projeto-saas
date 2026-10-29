import Link from "next/link";

import { cabecalho, metadados, RODAPE } from "@/components/site";
import { buttonClasses, PublicFeature, PublicGrid, PublicPage, PublicSection, PublicSteps } from "@/design-system";

export const metadata = metadados("/como-funciona");

const FLUXO = [
  { tag: "1", title: "O órgão recebe o acesso", text: "O administrador cadastra as secretarias e cria as contas dos servidores." },
  { tag: "2", title: "A demanda vira processo", text: "A secretaria registra a necessidade; demandas parecidas podem ser consolidadas." },
  { tag: "3", title: "Os documentos são redigidos", text: "DFD, ETP, Mapa de Riscos e TR saem como rascunho a partir do processo." },
  { tag: "4", title: "Os preços são pesquisados", text: "A pesquisa coleta, tria e monta a cesta, com relatório e origem de cada valor." },
  { tag: "5", title: "O servidor revisa e aprova", text: "Cada documento é revisado e aprovado por quem responde pelo processo." },
];

export default function ComoFunciona() {
  return (
    <PublicPage
      header={cabecalho("/como-funciona")}
      footer={RODAPE}
      eyebrow="Como funciona"
      title="Do registro da demanda ao Termo de Referência"
      lead="O Gov Conect segue a ordem da fase preparatória. Cada etapa usa o que a anterior registrou, e cada decisão tem um responsável identificado."
      actions={
        <Link className={buttonClasses({ size: "lg" })} href="/solucoes">
          Ver as soluções
        </Link>
      }
    >
      <PublicSection eyebrow="Etapas" title="O caminho de uma contratação">
        <PublicSteps steps={FLUXO} />
      </PublicSection>

      <PublicSection muted eyebrow="Papéis" title="Quem faz o quê">
        <PublicGrid>
          <PublicFeature icon="gear-six" title="Administrador do órgão">
            Cadastra secretarias e usuários, mantém a base de conhecimento e acompanha o uso.
          </PublicFeature>
          <PublicFeature icon="users-three" title="Servidor da secretaria">
            Registra demandas, conduz o processo, revisa os documentos e a pesquisa de preços.
          </PublicFeature>
          <PublicFeature icon="scales" title="Revisão jurídica">
            Revisa e publica as cláusulas padronizadas usadas nos modelos, separada de quem as escreve.
          </PublicFeature>
        </PublicGrid>
      </PublicSection>

      <PublicSection eyebrow="Segurança" title="O que protege os dados do órgão" narrow>
        <p>
          <strong>Acesso por conta institucional.</strong> Não há cadastro aberto: as contas são criadas pelo
          administrador do órgão, e a sessão expira.
        </p>
        <p>
          <strong>Isolamento no banco de dados.</strong> As regras de acesso são aplicadas pelo próprio banco, por
          município e por secretaria. Uma tela com defeito não abre os dados de outro órgão.
        </p>
        <p>
          <strong>Permissão conferida no servidor.</strong> Toda operação é conferida de novo no servidor, com a
          identidade de quem a pediu — o que a tela esconde também é recusado por trás dela.
        </p>
      </PublicSection>
    </PublicPage>
  );
}
