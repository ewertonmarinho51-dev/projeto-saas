# Investigação de fidelidade das tabelas — G3

Estado: correção tipada implementada no overlay, compilada e testada localmente
no alvo Windows GNU; round-trip/raster do corpus corrigido e aceite visual ainda
dependem da execução Linux. Escopo: as seis páginas com diferenças raster entre
LO do DOCX original e LO do DOCX reexportado nativo: C01/DFD p2, C03/Mapa p2–3,
C04/TR p1–2 e C06/ARP p1.

As entradas são os DOCX sintéticos exatos de `work/wordcraft-full-corpus-01` e `work/wordcraft-full-roundtrip-a9f-01`, correlacionados pelo `comparison.json` nativo pinado `183f8a86afbcfd5a5e936eaa792f450abd498a32f99f7116fe2fce8606feb552` e pelas evidências de LO existentes em `work/wordcraft-lo-windows-review-01`. O checkout local de leitura `work/wordcraft-filtered` tem HEAD `533615620ef91ae57fa7aa4cd77fd98b2179e693`, igual a `docs/wordcraft/upstream.lock.json`.

Não serão executadas novas conversões Windows, downloads, builds, alterações no core/overlay/runner, cópias de XML para reparar exportação ou edição de checkpoint como motor concorrente. A investigação compara XML e modelo real já produzido, localiza as rotas de importação/exportação e propõe uma regressão mínima a executar pelo mesmo motor.

## Resultado: três perdas de IO confirmadas, sem atribuição visual além da prova

Foram identificadas perdas concretas no modelo/importador/exportador do mesmo motor:

1. `w:tblInd w:w="0" w:type="dxa"` em **estilos de tabela** é descartado. Não é perda de `tblGrid`, `tcW`, `tblW` ou autofit.
2. Formatação de **runs vazios** de parágrafos sem texto desaparece, inclusive nos cinco parágrafos vazios da célula horizontalmente mesclada do Mapa de Riscos.
3. `w:compat` preserva somente `compatibilityMode`. As flags originais `overrideTableStyleFontSizeAndJustification`, `enableOpenTypeFeatures`, `doNotFlipMirrorIndents` e `useFELayout` são descartadas.

As três perdas foram observadas nos DOCX/checkpoints existentes. As duas primeiras e a lista de compatibilidade também foram reproduzidas pelo WASM QA 39 atual, com `importar_docx → validar → exportar`, sem modificar bytes de checkpoint. O resultado visual permite medir a translação e o tamanho dos links, mas **não isola por ablação qual flag causa cada diferença**. Não foram renderizadas versões alterando uma propriedade por vez, por restrição explícita desta investigação. Portanto, corrigir as perdas de IO é uma proposta fundamentada; afirmar que um patch específico eliminará todos os pixels diferentes ainda dependerá da prova Linux.

## Entradas e correção da hipótese visual anterior

Os hashes abaixo identificam os arquivos efetivamente examinados; nenhum deles foi modificado:

| DOCX sintético | SHA-256 original | SHA-256 reexportado nativo a9f |
| --- | --- | --- |
| C01/dfd | `9e7796532006e31c1a7df0d4c9dd32c575a37e78a143e20372f8bcb1a45689f1` | `83aaa1c9cb3b628ab46402683931ae6e9f51601e87ac5646411c7eeb7c00ffe9` |
| C03/mapa-riscos | `aab24cc86cbd384e4bf63de32cf9c366265b304012ddcfb07d88564c2a5a63b8` | `97dc2a22e694634ede4de885114f5f03bfdf2354a1136ceecb0e091adb028582` |
| C04/tr | `0c42dcc421c887b81d893f4ae8eaaad1c591708ccd0c0dcd6ed55f9088ef8a07` | `31df5326b1323a1cc34d2fb7894714940f1aa9cfd99160cb9379a48b69b0015c` |
| C06/arp-srp | `3a81f3f9653f275ea95f5491e88b9779a9b59f78f592ac6b4ae9d761f007e153` | `609e6beb4c5b840a473169bb1d4e79483be999edefe37f423cfecc515f2bdff0` |

