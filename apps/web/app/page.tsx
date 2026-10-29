import Link from "next/link";
import {
  ArrowRight,
  Buildings,
  CheckCircle,
  MagnifyingGlass,
  UserCheck,
} from "@phosphor-icons/react/dist/ssr";

import { cartao } from "@/components/ui";
import { LandingHero } from "@/design-system";

const ETAPAS = [
  { sigla: "DFD", nome: "Documento de Formalização da Demanda", texto: "Registra a necessidade, o responsável e a justificativa." },
  { sigla: "ETP", nome: "Estudo Técnico Preliminar", texto: "Analisa soluções, quantidades e viabilidade da contratação." },
  { sigla: "TR", nome: "Termo de Referência", texto: "Define o objeto, as obrigações e os critérios de aceite." },
  { sigla: "Preços", nome: "Pesquisa de preços", texto: "Reúne referências públicas com fonte, data e critério de escolha." },
  { sigla: "Edital", nome: "Edital e relatórios", texto: "Consolida o processo para publicação e controle." },
];

const PERGUNTAS: { id?: string; p: string; r: string }[] = [
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
    id: "acesso",
    p: "Como obter acesso?",
    r: "As contas são criadas pelo administrador do seu órgão. Não há cadastro aberto.",
  },
];

export default function Inicio() {
  return (
    <>
      <main id="conteudo">
        <LandingHero
          nav={[
            { label: "Plataforma", href: "#plataforma" },
            { label: "Revisão e segurança", href: "#seguranca" },
            { label: "Perguntas", href: "#perguntas" },
          ]}
          secondary={{ label: "Como obter acesso", href: "#acesso" }}
          signIn={{ label: "Acessar sistema", href: "/entrar" }}
          explore={{ label: "Conhecer a plataforma", href: "#plataforma" }}
        />
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
        <section id="seguranca" className="mx-auto max-w-6xl scroll-mt-6 px-4 py-20 sm:px-6">
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
                <details key={item.p} id={item.id} className="group scroll-mt-6 border-b border-linha py-5">
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
