# Referência do Claude Design (export de 23/10/2026)

Cópia fiel do que o export do Claude Design renderiza: os cartões de cada
grupo de componentes, as especificações de fundamentos, os dois kits de
tela e a miniatura. **Não é código do app**: o ESLint, o TypeScript e o
Tailwind ignoram esta pasta. Serve para comparar com `/design-system`.

Abrir: sirva a pasta com um servidor estático (os kits carregam `.jsx`
por XHR, que `file://` bloqueia) e abra `index.html`:

```bash
python -m http.server 8765 --directory apps/web/design-system/referencia
```

React 18, Babel e os ícones Phosphor vêm de CDN (unpkg), então precisa de
rede. Os caminhos são os do export, relativos a esta pasta — nenhum foi
alterado.

Única alteração de conteúdo: o e-mail de demonstração do login do kit
(`ui_kits/app/LoginScreen.jsx` e a cópia compilada em `_ds_bundle.js`)
era o endereço institucional de uma pessoa real; virou
`servidor@prefeitura.example`. Como a simulação só "entra" com
`.gov.br`, o botão Entrar agora mostra o estado de falha de
autenticação — digite um `@….gov.br` qualquer para ver o resto do kit.

O que ficou de fora, e por quê:

| Do export | Destino |
|---|---|
| `components/*/*.jsx`, `*.d.ts`, `*.prompt.md` | portados para `../components/` em TypeScript; as notas viraram JSDoc. O cartão continua usando `_ds_bundle.js`, a versão compilada que o próprio export gerou |
| `readme.md`, `SKILL.md`, `github.md` | consolidados em `DESIGN.md` (raiz) e `../README.md` |
| `_adherence.oxlintrc.json` | portado para `apps/web/eslint.config.mjs` |
| `_ds_manifest.json`, `.thumbnail` | internos da ferramenta; a lista de componentes do manifesto está em `tests/design-system.test.ts` |
| `uploads/` | insumos enviados ao Claude Design (prints do Streamlit, PNGs de inspiração). O logo e os dois grafismos eram cópias idênticas de `assets/` |
