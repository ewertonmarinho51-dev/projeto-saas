# SINAPI — custos de referência de engenharia (piloto: Pará)

23/11/2026. Domínio em `src/precos/sinapi.py`, importação em `src/precos/sinapi_servico.py`, migração `0046_precos_sinapi_indice.sql` (não aplicada), rota `GET /api/v1/precos/referencias/sinapi`, tela `/app/precos/referencias/sinapi`.

## O que é, e o que não é

O SINAPI (CAIXA/IBGE) é a referência de custos de obra e serviço de engenharia (Lei 14.133, art. 23, § 2º, I; Decreto 7.983/2013). O preço de insumo é mediana coletada pelo IBGE; o custo de composição é calculado pela CAIXA.

**Não é preço de compra.** Por isso o SINAPI não entra em `fontes_padrao()`, não alimenta a cesta, o teto de 5 nem o CV da pesquisa de preços. Tem tabela, rota e tela próprias. A rota e a tela dizem isso em toda resposta. Há prova (`test_sinapi_nunca_entra_na_cesta_de_precos_de_compras`): mesmo com a consulta liberada, `cotacoes._fontes_padrao()` não traz o SINAPI.

## A publicação oficial (conferida em 23/11/2026)

Desde 2025 a CAIXA publica **um arquivo mensal nacional**:

`https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/SINAPI-AAAA-MM-formato-xlsx.zip`

O de 10/2026 tem 16.083.991 bytes, SHA-256 `2e99cde7…7c66d4`, `Last-Modified` 12/11/2026. Dentro dele há quatro planilhas; a usada é `SINAPI_Referência_2026_10.xlsx`, com seis abas de preço e uma coluna por UF:

| Aba | Tipo | Regime |
| --- | --- | --- |
| ISD / ICD / ISE | insumo | sem desoneração / com desoneração / sem encargos sociais |
| CSD / CCD / CSE | composição | idem |

- **Mês de Referência:** na linha 3 de cada aba. Ele é conferido contra a competência pedida, e arquivo de outro mês é recusado.
- **Encargos sociais da UF:** horista e mensalista, nas linhas 6 e 7. Ficam gravados na versão.
- **Insumo:** classificação, código, descrição, unidade e origem do preço (C = coletado; CR = coeficiente de representatividade).
- **Composição:** grupo, código, descrição, unidade e, por UF, o custo e o %AS (parte do custo obtida com preço de São Paulo por falta de preço na UF).
- **Código da composição:** vem numa fórmula `HYPERLINK(...;104658)`, e o valor em cache é **0**. O código é lido da fórmula.
- **Números:** são constantes no XML. O `float` lido é convertido pelo `repr`, que devolve o texto gravado (269.08), nunca `Decimal(float)`.

## O que é recusado (contado, nunca gravado)

| Motivo | PA, 10/2026 |
| --- | --- |
| Preço em branco ("não houve coleta mínima de preços no mês") | 2.742 |
| Preço ou custo **zero** (composições "sem custo"; a CAIXA já publicou zerados e corrigiu depois — Notas SINAPI) | 6.582 |
| Código não numérico, descrição ou unidade vazia | 0 |

O banco reforça: `valor > 0`, código só dígitos, aba da lista, arquivo só dos relatórios mensais da CAIXA.

## Versão e retificação

- **Versão:** é a tripla competência + UF + SHA-256 do arquivo.
- **Idempotência:** reimportar o mesmo arquivo não faz nada.
- **Retificação:** a CAIXA republica a competência; isso gera outro SHA e, portanto, versão nova. As linhas da versão nova nascem invisíveis e só passam a valer quando a versão é publicada inteira. A anterior fica guardada, com as mesmas `chave_linha` (`competência:UF:tipo:regime:código`).
- **Arquivo que encolheu:** com menos da metade dos registros válidos da versão vigente, o arquivo é **recusado** e a anterior continua valendo.

Cada linha guarda:

- a aba e a **linha da planilha oficial**;
- o SHA-256 do arquivo e o endereço dele;
- o hash da linha e a versão do leitor.

## Medição (bancada, 23/11/2026)

| | |
| --- | --- |
| Registros válidos do PA (6 abas) | 37.920 |
| Insumos com preço, por regime | 4.124 de 5.038 |
| Composições com custo, por regime | 8.516 de 10.710 |
| Importação em memória | 14,6 s |
| Reimportação do mesmo arquivo | 0 linhas lidas (`ja_publicado`) |
| Amostra relida célula a célula na planilha oficial | 200 de 200 iguais (código, unidade e valor na coluna do PA) |

Exemplos (PA, 10/2026, sem desoneração):

| Código | Descrição | Unidade | Custo | Origem |
| --- | --- | --- | --- | --- |
| 1379 | Cimento Portland composto CP II-32 | kg | R$ 1,08 | coletado; ISD, linha 1169 |
| 104658 | Piso podotátil de concreto | m² | R$ 189,32 | CSD, linha 11 (com desoneração R$ 186,58; sem encargos R$ 169,00) |

Reproduzir:

```bash
python -m src.precos.sinapi_servico conferir --competencia 2026-10 --uf PA --amostra 200
python -m src.precos.sinapi_servico buscar --competencia 2026-10 --uf PA --termos "cimento portland" --tipo insumo
```

O download vai do endereço oficial, com pote de cookies próprio da sessão. Em 23/11/2026 a primeira tentativa caiu num laço de 302 do balanceador da CAIXA; as seguintes, com os mesmos cabeçalhos, responderam 200. Por isso o serviço tenta de novo até 3 vezes, **só** em erro de redirecionamento.

## O que falta para ligar (em ordem)

1. **Licença** — decisão do dono. A publicação é oficial e obrigatória, mas a página e o arquivo não declaram licença de reúso. Registrar a decisão em `fontes_externas.REGISTRO["sinapi"].prova_licenca`, com `licenca=APROVADA`. Sem isso, a flag não abre a consulta.
2. **0046** — aplicar pelo ritual: ensaio no descartável, revisão do `revisor-de-banco-e-seguranca` e autorização.
3. **Importação** — importar o PA com a credencial de servidor no ambiente:
   `python -m src.precos.sinapi_servico importar --competencia 2026-10 --uf PA --banco`
4. **Conferência** — rodar `conferir` no servidor e comparar uma amostra à mão com a edição oficial.
5. **Ligar** — `flag_price_source_sinapi = on`. Reverter é desligar a flag.

## Limites

- **Sem composição analítica:** só o custo unitário publicado; os coeficientes do analítico não são importados.
- **Sem critérios do órgão:** a consulta não aplica BDI, fonte alternativa (art. 23, § 3º) nem critérios do órgão. Isso é do orçamento de engenharia, não desta tela.
- **Relatório de engenharia:** o relatório de cotação de compras não mostra SINAPI, de propósito. O orçamento de engenharia como documento é trabalho separado.
- **Busca:** a do banco é texto completo do PostgreSQL (`websearch_to_tsquery` + `ts_rank`). A medição acima usou a busca em memória por termos, que só aproxima a ordenação.
