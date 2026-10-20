# Saneamento pré-cesta, remoção sem justificativa e ciência na emissão

Pacote Jev de 17/10/2026. Três mudanças no módulo de preços, cada uma
atrás de uma decisão explícita:

| | O quê | Onde | Flag |
|---|---|---|---|
| A | Triagem de cada item **antes** da cesta automática | `src/precos/saneamento.py`, `estatistica.selecionar_cesta`, `cotacoes.pesquisar_item`, `execucao.pesquisar_item` | `precos_saneamento_pre_cesta` (nasce OFF) |
| B | Retirar cotação ou item **sem** texto obrigatório | `cotacoes.alterar_status_referencia`, `cotacoes.remover_item`, `repositorio.reclassificar_referencia`, `cesta.excluir_discrepantes`, telas | sem flag (só afrouxa exigência; trilha automática) |
| C | Preço atípico **não trava** o relatório: aviso + ciência | `src/precos/ciencia.py`, `precos_ui._conteudo_do_relatorio` e diálogo | `precos_ciencia_emissao` (nasce OFF) |

Nenhuma migração. Nenhum dado antigo é recalculado ao ligar as flags: a
triagem age na PRÓXIMA busca automática de cada item; a ciência, na
próxima emissão.

## A. Metodologia da triagem (motor único)

`saneamento.avaliar` é a única régua. A cotação automática a chama antes
de montar a cesta; a emissão a chama sobre a cesta, para os alertas.

**Camada 1 — invalidação objetiva** (vale para qualquer referência):

| Código | Situação | Desfecho |
|---|---|---|
| `INVALID_VALUE` | valor nulo, zero, negativo, não numérico | desconsiderada |
| `UNIT_NOT_CONVERTIBLE` | grandezas diferentes (hora × mês) | desconsiderada |
| `UNIT_NOT_CONVERTIBLE` | embalagem sem capacidade, unidade fora do dicionário (o fator pode estar na fonte) | revisão |
| `VALUE_NOT_MARKET_PRICE` | estimativa de outro órgão, não preço praticado | revisão |
| `DUPLICATE_SAME_ORIGIN` | mesma linha do mesmo documento (id oficial + fornecedor + valor) | desconsiderada; conta uma vez |

**Camada 2 — suspeita estatística por item** (só os comparáveis válidos
do MESMO item; 15 itens são 15 séries, nunca uma):

- mediana, MAD = mediana(|xᵢ − mediana|), z modificado = 0,6745·|xᵢ − mediana| / MAD;
- Q1, Q3 e IQR pelo método de interpolação linear de `estatistica.calcular` (o mesmo do Excel);
- razão xᵢ / mediana.

Critérios atingidos por preço: `z_modificado` (> 3,5), `iqr` (fora de
Q1 − 1,5·IQR … Q3 + 1,5·IQR), `razao` (≥ 3 ou ≤ 1/3), `mad_zero` (MAD = 0 e
preço ≠ mediana — sem divisão por zero).

- **suspeita** = razão extrema, ou dois critérios;
- **forte** = razão extrema confirmada por mais um critério;
- um critério isolado é dispersão natural: fica elegível.

**Descarte estatístico automático** só com TODOS: suspeita forte; n ≥ 5
comparáveis; grupo não suspeito homogêneo (maior/menor < 3) vindo de ≥ 3
origens independentes (órgão + fornecedor); nenhum sinal comercial na
referência que o item não tenha (instalação, garantia, frete, km
adicional, kit, lote, premium…); política que permita. Faltando um,
**revisão**. Com n < 5 nada é descartado por estatística; com dois
preços distantes (ou série larga sem destoante claro) os dois vão para
revisão.

**O Jev** entra com a escolha fechada de `decisoes.MOTIVOS` (o contrato
que já existia; prompt e perguntas não mudaram, para não invalidar o
cache das análises gravadas). O motor decide:

- `different_product`/`different_specification` + preço suspeito + grupo
  corroborado → desconsiderada (duas evidências independentes);
- o mesmo sem suspeita estatística → revisão (o Jev sozinho nunca descarta);
- `different_unit`, `different_packaging`, `insufficient_information` → revisão.

Decisão de PESSOA (evento de inclusão/exclusão, cotação direta) nunca é
reavaliada pelo Jev nem pela triagem.

