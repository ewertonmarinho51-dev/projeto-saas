# Índice do PNCP no fluxo automático — origem, canal e operação

Cotação automática multiportal, PR 1 (10/11/2026). Empilhado sobre o #188
(índice) e o #187 (teto de 5, barreira do CV).

## Origem e canal

Cada referência passa a dizer **onde a compra aconteceu** (origem) e **por
onde o preço foi lido** (canal): `Origem Licitanet · Coleta via PNCP`.
A atribuição (`src/precos/portais.py`) usa o publicador declarado no PNCP
(`usuarioNome`) e o `linkSistemaOrigem`. Vale quando as duas evidências
corroboram — ou uma aponta e a outra falta. Contradição ou nenhum portal
reconhecido: **Origem não identificada**, com publicador e link guardados.
O casamento do publicador é por palavra inteira (“Licitanet Licitações
Eletrônicas” não é “Licitações-e”).

Aparece na API (`origem`, `canal`, `rotulo_origem` em `Referencia`), na
triagem do item (`apps/web/components/triagem-item.tsx`) e nas três tabelas
do relatório que imprimem a fonte (`documento_cotacao.py`).

### Reprodução no índice real (10/11/2026)

`python scripts/indexar_pncp.py rodar --uf PA --arquivo indice_pa.json --dias 20 --ate 2026-09-30 --modalidades 6 --max-chamadas 900 --max-contratacoes 150`

Uma rodada de 900 chamadas: 446 contratações descobertas, 183 do próprio
Compras.gov (fora do piloto), 263 de outras plataformas, 33 lidas, 854
resultados, **822 válidos**, 32 em quarentena (cancelado ou total
incoerente). Todos os 822 ganharam origem **corroborada**:

| Origem | Resultados | Publicador declarado | Domínio do link |
| --- | ---: | --- | --- |
| Licitanet | 547 | Licitanet Licitações Eletrônicas LTDA | licitanet.com.br |
| Licitações-e (BB) | 161 | Licitações-E BB | licitacoes-e2.bb.com.br |
| Portal de Compras Públicas | 60 | ECustomize Consultoria em Software S.A | portaldecompraspublicas.com.br |
| BNC | 36 | Bolsa Nacional De Compras - BNC | bnccompras.com |
| BLL | 10 | BLL Compras | bllcompras.com |
| Compras Pará | 5 | Compras Pará | (sem link) |
| M2A | 3 | M2A tecnologia | m2atecnologia.com.br |

Publicadores vistos sem portal registrado (sistemas municipais): AZ
Informática, Betha Sistemas — saem como “Origem não identificada”, com o
nome do publicador como evidência.

## Situação por portal

`portais.situacao_dos_portais()` é a fonte; esta tabela é o retrato de hoje.
Canal direto só conta como ativo depois de uma consulta real com preço por
item e evidência recuperável.

| Portal | Situação | O que falta para o canal direto |
| --- | --- | --- |
| Compras.gov.br | direta validada | — |
| Licitanet | via PNCP verificada | documentação oficial de leitura e prova de ganho sobre o PNCP |
| Licitações-e (BB) | via PNCP verificada | documentação oficial de leitura e prova de ganho |
| Portal de Compras Públicas | via PNCP verificada | PublicKey de parceiro (novas solicitações suspensas), termo, leiaute e preço por item em resposta real |
| BLL | via PNCP verificada | API ou exportação oficial por item, com termos |
| BNC | via PNCP verificada | API ou exportação oficial por item, com termos |
| Compras Pará | via PNCP verificada (+ atas como evidência manual) | canal autorizado com dados por item |
| M2A | via PNCP verificada | — |
| Compras BR, BBMNET, Licitar Digital | aguardando acesso/dados | resultado com origem comprovada no índice; autorização e prova real para o direto |
| Curitiba (Dados Abertos) | aguardando acesso/dados → PR do canal direto | validar a amostra de 01/11/2026 contra o dicionário e o contrato vigente |
| TCM-PA | evidência manual | base estruturada com preço por item |
| TCE-RS | aguardando acesso/dados | leiaute de `TP_RESULTADO_ITEM` e licença |
| TCE-PR | aguardando acesso/dados | dicionário com granularidade, etapa e vigência |

## Revisita: correção e cancelamento tardios

A 0042 ganhou `vigente`, `invalidado_em` e `invalidado_motivo` em
`precos_pncp_resultados`; a RPC `precos_pncp_buscar` só devolve `vigente`.
Quando a revisita (contratação com `dataAtualizacaoGlobal` novo) não
encontra mais um resultado como homologado conferível, a linha fica
`vigente = false` com o motivo — DELETE continua revogado de todos. Se
voltar a valer, o upsert a reativa. Retomada no meio de uma contratação só
invalida item a item, nunca o que a rodada anterior confirmou.

## Agendamento

Serviço `indexador-pncp` no `implantacao/docker-compose.yml`, perfil
**`indexador`** (o `--profile govconect` não o sobe). Usa a imagem do worker,
roda `python -m src.precos.pncp_indice_servico ciclo --banco` (a imagem não carrega `scripts/`) e lê a credencial de servidor
de `/etc/govdocs/indexador.env` — API e worker continuam sem ela.

```
SUPABASE_URL=https://<projeto>.supabase.co
SUPABASE_SERVICE_KEY=<chave de servidor, colada pelo dono>
INDEXADOR_UFS=PA
INDEXADOR_INTERVALO_S=21600
INDEXADOR_MAX_CHAMADAS=900
```

Cada rodada reparte o orçamento: 30% para a descoberta, o resto para a
coleta (com um orçamento só, uma UF grande gastava tudo descobrindo).

## Ordem para ligar (cada passo com o aceite do dono)

1. Aplicar a 0042 pelo ritual `revisar-migracao` (ensaio do CI + projeto
   descartável `uslaxaxomjawydqtbwkb`), depois produção.
2. Criar `/etc/govdocs/indexador.env` e subir:
   `docker compose --profile indexador up -d indexador-pncp`.
3. Conferir uma amostra do índice contra o portal (link do edital).
4. Ligar a flag `price_source_pncp_indice` (`config_app`).

## Reversão

- Fonte: `price_source_pncp_indice = 0` — sai da próxima busca, sem tocar
  referência gravada.
- Indexação: `docker compose stop indexador-pncp` — o cursor fica; voltar
  retoma de onde parou.
- Tela/relatório: origem e canal são só leitura do `bruto` já gravado;
  reverter é a imagem anterior.
