import { Icon, ICON_NAMES } from "../components/core/Icon";
import { Exemplo, Grade, Secao } from "./partes";

const ESCALAS = [
  { nome: "Azul da marca", tokens: ["25", "50", "100", "200", "300", "400", "500", "600", "700", "800", "900"].map((n) => `--gc-blue-${n}`) },
  { nome: "Neutros frios", tokens: ["0", "25", "50", "100", "200", "300", "400", "500", "600", "700", "800", "900"].map((n) => `--gc-gray-${n}`) },
  {
    nome: "Semânticas",
    tokens: ["green-50", "green-200", "green-500", "green-700", "amber-50", "amber-200", "amber-500", "amber-700", "red-50", "red-100", "red-200", "red-500", "red-700", "violet-500", "teal-500"].map(
      (n) => `--gc-${n}`,
    ),
  },
];

const SEMANTICOS = [
  "--bg-app",
  "--surface-card",
  "--surface-raised",
  "--surface-sunken",
  "--surface-hover",
  "--surface-selected",
  "--border-subtle",
  "--border-default",
  "--border-strong",
  "--border-field",
  "--text-primary",
  "--text-secondary",
  "--text-tertiary",
  "--text-disabled",
  "--accent",
  "--accent-hover",
  "--accent-brand",
  "--accent-subtle",
  "--focus-ring-color",
];

const ESTADOS = ["success", "warning", "error", "info", "neutral"];

const TIPOS = [
  { token: "--type-display", nome: "Display (KPI)", texto: "R$ 18.535,00" },
  { token: "--type-h1", nome: "Título 1", texto: "Pesquisa de preços" },
  { token: "--type-h2", nome: "Título 2", texto: "Itens da pesquisa" },
  { token: "--type-h3", nome: "Título 3 (cartão)", texto: "Cesta de preços" },
  { token: "--type-body-lg", nome: "Corpo grande", texto: "Comece registrando o órgão e o objeto da contratação." },
  { token: "--type-body", nome: "Corpo", texto: "Use a conta criada pelo administrador do seu órgão." },
  { token: "--type-label", nome: "Rótulo", texto: "O que vai ser comprado ou contratado" },
  { token: "--type-caption", nome: "Legenda", texto: "Atualizado em 23/10/2026, horário de Brasília" },
  { token: "--type-overline", nome: "Sobretítulo", texto: "AVALIAÇÃO PRELIMINAR" },
  { token: "--type-mono", nome: "Mono (códigos)", texto: "05.149.726/0001-04-1-000312/2026" },
];

const ESPACOS = ["0-5", "1", "1-5", "2", "2-5", "3", "4", "5", "6", "8", "10", "12", "16"];
const RAIOS = ["xs", "sm", "md", "lg", "xl", "pill"];
const SOMBRAS = ["xs", "sm", "md", "lg"];

function Amostra({ token }: { token: string }) {
  return (
    <div className="grid gap-1">
      <span
        className="block h-10 rounded-[var(--gc-radius-md)] border border-[color:var(--border-subtle)]"
        style={{ background: `var(${token})` }}
      />
      <code className="gc-mono break-all text-[length:var(--gc-fs-2xs)] text-secundario">{token}</code>
    </div>
  );
}