**Destino**: desfecho vira status existente (`rejected` / `manual_review`)
e o motivo técnico vai para `motivos`, prefixado por
"desconsiderada pelo Jev antes da cesta" ou "requer revisão (triagem
pré-cesta)", com os códigos e a versão da política. Com o teto da cotação
automática ligado, as retidas que pedem fundamento são **gravadas** (as
de unidade/natureza continuam só contadas, como antes). A trilha
(`busca_concluida.payload.saneamento`) guarda versão, política, série,
contagem, as avaliações retidas com métricas e o resumo do item.

**Reinclusão**: "Reincluir na cesta" pede motivo e põe a cotação na
cesta como **sinalizada** (`warning`) — o alerta acompanha o preço até a
emissão. Evento `referencia_incluida` com `operacao: reinstated`.

### Parâmetros (`PoliticaSaneamento`, versão `2026-10-17.saneamento-v1`)

| Parâmetro | Padrão | Papel |
|---|---|---|
| `minimo_para_autoexclusao` | 5 | abaixo disso, nada é descartado por estatística |
| `minimo_origens_independentes` | 3 | origens (órgão+fornecedor) que corroboram a faixa |
| `z_modificado` | 3,5 | Iglewicz–Hoaglin |
| `fator_iqr` | 1,5 | Tukey |
| `razao_alta` / `razao_baixa` | 3,0 / 0,333333 | razão à mediana |
| `autoexclusao_estatistica` | True | False = toda suspeita vai para revisão |

São limiares de **triagem**, não critério legal. Mudar qualquer um exige
nova `versao` — a trilha grava a política com que cada busca decidiu.

### Exemplos (massa sintética, `tests/fixtures/precos/jev_cenarios_15_itens.json`)

Medido com `python scripts/diagnostico_saneamento.py`
(`diagnostico-15-itens-depois.json`) e, na `main` sem a mudança, o mesmo
caminho de coleta (`diagnostico-15-itens-antes.json`):

| Item | Antes (main) | Depois |
|---|---|---|
| 01 papel A4 | R$ 190 na cesta; média **R$ 58,22** | R$ 190 desconsiderado (razão 7,5×, z modificado 222, 4 origens); R$ 25,28 |
| 02 caneta | R$ 23 na cesta; média R$ 6,21 | R$ 23 desconsiderado |
| 03 pasta (caixa c/ 10) | normalizada a R$ 6,00 | idem, elegível |
| 04 manutenção mensal | hora fora pelo piso | desconsiderada: `UNIT_NOT_CONVERTIBLE` (hora × mês) |
| 05 impressão (pacote 500) | pacote **sem conversão** (fora) | R$ 500 ÷ 500 = R$ 1,00 por folha, elegível |
| 06 notebook | R$ 9.000 na cesta; R$ 4.594 | com o Jev (objeto distinto) desconsiderado; sem o Jev, revisão |
| 07 teclado | 5 na cesta | 5 na cesta |
| 08 internet (2 preços) | 130 e 520 na cesta (R$ 325) | os dois em revisão |
| 09 toner (MAD = 0) | R$ 1.800 na cesta, **sem sinal**; R$ 504 | desconsiderado (`mad_zero` + razão 10×); R$ 180 |
| 10/11 zero e negativo | fora pelo piso | desconsiderados: `INVALID_VALUE` |
| 12 entrega (viagem) | **item sem preço** (unidade VIAGEM desconhecida) | 4 na cesta; R$ 1.600 em revisão (500 km adicionais) |
| 13 mouse (duplicata) | linha duplicada contada 2× | duplicata desconsiderada, preservada |
| 14 switch | R$ 2.800 na cesta; R$ 1.684 | revisão (garantia + instalação) |
| 15 limpeza m² (2 preços) | 5 e 25 na cesta (R$ 15) | os dois em revisão |

Duas lacunas de unidade apareceram no diagnóstico e foram corrigidas em
`unidades.py` pela regra que o módulo já tinha (só com fator explícito da
fonte): embalagem → **folha** como embalagem → unidade, e **VIAGEM** como
unidade que só casa consigo.

## B. Remoção sem justificativa obrigatória