A impressão inicial de mudança de larguras de coluna foi corrigida pela medição dos vetores reais dos PDFs com `PyMuPDF.Page.get_drawings()`. Todas as bordas verticais se deslocaram **+2,000 pt**, conservando as distâncias entre colunas. Exemplos:

| Caso/página | Bordas verticais no LO original, pt | Bordas no LO reexportado, pt |
| --- | --- | --- |
| DFD p2 | 54,5 / 116,8 / 226,4 / 276,3 / 335,8 / 406,0 / 471,2 / 536,4 | 56,5 / 118,8 / 228,4 / 278,3 / 337,8 / 408,0 / 473,2 / 538,4 |
| Mapa p2 e p3 | 54,5 / 123,1 / 182,0 / 307,3 / 367,4 / 413,0 / 536,4 | 56,5 / 125,1 / 184,0 / 309,3 / 369,4 / 415,0 / 538,4 |
| TR p1 e p2 | 54,5 / 117,1 / 228,5 / 278,4 / 337,9 / 408,5 / 471,1 / 536,4 | 56,5 / 119,1 / 230,5 / 280,4 / 339,9 / 410,5 / 473,1 / 538,4 |
| ARP p1 | mesmos valores do DFD | mesmos valores reexportados do DFD |

As observações anteriores de raster continuam válidas: seis páginas diferentes, 44 das 50 páginas derivadas com PNG byte idêntico ao original, texto compacto e paginação LO iguais nos seis casos disponíveis. A interpretação de "larguras de colunas diferentes" deve ser substituída pela **translação da tabela**, acompanhada por diferenças de fonte herdada/altura de conteúdo.

## Propriedades preservadas e propriedades ausentes

Nas quatro tabelas, a largura total permanece `9638` twips, `w:type="dxa"`, e `w:tblLayout w:type="fixed"`. A comparação de todas as células, e não somente da primeira linha, encontrou os mesmos `tcW` e tipos. Os grids são:

| Tabela | `gridCol/@w:w` antes e depois | Linhas antes/depois |
| --- | --- | ---: |
| DFD e ARP | 1247, 2194, 998, 1191, 1406, 1304, 1304 | 7/7 |
| Mapa | 1372, 1179, 2506, 1202, 913, 2466 | 14/14 |
| TR | 1253, 2228, 998, 1191, 1412, 1253, 1304 | 32/32 |

Também são iguais: margens diretas de tabela `[17,45,17,45]` twips; ausência de margens próprias de célula; espaçamento direto dos parágrafos `after=40,line=240,lineRule=auto`; ausência de `pStyle` e de `jc` direto nesses parágrafos; `TableGrid` baseado em `TableNormal`; cabeçalho repetido e `cantSplit`; ausência de shading/noWrap/direção especial direta nas células examinadas. O Mapa mantém `gridSpan=6`, três `vMerge restart` e nove continuações. O writer normaliza `tblHeader val="true"` para elemento vazio e `vMerge continue` para elemento sem `val`, equivalências de booleano/enum, sem perda de mescla.

DFD/ARP têm 39 ocorrências de `rFonts=Times New Roman` e `sz=20` preservadas; TR tem 189 preservadas. O Mapa passa de 75 para 70: desaparecem exatamente as cinco formatações dos runs vazios. Os IDs dos hyperlinks mudam e o writer acrescenta `history=1`; os destinos são preservados pelo relatório nativo já pinado. Esses IDs de relação não são larguras ou âncoras persistentes.

## Perda A: indentação explícita de estilo

No original, os dois estilos possuem:

```xml
<w:style w:type="table" w:styleId="TableNormal">…
  <w:tblPr><w:tblInd w:w="0" w:type="dxa"/>…</w:tblPr>
</w:style>
<w:style w:type="table" w:styleId="TableGrid">…
  <w:basedOn w:val="TableNormal"/>
  <w:tblPr><w:tblInd w:w="0" w:type="dxa"/>…</w:tblPr>
</w:style>
```

