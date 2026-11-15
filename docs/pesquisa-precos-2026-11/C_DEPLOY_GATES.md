# C — Gates de implantação

## P0 — cesta (PR #217)

| Gate | Estado |
|---|---|
| Migração | nenhuma (só o front; contrato da API inalterado) |
| Flag | nenhuma nova; a cesta segue sob `precos_habilitado` |
| RLS / tenant | inalterado: o PATCH continua pelo JWT do usuário; 404/403/409 da rota preservados |
| CI | ver PR #217 (`testes`, `api`, `api-rls`, `web`, `web-e2e`, `imagens`); o Vercel falha em todo PR (conhecido, não é gate) |
| Imagem | `govconect-imagens.yml` (`ambiente=production`) depois do merge |
| Promoção | `promover_govconect.sh <sha> production` no VPS (senha da chave pelo dono); conferir `--atual` |
| Rollback | `promover_govconect.sh sha-31ad0876c020 production` (o SHA anterior em produção) — sem migração, a volta é só de imagem |

## Estado (14/11/2026)

| | P0 cesta (#217) | Relatórios (#218) | Paginação/filtros/mapa (#219) |
|---|---|---|---|
| implementado | sim | sim | sim |
| testado | CI verde + e2e real | CI verde + PDF real local | ver PR |
| implantado | **sim** — `sha-e72a9abd7d02` (`--atual` conferido) | não (imagem `sha-5d8a588d4b7d` pronta; promoção junto com o #219) | não |
| validado em produção | não (sem login no navegador da sessão) | não | não |

Nenhuma migração, nenhuma flag nova nos três. Rollback: `promover_govconect.sh sha-31ad0876c020 production` (anterior ao #217) ou o SHA anterior de cada promoção.