- `alterar_status_referencia(..., incluir=False, motivo=None)`: aceita
  motivo ausente, `None` ou `""`. Trilha `referencia_excluida` com
  `operacao: manual_removed`, `origem: user`, `user_reason` (nulo sem
  texto), `de`/`para`, `revisao_anterior`, ator e hora (do banco). Texto
  de `motivos`: "retirada da cesta pelo usuário" — o fato, sem inventar
  fundamento estatístico. Repetir o clique não duplica a trilha.
- `remover_item(..., motivo=None)`: `item_removido` com
  `operacao: basket_item_removed`, `user_reason`, `estado_anterior`,
  `revisao`; confirmação simples na tela, sem texto; idempotente.
- `excluir_discrepantes(..., motivo=None)`: o critério estatístico de cada
  preço continua registrado (é a fundamentação técnica).
- **Não mudou**: incluir na cesta pede motivo; exceção à regra dos três
  exige texto, fundamento e aprovação; concluir item com pendência de
  análise crítica pede justificativa; reabrir item pede motivo.

## C. Ciência na emissão

1. A seção de relatórios mostra o aviso (não bloqueante) e as pendências.
2. No clique de emitir, `ciencia.exigir` roda **no gerador**
   (`_conteudo_do_relatorio`/pacote): sem alerta nem pendência, emite
   direto; com, abre o diálogo "Preços com variação relevante" — item,
   fonte/órgão, valor, mediana do item e as contas.
3. **Voltar e revisar** (ou fechar no X/Esc): nada é gerado, a cesta fica.
4. **Estou ciente, emitir relatório**: `ciencia.registrar` relê a cesta
   do servidor; se mudou, mostra o aviso novo sem gravar. Senão grava
   `pesquisa_revisada` com `payload.ato = ciencia_de_alertas_na_emissao`,
   assinatura, revisão (identificador do resultado), política, alertas e
   pendências; chave de idempotência = assinatura + ator.
5. O documento sai com a cesta como está e imprime, em "Alertas e
   ressalvas", a ciência: quantas cotações, quais itens, quem, quando,
   assinatura — e que **não é aprovação administrativa**. A emissão
   registrada (`relatorio_emitido`) leva a assinatura da ciência.

A assinatura cobre a pesquisa, o identificador do resultado, os alertas,
as pendências e a política: mudou a cesta, a ciência anterior não vale.
O gatilho do banco confere que o ator é quem está autenticado — ciência
de outro usuário não se forja; a de outra pesquisa tem outra assinatura.

O tipo `pesquisa_revisada` já estava no CHECK da trilha e não era usado
por nenhum fluxo — por isso não há migração. Um tipo dedicado exigiria
migração; fica como opção, não como pendência.

## Nota de conformidade

- A triagem apoia a análise crítica da pesquisa de preços (Lei
  14.133/2021, art. 23; IN SEGES/ME 65/2021 e normas locais, onde
  aplicáveis): ela **não** declara preço inexequível nem sobrepreço — os
  textos usam "preço atípico" e "variação relevante".
- Nenhum preço é apagado: desconsiderar é status + motivo, reversível por
  ato humano registrado; o dado bruto, a fonte e o `raw_hash` ficam.
- O descarte automático exige corroboração objetiva documentada; a
  recomendação de IA sozinha nunca descarta.
- A ciência não substitui justificativa, aprovação ou exceção exigidas
  pela norma aplicável; o relatório diz isso.
- Limiares são parâmetros de triagem a calibrar com casos reais e com a
  regulamentação do órgão.

## Homologação e rollback

Ligar (cada uma é independente):

```
flag_precos_saneamento_pre_cesta = on
flag_precos_ciencia_emissao = on
```

Homologar: rodar a Cotação automática em uma cotação de teste e conferir
o resumo "X encontrados • Y incluídos • Z desconsiderados pelo Jev • W
requer revisão" e a seção "Desconsideradas pelo Jev" de alguns itens;
emitir com e sem alerta. Ligar em produção só depois disso.

Rollback: desligar a flag. Referências já retidas continuam com status e
motivo (nada se apaga); voltam à cesta por "Reincluir" ou numa nova
busca automática sem a triagem. Ciências registradas ficam na trilha.
A parte B não tem flag: reverter é reverter o commit.
