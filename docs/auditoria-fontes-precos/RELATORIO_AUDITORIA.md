# Auditoria técnica — autenticidade e rastreabilidade das fontes de preços do GovConnect

Data: 18/10/2026 · Versão em produção auditada: v1.9.7 (`4f979ca`)
Modo: somente leitura. Nenhum código, dado ou configuração foi alterado.
Banco consultado: produção (Supabase), apenas `SELECT`.
Fontes externas consultadas: API Dados Abertos do Compras.gov.br e portal
público "Acompanhar Contratação" do Compras.gov.br.
Evidências brutas: [`evidencias/`](evidencias/), com a amostra, a resposta
da reconsulta, os scripts e a tabela B gerada a partir deles.

---

## A. Diagnóstico geral

### A.1 Como o sistema obtém as cotações

```
Item da pesquisa (descrição, unidade, CATMAT opcional)
  │
  ├─ camada semântica (IA, opcional) ── só PROPÕE termos de busca extras
  │     src/precos/semantica.py · sugerir_termos → amplia candidatos, não cria preço
  │
  ▼
Adapters determinísticos (HTTP direto às APIs oficiais)
  ├─ Compras.gov.br — Preços Praticados   src/precos/compras_gov.py
  │     /modulo-pesquisa-preco/1_consultarMaterial (por CATMAT/PDM)
  │     → _referencia_de_preco_praticado(bruto): campos copiados 1:1 do JSON
  ├─ Compras.gov.br — Itens de Contratações (Lei 14.133)   mesmo arquivo
  ├─ PNCP (enriquecimento/comprovação)    src/precos/pncp.py
  └─ Cotação direta / importação de planilha   src/precos/importacao.py
  │
  ▼
Referencia (src/precos/modelo.py): guarda o JSON BRUTO + raw_hash (SHA-256)
  │
  ▼
Normalização de unidade (src/precos/unidades.py) → valor_unitario_normalizado
Matching/comparabilidade (src/precos/matching.py) → score, identidade
Triagem pré-cesta (src/precos/saneamento.py) → status + motivo
Análise Jev (IA, src/precos/decisoes.py) → só classificação; nunca aceita sozinha
  │
  ▼
Cesta (src/precos/estatistica.py, cesta.py) → média/mediana, teto de 15
  │
  ▼
Banco: pesquisa_preco_referencias (1 linha por referência, com bruto)
  │
  ▼
Tela (src/ui/cotacoes_ui.py) e relatório (relatorio_view.projetar →
documento_cotacao.py / relatorio.py): leem as MESMAS linhas gravadas;
links calculados por src/precos/links.py, sem rede e sem IA.
```

### A.2 Fontes usadas em produção (medido no banco)

| Fonte | Referências | Natureza | Período de coleta |
|---|---|---|---|
| Compras.gov.br — Preços Praticados | **5.741** (100%) | praticado | 15 a 18/10/2026 |
| Compras.gov.br — Itens de Contratações | 0 | — | — |
| PNCP | 0 | — | — |
| Cotação direta / planilha importada | 0 | — | — |

São 3 pesquisas, 16 itens e 766 compras distintas, todas de 2025–2026.
**Nenhum registro sintético, de teste ou de fonte desconhecida** foi
encontrado: 0 `id_externo` fora do padrão numérico, 0 nomes "teste" ou
"fictício", 0 `fonte_id` fora das quatro registradas. Nenhum módulo de `src/`
importa os dublês de teste (`ClientePrecosFalso`, fixtures).

### A.3 Mecanismos de verificação que já existem

1. **Resposta bruta preservada:** `bruto` em 5.741 de 5.741 linhas. 0 linhas sem
   valor, sem identificador da compra ou com `bruto` vazio.
2. **Impressão digital da resposta (`raw_hash`):** recalculada dentro do banco
   (SHA-256 do JSON canônico) para as 5.741 linhas: **5.741 conferem, 0 divergem.**
3. **Colunas iguais ao bruto:** 12 campos comparados em todas as linhas
   (valor, quantidade, unidade, idCompra, idItem, órgão, fornecedor, CNPJ,
   data, UF, descrição, CATMAT): **0 divergências.**
4. **IA sem poder de decisão:** em produção, a análise Jev foi chamada
   1.123 vezes. Todas terminaram em `manual_review`, com
   `automatic_acceptance = false`. A resposta é só classificação fechada
   ("compatible", "different_unit"…) com probabilidade e nota 0–4. Não há
   campo de texto livre, preço, identificador, órgão ou URL vindos do modelo.
5. **Estimativas reproduzíveis:** o `preco_estimado` dos 16 itens foi
   recalculado em SQL a partir das referências da cesta e bate em todos.
   No perfil federal, o valor adotado é a mediana quando a média a supera (teto).
6. **Links deterministas:** `links.py` monta o endereço só a partir de
   identificador oficial gravado, aceita só https em hosts oficiais e nunca
   inventa ata.

