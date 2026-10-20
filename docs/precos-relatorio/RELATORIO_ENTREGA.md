# Relatório de Cotação — entrega para homologação

Branch `feature/relatorio-cotacao-visual` (base `main` `f5c004d`, v1.9.1).
Progresso por gate: `docs/precos-relatorio-progress.md`.
**Recomendação: APTO PARA HOMOLOGAÇÃO** (flag desligada por padrão; sem
merge, deploy ou migração).

## Antes e depois — o MESMO snapshot sintético

Gerado por `scripts/relatorio_cotacao_amostras.py` (LibreOffice 26.2 local
com as fontes DejaVu da produção). Números em `metricas.json`.

| Amostra | Anterior (completo) | Novo | 
|---|---|---|
| 5 itens · 871 consideradas · 2.857 referências (regra legada: mediana) | 321 págs · 13,3 MB · 54 s | **Relatório de Cotação: 6 págs · 258 KB · 6 s · 32 links** |
| idem, todas as referências | (no próprio completo) | **Analítico Integral: 158 págs paisagem · 11,5 MB · 27 s · 2.857 links** |
| 210 itens · 1.474 referências | 374 págs · 12,1 MB · 64 s | 122 págs · 5,0 MB · 17 s · 906 links |
| pendências (5 itens: concluído, sem preço, 2/3, em revisão, exceção) | 11 págs | 5 págs |
| institucional (timbrado do tenant) | 5 págs, **sem timbrado** | 2 págs, timbrado |
| cotação sem itens | — | 1 pág., "não tem itens" |

QA auxiliar do pacote (`scripts/pdf_quality_check.py`): todos os PDFs
novos aprovados (sem página vazia, sem texto fora da folha, sem
cabeçalho partido, título obrigatório presente; compacto ≤ 15 págs). O
anterior do mesmo snapshot reprova (321 págs, título fora do padrão).

## Capturas

| Arquivo | O que mostra |
|---|---|
| `01_primeira_pagina.png` | abertura, metadados, quadro de 7 colunas, subtotal e valor global, método |
| `02_quadro_resumo_pendencias.png` | aviso nominal, pendentes destacados com texto, subtotal só dos concluídos |
| `03_item_detalhado.png` | faixa do item, indicadores, "exibidas 5 de 196", não consideradas por motivo, memória |
| `04_fontes_e_alertas.png` | fontes com enquadramento e coleta, alertas |
| `05_pagina_com_pendencia.png` | "Não estimado", "provisório", desconsiderada riscada com justificativa |
| `06_quebra_de_tabela_210_itens.png` | cabeçalho repetido na quebra |
| `07_ultima_pagina.png` | identificação, identificador SHA-256, conferência, "Página 6 de 6" |
| `08_anexo_analitico.png` | anexo em paisagem, uma linha por referência, link e evidência |
| `09_timbrado_institucional.png` | cabeçalho com timbrado (sintético) do tenant |
| `10_`, `11_ANTERIOR_*.png` | o relatório anterior do mesmo snapshot |

## Testes

* `tests/test_relatorio_cotacao.py` — 39 provas: golden 22,70/29,00/25,85
  → R$ 25,85 e R$ 258,50; exclusão depois da seleção → 2/3 e fora do
  subtotal; sem preço nunca "R$ 0,00"; provisório fora do quadro e do
  subtotal; subtotal = soma exata dos concluídos (210 itens); legado
  continua mediana; N = `cesta.consideradas`; marcada sem preço
  normalizado fora e sem link; 196/317 com amostra declarada e anexo
  completo; três saídas concordam (hash, N, totais, links, IDs); perfil
  real sem conformidade automática a IN; nada do documento comercial;
  projeção imutável e sem efeito colateral; hash independe da emissão;
  especificação de 500+ caracteres inteira; timbrado por tenant;
  geometria, "Página X de Y", cabeçalhos inteiros, links reais e bloco
  do item que não se parte no PDF real.
* `tests/test_relatorio_cotacao_tela.py` — 9 provas da tela (flag
  desligada/ligada, emissão registrada como `completo`, falha de
  conversão vira mensagem, limite do integral, pacote sem integral,
  timbrado pelo resolvedor).
* Teste de mutação: 6 regras quebradas de propósito (subtotal com não
  concluídos, N com marcadas sem preço, zero no quadro, amostra = mais
  baratas, link fabricado, global com pendentes) — as 6 pegas.
* Suíte completa local, com LibreOffice: **2935 passed, 306 skipped**
  (os pulos são do PostgreSQL de ensaio, ausente nesta máquina).

## Custo

Nenhuma chamada de IA, rede ou banco na emissão. O compacto custa ~6 s
(quase todo o tempo é a partida do LibreOffice); o integral de 2.857
referências, ~27 s localmente — a produção roda LibreOffice 7.4 e pode
ser mais lenta; a tela avisa o volume antes e limita a 15.000
referências. DOCX do compacto em < 1 s.

## Rollback

Flag `flag_precos_relatorio_visual` desligada (padrão). Desligar não
mexe em cesta, preço, emissão registrada ou PDF emitido; o gerador
anterior está intacto.

## Abertos

* Ligar a flag em homologação é ato do operador (`config_app`).
* Compacto de 210 itens = 122 páginas (um bloco por item). Se preferir,
  um modo "quadro + pendências" para processos grandes cabe no mesmo
  renderer.
* Quantidade muito grande ("65.600 UNIDADE") quebra em duas linhas no
  quadro — legível, sem palavra partida.
