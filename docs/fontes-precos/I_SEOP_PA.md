# SEOP-PA — Planilha Padrão em PDF, importação supervisionada

23/11/2026. Domínio em `src/precos/seop.py`, importação em `src/precos/seop_servico.py`, migração `0047_precos_seop_referencia.sql` (não aplicada), rota `GET /api/v1/precos/referencias/seop`, tela `/app/precos/referencias/seop`. A flag `referencia_custos_seop_pa` nasce desligada.

## O que é

É a tabela de custos de obras do Estado do Pará. Como o SINAPI, é **custo de referência de engenharia, não preço de compra**: não entra na cesta. O órgão pode adotá-la no lugar do SINAPI nas condições do art. 23, § 3º, da Lei 14.133. Essa decisão é do orçamentista e não deste código.

## A publicação (conferida em 23/11/2026)

A página `https://seop.pa.gov.br/planilha-de-custo-0` só traz **PDF**, gerado do Excel e com texto extraível. Para outubro de 2026 são dois arquivos, ambos de 02/10/2026:

| Arquivo | Páginas | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `plainha_padrao_outubro_2026.pdf` (Planilha Padrão) | 48 | 2.199.935 | `62cfffd2…` |
| `cpus_outubro_2026.pdf` (composições analíticas) | 511 | 29.939.848 | `dd870425…` |

O cabeçalho diz **"PLANILHA PADRÃO - OUTUBRO 2026 (SEM BDI) - SEM DESONERAÇÃO"** e traz as leis sociais: horista 119,42% e mensalista 72,70%. Tudo isso fica gravado na versão e aparece em cada linha.

O nome dos arquivos não segue padrão (`plainha_…`, `planilha_padrao_seop_…`, `cpus_seop_…`). Por isso o endereço é informado a partir da página oficial e conferido: só `https://seop.pa.gov.br/sites/default/files/<nome>.pdf`.

## Como a supervisão funciona

1. **Leitura.** Cada linha sai com item, código de 6 dígitos, descrição (inclusive quando quebrada em duas linhas), unidade, valor e a **página** do PDF. Valor zero e código repetido são recusados e contados, com a página.
2. **Confronto.** Cada linha é comparada com a composição de mesmo código no PDF analítico: mesmo código, mesma unidade e mesmo valor.
3. **Em conferência.** A versão é gravada **em conferência**, com o relatório (`seop_servico relatorio`), e não aparece na consulta.
4. **Aprovação.** Uma pessoa aprova (`seop_servico aprovar --sha … --por "Nome"`). Com divergência no confronto, a aprovação exige `--aceitar-divergencias`. O banco recusa versão publicada sem `aprovado_por` e `aprovado_em`, por uma restrição com nome próprio que a conferência da 0047 exige.
5. **Republicação.** Republicar a competência gera versão nova, que só vale quando aprovada. A anterior fica guardada. Uma republicação com menos da metade das linhas da vigente é recusada.

## Medição sobre os PDFs reais

| | |
| --- | --- |
| Linhas lidas / válidas | 1.320 / 1.319 |
| Recusada | 1: item 1.18, código 000006, "Mobilização e Desmobilização", valor 0,00, página 1 |
| Grupos | 33, com a numeração dos itens contínua em todos (nenhum item pulado) |
| Composições no analítico | 1.360 |
| Confronto planilha × analítico | **1.319 de 1.319 iguais** (código, unidade, valor) |
| Tempo | planilha 1,7 s; analítico 5,5 s |

Exemplos:

| Código | Descrição | Unidade | Valor | Item | Página |
| --- | --- | --- | --- | --- | --- |
| 060046 | Alvenaria tijolo de barro a cutelo | m² | R$ 141,99 | 8.4 | 7 |
| 280026 | Servente com encargos complementares | h | R$ 27,78 | 3.26 | 3 |

Reproduzir, em memória:

```bash
python -m src.precos.seop_servico buscar --competencia 2026-10 --pdf-planilha plainha_padrao_outubro_2026.pdf --pdf-analitico cpus_outubro_2026.pdf --termos "alvenaria tijolo"
```

## Para ligar (em ordem)

1. Aplicar a 0047 pelo ritual: ensaio no descartável, revisão do `revisor-de-banco-e-seguranca` e autorização.
2. Importar com a credencial de servidor no ambiente:
   `python -m src.precos.seop_servico importar --competencia 2026-10 --banco --planilha <url> --analitico <url>`
3. Ler o relatório e **aprovar**, com o nome de quem conferiu.
4. Ligar `flag_referencia_custos_seop_pa`. Reverter é desligar a flag.

## Limites

- Só o custo unitário da Planilha Padrão. Os coeficientes do analítico servem para conferir e não são gravados.
- A licença de reúso não está declarada na página. A publicação é oficial e aberta; a decisão de exibir num SaaS fica com o dono, como no SINAPI.
- O leitor depende do leiaute do PDF (gerado do Excel). Um leiaute novo cai em recusa ou em divergência no confronto, nunca em publicação automática.