### A.4 Nível de confiabilidade demonstrado

* **Autenticidade: alta.**
  * Amostra de 42 linhas (36 registros distintos, 3 pesquisas, 6 tipos de
    produto, modalidades pregão, dispensa e inexigibilidade, preços de
    R$ 0,10 a R$ 4.415,00, incluindo os extremos e os suspeitos).
  * Os 36 foram localizados na API oficial e batem nos 9 campos comparados,
    com 0 divergências.
  * 6 deles foram conferidos item a item no portal público: fornecedor
    adjudicado e valor iguais.
  * 2 compras foram conferidas também no nível da compra (órgão, número e
    situação).
* **Adequação ao item: insuficiente em parte das cestas.** Preços reais de
  produtos **diferentes** entraram em cestas: papel A3 e papel offset na cesta
  de papel A4, grampeador cirúrgico na de grampeador de mesa. O problema não
  é de autenticidade (o preço existe e está certo); é de comparabilidade.
* **Rastreabilidade no documento: falha em 5,2% das referências**
  (identificador perdido por zero à esquerda; ver C-2).

---

## B. Tabela de cotações auditadas

Critério de classificação:
* **Autenticidade:** VERIFICADA quando o registro foi localizado na fonte
  oficial e os 9 campos conferem (valor, quantidade, unidade, CNPJ, data,
  modalidade, nº do item, UASG, órgão).
* **Adequação ao item:** avaliação separada, a partir da descrição que a
  própria fonte dá.

O link da coluna "Contratação" aponta para a página do **item** no portal.
Nas linhas marcadas "16 dígitos", o link usa o identificador com o zero
recolocado, como a fonte o grava em `idCompraItem`. O relatório do GovConnect
hoje **não** imprime esse link.

Resumo: 36 de 36 VERIFICADAS, 0 PARCIALMENTE VERIFICADAS, 0 INVÁLIDAS,
0 NÃO VERIFICADAS. Quanto à adequação: 6 inadequadas dentro da cesta ou em
revisão, 3 inadequadas já rejeitadas pelo próprio sistema, 4 duvidosas e
23 adequadas (uma delas só depois da conversão de unidade).

Correção posterior: a linha 2 (13021849) foi classificada como "adequada"
na primeira versão deste relatório. A descrição completa da fonte, lida
durante a correção da fase 1, diz "cor: colorido", e o item pede papel
branco. Ela foi reclassificada para INADEQUADA.

