# B — Implementação realizada

Primeira entrega do pacote "Fontes de Preços" (20/10/2026): **infraestrutura e ETL de staging,
testados sobre os arquivos oficiais reais, com toda fonte nova desligada.** Nenhuma pesquisa,
cesta, triagem ou relatório mudou de comportamento.

## O que entrou

| Arquivo | Para quê |
|---|---|
| `src/precos/evidencia.py` | Contrato canônico: `TipoPreco` (o `price_kind`), `Evidencia`, motivos de quarentena estáveis, `ler_decimal` estrito (texto → `Decimal` na escala da fonte; recusa float, NaN, expoente, sublinhado), `cnpj_ou_nada` (CPF não segue), `conferir` (unidade, quantidade, preço > 0, total = unitário × quantidade, etapa comprovada, URL HTTPS). Ponte `NATUREZA_DO_TIPO` para as naturezas que a cesta já trata, sem migração. |
| `src/precos/fontes_externas.py` | Registro das fontes novas (TCE-RS, BPS, Portal de Compras Públicas, LICITANET, BLL, BNC, Compras BR, BBMNET, TCM-PA, Licitar Digital). Flags `price_source_<id>`, desligadas por padrão. **Trava dupla**: a fonte só fica habilitada com a flag ligada, licença `APROVADA` com prova citada e mapeamento confirmado. Licença e mapeamento moram no código versionado, então a tela não liga a fonte sozinha. |
| `src/precos/arquivos.py` | Download com lista de hosts (também depois de redirecionar), só HTTPS, teto de bytes (no cabeçalho e durante o streaming), timeout, nova tentativa só em 429/5xx e falha de rede, arquivo `.parcial` e SHA-256. ZIP conferido antes de ler: zip-slip, link simbólico, entrada cifrada, extensão, tamanho, taxa de compressão. Leitura em streaming, sem extrair para o disco. |
| `src/precos/etl_tce_rs.py` | Parser do LicitaCon 2026: junta `licitacao.csv` e `item.csv` pela chave conferida, lê o cabeçalho com nomes repetidos por posição, lê o **valor homologado da coluna própria**, guarda o estimado só como atributo e conta o item que só tem estimado sem materializá-lo. Toda linha fica em quarentena (`CODIGO_DE_RESULTADO_SEM_SIGNIFICADO_CONFIRMADO`) até `RESULTADO_CONFIRMADO` ser preenchido com o leiaute. |
| `src/precos/etl_bps.py` | Parser do BPS 2026 (CSV, não o JSON com float). Etapa do preço **PRATICADO**, citando o dicionário oficial ("Preço pago por unidade do item adquirido… valor efetivamente negociado"). Quarentena por falta de URL por registro; motivo próprio para compra judicial e leilão. Equivalência só entre o mesmo CATMAT na mesma unidade de fornecimento. |
| `src/precos/dedup_fontes.py` | Chave forte (fonte + id) para reprocessamento. Possível duplicata com as fontes atuais (mesmo CNPJ de fornecedor, valor `Decimal` idêntico, data a até 30 dias) **só sinaliza, nunca funde**. |
| `src/precos/pcp.py` | Adaptador do Portal de Compras Públicas **desconectado**: sem endpoint, header ou payload; `pesquisar` devolve falha "aguardando credenciamento" e não abre rede. |
| `scripts/etl_fontes_precos.py` | Job de bancada: `baixar` (só URL registrada) e `relatorio` (streaming, amostragem por reservatório com semente fixa, contagem por termo). **Não grava no banco.** |
| `docs/fontes-precos/0030_proposta_fontes_externas.sql` | Proposta de tabelas (snapshot, evidências, execuções) com RLS, sem DELETE e sem `tenant_id`. **Não aplicada**, e fora de `supabase/migrations/` de propósito. |
| `docs/fontes-precos/mapeamento_fontes.yaml` | Mapeamento real das colunas, com hashes dos snapshots e códigos observados (significado pendente). |
| `tests/test_fontes_externas.py` + `tests/fixtures/fontes_precos/` | 20 provas com linhas reais dos dois arquivos oficiais. |

## O que NÃO entrou, e por quê

* **Nenhuma fonte ligada.** Falta licença em todas; no TCE-RS falta o leiaute dos códigos; no BPS falta decidir se o arquivo oficial + `co_seq_bps` basta como evidência sem URL por registro.
* **Nenhuma migração aplicada.** A tabela é proposta; aplicar exige o ritual de migração e a sua aprovação.
* **Nenhum adaptador de busca sobre o índice.** Ele lê a tabela proposta, que ainda não existe. Ligá-lo
  a `fontes_padrao()` é o último passo, depois da licença.
* **Nenhuma UI nova.** Fonte desligada não tem o que mostrar; filtros de fonte, UF e situação do dado
  entram com a primeira fonte habilitada, para não mexer na tela à toa.
* **Nenhum código para LICITANET, BLL, BNC, Compras BR, BBMNET, TCM-PA ou Licitar Digital** além do
  registro desabilitado. Os pedidos de acesso estão em `D_PENDENCIAS_ACESSO.md`.
* **Nenhuma alteração** em `compras_gov.py`, `pncp.py`, `busca.py`, `cesta.py`, `estatistica.py`,
  `saneamento.py`, no relatório ou na UI.

## Números reais da rodada de staging (20/10/2026)

| | TCE-RS 2026 | BPS 2026 |
|---|---|---|
| arquivo | 258.492.699 bytes, sha256 `45ee32c1…f4fce2` | 903.596 bytes, sha256 `60ed6b06…b2c137` |
| linhas brutas | 1.067.159 itens em 128.806 licitações | 10.609 |
| com preço | 452.295 com valor homologado positivo (614.864 só com estimado) | 10.609 |
| unitário × quantidade = total | 100% | 100% |
| com URL oficial | 452.295 (link da licitação, não do item) | 0 |
| fornecedores CNPJ distintos | 11.367 | 508 |
| **validadas** | **0**: todas presas pelo código de resultado sem significado | **0**: etapa comprovada (preço pago), mas sem URL por registro; **10.001 linhas presas só por isso**; 607 judiciais e 11 leilões com motivo próprio |
| linhas que casam com "papel a4" / "caneta" / "dipirona" | 1.564 / 2.652 / 510 | 0 / 21 / 148 |

As contagens por termo medem o ganho **possível**, não o ganho em preços válidos e distintos, que hoje
é zero por construção. A métrica certa (`valid_unit_prices_count`, `distinct_awards_count`) só tem
valor depois do leiaute e da licença.
