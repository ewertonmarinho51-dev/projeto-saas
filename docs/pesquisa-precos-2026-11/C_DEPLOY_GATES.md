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

## Estado

| | P0 cesta |
|---|---|
| implementado | sim (branch `claude/cesta-p0`) |
| testado | unidade e mutação locais; CI verde com e2e real (run 43648842106) |
| implantado | não |
| validado em produção | não |