export function Fundamentos({ tema }: { tema: string }) {
  return (
    <>
      <Secao
        id="cores"
        tema={tema}
        titulo="Cores"
        descricao="Um acento só (azul do logo), neutros frios e borda de 1 px. Status sempre com ícone e rótulo, nunca só cor."
      >
        {ESCALAS.map((e) => (
          <Exemplo key={e.nome} rotulo={e.nome}>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(calc(var(--space-16)+var(--space-6)),1fr))] gap-3">
              {e.tokens.map((t) => (
                <Amostra key={t} token={t} />
              ))}
            </div>
          </Exemplo>
        ))}
        <Exemplo rotulo="Aliases semânticos (trocam com o tema)">
          <div className="grid grid-cols-[repeat(auto-fill,minmax(calc(var(--space-16)+var(--space-10)),1fr))] gap-3">
            {SEMANTICOS.map((t) => (
              <Amostra key={t} token={t} />
            ))}
          </div>
        </Exemplo>
        <Exemplo rotulo="Estados: texto, fundo e borda">
          <div className="flex flex-wrap gap-3">
            {ESTADOS.map((s) => (
              <span
                key={s}
                className="rounded-[var(--gc-radius-md)] border px-3 py-2 text-[length:var(--gc-fs-sm)]"
                style={{ color: `var(--${s}-fg)`, background: `var(--${s}-bg)`, borderColor: `var(--${s}-border)` }}
              >
                --{s}-fg / bg / border
              </span>
            ))}
          </div>
        </Exemplo>
        <Exemplo rotulo="Séries de gráfico">
          <div className="flex gap-3">
            {[1, 2, 3, 4, 5].map((n) => (
              <Amostra key={n} token={`--chart-${n}`} />
            ))}
          </div>
        </Exemplo>
      </Secao>

      <Secao id="tipografia" tema={tema} titulo="Tipografia" descricao="Geist na interface, Geist Mono em código, número de processo e hash. Número de dinheiro e quantidade sempre tabular.">
        <div className="grid gap-4">
          {TIPOS.map((t) => (
            <div key={t.token} className="grid gap-1 border-b border-linha pb-3 md:grid-cols-[calc(var(--space-16)*3)_1fr] md:items-baseline">
              <code className="gc-mono text-[length:var(--gc-fs-xs)] text-secundario">
                {t.nome} · {t.token}
              </code>
              <span className="gc-num" style={{ font: `var(${t.token})` }}>
                {t.texto}
              </span>
            </div>
          ))}
        </div>
      </Secao>

      <Secao id="espaco" tema={tema} titulo="Espaço, raio e elevação" descricao="Base de 4 px com meios passos de 2, 6 e 10. Raio de 8 px em todo controle, 12 px em cartão e tabela, 16 px em diálogo. Borda antes de sombra.">
        <Grade>
          <Exemplo rotulo="Espaçamento (--space-*)">
            <div className="grid gap-2">
              {ESPACOS.map((s) => (
                <div key={s} className="flex items-center gap-3">
                  <code className="gc-mono w-[calc(var(--space-16)+var(--space-4))] text-[length:var(--gc-fs-xs)] text-secundario">
                    --space-{s}
                  </code>
                  <span className="block h-3 rounded-[var(--gc-radius-xs)] bg-[var(--accent-brand)]" style={{ width: `var(--space-${s})` }} />
                </div>
              ))}
            </div>
          </Exemplo>
          <Exemplo rotulo="Raios (--gc-radius-*) e sombras (--gc-shadow-*)">
            <div className="flex flex-wrap gap-4">
              {RAIOS.map((r) => (
                <div key={r} className="grid justify-items-center gap-1">
                  <span
                    className="block size-14 border border-[color:var(--border-default)] bg-superficie"
                    style={{ borderRadius: `var(--gc-radius-${r})` }}
                  />
                  <code className="gc-mono text-[length:var(--gc-fs-2xs)] text-secundario">{r}</code>
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-4">
              {SOMBRAS.map((s) => (
                <div key={s} className="grid justify-items-center gap-1">
                  <span
                    className="block size-14 rounded-[var(--gc-radius-lg)] bg-superficie"
                    style={{ boxShadow: `var(--gc-shadow-${s})` }}
                  />
                  <code className="gc-mono text-[length:var(--gc-fs-2xs)] text-secundario">{s}</code>
                </div>
              ))}
            </div>
          </Exemplo>
        </Grade>
      </Secao>

      <Secao
        id="icones"
        tema={tema}
        titulo={`Ícones (${ICON_NAMES.length})`}
        descricao="Phosphor, peso bold por padrão; fill só para item ativo, status e o brilho do GovBot. O registro é fechado: ícone novo entra em Icon.tsx."
      >
        <div className="grid grid-cols-[repeat(auto-fill,minmax(calc(var(--space-16)*2),1fr))] gap-2">
          {ICON_NAMES.map((n) => (
            <div key={n} className="flex items-center gap-2 rounded-[var(--gc-radius-md)] border border-linha bg-superficie px-2 py-1.5">
              <Icon name={n} size={18} />
              <code className="gc-mono truncate text-[length:var(--gc-fs-2xs)] text-secundario">{n}</code>
            </div>
          ))}
        </div>
      </Secao>
    </>
  );
}
