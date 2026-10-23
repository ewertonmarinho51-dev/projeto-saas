import next from "eslint-config-next";

/*
 * Aderência ao design system — portada de `_adherence.oxlintrc.json` do
 * export do Claude Design (formato oxlint; aqui como regra do ESLint,
 * que é o lint do projeto). Fica de fora a parte que validava prop por
 * componente: o TypeScript estrito já recusa prop inexistente, com erro
 * melhor que o seletor do lint.
 *
 * Nível "warn" no app (o legado ainda tem valor solto e migra aos
 * poucos); "error" dentro de design-system/, que nasce limpo.
 */
const VALOR_SOLTO = [
  {
    selector: "Literal[value=/#[0-9a-fA-F]{3,8}\\b/]",
    message: "Cor hex solta: use um token do design system via var() (DESIGN.md).",
  },
  {
    selector: "Literal[value=/\\b\\d+px\\b/]",
    message: "Valor em px solto: use um token (--space-*, --control-*, --gc-radius-*) via var() (DESIGN.md).",
  },
  {
    selector: "Literal[value=/font-family\\s*:\\s*(?!['\"]?(?:Geist|Geist Mono|var\\())/i]",
    message: "Fonte fora do design system. Disponíveis: Geist e Geist Mono (--gc-font-sans, --gc-font-mono).",
  },
];

const config = [
  ...next,
  {
    ignores: [".next/**", "node_modules/**", "e2e/resultados/**", "next-env.d.ts", "design-system/referencia/**"],
  },
  {
    files: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "warn",
        {
          patterns: [
            {
              group: ["@/design-system/*", "!@/design-system/vitrine"],
              message: "Importe do índice (`@/design-system`), não de arquivo interno do design system.",
            },
          ],
        },
      ],
      "no-restricted-syntax": ["warn", ...VALOR_SOLTO],
    },
  },
  {
    files: ["design-system/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": ["error", ...VALOR_SOLTO],
    },
  },
];

export default config;
