import Link from "next/link";
import {
  ArrowRight,
  Buildings,
  CheckCircle,
  MagnifyingGlass,
  UserCheck,
} from "@phosphor-icons/react/dist/ssr";

import { Logo, MarcaComNome } from "@/components/marca";
import { botaoPrimario, botaoSecundario, cartao } from "@/components/ui";

const ETAPAS = [
  { sigla: "DFD", nome: "Documento de Formalização da Demanda", texto: "Registra a necessidade, o responsável e a justificativa." },
  { sigla: "ETP", nome: "Estudo Técnico Preliminar", texto: "Analisa soluções, quantidades e viabilidade da contratação." },
  { sigla: "TR", nome: "Termo de Referência", texto: "Define o objeto, as obrigações e os critérios de aceite." },
  { sigla: "Preços", nome: "Pesquisa de preços", texto: "Reúne referências públicas com fonte, data e critério de escolha." },
  { sigla: "Edital", nome: "Edital e relatórios", texto: "Consolida o processo para publicação e controle." },
];

const PERGUNTAS = [
  {
    p: "A inteligência artificial aprova documentos sozinha?",
    r: "Não. O sistema redige e sugere; cada documento passa pela revisão e aprovação de um servidor antes de seguir.",
  },
  {
    p: "De onde vêm os preços de referência?",
    r: "De bases públicas como o PNCP e o Compras.gov.br, entre outras. Cada valor guarda a origem, a data da coleta e o critério usado na cesta.",
  },
  {
    p: "Um município vê os processos de outro?",
    r: "Não. O isolamento é aplicado no próprio banco de dados, por município e por secretaria, e não depende só da tela.",
  },
  {
    p: "Como obter acesso?",
    r: "As contas são criadas pelo administrador do seu órgão. Não há cadastro aberto.",
  },
];

