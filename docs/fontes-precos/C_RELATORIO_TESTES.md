# C — Relatório de testes

Executado em 20/10/2026, Windows, Python 3.11 (`.venv311`), sem rede nos testes.

## Suíte do projeto

```
python -m pytest -q
3166 passed, 354 skipped in 281.20s
```

Antes desta entrega: 3.146 passaram e 354 pulados. A diferença são as 20 provas novas; nenhuma prova
antiga mudou ou quebrou. Os 354 pulados são os mesmos de antes (pedem Postgres de ensaio ou motor de
IA real).

## Provas novas — `tests/test_fontes_externas.py` (20)

Linhas reais de `tests/fixtures/fontes_precos/`, copiadas dos arquivos oficiais de 20/10/2026. A única
linha inventada é a do vencedor pessoa física, com CPF sintético.

| Prova | O que garante |
|---|---|
| nenhuma fonte habilitada, nem com a flag ligada | o registro nasce desligado |
| só liga com licença + prova + mapeamento + flag | a trava dupla; erro ao ler a flag não liga |
| fontes da pesquisa continuam Compras.gov e PNCP | zero regressão na busca |
| decimal na escala da fonte | `5029.73`, `1.0393` (4 casas), `0.0150 × 3 = 0.0450`; recusa float, NaN, `1e5`, `1_000`, `+5` |
| CPF não segue, CNPJ segue | LGPD |
| só resultado comprovado é validado | estimado, proposta e desconhecido ficam em quarentena; total incoerente; URL não HTTPS |
| TCE-RS lê o homologado real e segura tudo | pasta AZ de Barra Funda: R$ 9,14 × 70 = R$ 639,80, link da licitação, estimado guardado só como atributo; item só-estimado contado e não materializado |
| TCE-RS com código confirmado, só ele passa | com "A" mapeado, a pasta AZ valida; a lidocaína com resultado "R" (Novo Hamburgo) e o item sem código seguem presos |
| vencedor pessoa física | o CPF não aparece no registro |
| leiaute mudado | `ValueError` com as colunas que faltam |
| BPS lê o texto com 4 casas | palivizumabe R$ 5.029,73 × 723 = R$ 3.636.494,79; bezafibrato R$ 1,0393 |
| BPS judicial e leilão | motivo próprio (somatropina, evolocumabe) |
| BPS equivalência | só mesmo CATMAT na mesma unidade |
| reprocessar não duplica; parecido não funde | possível duplicata exige CNPJ, valor idêntico e data próxima |
| URL só das fontes registradas | HTTP, outro host, outro bucket do S3 e URL com credencial recusados |
| download tenta de novo só em 5xx | 503 repete com recuo; 404 não repete; SHA-256 confere |
| download recusa redirecionamento e tamanho | redirecionar para fora, `Content-Length` grande e corpo maior que o declarado |
| ZIP hostil | `../`, caminho absoluto, `C:`, extensão `.py`, bomba de compressão, link simbólico |
| Portal de Compras Públicas | `pesquisar` falha com o motivo, sem abrir rede |
| relatório de staging nas linhas reais | contagens, amostra e ausência de CPF no JSON |

## Teste de mutação (dente das provas)

30 mutantes, um por regra, cada um aplicado sozinho contra `tests/test_fontes_externas.py`:
**30 mortos, 0 sobreviventes.** Na primeira rodada sobreviveu um: desligar a regex do formato
"ponto". O `Decimal()` sozinho já recusava os casos testados, mas aceitaria `1e5`, `1_000` e `+5`. A
prova ganhou esses casos e passou a matá-lo.

Mutantes, por área:
- **registro:** flag sozinha liga; dispensa a prova da licença; erro de flag liga.
- **decimal:** aceita float; arredonda a 2 casas; regex do formato "ponto" desligada; regex do "br" desligada.
- **quarentena e privacidade:** CPF segue adiante; estimado validado; total incoerente aceito; URL HTTP aceita.
- **TCE-RS:** código desconhecido não prende; "A" presumido homologado; estimado no lugar do homologado; lê só o documento cru; só-estimado materializado.
- **BPS:** judicial sem motivo; leilão sem motivo; equivalência só por CATMAT truncado.
- **dedup:** funde sem CNPJ; sem janela de data; reprocessamento duplica.
- **ZIP:** aceita `..`; aceita bomba; aceita link simbólico.
- **download:** segue redirecionamento; repete 404; ignora o teto no streaming; aceita outro bucket.
- **Portal de Compras Públicas:** abre rede.

## Rodada sobre os arquivos oficiais completos

```
python scripts/etl_fontes_precos.py relatorio --fonte tce_rs --zip 2026.csv.zip --termos "papel a4" caneta ...
python scripts/etl_fontes_precos.py relatorio --fonte bps    --zip 2026_csv.zip --termos dipirona ...
```

* TCE-RS: 452.295 evidências em ~17 s de leitura em streaming; 0 validadas; quarentena única,
  `CODIGO_DE_RESULTADO_SEM_SIGNIFICADO_CONFIRMADO` + `ETAPA_DO_PRECO_NAO_COMPROVADA`. Nenhuma linha com
  outro defeito: unidade, quantidade, total e link estavam todos presentes.
* BPS: 10.609 evidências; 0 validadas; `ETAPA_DO_PRECO_NAO_COMPROVADA` e `SEM_URL_OFICIAL_DO_REGISTRO`
  em todas; 607 `COMPRA_POR_ORDEM_JUDICIAL`; 11 `MODALIDADE_SEM_DISPUTA_DE_PRECO`; 1 `SEM_UNIDADE`.
* Os 15 testes do PoC do pacote (`05_poc`) também passam neste ambiente.

## O que NÃO foi testado (e não se afirma)

* Conferência manual de 10 evidências por fonte contra a página oficial. O link do TCE-RS abre
  (HTTP 200, "LicitaCon Cidadão"), mas a página é dinâmica e o valor do item não foi conferido nela.
* Tabela no Postgres, RLS da proposta e desempenho da busca no índice (a tabela não existe).
* Latência de retirar da cesta antes e depois: esta entrega não toca nesse caminho, então não houve o
  que medir.
* Ganho em preços válidos e distintos: hoje é zero por construção, porque nenhuma fonte está habilitada.