No reexportado, `tblInd` está ausente em ambos. O checkpoint também não possui propriedade de indentação no `table` dos estilos; `Table.props.indent=None` porque a tabela direta não tinha `tblInd`. Logo, não é um mero erro de escrita final: a informação já se perde na leitura para o modelo.

Rota no upstream pinado, com arquivos locais limpos em relação ao HEAD:

- [`crates/doc/src/styles.rs:51`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/doc/src/styles.rs#L51): `TableStyleParts` possui bordas, fill e margens, mas nenhum campo de indentação; o `overlay` começa em L92.
- [`crates/docx/src/read/mod.rs:820`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/read/mod.rs#L820): `table_style_parts` lê `tblBorders`, `shd`, `tblCellMar` e band size, ignorando `tblInd`.
- [`crates/docx/src/write/mod.rs:731`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/write/mod.rs#L731): o writer de estilos nem inclui indentação no critério para abrir `tblPr`, nem escreve `tblInd`.
- A rota de **formatação direta** já suporta `Some(0.0)`: `read/props.rs:443` lê `tblInd`; [`write/props.rs:440`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/write/props.rs#L440) escreve sempre que `Option` é `Some`. Deve ser reutilizada a mesma conversão/unidade, mantendo `None` diferente de zero.

A translação medida e a perda de indentação coexistem nos quatro casos. É a hipótese principal para o deslocamento horizontal. Ainda não foi feito teste visual de uma versão que preserve somente essa propriedade; não se afirma causalidade exclusiva, pois as flags de compatibilidade também mudam.

## Perda B: runs vazios no cabeçalho mesclado

O cabeçalho horizontalmente mesclado do Mapa mantém seis parágrafos: um com o título e cinco sem texto. Em cada um desses cinco, o original contém um run vazio com `Times New Roman`, `bold`, `sz=20`. O reexportado conserva o parágrafo e `pPr`, mas remove o run; o checkpoint fica com `text=""`, `runs=[]` e nenhuma formatação `mark`.

Nos PDFs existentes, o retângulo do cabeçalho mede 94,700 pt de altura no original e 89,000 pt no derivado: redução de **5,700 pt**, tanto em p2 quanto no cabeçalho repetido de p3. As linhas subsequentes mantêm a mesma altura e seguem esse deslocamento vertical; não há exclusão de riscos ou mudança de `gridSpan`/`vMerge`. A redução é compatível com a mudança do fallback de formatação dos cinco parágrafos vazios, mas a contribuição isolada depende de regressão visual após a correção.

Rota confirmada:

- [`read/story.rs:542`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/read/story.rs#L542): `read_run` lê os `rPr` locais, mas sem `w:t`/objeto não emite informação para o builder.
- [`read/story.rs:133`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/read/story.rs#L133): `PB::push_text` retorna imediatamente para texto vazio.
- [`read/story.rs:328`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/read/story.rs#L328): `read_para` preenche `mark` apenas a partir de `pPr/rPr`, que não existe nesses parágrafos; depois chama `normalize`.
- [`crates/doc/src/para.rs:1031`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/doc/src/para.rs#L1031): `normalize` elimina runs de comprimento zero. Desabilitar essa normalização não é a proposta.
- O modelo já tem [`Paragraph.mark`, L758](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/doc/src/para.rs#L758), e [`write/story.rs:155`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/write/story.rs#L155) já escreve formatação de marca como `pPr/rPr`. Deve-se avaliar esse mecanismo existente para a formatação efetiva de parágrafo vazio; a equivalência visual com o run vazio precisa ser testada.

## Perda C: compatibilidade e fonte herdada dos hyperlinks

O `settings.xml` original, igual nos casos examinados, contém:

```xml
<w:compat>
  <w:useFELayout/>
  <w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="14"/>
  <w:compatSetting w:name="overrideTableStyleFontSizeAndJustification" w:uri="http://schemas.microsoft.com/office/word" w:val="1"/>
  <w:compatSetting w:name="enableOpenTypeFeatures" w:uri="http://schemas.microsoft.com/office/word" w:val="1"/>
  <w:compatSetting w:name="doNotFlipMirrorIndents" w:uri="http://schemas.microsoft.com/office/word" w:val="1"/>
</w:compat>
```

O reexportado possui apenas `compatibilityMode=14`. O checkpoint expõe somente `compatMode`. [`read/mod.rs:999`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/read/mod.rs#L999) procura exclusivamente esse nome; o modelo [`Settings.compat_mode`, doc/lib.rs:466](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/doc/src/lib.rs#L466) não contém as demais opções, e [`write/mod.rs:974`](https://github.com/storytold/wordcraft/blob/533615620ef91ae57fa7aa4cd77fd98b2179e693/crates/docx/src/write/mod.rs#L974) emite somente o modo.

A extração de spans dos PDFs fornece um efeito herdado concreto: no DFD e TR, o texto `link` passa de **TimesNewRomanPSMT 12,0 pt para a mesma fonte 11,0 pt**. Exemplo DFD p2: origem `(473,5;495,7508)` → `(475,5;494,8008)`. O X acompanha a translação de 2 pt; o Y/bbox/underline acompanha a mudança de tamanho. Os XML dos runs de hyperlink têm a mesma cor `1B4F8A` e underline single, sem `rFonts`, `sz` ou estilo explícito; `Normal/rPr/sz=24` e `docDefaults/rPrDefault/rPr/sz=22` são preservados. Portanto, não há perda de um tamanho direto do link: mudou a resolução de uma propriedade herdada.

A flag perdida `overrideTableStyleFontSizeAndJustification` é o candidato prioritário para isolar esse comportamento de herança. Isso **não foi provado por remoção/restauração isolada da flag**. Outras normalizações coexistem: o `docDefaults/rFonts` simbólico de tema vira `Cambria`, e outras propriedades de settings fora da compatibilidade são descartadas. Como a fonte PDF do link continua Times New Roman e os tamanhos 12/11 coincidem com Normal/defaults, a flag merece o primeiro teste; não se deve substituir essa investigação por fonte/tamanho hardcoded nos DOCX.

## Repro mínimo real com QA 39, já executado em memória

Foi reutilizado o bundle local `work/wordcraft-browser-g4-39/static/wordcraft`, manifesto `bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548`, Node existente e `src.wordcraft_native`. Não houve escrita de DOCX, checkpoint ou PDF, nem execução LibreOffice nesta etapa.

O primeiro repro usa o exportador canônico `gerar_docx` com uma tabela de duas colunas e um link. O segundo usa a mesma superfície canônica e a operação de merge de `python-docx` exclusivamente para autorar uma fixture mínima com um parágrafo vazio formatado. Ambos passaram na validação nativa. Em ambos, os dois `tblInd=0` e as três `compatSetting` adicionais desapareceram; no segundo, o run vazio formatado desapareceu e o modelo ficou sem `mark`.

| Repro em memória | SHA-256 entrada desta execução | SHA-256 checkpoint validado | SHA-256 DOCX nativo |
| --- | --- | --- | --- |
| indent-and-compat | `027b3e979e81d41147ff73f03aa5dc7774a3f5f42e2961e750f6bfb7b16fd1db` | `bb26ebf9bce3cbfd673b1bb495bf05adb8634051a50c63fe63d167b554d1c6da` | `30d858279febafa39749cee8ea7f61b312e5d70c5567c9758ab02aad45449ff1` |
| merged-empty-run | `baf9c929a11f73de49ff122498a88ad153030868311ad0f43c39a392356bb381` | `cdbe39a4c516a6b26cec1083a85b97d2c1c60ed153b10d66eeb303df49be1b4d` | `fa7f4638c64257e93140a5a9c7ed7613fffbc43cfe37a9f8a5293ed22e4430f8` |

Esses digests identificam a execução observada, não são hashes de golden fixture: o empacotamento DOCX pode incluir timestamps em uma geração posterior. O roteiro mínimo é:

```python
import io
from pathlib import Path
from docx import Document
from src.export import gerar_docx
from src.wordcraft_native import importar_docx, validar, exportar

runtime = dict(node=NODE_EXISTENTE, bundle=BUNDLE_QA39,
    manifest_sha256="bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548")
source = gerar_docx("Repro sintético mínimo IO",
    "| Coluna A | Coluna B |\n|---|---|\n| Dado | [link](https://example.invalid/min) |")
checkpoint = importar_docx(source, **runtime)
validar(checkpoint, **runtime)
native_docx = exportar(checkpoint, formato="docx", **runtime)
# Inspecionar somente projeções de source/native_docx; não editar checkpoint.

source = gerar_docx("Repro sintético mínimo IO",
    "| Titulo | |\n|---|---|\n| A | B |")
fixture = Document(io.BytesIO(source))
fixture.tables[0].cell(0, 0).merge(fixture.tables[0].cell(0, 1))
buffer = io.BytesIO()
fixture.save(buffer)
checkpoint = importar_docx(buffer.getvalue(), **runtime)
validar(checkpoint, **runtime)
native_docx = exportar(checkpoint, formato="docx", **runtime)
```

## Proposta de patch e regressões no mesmo motor

O patch versionado `integrations/wordcraft/io-fidelity.patch` corrige os contratos tipados de IO sem copiar XML de documentos:

1. **Indentação de estilo:** acrescentar `Option<f32>` ao `TableStyleParts`, com defaults de serde compatíveis; ler `tblInd` em `table_style_parts`, herdar por `overlay` preservando zero explícito e escrever `tblInd` no writer de estilos. O critério de abertura de `tblPr` deve incluir `indent.is_some()`, não `indent != 0`. Validar a precedência: direto da tabela → estilo filho → estilo base → ausência. A resolução de layout em `crates/layout/src/table.rs:384` hoje considera só `Table.props.indent`; a consistência com a nova propriedade de estilo deve ser tratada conscientemente, sem substituir todos os indents por zero.
2. **Compatibilidade:** representar as flags identificadas por campos tipados com presença/valor, no `Settings` nativo; ler e escrever a enumeração conhecida, URI correta e valores booleanos, preservando ausente versus falso. Manter o modo existente separado. Não guardar/reinjetar um blob XML de settings. Começar a prova de herança por `overrideTableStyleFontSizeAndJustification`, seguida das demais flags, uma por alteração controlada.
3. **Parágrafo vazio:** capturar a formatação efetiva de run vazio quando o parágrafo não contém texto/objetos e ainda não tem marca explícita. Primeiro avaliar `Paragraph.mark`, já existente, com precedência de `pPr/rPr`. O writer atual suporta esse campo; a regressão visual deve provar equivalência com o original. Se isso não preservar a semântica, modelar tipadamente um carrier de formatação de parágrafo vazio; não conservar runs de comprimento zero indiscriminadamente nem desligar `normalize`.

Os testes atuais `crates/docx/tests/roundtrip.rs:498` cobrem bordas, margens e formatação de estilo, mas o modelo não tem indentação para testar. `fixtures.rs:642` e `roundtrip.rs:1155` cobrem somente compatibility mode. `roundtrip.rs:845` cobre marcas de parágrafo em tracked changes, não o run vazio formatado destes casos. Regressões propostas:

- Fixture OOXML mínima no helper existente de `crates/docx/tests/fixtures.rs`: tabela 2×2, estilo base com `tblInd=360`, estilo filho com `tblInd=0` e formatação direta ausente. Ler → escrever → reler deve manter o override zero. Repetir com ausência, indent direto e cadeia cíclica já limitada pelo resolver existente.
- Settings com as flags conhecidas em true/false/ausentes e URI de outro fornecedor. Verificar os campos do modelo e o XML reexportado, sem aceitar qualquer URI arbitrária como autoridade.
- Célula mesclada com um título e um único parágrafo vazio formatado TNR 10/bold, além de variante com `pPr/rPr` explícito. Ler → escrever → reler deve preservar a formatação efetiva e as contagens de parágrafos/mesclas. Acrescentar teste de digitação em parágrafo vazio para não regredir o uso já existente de `mark`.
- Aplicar cada correção pelo overlay normal do mesmo upstream, reconstruir o WASM pelo workflow existente e executar o workflow G3 Linux dedicado com **corpus novo**, sempre convertendo originais e reexportados no mesmo LO. Conferir bordas X, spans/fontes dos links, altura do cabeçalho e raster; nenhuma restauração manual de XML e nenhuma edição de JSON para obter o resultado esperado.

Os arquivos de fonte examinados em `work/wordcraft-filtered` estavam limpos no `git status` dos paths relevantes; os links acima apontam exatamente para o commit pinado, sem consulta de rede nesta investigação. A série Windows permanece parcial em 6/16 derivados. Não há conclusão de fidelidade, certificação de compatibilidade Word ou aceite do caminho PDF único nesta entrega.

## Inventário e decisão incremental — implementação autorizada

O integrador autorizou implementar e testar as perdas de IO pelo overlay normal. Antes de editar código, foram conferidos `scripts/wordcraft_overlay.py`, seus testes, o modelo `TableStyleParts`/`Settings`/`Paragraph.mark`, os readers/writers DOCX e a resolução de indentação no layout. O overlay atual já valida pin, hashes LF, idempotência e todos os destinos antes de qualquer escrita; essa mesma fronteira será preservada para os patches de IO. Nenhum caminho de documento será reparado fora do motor.

As três correções estão identificáveis por hunks independentes no artefato revisado: indentação de estilo, marca de parágrafo vazio e flags de compatibilidade. A aplicação normal inclui as três de modo atômico; a futura ablação visual deve gerar patches controlados a partir desse artefato em checkouts descartáveis, sem criar modos operacionais parciais no produto. A indentação usa `Option<f32>` com zero explícito e precedência direto/estilo; as flags são opcionais/booleanas tipadas, preservando ausência e false; a formatação vazia usa `Paragraph.mark` com precedência da marca explícita, sem introduzir runs de comprimento zero. Reader, writer, serde e layout permanecem coerentes, e fixtures Rust reais são instaladas pelo overlay para os testes do próprio motor.

Escopo realizado nesta etapa: patch/fixtures de IO em `integrations/wordcraft`, integração estreita no script de overlay, testes Python do planejamento/confinamento e este documento. O patch altera oito arquivos do upstream pinado, com 93 inserções e duas substituições. A aplicação foi provada em worktree limpo no commit `533615620ef91ae57fa7aa4cd77fd98b2179e693`; `git apply --check`, aplicação, `git apply --reverse --check`, `git diff --check` e `cargo fmt --all -- --check` passaram. O overlay reconhece de modo idempotente os estados pendente/aplicado e recusa qualquer terceiro estado antes das demais escritas.

Os testes Python do overlay passaram (`18 passed`). A primeira tentativa Rust
local parou pela ausência do linker MSVC `link.exe`. Em 19/10/2026, a mesma
fonte com o patch aplicado foi compilada pelo Rust 1.99.0 para
`x86_64-pc-windows-gnu`, usando link autocontido e LLVM-MinGW portátil no
workspace. `wordcraft-docx` passou **243/243** testes e `wordcraft-layout`
passou **250/250**, incluindo as regressões novas de indentação/compatibilidade,
marca de parágrafo vazio e layout de tabela. A evidência fechada está em
`docs/wordcraft/evidencia-io-fidelity-rust-windows.json`.

O workflow Linux continua executando explicitamente os dois pacotes. Permanecem
pendentes o round-trip do corpus corrigido, a nova comparação raster, atribuição
por ablação e aceite visual. Nenhuma funcionalidade antiga foi removida e
nenhuma conclusão de fidelidade final foi emitida.