| Nº | Registro (idItemCompra) | Onde aparece no GovConnect | Contratação (link original) | Valor no GovConnect | Valor na fonte | Divergências | Autenticidade | Adequação ao item | Evidência |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 12728225 | aquisição (17/10) item 1 (selected) | [98788505900532026 · item 162](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/162?compra=98788505900532026) | R$ 45,20 / EMB | R$ 45,20 / EMB | nenhuma (9 campos) | VERIFICADA | INADEQUADA — papel A3 (420×297) na cesta de papel A4 | API Dados Abertos (18/10) + portal, item a item |
| 2 | 13021849 | aquisição (17/10) item 1 (selected) | [10231205000122026 · item 2](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/2?compra=10231205000122026) | R$ 7,50 / EMB | R$ 7,50 / EMB | nenhuma (9 campos) | VERIFICADA | INADEQUADA — papel A4 "cor: colorido" na cesta de papel branco | API Dados Abertos (18/10) |
| 3 | 12677983 | aquisição (17/10) item 1 (rejected); Material de Expediente (08/10) item 2 (rejected) | [15812306006102026 · item 1](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/1?compra=15812306006102026) | R$ 0,10 / FL | R$ 0,10 / FL | nenhuma (9 campos) | VERIFICADA | inadequada (já rejeitada) — offset 210×148, preço por folha | API Dados Abertos (18/10) |
| 4 | 12990257 | aquisição (17/10) item 2 (selected) | [93040205000102026 · item 173](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/173?compra=93040205000102026) | R$ 40,00 / CX | R$ 40,00 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 5 | 12977585 | aquisição (17/10) item 2 (selected) | [98502305000042026 · item 30](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/30?compra=98502305000042026) | R$ 23,28 / CX | R$ 23,28 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 6 | 12998038 | aquisição (17/10) item 3 (selected); Fornecimento (18/10) item 3 (rejected) | [93368306000162026 · item 32](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/32?compra=93368306000162026) | R$ 44,80 / UN | R$ 44,80 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 7 | 13000312 | aquisição (17/10) item 3 (selected); Fornecimento (18/10) item 3 (selected) | [92539605000912026 · item 36](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/36?compra=92539605000912026) | R$ 16,07 / UN | R$ 16,07 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 8 | 12978349 | aquisição (17/10) item 4 (selected) | [98991505000132026 · item 120](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/120?compra=98991505000132026) | R$ 29,77 / UN | R$ 29,77 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) + portal, item a item |
| 9 | 12989072 | aquisição (17/10) item 4 (selected) | [78731006000842026 · item 27](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/27?compra=78731006000842026) | R$ 7,00 / UN | R$ 7,00 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) + portal, item a item |
| 10 | 11731063 | aquisição (17/10) item 4 (manual_review); Material de Expediente (08/10) item 4 (manual_review) | [09260105900292026 · item 1](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/1?compra=09260105900292026) · 16 dígitos na fonte: relatório sem link | R$ 4.415,00 / UN | R$ 4.415,00 / UN | nenhuma (9 campos) | VERIFICADA | inadequada (em revisão) — grampeador cirúrgico | API Dados Abertos (18/10) |
| 11 | 12841884 | aquisição (17/10) item 4 (rejected); Material de Expediente (08/10) item 4 (rejected) | [09230105904082026 · item 7](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/7?compra=09230105904082026) · 16 dígitos na fonte: relatório sem link | R$ 2.050,00 / s/ unid. | R$ 2.050,00 / s/ unid. | nenhuma (9 campos) | VERIFICADA | inadequada (já rejeitada) — grampeador cirúrgico | API Dados Abertos (18/10) |
| 12 | 12976393 | aquisição (17/10) item 5 (selected) | [92864805000012026 · item 29](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/29?compra=92864805000012026) | R$ 4,89 / CX | R$ 4,89 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 13 | 12977596 | aquisição (17/10) item 5 (selected) | [98502305000042026 · item 41](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/41?compra=98502305000042026) | R$ 1,68 / CX | R$ 1,68 / CX | nenhuma (9 campos) | VERIFICADA | DUVIDOSA — clipe tamanho 0; o item pede 2/0 | API Dados Abertos (18/10) |
| 14 | 12905112 | aquisição (17/10) item 5 (rejected); Material de Expediente (08/10) item 5 (rejected) | [15306307009292026 · item 2](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/2?compra=15306307009292026) | R$ 30,77 / UN | R$ 30,77 / UN | nenhuma (9 campos) | VERIFICADA | inadequada (já rejeitada) — clipe 4/0, inexigibilidade | API Dados Abertos (18/10) |
| 15 | 12938964 | Fornecimento (18/10) item 1 (selected) | [92554606001442026 · item 1](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/1?compra=92554606001442026) | R$ 26,00 / EMB | R$ 26,00 / EMB | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 16 | 13014714 | Fornecimento (18/10) item 1 (selected) | [92984205000022026 · item 7](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/7?compra=92984205000022026) | R$ 19,03 / EMB | R$ 19,03 / EMB | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 17 | 12976385 | Fornecimento (18/10) item 2 (selected) | [92864805000012026 · item 21](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/21?compra=92864805000012026) | R$ 31,48 / CX | R$ 31,48 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 18 | 13003564 | Fornecimento (18/10) item 2 (selected) | [98748905000382026 · item 15](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/15?compra=98748905000382026) | R$ 24,50 / CX | R$ 24,50 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 19 | 12990292 | Fornecimento (18/10) item 3 (selected) | [93040205000102026 · item 208](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/208?compra=93040205000102026) | R$ 22,00 / UN | R$ 22,00 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 20 | 12963850 | Fornecimento (18/10) item 4 (selected) | [38014206001542026 · item 5](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/5?compra=38014206001542026) | R$ 16,07 / UN | R$ 16,07 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 21 | 12964736 | Fornecimento (18/10) item 4 (selected) | [79538006001212026 · item 61](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/61?compra=79538006001212026) | R$ 6,9642 / UN | R$ 6,9642 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 22 | 12995276 | Fornecimento (18/10) item 5 (selected) | [08034306000162026 · item 18](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/18?compra=08034306000162026) · 16 dígitos na fonte: relatório sem link | R$ 2,15 / CX | R$ 2,15 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 23 | 12988370 | Fornecimento (18/10) item 5 (selected) | [38013506000772026 · item 2](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/2?compra=38013506000772026) | R$ 1,85 / CX | R$ 1,85 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 24 | 12987987 | Fornecimento (18/10) item 5 (rejected) | [18022405000302026 · item 8](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/8?compra=18022405000302026) | R$ 1,88 / CX | R$ 1,88 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 25 | 13023580 | Fornecimento (18/10) item 6 (selected) | [13005805000382026 · item 97](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/97?compra=13005805000382026) | R$ 23,43 / UN | R$ 23,43 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 26 | 12919392 | Fornecimento (18/10) item 6 (selected) | [98754105000742026 · item 8](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/8?compra=98754105000742026) | R$ 7,86 / UN | R$ 7,86 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 27 | 12809472 | Material de Expediente (08/10) item 1 (warning) | [11012005001862026 · item 57](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/57?compra=11012005001862026) | R$ 204,32 / CX | R$ 204,32 / CX | nenhuma (9 campos) | VERIFICADA | DUVIDOSA — caneta de metal personalizada (sinalizada) | API Dados Abertos (18/10) + portal (compra: UASG 110120 ABIN/GSI/PR) |
| 28 | 12913394 | Material de Expediente (08/10) item 1 (selected) | [15404705002112026 · item 87](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/87?compra=15404705002112026) | R$ 0,49 / UN | R$ 0,49 / UN | nenhuma (9 campos) | VERIFICADA | DUVIDOSA — caneta avulsa R$ 0,49 convertida para caixa de 50 (R$ 24,50) pela capacidade da fonte | API Dados Abertos (18/10) |
| 29 | 12660435 | Material de Expediente (08/10) item 2 (warning) | [06000105001912026 · item 193](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/193?compra=06000105001912026) · 16 dígitos na fonte: relatório sem link | R$ 401,73 / EMB | R$ 401,73 / EMB | nenhuma (9 campos) | VERIFICADA | INADEQUADA — papel offset 960×660 mm (sinalizado, mas dentro da cesta) | API Dados Abertos (18/10) + portal, item a item |
| 30 | 12728156 | Material de Expediente (08/10) item 2 (selected) | [98788505900532026 · item 88](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/88?compra=98788505900532026) | R$ 0,46 / EMB | R$ 0,46 / EMB | nenhuma (9 campos) | VERIFICADA | INADEQUADA — papel texturizado colorido; convertido de 50 folhas para pacote (R$ 4,60) | API Dados Abertos (18/10) |
| 31 | 12977646 | Material de Expediente (08/10) item 3 (selected) | [98502305000042026 · item 91](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/91?compra=98502305000042026) | R$ 223,68 / CX | R$ 223,68 / CX | nenhuma (9 campos) | VERIFICADA | adequada com conversão — caixa com 20 (fonte) → R$ 11,18 por unidade | API Dados Abertos (18/10) + portal, item a item |
| 32 | 11950183 | Material de Expediente (08/10) item 3 (selected) | [92979805900052026 · item 55](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/55?compra=92979805900052026) | R$ 4,99 / UN | R$ 4,99 / UN | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 33 | 12848928 | Material de Expediente (08/10) item 4 (selected) | [98659505001172026 · item 20](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/20?compra=98659505001172026) | R$ 762,00 / UN | R$ 762,00 / UN | nenhuma (9 campos) | VERIFICADA | INADEQUADA — grampeador cirúrgico na cesta de grampeador de mesa | API Dados Abertos (18/10) + portal, item a item |
| 34 | 12729225 | Material de Expediente (08/10) item 4 (selected) | [98014505900062026 · item 66](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/66?compra=98014505900062026) | R$ 2,64 / UN | R$ 2,64 / UN | nenhuma (9 campos) | VERIFICADA | DUVIDOSA — grampeador tipo alicate na cesta de grampeador de mesa | API Dados Abertos (18/10) |
| 35 | 12908507 | Material de Expediente (08/10) item 5 (selected) | [98154705001782026 · item 47](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/47?compra=98154705001782026) | R$ 12,10 / CX | R$ 12,10 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |
| 36 | 9961182 | Material de Expediente (08/10) item 5 (selected) | [38917405900162025 · item 23](https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra/item/23?compra=38917405900162025) | R$ 1,52 / CX | R$ 1,52 / CX | nenhuma (9 campos) | VERIFICADA | adequada | API Dados Abertos (18/10) |

