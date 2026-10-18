# Revisão 02 — Jev, cesta, desempenho, interface e relatório (17/10/2026)

Pacote `GovConect_Revisao_02_Jev_Cesta_Relatorio_2026-10-17`, executado
a partir de `main` em `ce4cf2a` (PR #59), branch
`claude/revisao-02-cesta-relatorio`. **Sem migração, sem deploy, sem
merge.** Nada foi gravado em Supabase: todo teste e toda medição usam o
banco dublê das provas.

## 1. Fase 0 — o que o código confirmou dos 15 achados

| ID | Achado do pacote | Causa encontrada no código | Tratamento |
|---|---|---|---|
| D01/D02 | 317/3 na tela, R$ 20.637 × R$ 20.433 | Duas pesquisas DIFERENTES (tela: "Material de Expediente", data-base 08/10, busca de 16/10 22:57 UTC, antes do teto; PDF: "aquisição de materiais de expediente", data-base 17/10). A tela de 317 é cesta formada sem teto. | Integridade da cesta (`cesta.integridade_do_item`) avisa na tela e no PDF quando a cesta passa de 15 ou o N gravado diverge das linhas. Nada é recalculado sozinho. |
| D03–D05 | Atípicos no cálculo (pasta AZ, grampeador, clipes) | Triagem v1 só agia no pool; a cesta de 15 não era reavaliada, e o alerta da emissão usava outra régua. | Triagem v2 + reavaliação e reposição da cesta (§2). |
| D06 | "PROVISÓRIO" junto de "CONCLUÍDO" | A memória gravada no cálculo continuava impressa depois da conclusão. | Item concluído não imprime "PROVISÓRIO" nem "aguardam decisão"; "(em revisão)" só no item não concluído. |
| D07 | "Não consideradas (512)" e "excluída pelo revisor" para decisão automática | O rótulo vinha só do status `rejected`. | Relatório mostra só o que AFETOU a série, com autoria certa (triagem automática × servidor); o resto, uma linha de contagem. Inventário completo na Memória Analítica. |
| D08/D14 | 24 links para o JSON da API | `url_de_verificacao` montava o endpoint de dados abertos. | `links.py`: página pública da contratação (Compras.gov.br e PNCP, rotas conferidas no navegador); o JSON fica só no anexo técnico. |
| D09/D10 | Dados da contratação e links específicos | Campos existiam no registro bruto e não eram impressos. | Por referência: órgão, modalidade, item da compra, fornecedor com CNPJ, contratação clicável — só o que a fonte entrega. |
| D11 | "Item.", "completa", "Com 3+ considerado", IQR com -R$ 52,08 | Rótulos e frase estatística expostos ao servidor. | Microcopy nova; limite exibido nunca negativo; estatística dentro de "Entenda o cálculo". |
| D12 | UTC e texto técnico no corpo | Horários formatados em UTC. | Corpo no horário de Brasília; UTC só na identificação; hash abreviado no PDF (completo no analítico e no XLSX). |
| D13 | Remover é lento | Medido: 10 idas ao banco por remoção no serviço e 21 na tela inteira. | Mutação granular (§3): 6 no serviço e 12 na tela. |
| D15 | Média R$ 27,00 × adotado R$ 25,46 | O teto da mediana só aparecia na memória. | Valor adotado explicado no item e marcado (*) no quadro, só quando o perfil e a cesta o aplicam. |

## 2. Triagem v2 (Jev antes da cesta) — `saneamento.py`, `estatistica.py`

Política `2026-10-17.saneamento-v2`. A v1 continua no código
(`POLITICA_V1`) para reler as buscas antigas: cada busca grava a versão
com que foi triada.

| Regra | v1 | v2 |
|---|---|---|
| Descarte estatístico automático | 5+ comparáveis | **8+** comparáveis, com concordância de critérios (razão extrema + outro critério) e origens independentes que corroboram |
| IQR | qualquer n | só com n ≥ 4 |
| Suspeito em amostra pequena | sai da cesta para revisão | **fica na cesta, sinalizado** (`warning`), com o alerta acionável |
| Distância mínima para dois critérios virarem suspeita | — | **50% da mediana** (medido: série apertada inflava z e IQR e tirava R$ 7,00, 8,90 e 15,29 do grampeador — viés para o centro) |
| Cesta formada pelo teto | não reavaliada | **reavaliada e reposta**: o destoante sai para revisão (ou é desconsiderado, se corroborado com n ≥ 8) e a próxima elegível entra; sem alternativa, fica sinalizado |

Nada é apagado: quem sai leva status e motivo técnico e pode voltar à
cesta por ato humano. O Jev continua só como evidência; sozinho nunca
descarta.

Diagnóstico da massa SINTÉTICA de 15 itens do pacote
(`bench/diagnostico_15_itens.json`, `scripts/diagnostico_revisao02.py`):

| Item | Antes (sem triagem, sem teto) | Depois (v2, teto 15) |
|---|---|---|
| SYN-I01 papel A4 | 17 preços, R$ 27,00, maior R$ 253,00 | 15, R$ 26,48, maior R$ 32,00 (R$ 253 e a duplicata fora) |
| SYN-I02 caneta | 9, R$ 28,50 | 9, R$ 28,50 (R$ 40 fica: 43% acima não é extremo; vira alerta) |
| SYN-I03 pasta AZ (n=4) | 4, R$ 19,60 | 4, R$ 19,60, **R$ 44,80 sinalizado na cesta** (AC-06) |
| SYN-I04 grampeador (12) | 12, R$ 11,74, maior R$ 29,77 | 11, R$ 11,30; R$ 29,77 em revisão; R$ 7,00/8,90/15,29 ficam |
| SYN-I05 clipes | 9, R$ 2,10, maior R$ 4,82 | 7, R$ 2,10; R$ 0,98 e R$ 4,82 em revisão |
| SYN-I06 a I15 | — | iguais (séries homogêneas) |

## 3. Cesta rápida — `cotacoes.py`, `repositorio.py`, `cotacoes_ui.py`

* **Remover = um clique**, sem formulário nem campo de texto. A trilha
  continua automática (`manual_removed`, ator, hora, de/para, revisão).
* **Desfazer**: `cotacoes.desfazer_retirada` só desfaz a última retirada
  da PRÓPRIA pessoa sobre aquela referência, volta ao status anterior e
  registra `undo_manual_removal`.
* **Manter preço** (alerta): `cotacoes.manter_referencia` grava a decisão
  em `estatisticas.decisoes.mantidas` (quem, quando, valor); o atípico
  mantido deixa de ser pendência de conclusão, continua sinalizado e a
  memória diz que foi mantido por decisão.
* **Mutação granular** (`_mudar_e_recalcular`): a linha alterada é a já
  lida; só o item é recalculado; nenhuma fonte, nenhum Jev; a cotação só
  é sincronizada quando o estado do item muda; a tela passa o que acabou
  de ler na mesma execução (`lidos`). A escrita final continua presa à
  revisão do item: conflito de outra aba desfaz a mudança e avisa.
* A trilha da tela é lida uma vez por execução (eram duas consultas iguais).

## 4. Links e relatório — `links.py`, `relatorio_view.py`, `documento_cotacao.py`, `relatorio.py`

* Três endereços separados por referência: fonte, **página da
  contratação** e dados técnicos (JSON). Só `https` e host oficial.
* Relatório de Cotação:
  * todas as referências usadas, com data, órgão, modalidade, item, fornecedor (CNPJ) e contratação clicável — ou "Não disponível na fonte";
  * "Desconsiderados da série" só com o que saiu da série analisada, com autoria e critério sem códigos internos;
  * atípicos mantidos e a decisão;
  * valor adotado pelo teto explicado;
  * metodologia curta, que só descreve a triagem quando ela agiu;
  * horário de Brasília;
  * ciência resumida, sem nome de usuário (o registro completo fica na emissão).
* Memória Analítica (XLSX): duas colunas ao fim, "Página da contratação"
  e "Como saiu da série".

### Links do PDF de amostra, conferidos no navegador em 17/10/2026

Amostra com registros REAIS das APIs gravados nas fixtures
(`scripts/relatorio_revisao02_amostra.py`; PDF em `amostra/`). Auditoria com
o script do pacote: **antes, 24 links, 24 para o JSON de dados abertos;
depois, 8 links, nenhum técnico.**

| Número impresso | URL | O que abriu | Confere |
|---|---|---|---|
| 10210305900092025 | `cnetmobile…/acompanhamento-compra?compra=10210305900092025` | Pregão 90009/2025, UASG 102103 Escola Politécnica USP, item 5 ALICATE WATTÍMETRO | sim |
| 10210305900022025 | `…compra=10210305900022025` | Pregão 90002/2025, UASG 102103 USP, item 1 ALICATE WATTÍMETRO | sim |
| 16004505900122024 | `…compra=16004505900122024` | Pregão 90012/2024 (SRP), UASG 160045 Base Adm. Guarnição de Fortaleza (Exército) | sim |
| 25705205900242024 | `…compra=25705205900242024` | Pregão 90024/2024 (SRP), UASG 257052 DSEI Yanomami (Ministério da Saúde) | sim |
| 78481005900292024 | `…compra=78481005900292024` | Pregão 90029/2024 (SRP), UASG 784810 Centro de Intendência da Marinha em Belém | sim |
| 10806496000149-1-000070/2025 | `pncp.gov.br/app/editais/10806496000149/2025/70` | Edital 90016/2025, IFPI (UASG 158146) | sim |

Rotas conferidas também na Fase 0: compra 92984205000022026 (Câmara de
Santa Maria, Pregão 2/2026, item 7 papel — a do PDF anexado) e PNCP
90483058000126-1-000078/2025 (Município de Caseiros).

## 5. Interface — `cotacoes_ui.py`, `precos_ui.py`

| Antes | Depois |
|---|---|
| "Com 3+ considerados 9/10" | "Com preços suficientes 9 de 10" (ajuda com o mínimo) |
| "6/3 considerados", "317/3" na lista | "6 preços usados (mínimo 3)", "6 preços" |
| "valor provisório" | "em revisão", só em item não concluído com pendência |
| "Amostra suficiente…; revise antes de concluir." | "Preço formado com N preços."; nada em item concluído |
| "Item concluído." + "Para mudar, reabra o item em Ações do item." | "Pesquisa do item concluída." + botão "Revisar preços deste item" |
| Encontradas/Comparáveis/Consideradas/Descartadas no topo | em "Detalhes da busca" |
| "Tirar da cesta" → formulário → "Retirar da cesta" | "Remover da cesta" (um clique) + barra "Desfazer" |
| alerta com IQR/MAD e faixa negativa | card "Confira este preço": valor, órgão/UF, data, faixa dos demais, Ver contratação, Remover, Manter preço |
| "Última busca … UTC" | horário de Brasília |
| Diálogo "Preços com variação relevante" (tabela técnica) | "Preços que merecem conferência" (item · valor · origem) + "Estou ciente, gerar relatório" |

Capturas em `ux/` (prévia local `scripts/demo_cotacoes.py`, banco dublê,
1600×1000, tema claro): `antes_*` da `main`, `depois_*` deste branch.

## 6. Desempenho — `scripts/benchmark_revisao02.py`

Mesma máquina (Windows 11, Python 3.11.9, AMD Family 25), mesmo roteiro,
banco dublê com **60 ms simulados por requisição**; `antes` = checkout de
`main ce4cf2a`, `depois` = este branch. Arquivos: `bench/antes.json`,
`bench/depois.json`.

| Operação | Antes p50 / p95 | Depois p50 / p95 | Requisições ao banco |
|---|---|---|---|
| Remover (serviço), cesta de 15 | 604 / 605 ms | **362 / 363 ms** | 10 → 6 |
| Remover (serviço), cesta de 317 | 609 / 610 ms | **367 / 368 ms** | 10 → 6 |
| Remover (tela inteira, AppTest) | 1.370 / 1.426 ms | **813 / 881 ms** | 21 → 12 |
| Trocar de item (tela inteira) | 563 / 622 ms | **492 / 560 ms** | 8 → 7 |
| Relatório DOCX, 5 itens | 43 / 173 ms | 58 / 170 ms | — |
| Relatório DOCX, 15 itens | 78 / 86 ms | 112 / 113 ms | — |

* Meta de API (≤ 700 ms) **atendida**.
* Metas de clique-até-desenho (≤ 200 ms) e troca de item (≤ 250 ms) **não
  atendidas**: no Streamlit cada clique reexecuta o script no servidor.
  O que sobra é leitura da tela (cotação, itens, referências, trilha). Os
  próximos passos são `st.fragment` no painel do item e uma consulta
  agregada.
* O DOCX ficou ~35 ms mais lento porque agora traz todas as referências
  usadas, e não 5.
* A conversão para PDF (LibreOffice da produção) não foi medida: o
  conversor não existe nesta máquina.

## 7. Testes

* Novos:
  * `tests/test_revisao02_triagem.py` (32);
  * `tests/test_revisao02_relatorio.py` (21);
  * `tests/test_revisao02_ui.py` (4, AppTest).
* Atualizados para a especificação nova:
  * `test_saneamento_pre_cesta.py` (fixa a v1, que continua no código);
  * `test_ciencia_emissao.py`, `test_cotacoes_g2_ui.py`, `test_remocao_sem_motivo.py`, `test_relatorio_cotacao.py`, `test_precos_fase2.py`, `test_pricebank_nucleo.py`.
* Suíte completa (Windows, Python 3.11.9, `--basetemp` próprio, 17/10/2026):

  | | `main ce4cf2a` | este branch |
  |---|---|---|
  | passaram | 2.976 | **3.033** (+57 novas) |
  | falharam | 1 | 1 (o mesmo) |
  | erros | 56 | 56 (os mesmos) |
  | puladas | 354 | 354 |

  A falha e os erros que sobram são de ambiente e já estavam na `main`:
  `test_ensaio_sql_local` exige PostgreSQL com pgvector; os 56 erros
  (`test_varredura_segredos`, `test_vinculo_contas_auth`,
  `test_auth_migracao_gates`, `test_jev_benchmark`,
  `test_precos_catmat_180d`, `test_cotacoes_g4_seletor`) são de permissão
  de pasta temporária nesta máquina Windows. Nenhuma regressão.

## 8. Flags, dados antigos e rollback

* **Triagem v2:** atrás da flag que já existia, `precos_saneamento_pre_cesta`. Ligada, as novas buscas usam a v2; as antigas mantêm motivos e versão v1.
* **Teto de 15:** continua na flag `cotacao_automatica_teto`. A reposição da cesta só age com as duas ligadas.
* **Cesta, alerta, interface e relatório:** sem flag, como no padrão do repositório para apresentação; o rollback é reverter os commits.
* **Dados antigos:** nenhuma migração; nada é recalculado nem reemitido sozinho.
  * Cesta antiga acima de 15 recebe aviso de integridade.
  * `decisoes.mantidas` é campo novo dentro do JSON `estatisticas`.
  * PDFs emitidos antes não mudam; o identificador de versão continua o mesmo para o mesmo resultado.

## 9. Pendências e limitações (não verificadas ou não feitas)

1. **Clique-até-desenho ≤ 200 ms e troca de item ≤ 250 ms**: não atingidos (§6).
2. **Ata e lista completa de propostas**: nenhuma fonte integrada as entrega; o PDF não os simula (AC-18, AC-22).
3. **Busca de reforço automática** para amostra pequena com atípico (AC-06): o alerta orienta, mas não dispara nova busca.
4. **PDF pelo conversor da produção**: a amostra foi convertida pelo Word desta máquina. O carimbo de links usado com o LibreOffice 7.4 tem prova unitária (`test_carimbo_de_link_sobre_o_numero_impresso`), mas não foi exercitado com o LibreOffice real.
5. **Acessibilidade**: leitor de tela e zoom de 200% não testados.
6. **Staging, canário e 24 h de observação**: não disponíveis aqui (AC-35).
7. **Limiares da v2** (8 preços, 50%) são parâmetros de triagem a calibrar com casos reais e com a assessoria jurídica do ente (08_COMPLIANCE). Não são critério legal.
8. **Prévia local**: a renderização em tema escuro do navegador da prévia deixava textos invisíveis no CSS atual. As capturas usam o tema claro; o tema escuro não foi tratado.
