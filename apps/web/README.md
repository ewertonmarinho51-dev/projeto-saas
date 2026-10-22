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

Acento `#0050D8` amostrado do logo (`assets/marca/logo-original.png`);
neutros frios, raio de 8px, borda de 1px, Geist. O logo é usado com o
fundo branco original (o miolo do documento faz parte da marca), recortado
e redimensionado, sem redesenho. Contrastes conferidos por cálculo: texto
15,4:1, secundário 5,9:1, acento 6,7:1, borda de campo 3,8:1.

## E2E

`e2e/fluxo.spec.ts` roda no job `web-e2e` contra a pilha real
(`apps/api/tests_rls/pilha.py`): login, link profundo, senha errada,
redirecionamento externo ignorado, criar/editar, conflito de versão,
isolamento entre municípios, conta desativada e saída. Capturas em 375,
768 e 1440 px viram artefato do CI.
