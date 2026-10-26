# Gov Conect Web (`apps/web`)

Next.js 16 (App Router, TypeScript, Tailwind v4). Página pública, login
pelo Supabase Auth no servidor e área autenticada que lê e grava processos
**pela API** (`apps/api`), nunca direto no banco.

```bash
cd apps/web
npm ci
npm run lint && npm run typecheck && npm test
npm run build && npm run verificar-bundle
```

## Como a sessão funciona

| Camada | Onde | O que confere |
|---|---|---|
| Proxy | `proxy.ts` → `lib/supabase/proxy.ts` | renova a sessão; `/app` sem identidade vai a `/entrar?proximo=` |
| Layout de `/app` | `app/app/layout.tsx` | `getClaims()` de novo + `/api/v1/me` (vínculo ativo) |
| API | `apps/api` | assinatura ES256 pelo JWKS, vínculo, tenant |
| Banco | RLS da 0020 | o que cada token enxerga |

Login, logout, recuperação e troca de senha são **ações de servidor**; o
navegador não fala com o Supabase nem com a API (`connect-src 'self'`).
`?proximo=` passa por `destinoSeguro` (só caminhos de `/app`).

## Variáveis

| Variável | Onde | Regra |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | build | pública por desenho |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | build | chave **publicável**; nunca a de servidor |
| `GOVCONECT_API_URL` | servidor | URL interna da API; nunca `NEXT_PUBLIC_` |
| `GOVCONECT_SITE_URL` | servidor | origem do link de recuperação de senha (não vem do cabeçalho `Host`) |

## Segurança no navegador

- CSP com `nonce` por requisição para script; `frame-ancestors 'none'`;
  `form-action 'self'`. Por isso toda página é dinâmica.
- `/app` e `/entrar` com `Cache-Control: private, no-store`.
- Cookie de sessão `Secure` em produção e `SameSite=Lax`. **Não é
  HttpOnly** (decisão do `@supabase/ssr`); o app não guarda nada além dele.
- `npm run verificar-bundle` reprova o build se formato de chave de
  servidor ou nome de variável de servidor aparecer em `.next/static`.

## Identidade visual

Vem do design system: [`DESIGN.md`](../../DESIGN.md) na raiz é a fonte
da verdade dos tokens, e [`design-system/`](design-system/README.md) tem
os componentes (importe de `@/design-system`) e o mapa da biblioteca.
Vitrine em `/design-system` (em produção, só com `GOVCONECT_VITRINE=1`).

Acento de ação `#0059D6` (6,2:1 sobre branco), confirmado pelo cliente em
23/10/2026 a partir dos azuis do logo; neutros frios, raio de 8 px em
controle e 12 px em cartão, borda de 1 px, Geist. O logo é o PNG
transparente do logo vetorizado, sem placa branca e sem redesenho.
Componente novo nasce no design system; valor visual solto (hex, px,
fonte) o ESLint aponta.

## E2E

`e2e/fluxo.spec.ts` roda no job `web-e2e` contra a pilha real
(`apps/api/tests_rls/pilha.py`): login, link profundo, senha errada,
redirecionamento externo ignorado, criar/editar, conflito de versão,
isolamento entre municípios, conta desativada e saída. Capturas em 375,
768 e 1440 px viram artefato do CI.
