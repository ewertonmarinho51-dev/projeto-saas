# G3 — revisão visual do PDF nativo do corpus completo

Estado: **PASS VISUAL LOCAL DO PDF NATIVO SINTÉTICO; G3 GERAL CONTINUA PARCIAL**

Em 2026-10-18, os 16 PDFs do round-trip integral em
`work/wordcraft-full-roundtrip-c08-rows-02` foram renderizados com Poppler
`pdftoppm` a 120 DPI. A revisão cobriu 87 páginas em folhas de contato geradas a
partir dos PDFs atuais. As páginas com tabelas, timbrado e estrutura externa
também foram abertas em resolução integral; as 16 páginas de C08 tiveram
inspeção individual adicional a 144 DPI, documentada no aceite próprio.

## Inventário observado

| Caso | Páginas | SHA-256 do PDF |
|---|---:|---|
| C01 DFD | 4 | `204cc18498ca17bbf79bf90a4594ef2856b2f01a3faa5e1ef1f865a1efc9de4a` |
| C02 ETP | 29 | `52c1eb0fbeebb2843f434ffd4c4d5647cd13c32890d8c67010c7eafb405ae72c` |
| C03 Mapa de Riscos | 3 | `7fc279ecee7720848b54723eaffcfc7c28c7839d8f53fcd4bf0a738d740fd28c` |
| C04 TR | 8 | `f578f8e5a8237f712756054cab98dcfe8f242b71a4231cdf49f5b8726d3ec75f` |
| C05 Edital | 15 | `561ab3684ec40bba86de0f5c4006d2967164c19ada8a411585161e4d0303dda7` |
| C06 ARP SRP | 1 | `d07dbd8a4169fd4d085b6ea8081ec6fec3926e5900b8f450720c963c2d255bec` |
| C06 dossiê sem SRP | 2 | `2afb3a9f9e0734d010fb67a2d5a57ae2bf62accbbad820d417d978669a10770c` |
| C07 município | 1 | `e35a6160cc02ee2216ab8bed5db8e650ae569e58f6cb48cd34c19f835afd6b62` |
| C07 secretaria | 1 | `898b98b99e0fe82ed3dc93ba7a9c2b2931a8c45f8f860fccacb6b709d3afb85f` |
| C08 planilha | 16 | `da8cd6978fc75af610a58bb9cef966e6344d6e7256936e1392a31b099ac17acf` |
| C09 parecer | 1 | `81b7403515d682f569e162290285429d77bb225c67a09703e20cab1803cb4bd9` |
| C10 modelo externo | 2 | `8495cea6fa061c57f7876f7c11b6da1403fd438376131cfa14d018757916c5c9` |
| C11 nova revisão | 1 | `905942bf81590cc47275f9bf558e2fa1015a95cfd0bf2178d76225bbc228a958` |
| C11 original | 1 | `307eeeb3be4c2003a2c4a85ac13e46fced7dfb8258f5360479e074da845f8175` |
| C12 tenant A | 1 | `c2cfc7d209cd1217a1f457a643dfa92efbfb436a9345b70e8877fefd7548e8a8` |
| C12 tenant B | 1 | `364cc7947a81781792e328cdd08763e859d572d91c3e51b49dde78aabbbb3fd3` |

## Resultado

- as 87 páginas renderizaram sem página ausente, quadrado preto ou glifo
  ilegível;
- nenhuma página apresentou tinta nos seis pixels externos da imagem, afastando
  corte nas bordas do PDF renderizado;
- títulos, numeração, acentuação, hyperlinks azuis e rodapés permaneceram
  legíveis e coerentes entre páginas;
- C01, C04, C06 e C08 exibiram tabelas monetárias com bordas fechadas, conteúdo
  dentro das células e totais globais visíveis;
- C03 preservou a célula mesclada alta e as categorias agrupadas declaradas no
  oráculo; o espaço vertical resultante é parte da fixture e não foi ocultado;
- C05 preservou índice, remissões e sequência das 32 cláusulas;
- C07 secretaria preservou marca sintética, identidade, signatários e rodapé;
- C10 preservou tabela aninhada, célula mesclada, hyperlink, segunda página e
  campo de página;
- C11 manteve original e nova revisão visualmente separados;
- C12 manteve os marcadores visuais distintos de tenant A e tenant B.

Este aceite trata da legibilidade visual dos PDFs nativos sintéticos exatos
listados acima. Não afirma identidade pixel a pixel com LibreOffice ou Word,
fidelidade de um documento municipal real, acessibilidade completa, impressão
física ou aceite no navegador. As diferenças de tabelas já registradas na
comparação LibreOffice e a execução Linux continuam impedindo fechar G3 geral.
