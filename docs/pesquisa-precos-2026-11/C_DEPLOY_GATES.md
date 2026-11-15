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

## Estado (15/11/2026)

| | P0 cesta (#217) | Relatórios (#218) | Paginação/filtros/mapa (#219) | Fluxo + relatório só após concluir (#220) |
|---|---|---|---|---|
| implementado | sim | sim | sim | sim |
| testado | CI verde + e2e real | CI verde + PDF real | CI verde + e2e real | CI verde + e2e real + RLS |
| implantado | `sha-e72a9abd7d02` | `sha-d6453527495d` | `sha-d6453527495d` | `sha-6f663a3568d4` (`--atual` conferido, 15/11/2026) |
| validado em produção | não (sem login na sessão) | não | não | não |

Nenhuma migração, nenhuma flag nova. #220 muda contrato de comportamento: `POST /relatorios` com a cotação aberta → 409 `QUOTATION_NOT_COMPLETED` (decisão do dono, 15/11/2026). Rollback de imagem: o SHA anterior de cada promoção.
