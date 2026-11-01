import { Logo } from "../components/core/Logo";
import { Fundamentos } from "./Fundamentos";
import { GaleriaBase } from "./GaleriaBase";
import { GaleriaConteudo } from "./GaleriaConteudo";
import { GaleriaIA } from "./GaleriaIA";

const SECOES = [
  ["cores", "Cores"],
  ["tipografia", "Tipografia"],
  ["espaco", "Espaço"],
  ["icones", "Ícones"],
  ["core", "Core"],
  ["actions", "Actions"],
  ["forms", "Forms"],
  ["navigation", "Navigation"],
  ["content", "Content"],
  ["feedback", "Feedback"],
  ["data", "Data"],
  ["ai", "GovBot"],
  ["price", "Preços"],
  ["templates", "Templates"],
] as const;

const TEMAS = [
  { id: "claro", nome: "Tema claro", atributo: "light" },
  { id: "escuro", nome: "Tema escuro", atributo: "dark" },
] as const;

/**
 * Vitrine do design system: todos os componentes, variantes e estados,
 * uma vez em cada tema. Cada painel força o tema com `data-theme`, então
 * os dois aparecem juntos qualquer que seja o tema do sistema.
 */
export function Vitrine() {
  return (
    <div className="gc-base min-h-[100dvh] bg-canvas">
      <header className="sticky top-0 z-[var(--z-sticky)] border-b border-linha bg-superficie">
        <div className="mx-auto flex max-w-[var(--content-max)] flex-wrap items-center gap-x-6 gap-y-2 px-[var(--page-padding-x)] py-3">
          <Logo size={28} />
          <nav aria-label="Seções da vitrine" className="flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--gc-fs-sm)]">
            {TEMAS.map((t) => (
              <a key={t.id} href={`#${t.id}`} className="font-[number:var(--weight-semibold)]">
                {t.nome}
              </a>
            ))}
            {SECOES.map(([id, nome]) => (
              <a key={id} href={`#claro-${id}`}>
                {nome}
              </a>
            ))}
          </nav>
        </div>
      </header>
      <main id="conteudo">
        <div className="mx-auto grid max-w-[var(--content-max)] gap-2 px-[var(--page-padding-x)] pt-8">
          <h1>Design system Gov Conect</h1>
          <p className="max-w-[70ch] text-secundario">
            Fonte da verdade dos tokens: DESIGN.md na raiz do repositório. Componentes em apps/web/design-system, importados de
            @/design-system. Textos e números desta página são ilustrativos.
          </p>
        </div>
        {TEMAS.map((t) => (
          <section
            key={t.id}
            id={t.id}
            data-theme={t.atributo}
            aria-label={t.nome}
            className="gc-base mt-8 border-t border-linha bg-canvas py-10"
          >
            <div className="mx-auto grid grid-cols-[minmax(0,1fr)] max-w-[var(--content-max)] gap-14 px-[var(--page-padding-x)]">
              <p className="font-[number:var(--weight-semibold)] text-[length:var(--gc-fs-2xs)] uppercase tracking-[var(--gc-tracking-caps)] text-[color:var(--accent-strong-text)]">
                {t.nome}
              </p>
              <Fundamentos tema={t.id} />
              <GaleriaBase tema={t.id} />
              <GaleriaConteudo tema={t.id} />
              <GaleriaIA tema={t.id} />
            </div>
          </section>
        ))}
      </main>
    </div>
  );
}