**Conferência no portal, item a item (18/10/2026).** Para cada item,
"Adjudicada" e "Valor ofertado (unitário)" foram lidos em
`…/acompanhamento-compra/item/{n}?compra={idCompra}`:

| Registro | Portal mostra | GovConnect grava |
|---|---|---|
| Jaguariúna, PE 117/2026, item 20 | GRAMPEADOR CIRÚRGICO · SCITECH PRODUTOS MEDICOS SA (01.437.707/0001-22) · R$ 762,0000 · qtde 38 | R$ 762,00 · CNPJ 01437707000122 · qtde 38 |
| São José dos Pinhais, PE 90053/2026, item 162 | PAPEL PARA IMPRESSÃO FORMATADO · VPN DE PAULA LTDA · R$ 45,2000 · qtde 1450 | R$ 45,20 · qtde 1450 |
| STM, PE 191/2026, item 193 (idCompra com zero) | PAPEL PARA IMPRESSÃO FORMATADO · META PAPER · R$ 401,7300 · qtde 20 | R$ 401,73 · qtde 20 |
| Diamante d'Oeste, item 120 | GRAMPEADOR · DAMAZIO LICITACOES E SERVICOS LTDA · R$ 29,7700 · qtde 20 | R$ 29,77 · qtde 20 |
| Pirapora, PE 4/2026, item 91 | PASTA ARQUIVO · HAUSE NEON PAINEIS LUMINOSOS LTDA · R$ 223,6800 · qtde 110 | R$ 223,68 / CX · qtde 110 |
| Capitania Fluvial do Araguaia, DE 84/2026, item 27 | GRAMPEADOR · G2 CORPORATION LTDA · R$ 7,0000 · qtde 50 | R$ 7,00 · qtde 50 |