export default function Inicio() {
  return (
    <>
      <header className="border-b border-linha bg-canvas/90 backdrop-blur supports-[backdrop-filter]:bg-canvas/75">
        <nav
          aria-label="Principal"
          className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6"
        >
          <MarcaComNome />
          <div className="flex items-center gap-1 sm:gap-2">
            <a
              href="#plataforma"
              className="hidden rounded-[var(--radius-ui)] px-3 py-2 text-sm text-secundario transition-colors hover:text-texto sm:inline-block"
            >
              Plataforma
            </a>
            <a
              href="#perguntas"
              className="hidden rounded-[var(--radius-ui)] px-3 py-2 text-sm text-secundario transition-colors hover:text-texto sm:inline-block"
            >
              Perguntas
            </a>
            <Link href="/entrar" className={`${botaoPrimario} h-10 px-4 text-sm`}>
              Entrar
            </Link>
          </div>
        </nav>
      </header>

      <main id="conteudo">
        {/* Hero: texto à esquerda, marca à direita. */}
        <section className="relative overflow-hidden">
          <div
            aria-hidden
            className="pointer-events-none absolute -right-40 -top-40 size-[36rem] rounded-full opacity-[0.07] blur-3xl"
            style={{ background: "radial-gradient(circle, var(--color-acento), transparent 70%)" }}
          />
          <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 md:grid-cols-[1.25fr_1fr] md:py-24">
            <div>
              <h1
                className="max-w-[18ch] text-4xl font-semibold leading-[1.08] tracking-tight text-balance md:text-5xl lg:text-[3.4rem]"
              >
                Da demanda ao termo de referência, com cada valor rastreável.
              </h1>
              <p
                className="mt-6 max-w-[52ch] text-lg text-secundario"
              >
                Planeje contratações sob a Lei 14.133 com documentos revisados por servidores e preços
                de fonte verificável.
              </p>
              <div
                className="mt-9 flex flex-wrap gap-3"
              >
                <Link href="/entrar" className={botaoPrimario}>
                  Entrar
                  <ArrowRight size={18} weight="bold" aria-hidden />
                </Link>
                <a href="#plataforma" className={botaoSecundario}>
                  Conhecer a plataforma
                </a>
              </div>
            </div>
            <div className="hidden justify-end md:flex">
              <div className={`${cartao} p-6 md:p-8`}>
                <Logo tamanho={280} prioridade />
              </div>
            </div>
          </div>
        </section>

        {/* Fluxo da fase preparatória: lista ordenada, sem decoração falsa. */}
        <section id="plataforma" className="border-t border-linha bg-superficie">
          <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
            <h2 className="max-w-[28ch] text-3xl font-semibold tracking-tight">
              A fase preparatória inteira, na ordem da lei
            </h2>
            <p className="mt-4 max-w-[62ch] text-secundario">
              Cada etapa aproveita o que a anterior registrou, sem redigitar e sem perder a origem do dado.
            </p>
            <ol className="mt-12 grid gap-px overflow-hidden rounded-[var(--radius-ui)] border border-linha bg-linha md:grid-cols-5">
              {ETAPAS.map((e, i) => (
                <li key={e.sigla} className="relative bg-superficie p-6">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-acento">{String(i + 1).padStart(2, "0")}</span>
                    <span className="text-lg font-semibold">{e.sigla}</span>
                  </div>
                  <p className="mt-3 text-sm font-medium">{e.nome}</p>
                  <p className="mt-2 text-sm text-secundario">{e.texto}</p>
                  {i < ETAPAS.length - 1 && (
                    <ArrowRight
                      aria-hidden
                      size={16}
                      weight="bold"
                      className="absolute right-4 top-6 hidden text-secundario md:block"
                    />
                  )}
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Compromissos: grade assimétrica 2 + 1 + 1. */}
        <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <h2 className="max-w-[30ch] text-3xl font-semibold tracking-tight">
            Feito para quem responde pelo processo
          </h2>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            <article className={`${cartao} bg-acento-claro p-8 md:col-span-2 md:row-span-2`}>
              <UserCheck size={28} weight="bold" className="text-acento" aria-hidden />
              <h3 className="mt-5 text-xl font-semibold">Revisão humana em cada documento</h3>
              <p className="mt-3 max-w-[52ch] text-secundario">
                O texto sugerido nunca segue direto para o processo. Quem aprova é um servidor
                identificado, e a aprovação fica registrada com data e autor.
              </p>
            </article>
            <article className={`${cartao} p-6`}>
              <MagnifyingGlass size={24} weight="bold" className="text-acento" aria-hidden />
              <h3 className="mt-4 font-semibold">Preço com evidência</h3>
              <p className="mt-2 text-sm text-secundario">
                Fonte, data e critério ao lado de cada valor da cesta.
              </p>
            </article>
            <article className={`${cartao} p-6`}>
              <Buildings size={24} weight="bold" className="text-acento" aria-hidden />
              <h3 className="mt-4 font-semibold">Isolamento por município</h3>
              <p className="mt-2 text-sm text-secundario">
                Regras no banco de dados garantem que cada órgão veja só o que é seu.
              </p>
            </article>
          </div>
        </section>

        <section id="perguntas" className="border-t border-linha bg-superficie">
          <div className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
            <h2 className="text-3xl font-semibold tracking-tight">Perguntas frequentes</h2>
            <div className="mt-8">
              {PERGUNTAS.map((item) => (
                <details key={item.p} className="group border-b border-linha py-5">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-6 font-medium">
                    {item.p}
                    <span aria-hidden className="font-mono text-lg text-secundario group-open:hidden">+</span>
                    <span aria-hidden className="hidden font-mono text-lg text-secundario group-open:inline">-</span>
                  </summary>
                  <p className="mt-3 max-w-[62ch] text-secundario">{item.r}</p>
                </details>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-linha">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-10 text-sm text-secundario sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span className="inline-flex items-center gap-2">
            <CheckCircle size={18} weight="bold" className="text-acento" aria-hidden />
            Gov Conect, planejamento de contratações públicas
          </span>
          <Link href="/privacidade" className="underline-offset-4 hover:text-texto hover:underline">
            Privacidade
          </Link>
        </div>
      </footer>
    </>
  );
}
