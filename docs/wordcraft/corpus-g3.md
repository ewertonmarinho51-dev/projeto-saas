# Corpus sintético complementar de G3

Decisão e inventário registrados antes do código: acrescentar uma opção explícita `--full-corpus` ao gerador de QA existente, sem alterar a geração G1, os três DOCX versionados, seus hashes ou o workflow Rust em execução. Este incremento prepara entradas e oráculos; não aprova fidelidade, emissão institucional ou rollout.

## Reuso e limite

`scripts/wordcraft_corpus.py` continuará usando `src.export.gerar_docx` e a planilha existente. O corpus completo reutilizará as funções puras de `perfis`, `contexto.resolver_identidade`, `portarias` e `assinaturas` para montar perfis, identidade e snapshots inteiramente sintéticos, sem ler banco, sessão, cadastros reais ou chamar IA/rede. Esses snapshots são entradas de ensaio, não aprovações registradas no banco.

Python-docx acrescentará somente recursos de fixture que o Markdown atual não expressa: mesclas horizontais/verticais, tabela aninhada, bookmarks/remissões e campo de página de um modelo de terceiro simulado. Esse enriquecimento será declarado por caso; não vira exportador de produção. A marca rasterizada será uma figura geométrica original criada pelo próprio gerador para QA, sem copiar logos ou material de terceiros.

As contas esperadas usarão `Decimal` sobre os dados literais de origem antes de consultar o calculador/exportador do produto, e ficarão em arquivos de oráculo separados. A validação não poderá simplesmente adotar os valores devolvidos pelo exportador como resultados esperados.

PDF será opcional e exigirá LibreOffice real. O helper de conversão DOCX→PDF existente receberá os bytes finais já enriquecidos; fallback fpdf2 não será aceito. Paginação/visual permanecerão pendentes até inspeção dos arquivos renderizados e comparação WordCraft/LibreOffice. Nenhum DOCX/PDF deste incremento será apresentado como documento final aprovado.

## Inventário deste incremento

| Arquivo | Responsabilidade |
|---|---|
| `scripts/wordcraft_corpus.py` | Geração opcional completa, oráculos independentes, enriquecimento exclusivo de QA, verificação de arquivos gerados |
| `tests/test_wordcraft_corpus.py` | Regressões das três fixtures antigas e validações significativas dos casos completos, incluindo negativa de ARP e de fallback PDF |
| `docs/wordcraft/corpus-g3.md` | Contrato do corpus, escopo por caso e evidências/pendências |

## Cobertura exigida pelo documento 05

| ID | Entrada planejada | Evidência ainda necessária após a geração |
|---|---|---|
| C01 | DFD com 5 itens, perfil existente e signatários elegíveis em portaria sintética | Abrir/editar/exportar e conferir layout/assinaturas |
| C02 | ETP longo com todos os títulos aplicáveis do perfil e marcadores ordenados | Paginação, quebras, títulos e texto integral nos dois motores |
| C03 | Mapa de Riscos com mesclas horizontais e verticais e quebra explícita | Geometria das células e continuação de página |
| C04 | TR com 30 itens e oráculo Decimal independente | Valores, colunas e total no modelo, DOCX e PDF |
| C05 | Edital extenso, índice de cláusulas, bookmarks, remissões e links sintéticos | Numeração e destinos preservados no round-trip |
| C06 | ARP com SRP e dossiê negativo sem SRP usando a regra canônica | Emissão condicional no fluxo operacional |
| C07 | Timbrado por secretaria, fallback municipal e snapshot da marca | Marca/cabeçalho/rodapé estáveis após alterar cadastro de ensaio |
| C08 | Planilha de 210 itens reutilizando o gerador já existente | 210/210 em níveis canônico, editor, DOCX e PDF |
| C09 | Parecer sintético com recomendação objetiva, ambígua e conflitante | Aplicador único, diff, revisão e pendências reais |
| C10 | Modelo DOCX externo simulado com recursos estruturados declarados | Importar/editar/exportar sem perda dos recursos declarados |
| C11 | Original Markdown e duas versões documentais distintas | Owner rejeita alteração do emitido/aprovado e mantém versão histórica |
| C12 | Dois tenants/secretarias sintéticos com marcadores disjuntos | JWT/RLS/storage/cache/bridge isolados em execução real |