---

## C. Problemas identificados

Legenda: **comprovado** = observado nos dados ou na fonte; **potencial** =
risco plausível pelo código, sem caso observado.

### C-1 · ALTA · Preço autêntico de produto diferente entra na cesta (comprovado)

* **Arquivos:**
  * `src/precos/matching.py` (`comparar`, `_fator_descricao`, `_fator_catalogo`);
  * `src/precos/saneamento.py`, que só olha preço;
  * `src/precos/estatistica.py` (`selecionar_cesta`).
* **Causa provável:**
  * A comparabilidade aceita referências do mesmo grupo de catálogo (PDM)
    com descrição parecida.
  * Atributos que definem o produto (formato do papel, tipo do grampeador,
    tamanho do clipe, cor/textura) não funcionam como barreira.
  * A triagem estatística só pega o preço destoante, e um produto diferente
    com preço parecido passa (papel A3 a R$ 45,20, clipe 0 a R$ 1,68).
* **Evidência:**
  * Pesquisa recente "aquisição" (17/10), com teto e triagem, conferida nas
    112 linhas das cestas das duas pesquisas recentes:
    * papel A4: papel A3 (420×297), 4 papéis "cor: colorido" e 1 reciclado
      na cesta do papel A4 branco (6 de 15);
    * clipe: nº 0, nº 1/0 e nº 4/0 na cesta do clipe 2/0;
    * caneta: tinta preta na cesta da caneta azul.
  * Pesquisa antiga "Material de Expediente" (08/10), sem teto e sem triagem:
    * 55 papéis não A4 entre 317 na cesta do papel A4;
    * 3 grampeadores cirúrgicos, de até R$ 762,00, na cesta de 270 grampeadores
      de mesa;
    * papel offset 960×660 a R$ 401,73 e papel texturizado colorido.
* **Impacto:**
  * Na pesquisa antiga, a média da cesta de papel seria R$ 126,48 contra uma
    mediana de R$ 29,00. Só a escolha da mediana evitou um valor absurdo.
  * Mesmo com a mediana, a cesta e o relatório listam como "preços usados"
    produtos que não são o item pesquisado. Isso fragiliza a pesquisa diante
    do controle externo.
* **Correção recomendada:**
  * Barreira determinística por atributo do catálogo: para cada PDM, uma
    lista de atributos obrigatórios (papel: tamanho; clipe: número;
    grampeador: tipo).
  * Descartar como "produto diferente" quando o atributo da fonte contradiz
    o item, e lista negra de termos ("CIRÚRGICO") por PDM.
  * Quando o atributo faltar na fonte, mandar para revisão, nunca direto
    para a cesta.

### C-2 · ALTA · Identificador da compra perdido por zero à esquerda; o relatório diz "Não disponível na fonte" (comprovado)

* **Arquivos:**
  * `src/precos/links.py:46` (`ID_COMPRA = ^\d{17}$`), em
    `acompanhamento_compra` e `resolver`;
  * `src/precos/documento_cotacao.py:697` (`_celula_contratacao`).
* **Causa comprovada:**
  * A API devolve `idCompra` como **número JSON**, e o zero inicial das UASG
    que começam com 0 (060001, 092601, 080343…) desaparece:
    `6000105001912026`.
  * A própria fonte guarda o identificador correto em `idCompraItem`
    (**texto**): `0600010500191202600193`.
* **Evidência:**
  * 300 referências (5,2%) estão nessa situação, **57 delas dentro de cestas**
    (48 usadas e 9 sinalizadas).
  * O link com o zero recolocado abre a compra certa (STM, PE 191/2026,
    item 193, R$ 401,73).
* **Impacto:**
  * Para essas referências, o relatório **não imprime número de compra nem
    link** e afirma "Não disponível na fonte", o que é falso: o dado existe na
    fonte e o problema é nosso.
  * A conferência independente fica impossível pelo documento.
* **Correção recomendada:**
  * Tirar o identificador de `idCompraItem[:17]` quando for texto de 22
    dígitos, ou completar com zero quando `idCompra` vier com 16 dígitos
    numéricos e `codigoUasg` começar com 0. Os dois caminhos usam só o que a
    fonte entregou.
  * Sem link, imprimir mesmo assim o identificador e a UASG.
  * Nunca escrever "não disponível na fonte" quando a causa for interna.

### C-3 · MÉDIA · Conversão de unidade com fator de origem mista e rótulo "informado pela fonte" (comprovado)

* **Arquivos:**
  * `src/precos/unidades.py:170-213`;
  * `src/precos/matching.py:228` (texto do motivo).
