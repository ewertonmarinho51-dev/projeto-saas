# C10 — round-trip de modelo externo sintético

## Resultado

O cenário C10 passou no worker WASM local pinado para o fluxo completo
`importar DOCX -> editar pelo patch nativo -> validar -> exportar DOCX ->
reimportar -> exportar PDF`. A verificação compara o texto e os links esperados
após a edição e mede separadamente todos os recursos declarados pelo cenário:
tabela aninhada, mescla horizontal, cabeçalho, rodapé, campo `PAGE` e quebra de
página.

A aprovação é restrita ao corpus sintético e à fidelidade estrutural declarada.
As duas páginas do PDF nativo exato foram revisadas visualmente em 2026-10-18:
cabeçalho, rodapé com campo de página, hyperlink, tabela externa, célula mesclada
e tabela aninhada estavam legíveis e sem corte. A abertura visual do DOCX em
Word/LibreOffice continua pendente; portanto este resultado não aprova
homologação, substituição do editor legado, deploy ou uso em produção. A revisão
do PDF está consolidada em `revisao-visual-pdf-nativo.md`.

## Evidência local reproduzível

- entrada: `work/wordcraft-full-corpus-01`, manifesto SHA-256
  `6680613b324d4850346094b3d96b7f6d56e8f8d515d4114feb320b56eea624de`;
- motor: manifesto SHA-256
  `bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548`;
- saída: `work/wordcraft-full-roundtrip-c10-edit-03/comparison.json`, SHA-256
  `162a3bd25d055a279bb5a28c4c1fcb60fc3cfdd5f9d5279dd7a57ef58667b6c7`;
- corpus completo: 16 variantes, zero falhas ou diferenças;
- C10 DOCX SHA-256:
  `c2b0c318213c6b0ea1584b9cd767bec942745dac2fab243486486ed7cf6df951`;
- C10 checkpoint editado SHA-256:
  `68f4aa29ec2e168988002e7974299ed9c39dd8c373c407a33604454189784feb`;
- C10 PDF SHA-256:
  `8495cea6fa061c57f7876f7c11b6da1403fd438376131cfa14d018757916c5c9`.

O marcador `C10-EXTERNAL` foi alterado para `C10-EXTERNAL-EDITED` pela API
`gc-wordcraft-native-patch/v1`. O runner rejeita alvo ausente ou duplicado e
vincula o comando ao hash exato do checkpoint e à revisão 1. A exportação
preservou exatamente os seis recursos declarados antes e depois da edição.

## Regressão automatizada

`tests/test_wordcraft_c10_roundtrip.py` garante que a fixture realmente contém
os seis recursos e que o plano de patch aponta para uma única ocorrência, com
offsets UTF-8 e hash do checkpoint. O runner
`scripts/wordcraft_full_roundtrip.py` executa a prova real e faz qualquer etapa
recusada ou diferente contar como falha.