Gerar os doze IDs não prova os doze aceites. C09, C11 e C12 são sementes para testes funcionais posteriores, com estado `NOT_TESTED` para aplicação, imutabilidade e autorização. Links `example.invalid` são dados de formato/proveniência e nunca serão consultados. Datas, nomes, portarias, valores e identificadores serão declaradamente fictícios.

## Uso e evidência do incremento

No checkout do produto, usar uma pasta nova fora da árvore tests/fixtures/wordcraft:

    python scripts/wordcraft_corpus.py --full-corpus --out ../wordcraft-full-corpus-qa

Com LibreOffice real disponível e funcional, gerar outra pasta nova:

    python scripts/wordcraft_corpus.py --full-corpus --pdf --out ../wordcraft-full-corpus-lo

O modo antigo sem --full-corpus e o comparador G1 continuam separados. A opção completa recusa a árvore das fixtures G1 e qualquer pasta de saída não vazia. O manifesto completo se chama full-manifest.json; verify_full_inputs verifica hashes/tamanhos, inventário fechado e estrutura/valores contra os oráculos separados, sem mudar os estados de aceite.

Execução real da CLI em work/wordcraft-full-corpus-01: **12 cenários, 16 DOCX e 50 arquivos, total de 884.943 bytes**. A verificação posterior de todos os arquivos passou. O ETP possui 8.484 palavras na fonte Markdown. O conjunto inclui:

- C01: cinco itens, total independente **R$ 10.003,55**, nove cláusulas do perfil existente e dois snapshots de signatários elegíveis pela portaria fictícia QA-001/2026.
- C03: mescla horizontal de seis células, três mesclas verticais com nove continuações e uma quebra de página solicitada na estrutura.
- C04: trinta itens, total independente **R$ 1.085,85**, com descrição, unidade, quantidade, valor unitário, total de cada linha e ordem conferidos no OOXML.
- C05: 32 bookmarks e 32 remissões internas reais, além de oito links sintéticos externos.
- C06: ARP presente no caso SRP e ausente do dossiê negativo renderizado pelo exportador canônico.
- C07: PNG geométrico original incorporado ao DOCX por SHA-256, identidade própria e fallback municipal produzidos pelo resolvedor existente.
- C08: 210 códigos e respectivas descrições/quantidades/valores, com total independente **R$ 92.900,30** e rejeição comprovada de adulteração de quantidade e total.
- C10: tabela externa com mescla, tabela aninhada, header/footer, campo PAGE e quebra explícita; origem declarada como modelo externo simulado, não arquivo real de terceiros.

Verificação final: **23 testes passaram em 13,86 s** — cinco regressões existentes e dezoito verificações novas. A execução completa também passou com os acessos a banco e a abertura de conexão de rede instrumentados para falhar. Testes negativos confirmaram rejeição de calculador adulterado, célula monetária alterada, quantidade/total alterados, arquivo modificado, destino ocupado e fallback/falha de conversão PDF. git diff --check sem erros; o Git apenas avisou sobre a política LF/CRLF do checkout. Nenhum dos três arquivos de fixture ou manifestos G1 foi alterado.

Não havia soffice/libreoffice no PATH local desta execução. Não foram gerados PDFs nem imagens de revisão, e nenhum DOCX recebeu aceite visual. Os campos wordcraft_roundtrip=NOT_RUN, libreoffice_pdf=NOT_REQUESTED e visual_review=PENDING permanecem no manifesto. As sementes de parecer, legado/histórico e tenants mantêm os testes operacionais em NOT_TESTED. A validação de geração e OOXML não substitui importação/edição/exportação no WordCraft, renderização pelo LibreOffice, inspeção de páginas, aprovação imutável ou isolamento real.