* **Evidência:**
  * Caneta vendida por **unidade** a R$ 0,49 virou R$ 24,50 por caixa: a
    `capacidadeUnidadeFornecimento = 50` da fonte foi aplicada a um item cuja
    unidade é UN.
  * Papel texturizado de 50 folhas virou R$ 4,60 por pacote, com o fator 0,1
    combinando a capacidade da fonte (50) e o conteúdo do item (500).
  * O motivo gravado diz "fator … informado pela fonte", mas parte do fator
    vem do item.
* **Impacto:**
  * A conta está certa e o valor original aparece no PDF ("orig. R$ 0,49 / UN").
  * Mas o fator e a sua origem não aparecem para o servidor, e a capacidade
    da caixa do **item** não é confirmada.
* **Correção recomendada:**
  * Gravar e exibir o fator com as duas origens ("fonte: 50 folhas; item:
    500 folhas").
  * Exigir conteúdo explícito no item para converter.
  * Mandar para revisão qualquer conversão com fator ≥ 10 ou ≤ 0,1.

### C-4 · MÉDIA · Pesquisa antiga sem teto e sem triagem continua emitível (comprovado)

* **Evidência:**
  * "Material de Expediente" (08/10) tem cestas de 196, 317 e 270 preços.
  * A integridade (Revisão 02) só **avisa** quando a cesta passa de 15; a
    emissão não é bloqueada e nada é recalculado.
* **Correção recomendada:**
  * Exigir que a busca automática rode de novo quando a cesta foi formada por
    política anterior à vigente, ou bloquear a emissão com orientação clara.
  * Para dados antigos, migração nenhuma: só a exigência na emissão.

### C-5 · MÉDIA · Não há "status de verificação da fonte" separado da adequação (comprovado pelo esquema)

* **Arquivo:** migração `0021_pesquisa_precos.sql`
  (`pesquisa_preco_referencias`).
* **Evidência:**
  * Existe `status` (candidate, selected, rejected…), que é **adequação**.
  * Não existe campo que diga quando e como a referência foi revalidada na
    fonte nem com que resultado.
  * `coletado_em` é só a data da coleta.
* **Correção recomendada:** acrescentar os campos `verificacao`
  (nao_revalidada | conferida | divergente | indisponivel), `verificado_em`
  e `verificacao_detalhe`. Ver D, fase 2.

### C-6 · MÉDIA · O link aponta para a compra, não para o item (comprovado)

* **Evidência:**
  * O portal tem página por item:
    `…/acompanhamento-compra/item/{n}?compra={idCompra}`.
  * Ela traz o item, a situação, todas as propostas, o fornecedor adjudicado
    e o valor. Conferido em 6 itens.
  * O GovConnect aponta para a compra inteira (até 194 itens em grupos), e o
    servidor precisa procurar o item à mão.
* **Correção recomendada:**
  * Usar a página do item quando `numeroItemCompra` existir.
  * Isso também cobre parte do AC-22: a lista de propostas fica a um clique,
    sem copiar dados.

### C-7 · BAIXA · Órgão impresso pode não ser a unidade que comprou (comprovado)

* **Evidência:** a referência do PE 186/2026 aparece como "PRESIDENCIA DA
  REPUBLICA" (`nomeOrgao`), mas a compra é da UASG 110120 – ABIN/GSI/PR
  (`nomeUasg`).
* **Correção recomendada:** imprimir também a UASG (código e nome), que é
  como o portal identifica a compra.

### C-8 · MÉDIA · `raw_hash` protege contra alteração acidental, não contra adulteração deliberada (potencial)

* **Evidência:**
  * O hash é recalculável por quem tem escrita no banco.
  * Nada prende o hash a um registro fora do banco.
* **Correção recomendada:**
  * Gravar o conjunto de `raw_hash` usados na emissão dentro do evento de
    emissão, que é só de inclusão (`pesquisa_preco_eventos`).
  * Imprimir o hash do conjunto no relatório analítico. Assim, a cópia em
    papel prova o que foi usado.

### C-9 · MÉDIA · `idCompra` numérico acima de 2^53 (potencial)

* **Evidência:**
  * `idCompra` chega como número de 17 dígitos (até ~9,9 × 10^16), acima do
    inteiro exato do JavaScript e do `float`.
  * Python e `jsonb` preservam o valor; qualquer consumidor futuro em JS
    (componente web, exportação JSON para planilha) arredondaria em silêncio.
* **Correção recomendada:** normalizar para texto na coleta, mantendo o
  `bruto` intacto.

### C-10 · BAIXA · Fontes não exercidas em produção (limitação)

* **Evidência:** PNCP, Itens de Contratações, cotação direta e planilha
  importada têm 0 referências em produção.
* **Consequência:**
  * Não foi possível auditá-las com dado real.
  * Cotação direta e planilha aceitam preço trazido pelo servidor. A
    autenticidade depende do comprovante anexado, que não foi testado aqui.

### C-11 · BAIXA · "Praticado" = valor adjudicado/homologado, não contrato assinado (esclarecimento)

* **Evidência:** nos 6 itens conferidos, `precoUnitario` é o valor da
  proposta **adjudicada** (o portal mostra "Valor ofertado"; o negociado
  estava vazio).
* **Consequência:**
  * O sistema chama a natureza de "praticado" e não confirma se houve
    contrato ou ata assinados.
  * A metodologia do relatório deve dizer "valor adjudicado/homologado em
    contratação pública" e não sugerir contrato executado.

### O que NÃO foi encontrado (verificado)

* Nenhuma referência inventada: 36 de 36 localizadas na fonte oficial,
  0 dados sintéticos em produção.
* Nenhum valor alterado entre a fonte e o banco: 0 divergências em
  5.741 × 12 campos e 5.741 de 5.741 hashes conferem.
* Nenhuma URL gerada por IA: os links saem de `links.py`, determinístico, e
  só para hosts oficiais.
* Nenhum preço, identificador, órgão ou data vindo de modelo de IA. A
  resposta do Jev é só classificação fechada, e a camada semântica só amplia
  termos de busca.
* Nenhum cache apresentado como consulta ao vivo: cada pesquisa coleta de
  novo, e o relatório mostra a data e a hora da coleta por fonte.

---

## D. Plano de correção (por prioridade)

| Fase | Correção | Componentes | Problemas |
|---|---|---|---|
| 1 (antes de uso em processo real) | Barreira por atributo obrigatório do PDM + lista de termos excludentes; atributo ausente → revisão | `matching.py`, `saneamento.py`, `estatistica.py`, testes com os casos reais desta auditoria (A3, cirúrgico, offset, clipe 0) | C-1 |
| 1 | Identificador da compra a partir de `idCompraItem` / zero à esquerda; imprimir identificador e UASG mesmo sem link; nunca "não disponível na fonte" por falha interna | `links.py`, `documento_cotacao.py`, `relatorio.py` | C-2, C-7 |
| 1 | Exigir nova busca, ou bloquear a emissão, quando a cesta foi formada por política anterior | `cesta.integridade_do_item`, emissão (`precos_ui.py`) | C-4 |
| 2 | Link para a página do item no portal | `links.py` | C-6 |
| 2 | Fator de conversão com origem explícita; conversão ≥ 10× vai para revisão | `unidades.py`, `matching.py`, `relatorio_view.py` | C-3 |
| 2 | Status de verificação separado + revalidação sob demanda (reconsulta do registro pelo `url_de_verificacao`, já existente, e comparação determinística dos 9 campos, como em `evidencias/reconsultar.py`) | migração nova (colunas), `repositorio.py`, tela | C-5 |
| 3 | Hash do conjunto usado gravado no evento de emissão e impresso no analítico | `emissao`, `documento_cotacao.py` | C-8 |
| 3 | `idCompra` como texto na coleta | `compras_gov.py` | C-9 |
| 3 | Metodologia: "valor adjudicado/homologado" em vez de sugerir contrato | `documento_cotacao.py` | C-11 |
| 3 | Testes de ponta a ponta para PNCP, cotação direta e planilha com comprovante | testes | C-10 |

Sobre o desempenho da revalidação (fase 2): é 1 requisição por referência,
~1 s cada, medido nesta auditoria. Deve ser feita sob demanda ou em lote
antes da emissão, só para as referências **da cesta** (no máximo 15 por
item), nunca para os 500 candidatos.

---

## E. Resultado conclusivo

1. **O GovConnect está utilizando fontes reais?**
   **Sim.** Em produção, 100% das 5.741 referências vêm da API oficial de
   Dados Abertos do Compras.gov.br. 36 de 36 registros da amostra foram
   localizados na fonte, e 6 deles conferidos também no portal público,
   item a item.

2. **Existem evidências de referências inventadas?**
   **Não.** Nenhuma referência, identificador, URL ou valor sem origem.
   Também nenhum dado sintético em produção. A IA não tem caminho para gravar
   esses campos.

3. **Os preços apresentados correspondem às fontes originais?**
   **Sim, como valor.** Houve 0 divergências entre banco e fonte (5.741 × 12
   campos; amostra de 36 × 9 campos contra a fonte ao vivo). **Mas** parte dos
   preços usados é de produtos diferentes do item pesquisado (C-1), e algumas
   conversões de unidade são frágeis (C-3).

4. **Existem falhas no processamento dos resultados?**
   **Sim, três relevantes:**
   * comparabilidade insuficiente, com produto diferente entrando na cesta
     (C-1);
   * perda do identificador da compra em 5,2% das referências, com relatório
     afirmando falsamente indisponibilidade (C-2);
   * pesquisa antiga ainda emitível com cestas não saneadas (C-4).

5. **O sistema consegue comprovar documentalmente os preços?**
   **Em grande parte, sim.** Preserva a resposta bruta, o hash e o link
   oficial para 94,8% das referências. **Não** consegue para as 300 com zero
   perdido (C-2). Também não tem status de revalidação nem prova externa do
   conjunto emitido (C-5, C-8).

6. **Riscos a corrigir antes do uso em processos licitatórios reais:**
   C-1, C-2 e C-4 (fase 1 do plano), corrigidos no branch
   `claude/auditoria-fontes-fase1` (seção F). Valem em produção só depois
   do deploy. Mesmo com o deploy, as cestas já gravadas só se ajustam
   quando a cotação automática do item é refeita. Até lá, o servidor deve
   conferir a descrição de cada preço da cesta. A pesquisa "Material de
   Expediente" de 08/10 fica bloqueada para emissão até a busca ser
   refeita. Fases 2 e 3 (C-3, C-5, C-6, C-8 a C-11) continuam pendentes.

---

## F. Correções da fase 1 (18/10/2026, branch `claude/auditoria-fontes-fase1`)

Implementadas depois de o diagnóstico ser apresentado, com autorização.
Rollback: desligar a flag `precos_saneamento_pre_cesta` desliga a barreira
(C-1); os demais itens voltam revertendo o commit. Nenhuma migração, e
nada gravado é recalculado sozinho.

| Problema | O que mudou | Onde |
|---|---|---|
| C-1 | Barreira por atributo antes da triagem estatística.<br>• O que **contradiz** o item (formato e cor do papel; tipo do papel; numeração do clipe; tipo do grampeador; cor da tinta da caneta; finalidade cirúrgica, odontológica ou veterinária) é **rejeitado** e gravado com o motivo ("produto diferente do item (formato): papel de 420 × 297 mm; o item pede A4 …").<br>• Atributo essencial **ausente** na fonte (formato do papel, numeração do clipe) vai para **revisão**.<br>• Só decide quando o item diz o atributo.<br>• O relatório atribui a saída ao sistema ("fora da série: produto diferente do item"), não ao servidor. | `src/precos/atributos.py` (novo), `estatistica.selecionar_cesta`, `relatorio_view.autoria_da_saida` |
| C-2 | `id_compra_oficial` recupera o zero da UASG pelo próprio registro (`idCompraItem` em texto, ou o código da UASG), só quando os dois concordam com o número; sem prova, não completa.<br>O PDF imprime o número **mesmo sem link** e diz "Página pública não localizada pelo sistema", nunca mais "Não disponível na fonte". | `links.py`, `documento_cotacao._celula_contratacao` |
| C-4 | A emissão (botão, pacote ZIP, qualquer formato) pára com mensagem quando a cesta de um item tem mais preços **escolhidos pela máquina** do que o teto. Inclusões do servidor não contam. A saída é refazer a cotação automática do item. | `cesta.itens_acima_do_teto`, `precos_ui._conferir_cestas` |
| C-7 | O relatório imprime a UASG que comprou ("UASG 110120 — …ABIN/GSI/PR") abaixo do órgão. | `links.unidade_compradora`, `documento_cotacao._celula_origem` |

Decisões tomadas por conta própria, para o usuário confirmar:
* Contradição de atributo → **rejeitada** (não "revisão"). O servidor
  pode reincluir pela tela, como qualquer retida.
* Papel **reciclado** na cesta de papel **sulfite** conta como outro
  produto (o item pede sulfite). Se o órgão aceitar reciclado como
  equivalente, basta tirar `RECICLADO` de `TIPOS_PAPEL`.
* Gramatura diferente (75 × 90 g/m²) **não** foi tratada como outro
  produto.
* C-4 **bloqueia** a emissão em vez de só avisar, porque a cesta antiga
  contém produtos diferentes comprovados (C-1).

Efeito esperado nas pesquisas de produção (ao refazer a cotação
automática; nada muda sozinho):
* papel A4 branco: saem o A3, os 4 coloridos e o reciclado;
* clipe 2/0: saem os nº 0, 1/0 e 4/0;
* caneta azul: sai a de tinta preta;
* a pesquisa "Material de Expediente" (08/10) deixa de ser emitível até
  a cotação automática ser refeita.

Testes: `tests/test_auditoria_fase1.py` traz 34 casos com as descrições
**reais** dos registros auditados, incluindo os sem falso positivo nas
cestas de 17/10. Prova de mutação: com a barreira desligada ou o bloqueio
removido, o teste correspondente falha.

## Limitações desta auditoria

* A amostra cobre 36 registros, todos de **uma** fonte (a única com dados em
  produção). PNCP, cotação direta e planilha não puderam ser auditados com
  dado real.
* A conferência no portal foi item a item em 6 registros e no nível da compra
  em mais 2. Nos demais, a evidência é a API oficial, que é do mesmo sistema
  do portal, mas é outro canal.
* As compras de 16 dígitos foram abertas no portal só no caso do STM. Para
  as outras, o link da tabela B segue o mesmo formato, mas não foi aberto.
* Acesso ao banco: leitura pela ferramenta administrativa (Supabase MCP). As
  políticas de acesso (RLS) não fizeram parte do escopo.
