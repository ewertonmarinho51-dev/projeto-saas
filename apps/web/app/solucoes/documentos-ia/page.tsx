import Link from "next/link";

import { cabecalho, metadados, RODAPE } from "@/components/site";
import { buttonClasses, PublicFeature, PublicGrid, PublicPage, PublicSection, PublicSteps } from "@/design-system";

export const metadata = metadados("/solucoes/documentos-ia");

const DOCUMENTOS = [
  { tag: "DFD", title: "Documento de Formalização da Demanda", text: "Necessidade, quantidades estimadas, responsável e justificativa da demanda." },
  { tag: "ETP", title: "Estudo Técnico Preliminar", text: "Levantamento de soluções, requisitos, estimativa e viabilidade (art. 18)." },
  { tag: "Riscos", title: "Mapa de Riscos", text: "Riscos da contratação, probabilidade, impacto e medidas de tratamento." },
  { tag: "TR", title: "Termo de Referência", text: "Objeto, obrigações, modelo de execução e de gestão, critérios de medição e pagamento (art. 6º, XXIII)." },
];

export default function DocumentosIa() {
  return (
    <PublicPage
      header={cabecalho("/solucoes/documentos-ia")}
      footer={RODAPE}
      parent={{ label: "Soluções", href: "/solucoes" }}
      eyebrow="Documentos com IA"
      title="DFD, ETP e Termo de Referência redigidos a partir do processo"
      lead="A IA escreve o rascunho com o que a demanda, o estudo e a pesquisa de preços já registraram. O servidor revisa, ajusta e aprova — nada segue sem essa aprovação."
      actions={
        <Link className={buttonClasses({ size: "lg" })} href="/contato">
          Fale com a equipe
        </Link>
      }
    >
      <PublicSection eyebrow="Documentos" title="Os documentos da fase preparatória">
        <PublicSteps steps={DOCUMENTOS} />
      </PublicSection>

      <PublicSection muted eyebrow="Como a redação funciona" title="Rascunho com fundamento, decisão com o servidor">
        <PublicGrid>
          <PublicFeature icon="clipboard-text" title="Parte do que já foi registrado">
            Dados da demanda, quantidades e preços entram no texto sem redigitação, e o documento seguinte
            aproveita o anterior.
          </PublicFeature>
          <PublicFeature icon="scales" title="Fundamentação na Lei nº 14.133/2021">
            A redação cita os dispositivos aplicáveis, e a conferência aponta fundamento trocado ou ausente antes da
            revisão.
          </PublicFeature>
          <PublicFeature icon="books" title="Normas do próprio órgão">
            Decretos, portarias e modelos enviados pelo administrador à base de conhecimento orientam o texto.
          </PublicFeature>
          <PublicFeature icon="seal-check" title="Revisão e aprovação humanas" wide>
            O rascunho fica marcado como texto gerado até um servidor revisar. A aprovação registra quem aprovou e
            quando; o documento só avança para a etapa seguinte depois disso.
          </PublicFeature>
          <PublicFeature icon="shield-check" title="Modelo homologado">
            Documento oficial só é redigido por motor de IA homologado: antes de entrar, o modelo gera a cadeia
            inteira sobre um caso real e não pode alterar um único valor, quantidade, data ou artigo.
          </PublicFeature>
        </PublicGrid>
      </PublicSection>
    </PublicPage>
  );
}
