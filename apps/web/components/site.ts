import type { Metadata } from "next";

import type { PublicFooterProps, PublicHeaderProps, PublicLink } from "@/design-system";

/**
 * O site institucional num lugar só: endereço canônico, navegação,
 * rodapé, metadados de cada página e o mapa do site. Página nova entra
 * em PAGINAS — o sitemap e a prova (tests/site.test.ts) leem daqui.
 */

/** Endereço público canônico. Em outro ambiente, `GOVCONECT_SITE_URL`. */
export const SITE_URL = (process.env.GOVCONECT_SITE_URL ?? "https://govconect.com").replace(/\/+$/, "");

/** Resolve um caminho interno sempre contra a origem pública configurada. */
export function urlPublica(caminho: string): URL {
  return new URL(caminho, SITE_URL);
}

export const NOME = "Gov Conect";

export const DESCRICAO =
  "Plataforma para a fase preparatória das contratações públicas sob a Lei nº 14.133/2021: DFD, ETP, Mapa de Riscos e Termo de Referência com apoio de IA e revisão humana, e pesquisa de preços com a origem de cada valor.";

export type PaginaPublica = {
  caminho: string;
  titulo: string;
  descricao: string;
  prioridade: number;
};

export const PAGINAS: PaginaPublica[] = [
  {
    caminho: "/",
    titulo: "Gov Conect — IA para Licitações e Pesquisa de Preços",
    descricao: DESCRICAO,
    prioridade: 1,
  },
  {
    caminho: "/entrar",
    titulo: "Entrar — Gov Conect",
    descricao: "Acesso ao Gov Conect com o e-mail institucional cadastrado pelo seu órgão.",
    prioridade: 0.4,
  },
  {
    caminho: "/solucoes",
    titulo: "Soluções — Gov Conect",
    descricao:
      "Documentos da fase preparatória com IA e revisão humana, pesquisa de preços rastreável, base de conhecimento do órgão e isolamento por município.",
    prioridade: 0.9,
  },
  {
    caminho: "/solucoes/documentos-ia",
    titulo: "Documentos com Inteligência Artificial",
    descricao:
      "Elabore DFD, ETP, Mapa de Riscos e Termo de Referência a partir dos dados do processo, com fundamentação na Lei nº 14.133/2021 e aprovação de um servidor.",
    prioridade: 0.8,
  },
  {
    caminho: "/solucoes/pesquisa-de-precos",
    titulo: "Pesquisa de Preços",
    descricao:
      "Pesquisa de preços em Compras.gov.br e PNCP, com triagem das referências, cesta justificada, estatísticas calculadas no servidor e relatório com a origem de cada valor.",
    prioridade: 0.8,
  },
  {
    caminho: "/como-funciona",
    titulo: "Como Funciona",
    descricao:
      "Do cadastro da demanda ao Termo de Referência: as etapas da fase preparatória no Gov Conect, quem faz o quê e onde a revisão humana entra.",
    prioridade: 0.7,
  },
  {
    caminho: "/sobre",
    titulo: "Sobre a Gov Conect",
    descricao:
      "Por que o Gov Conect existe e os princípios que orientam a plataforma: revisão humana, evidência em cada valor e isolamento entre órgãos.",
    prioridade: 0.5,
  },
  {
    caminho: "/contato",
    titulo: "Contato",
    descricao: "Fale com a equipe do Gov Conect sobre a contratação da plataforma pelo seu órgão.",
    prioridade: 0.6,
  },
  {
    caminho: "/privacidade",
    titulo: "Privacidade",
    descricao: "Como o Gov Conect trata dados de conta, sessões e documentos dos órgãos que usam a plataforma.",
    prioridade: 0.3,
  },
];

const NAV: PublicLink[] = [
  { label: "Soluções", href: "/solucoes" },
  { label: "Como funciona", href: "/como-funciona" },
  { label: "Sobre", href: "/sobre" },
  { label: "Contato", href: "/contato" },
];

export const ENTRAR: PublicLink = { label: "Entrar", href: "/entrar" };

export function cabecalho(caminho: string): PublicHeaderProps {
  return { nav: NAV, signIn: ENTRAR, secondary: { label: "Fale com a equipe", href: "/contato" }, current: caminho };
}

export const RODAPE: PublicFooterProps = {
  columns: [
    {
      title: "Soluções",
      links: [
        { label: "Visão geral", href: "/solucoes" },
        { label: "Documentos com IA", href: "/solucoes/documentos-ia" },
        { label: "Pesquisa de preços", href: "/solucoes/pesquisa-de-precos" },
      ],
    },
    {
      title: "Institucional",
      links: [
        { label: "Como funciona", href: "/como-funciona" },
        { label: "Sobre", href: "/sobre" },
        { label: "Contato", href: "/contato" },
      ],
    },
    {
      title: "Acesso",
      links: [
        { label: "Entrar", href: "/entrar" },
        { label: "Privacidade", href: "/privacidade" },
      ],
    },
  ],
  note: "Gov Conect · Fase preparatória das contratações públicas, Lei nº 14.133/2021.",
};

/** Metadados de uma página pública: título, descrição, canônica e Open Graph. */
export function metadados(caminho: string): Metadata {
  const pagina = PAGINAS.find((p) => p.caminho === caminho);
  if (!pagina) throw new Error(`Página pública sem registro em PAGINAS: ${caminho}`);
  const url = `${SITE_URL}${caminho === "/" ? "" : caminho}`;
  return {
    // A tabela editorial define o título completo de cada rota, sem o modelo global.
    title: { absolute: pagina.titulo },
    description: pagina.descricao,
    alternates: { canonical: url },
    openGraph: {
      type: "website",
      locale: "pt_BR",
      siteName: NOME,
      url,
      title: pagina.titulo,
      description: pagina.descricao,
      images: [{ url: `${SITE_URL}/logo-govconect.png`, alt: NOME }],
    },
    twitter: { card: "summary", title: pagina.titulo, description: pagina.descricao },
  };
}

/** Dados estruturados da organização e do site (schema.org), só com o que é verificável. */
export function dadosEstruturados() {
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${SITE_URL}/#organizacao`,
        name: NOME,
        url: SITE_URL,
        logo: `${SITE_URL}/logo-govconect.png`,
        description: DESCRICAO,
      },
      {
        "@type": "WebSite",
        "@id": `${SITE_URL}/#site`,
        name: NOME,
        url: SITE_URL,
        inLanguage: "pt-BR",
        publisher: { "@id": `${SITE_URL}/#organizacao` },
      },
      {
        "@type": "SoftwareApplication",
        name: NOME,
        applicationCategory: "BusinessApplication",
        operatingSystem: "Web",
        url: SITE_URL,
        description: DESCRICAO,
        publisher: { "@id": `${SITE_URL}/#organizacao` },
      },
    ],
  };
}
