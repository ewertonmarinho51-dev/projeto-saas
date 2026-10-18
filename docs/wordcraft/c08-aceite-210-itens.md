# C08 — integridade de 210 itens

Estado: **PASS NATIVO NOS QUATRO NÍVEIS; REVISÃO VISUAL PENDENTE**

O cenário C08 prova explicitamente os 210 itens na fonte canônica, no checkpoint
editável do WordCraft, no DOCX reexportado e no texto do PDF nativo. Cada código
ocorre uma única vez no checkpoint. No PDF, cada janela delimitada por código
contém a descrição completa, unidade, quantidade, preço unitário e total daquela
linha; um valor presente em outra linha não encobre truncamento. O total
monetário independente continua sendo `92900.30` e aparece no PDF.

## Execução local pinada

- corpus de entrada: `work/wordcraft-full-corpus-01`;
- manifesto do motor:
  `bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548`;
- relatório: `work/wordcraft-full-roundtrip-c08-rows-02/comparison.json`;
- SHA-256 do relatório:
  `6855af9d6fc3e0c201d37b9474e5fe3e9023311d1408566872e9506a4d8ec566`;
- resultado do corpus completo: 16 variantes, zero falhas ou diferenças;
- checkpoint C08: 210 códigos distintos e 210 ocorrências;
- PDF C08: 210 linhas completas, zero ausentes, total global presente, em 16 páginas;
- checkpoint SHA-256:
  `374277f15e266a4c515346ea8115e98324a686fe7cc5118c7d5e9b8322eb4f16`;
- DOCX SHA-256:
  `6c1fe3d358574517eb4797cce1d40909ac3cc6ed850a8e2c23b991012a88dbe3`;
- PDF SHA-256:
  `da8cd6978fc75af610a58bb9cef966e6344d6e7256936e1392a31b099ac17acf`.

O contador percorre somente os valores do objeto `document` do checkpoint; nomes
de campos JSON, `media` e `passthrough` não podem fabricar cobertura. Ausência ou
duplicação de qualquer código transforma a etapa em `DIFFERENT` e faz a execução
falhar.

Este PASS cobre integridade semântica e estrutural do corpus sintético. A
comparação visual ampliada das 16 páginas continua necessária e não foi inferida
a partir de contagem, hash ou extração de texto.
