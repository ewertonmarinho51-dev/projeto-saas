# A — Diagnóstico do repositório real

Pacote "Gov Conect — Fontes de Preços" (20/10/2026), Fase A. Feito sobre a
`main` em `b1abc69` (v1.9.9 em produção), branch `claude/fontes-precos-expansao`.

## 1. A stack que o pacote supõe e a que existe

| O pacote supõe | O repositório tem | Consequência |
|---|---|---|
| FastAPI | **não há**. App Streamlit monolítico (`app.py`, `src/ui/*`) | não há rota HTTP própria; o "serviço" é função Python chamada pela tela |
| Next.js | **não há** | UI = Streamlit |
| Celery + Redis | **não há** worker nem fila (`requirements.txt`, `implantacao/docker-compose.yml`: só `app` e `caddy`) | ETL roda como **script de bancada** (`scripts/etl_fontes_precos.py`); agendar exige um contêiner/cron novo — decisão do operador |
| Postgres + Alembic | **Supabase** (Postgres) com migrações **SQL versionadas** em `supabase/migrations/0001…0029`, aplicadas à mão (MCP/SQL Editor) | a proposta de tabela é SQL, não Alembic, e **não foi aplicada** |
| auth/RLS | Supabase Auth + RLS por tenant/secretaria (`0020`, `0021`); o app opera com `service_role` e filtra `tenant_id` no código | dado público de fonte (igual para todo tenant) não leva `tenant_id`; leitura só do que estiver validado |

## 2. Como o preço entra hoje

```
item da cotação ──► busca.coletar(item, fontes_padrao())
                     fontes_padrao() = [ComprasGovAdapter, PNCPAdapter]      (src/precos/__init__.py)
                     │  HTTP síncrono às APIs oficiais, com timeout e recuo (compras_gov.py, pncp.py)
                     ▼
                  modelo.Referencia (Decimal, bruto, raw_hash, natureza_valor)
                     ▼
   procedência (FONTES_REGISTRADAS) → deduplicar (fonte:id_externo)
   → busca.fundir_entre_portais (mesma compra Compras.gov × PNCP: idCompra + fornecedor + valor)
   → unidades.normalizar (fator só com prova; conversão extrema barrada, N-06)
   → matching (comparabilidade) → estatistica.selecionar_cesta
       (barreira de conversão → barreira por atributo → triagem pré-cesta → teto 15)
                     ▼
   pesquisa_preco_referencias (RLS por tenant; DELETE revogado; unique item+fonte+id_externo)
                     ▼
   cesta → ciência na emissão (alertas, parecer do Jev) → relatório/PDF
```

* Fonte é uma `FontePesquisaPreco` (`src/precos/fontes.py`): `pesquisar(Consulta) → ResultadoBusca`,
  `healthcheck()`, `capacidades` (PRECO/EVIDENCIA). Falha de uma fonte não derruba a pesquisa.
* Natureza do valor (`modelo.NaturezaValor`) já distingue praticado, homologado, adjudicado,
  contratado, estimado e proposta; só as quatro primeiras entram sozinhas na cesta. O CHECK da
  coluna `natureza_valor` (0021) espelha o enum.
* Flags: `db.flag_ativa(nome)` lê `flag_<nome>` em `config_app`, default OFF.

## 3. Retirar item da cesta (lentidão relatada)

`cotacoes.alterar_status_referencia → _mudar_e_recalcular`: **nenhum HTTP externo**, nenhum Jev.
São 4 a 5 idas ao Supabase (reclassificar, recalcular e gravar o item, registrar o evento e,
se o estado mudou, sincronizar a cotação), mais o rerun inteiro da página do Streamlit. A lentidão
não vem das fontes; esta entrega não acrescenta nada a esse caminho, e a busca por fonte nova
(quando existir) lerá o banco, nunca o arquivo nem a internet.

Ponto a medir à parte: desde a v1.9.9, o aviso de emissão (`precos_ui._render_aviso_nao_bloqueante`)
lê os pareceres do Jev da trilha (consulta paginada) a cada render da tela de emissão. Não está no
clique de retirar da tela de Cotações, mas roda a cada rerun da tela de Pesquisa de preços.

## 4. Testes, isolamento e riscos

* Suíte: `python -m pytest -q` — 3.146 passaram e 354 pulados antes desta entrega (os pulados
  pedem Postgres de ensaio ou motor de IA real). CI "testes" no GitHub Actions em todo push.
* Isolamento: RLS + `tenant_id` filtrado no código (`db.py` explica por que o filtro do código é a
  contenção real com `service_role`). Fonte nova sem `tenant_id` é **dado público compartilhado**;
  o que é do tenant (a cotação, a cesta) continua nas tabelas atuais.
* Riscos de efeito colateral, e como esta entrega os evita:
  * mudar `fontes_padrao()` mudaria toda pesquisa → **não mudou** (prova:
    `test_as_fontes_da_pesquisa_continuam_compras_gov_e_pncp`);
  * ampliar o CHECK de `natureza_valor` exigiria migração → **não foi preciso**:
    `evidencia.NATUREZA_DO_TIPO` mapeia para as naturezas que já existem;
  * flag ligada pelo painel pôr dado sem licença em produção → **trava dupla**: licença aprovada e
    mapeamento confirmado moram no código (`fontes_externas.py`), não na tabela.

## 5. Duplicidade com o PNCP e o Compras.gov

* Compras.gov × PNCP: já fundidos por `busca.fundir_entre_portais` (idCompra do link de origem do PNCP).
* **TCE-RS × PNCP/Compras.gov: risco alto e sem chave forte.** Os municípios gaúchos publicam no
  LicitaCon e, sob a Lei 14.133, também no PNCP. O arquivo do TCE-RS **não traz** número de controle
  PNCP nem idCompra, e `licitacao.csv` identifica o comprador pelo `CD_ORGAO` do TCE e pelo nome
  (`CNPJ_ORGAO_GERENCIADOR` só vale para ata de registro de preços). A única ponte é o par
  fornecedor CNPJ + valor unitário idêntico + data próxima, que serve como **possível duplicata**,
  nunca como fusão (`dedup_fontes.possiveis_duplicatas`).
* BPS × PNCP/Compras.gov: mesma situação (o BPS traz o CNPJ da instituição e o processo, mas não
  o id PNCP); BPS é só medicamento.

## 6. Lacunas que bloqueiam a próxima fase

1. **Licença**: TCE-RS e BPS sem licença declarada no CKAN (license_id vazio, 20/10/2026).
2. **Leiaute TCE-RS**: o significado de `TP_RESULTADO_ITEM` (A, D, F, R, N, vazio),
   `CD_TIPO_FASE_ATUAL` e `CD_TIPO_MODALIDADE` está no manual do eValidador. O PDF 1.4 citado no
   dataset dá 404, e a página do LICITACON responde 403 a acesso automatizado (não contornado).
3. **BPS sem URL por registro**: o dicionário (`Metadados_BPS_07_04_2026.pdf`, baixado com
   autorização) resolve a etapa do preço (preço pago = praticado), mas não há página por compra.
4. **Portal de Compras Públicas**: sem PublicKey nem documentação dos recursos de itens.
5. **Tabela de evidências**: proposta em `0030_proposta_fontes_externas.sql`, não aplicada.
