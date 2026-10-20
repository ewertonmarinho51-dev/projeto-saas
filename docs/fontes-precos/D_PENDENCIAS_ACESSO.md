# D — Pendências de acesso, licença e documentação

Nada aqui foi enviado a ninguém. Os textos de pedido são os do pacote
(`04_solicitacoes/01_EMAIL_PARCEIROS.md`); o envio é decisão sua.

## Por fonte

| Fonte | O que falta para habilitar | Quem pode destravar | Situação em 20/10/2026 |
|---|---|---|---|
| **TCE-RS / LicitaCon** | (1) licença de reúso em SaaS; (2) leiaute oficial com o significado de `TP_RESULTADO_ITEM` (A, D, F, R, N, vazio), `CD_TIPO_FASE_ATUAL` (PUB, ADH, EPU, HAP) e `CD_TIPO_MODALIDADE` | contato de dados abertos publicado no dataset do TCE-RS (CKAN) | Dataset sem licença no CKAN. O manual `eValidador_LicitaCon_Manual_Leiaute_1.4.pdf` citado no dataset dá **404**; a página do LICITACON responde **403** a acesso automatizado (não contornado). O diagrama `diagrama_licitacao.pdf` (2022) foi baixado com sua autorização: confirma as chaves e que o documento do item é o do vencedor, mas **não traz os códigos**. |
| **BPS** | (1) licença; (2) decidir se a falta de URL por registro é aceitável (o rastro seria arquivo oficial + `co_seq_bps`): é o único motivo que prende 10.001 das 10.609 linhas | contato publicado no dicionário do BPS; a decisão (2) é sua | Dataset sem licença. Só medicamentos. Etapa do preço **resolvida** pelo dicionário: "preço pago… efetivamente negociado" = praticado. |
| **Portal de Compras Públicas** | PublicKey, documentação dos recursos de itens e resultados, termo de reúso, exemplo real de resposta com valor homologado | formulário de Relações Institucionais (link no pacote) | Adaptador desconectado no código; nenhum endpoint escrito. |
| LICITANET, BLL, BNC, Compras BR, BBMNET, Licitar Digital | API ou exportação de **leitura** de resultados por item, termo e custo | canais públicos listados no pacote | Registro desabilitado; nenhum código. |
| TCM-PA | base estruturada de itens e resultados municipais | mural/ouvidoria do TCM-PA | Registro desabilitado. |

## Para ligar uma fonte (quando houver resposta)

1. Guardar o documento da licença e citá-lo em `prova_licenca` do registro (`fontes_externas.py`);
   mudar `licenca` para `APROVADA`.
2. TCE-RS: preencher `etl_tce_rs.RESULTADO_CONFIRMADO` só com os códigos cujo significado está no
   leiaute, citando a página. BPS: definir a etapa do preço a partir do dicionário.
3. `mapeamento_confirmado=True`, com prova em teste (linha real por código).
4. Aplicar a tabela (`0030_proposta_fontes_externas.sql` → `supabase/migrations/`) pelo ritual de
   migração, com sua aprovação.
5. Rodar `scripts/etl_fontes_precos.py relatorio` e conferir à mão 10 evidências por fonte contra a
   página oficial (o link do TCE-RS abre a licitação; o valor do item precisa ser conferido nela).
6. Escrever o adaptador de busca sobre o índice e ligar a flag `price_source_<id>` só em staging.
7. Medir o ganho em preços **válidos e distintos** contra a linha de base, em itens fixos.

## Decisões que são suas

* Enviar os pedidos de licença e documentação (TCE-RS, BPS, Portal de Compras Públicas, privados).
* Aprovar, ou não, a tabela proposta.
* Aceitar, ou não, evidência de nível licitação (TCE-RS) e sem URL por registro (BPS).
