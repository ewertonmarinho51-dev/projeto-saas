# D — Pendências de acesso, licença e documentação

Nada aqui foi enviado a ninguém. Os textos de pedido são os do pacote
(`04_solicitacoes/01_EMAIL_PARCEIROS.md`); o envio é decisão sua.

## Situação em 12/11/2026

| Fonte | Situação | Como entra na pesquisa |
|---|---|---|
| **BPS** (Ministério da Saúde) | **Ligada em produção.** Licença aprovada pelo dono (CC BY-ND 3.0 do portal); 0044 aplicada; arquivo de 2026 importado (10.755 registros); 60 de 60 conferidos na API oficial; `flag_price_source_bps = on` | Índice do BPS (PR #200) |
| **TCE-RS / LicitaCon** | **Parada.** Conjunto ainda com "licença não especificada" no CKAN (conferido em 12/11/2026); leiaute de `TP_RESULTADO_ITEM` sem documento. Só órgãos do Rio Grande do Sul, que também publicam no PNCP | Nenhuma. Contato: o e-mail de dados abertos publicado no próprio conjunto (CKAN do TCE-RS) |
| Portal de Compras Públicas, LICITANET, BLL, BNC, BBMNET, Licitar Digital | **Sem canal direto, por decisão de 12/11/2026.** Já chegam pelo PNCP (Lei 14.133, art. 174) | Índice do PNCP, com "Origem <plataforma> · Coleta via PNCP" |
| Compras BR | Sem canal direto (mesma decisão); nenhum resultado no índice até 12/11/2026 | Pelo PNCP, quando aparecer |
| TCM-PA | Sem canal direto. Não há base estruturada: o mural respondeu HTTP 500 e não há página de dados abertos (12/11/2026). Os municípios paraenses publicam no PNCP | Índice do PNCP; atas do mural como evidência manual |

### Por que as plataformas privadas não terão canal direto

Medido no índice do PNCP em produção em 12/11/2026 (resultados homologados
vigentes, todas as UFs indexadas):

| Plataforma (publicador no PNCP) | Resultados | Contratações | UFs |
|---|---|---|---|
| Portal de Compras Públicas ("ECustomize") | 1.658 | 54 | 9 |
| Licitanet | 1.166 | 41 | 10 |
| BLL Compras | 63 | 19 | 8 |
| Compras Pará | 47 | 10 | 1 |
| BNC | 43 | 13 | 6 |
| Licitar Digital | 33 | 11 | 4 |
| BBMNET ("Novo BBMNET Licitações") | 30 | 11 | 6 |

A contratação dessas plataformas é publicada no PNCP por obrigação legal, e o
preço chega pela via oficial, com o link do edital. Canal direto pediria, de
cada empresa, chave de API, termo de parceria e licença — o Portal de Compras
Públicas suspendeu novas solicitações de PublicKey — para trazer em boa parte
as mesmas compras, que a fusão por `idCompra` contaria uma vez.

**O que limita a cobertura delas é o indexador, não a integração.** Em
12/11/2026 havia mais de 1.800 contratações do Pará esperando leitura na fila
do índice (Portal de Compras Públicas 902, Compras Pará 372, BNC 218,
Licitanet 213, KP Sistemas 204). O serviço `indexador-pncp` existe no
`docker-compose` (perfil `indexador`) e lê a fila a cada 6 h quando ligado.

A origem de cada plataforma, para tela e relatório, mora em
`src/precos/portais.py`; `src/precos/fontes_externas.py` ficou só com as bases
que têm trilha de licença (BPS e TCE-RS).

## Para ligar uma fonte nova (quando houver resposta)

1. Guardar o documento da licença e citá-lo em `prova_licenca` do registro (`fontes_externas.py`);
   mudar `licenca` para `APROVADA`.
2. TCE-RS: preencher `etl_tce_rs.RESULTADO_CONFIRMADO` só com os códigos cujo significado está no
   leiaute, citando a página.
3. `mapeamento_confirmado=True`, com prova em teste (linha real por código).
4. Criar o índice da fonte por migração própria, pelo ritual (`revisar-migracao`), com sua
   aprovação — como a 0044 do BPS.
5. Importar e conferir à mão uma amostra contra a fonte oficial.
6. Ligar a flag `price_source_<id>`.
7. Medir o ganho em preços **válidos e distintos** contra a linha de base, em itens fixos.

## Decisões que são suas

* Enviar, ou não, o pedido de licença e de leiaute ao TCE-RS.
* Reabrir canal direto com alguma plataforma privada — exigiria pedido de API, termo e licença à
  empresa e prova de que ela traz preço que o PNCP não traz.
