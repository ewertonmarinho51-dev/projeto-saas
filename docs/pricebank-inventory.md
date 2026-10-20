# Banco de Preços — inventário e matriz de substituição

HEAD inicial: `0167c5f` (main, v1.7.2). Branch: `feature/govconnect-banco-precos-ia`.

## Inventário do que existia (Gate 0)

| Área | Arquivo | Achado |
|---|---|---|
| Adapters | `src/precos/fontes.py`, `compras_gov.py`, `pncp.py`, `catalogo.py` | Compras.gov por código ou por descrição (PDM); PNCP só evidência (itens/resultados 502/503 em 05 e 07/09) |
| Coleta + cesta + estimativa | `src/precos/execucao.py` | coleta, deduplicação, unidade e ranking DENTRO de `pesquisar_item` — sem serviço reutilizável |
| Modelo / procedência | `src/precos/modelo.py` | `Referencia` com bruto + hash; `FONTES_REGISTRADAS`; natureza do valor |
| Matching | `src/precos/matching.py` | identidade × circunstâncias; boost por grupo PDM |
| Estatística | `src/precos/estatistica.py` | Decimal; automático trocava média↔mediana pelo CV (0,25) |
| Perfis | `src/precos/perfil.py` | LEI_14133 e IN_65_2021 (teto da mediana), mínimo 3 |
| Persistência | `src/precos/repositorio.py`, `supabase/migrations/0021_pesquisa_precos.sql` | 4 tabelas com RLS, sem DELETE; `versao_regras`, `idempotency_key` |
| IA | `src/precos/jev.py`, `decisoes.py`, `semantica.py`, `src/ai_gateway.py` | Jev devolve só `manual_review` (modo sugestão) |
| Tela | `src/ui/precos_ui.py` | lista, itens, execução em lotes, revisão, resumo; **sem consulta manual** |
| Relatório | `src/precos/relatorio.py`, `src/export.py` | completo, resumido, XLSX, PDF/DOCX pelo motor institucional |
| Aplicação | `src/precos/aplicacao.py` | diff e aplicação ao processo |
| GovBot | `src/precos/orientacao.py` | orientação determinística |

Lacunas encontradas: revisão não refazia o preço; código interno zerava
identidade (0/10 concluídos); sem consulta manual; sem indicador N/3;
fila travava com itens que sempre falham; PNCP sem preço; sem cotação
direta; XLSX sem neutralização de fórmula; recálculo tiraria discrepante
calado; revisão de cesta grande não terminava de desenhar.

## Matriz de substituição (pacote 12), com o que foi feito

| Função | Existente | Ação | Status |
|---|---|---|---|
| Adapter de fonte | `fontes.py`, `compras_gov.py`, `pncp.py` | `codigo_confirmado`; `url_de_verificacao`; **`pncp.PNCPContratacao`** (preço homologado da contratação conhecida) | Reaproveitado e evoluído — IMPLEMENTADO E TESTADO (PNCP também live) |
| Busca por item | `execucao.pesquisar_item` | **`busca.coletar`** — serviço único; o trecho duplicado de `execucao` foi REMOVIDO | Refatorado — IMPLEMENTADO E TESTADO |
| Referência e proveniência | `modelo.py` | `cotacao_direta` registrada; bruto lido de volta em `cesta.referencia_da_linha` | Evoluído sem migração — IMPLEMENTADO E TESTADO |
| Dedup/matching | `modelo.deduplicar`, `matching.py` | **`busca.fundir_entre_portais`** (mesma compra no Compras.gov e no PNCP conta 1); cota principal/reservada conta 1 | Ampliado — IMPLEMENTADO E TESTADO (fusão observada live) |
| Jev e IA | `jev.py`, `decisoes.py`, `ai_gateway.py` | nenhum gateway novo; triagem dublada provando 1 chamada/item e 0 na retomada | Reutilizado — IMPLEMENTADO SEM TESTE LIVE (sem IA paga, por regra) |
| Estatística e perfil | `estatistica.py`, `perfil.py` | média padrão nas pesquisas novas (`REGRAS_MEDIA_PADRAO`); antigas na regra do CV; método fora do perfil = impedimento; **pendências de análise crítica** | Núcleo atualizado, sem 2º cálculo — IMPLEMENTADO E TESTADO |
| Persistência | `repositorio.py` | `atualizar_estimativa`; nenhuma migração | Expandido sem schema novo — IMPLEMENTADO E TESTADO (banco dublado) |
| Cesta | (não havia serviço) | **`cesta.py`**: recálculo pela seleção gravada, N/3, salvar consulta como pesquisa, excluir discrepantes com motivo | Adicionado ao domínio — IMPLEMENTADO E TESTADO |
| Tela | `precos_ui.py` | tela **Banco de Preços** na mesma página; N/3 na tabela; revisão paginada; cotação; exclusão em lote | Transformada, sem produto paralelo — IMPLEMENTADO E TESTADO (AppTest + navegador) |
| GovBot | `orientacao.py` | sem mudança; continua lendo o que o motor calcula | Preservado |
| Relatório | `relatorio.py`, `export.py` | seção de cotações diretas; XLSX com neutralização de fórmula; contagem "na cesta" inclui sinalizadas | Evoluído — IMPLEMENTADO E TESTADO |
| Aplicação ao processo | `aplicacao.py` | sem mudança; provado que a consulta manual chega ao processo por ele | Preservado — TESTADO |
| Cotação direta | não havia | **`cotacao.py`**: art. 23, § 1º, IV; comprovante por SHA-256 | Adicionado — IMPLEMENTADO E TESTADO (sintético). Link seguro ao fornecedor: NÃO IMPLEMENTADO |
| Indexação multi-fonte | não havia | — | NÃO IMPLEMENTADO (exige migração; ver progresso) |
| Fila da execução | `execucao.proximo_lote` | prioridade interrompido → pendente → erro; erro 1×/execução | Corrigido — IMPLEMENTADO E TESTADO |

## Descontinuado

* Coleta/ranking duplicados dentro de `execucao.pesquisar_item` →
  substituídos por `busca.coletar` (mesmos testes de fase 4 passando).
* `ROTULO_DESFECHO` com chaves `ok/vazio/falha` que nunca casavam com o
  enum real (a tela mostrava `success_with_prices`).

Nada foi apagado do banco e nenhuma migração foi criada ou removida.
