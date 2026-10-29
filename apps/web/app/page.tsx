import { headers } from "next/headers";

import { cabecalho, dadosEstruturados, ENTRAR, metadados, RODAPE } from "@/components/site";
import {
  Accordion,
  LandingHero,
  PublicFeature,
  PublicFooter,
  PublicGrid,
  PublicSection,
  PublicSteps,
} from "@/design-system";

export const metadata = metadados("/");

const ETAPAS = [
  { tag: "DFD", title: "Documento de Formalização da Demanda", text: "Registra a necessidade, o responsável e a justificativa." },
  { tag: "ETP", title: "Estudo Técnico Preliminar", text: "Analisa soluções, quantidades e viabilidade da contratação." },
  { tag: "TR", title: "Termo de Referência", text: "Define o objeto, as obrigações e os critérios de aceite." },
  { tag: "Preços", title: "Pesquisa de preços", text: "Reúne referências públicas com fonte, data e critério de escolha." },
  { tag: "Edital", title: "Edital e relatórios", text: "Consolida o processo para publicação e controle." },
];

const PERGUNTAS = [
  {
    title: "A inteligência artificial aprova documentos sozinha?",
    content: "Não. O sistema redige e sugere; cada documento passa pela revisão e aprovação de um servidor antes de seguir.",
  },
  {
    title: "De onde vêm os preços de referência?",
    content:
      "De bases públicas: os dados abertos do Compras.gov.br e o PNCP. Cada valor guarda a origem, a data da coleta e o critério usado na cesta.",
  },
  {
    title: "Um município vê os processos de outro?",
    content: "Não. O isolamento é aplicado no próprio banco de dados, por município e por secretaria, e não depende só da tela.",
  },
  {
    title: "Como obter acesso?",
    content:
      "As contas são criadas pelo administrador do seu órgão; não há cadastro aberto. Para contratar a plataforma, fale com a equipe na página de contato.",
  },
];

export default async function Inicio() {
  // Os dados estruturados vão num <script> de dados; o nonce da CSP o acompanha.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  const topo = cabecalho("/");
  return (
    <>
      <script
        type="application/ld+json"
        nonce={nonce}
        // JSON montado no servidor a partir de constantes: sem entrada do usuário.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(dadosEstruturados()).replace(/</g, "\\u003c") }}
      />
      <main id="conteudo">
        <LandingHero
          nav={topo.nav}
          secondary={topo.secondary}
          signIn={ENTRAR}
          explore={{ label: "Conhecer a plataforma", href: "/solucoes" }}
        />

        <PublicSection
          id="plataforma"
          muted
          eyebrow="Fase preparatória"
          title="A fase preparatória inteira, na ordem da lei"
          lead="Cada etapa aproveita o que a anterior registrou, sem redigitar e sem perder a origem do dado."
        >
          <PublicSteps steps={ETAPAS} />
        </PublicSection>

        <PublicSection
          id="seguranca"
          eyebrow="Revisão e segurança"
          title="Feito para quem responde pelo processo"
          lead="O servidor continua sendo o autor do processo. A plataforma organiza, redige e confere — e registra quem decidiu."
        >
          <PublicGrid>
            <PublicFeature icon="seal-check" title="Revisão humana em cada documento" wide href="/solucoes/documentos-ia">
              O texto sugerido nunca segue direto para o processo. Quem aprova é um servidor identificado, e a
              aprovação fica registrada com data e autor.
            </PublicFeature>
            <PublicFeature icon="magnifying-glass" title="Preço com evidência" href="/solucoes/pesquisa-de-precos">
              Fonte, data e critério ao lado de cada valor da cesta.
            </PublicFeature>
            <PublicFeature icon="buildings" title="Isolamento por município">
              Regras no banco de dados garantem que cada órgão veja só o que é seu.
            </PublicFeature>
            <PublicFeature icon="books" title="Base de conhecimento do órgão">
              Normas, modelos e decretos do próprio município alimentam a redação dos documentos.
            </PublicFeature>
            <PublicFeature icon="shield-check" title="Governança de cláusulas">
              Cláusulas padronizadas passam por revisão jurídica e publicação antes de entrar nos modelos.
            </PublicFeature>
          </PublicGrid>
        </PublicSection>

        <PublicSection id="perguntas" muted narrow eyebrow="Perguntas" title="Perguntas frequentes">
          <Accordion items={PERGUNTAS} />
        </PublicSection>
      </main>
      <PublicFooter {...RODAPE} />
    </>
  );
}
