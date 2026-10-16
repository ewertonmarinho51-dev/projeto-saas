# LibreOffice local isolado para o corpus G3

Decisão registrada antes do runner: usar somente o MSI oficial da Document Foundation, baixado a partir do domínio oficial e comparado com seu SHA-256 publicado. Espelhos selecionados pelo redirecionamento oficial são permitidos; reempacotados/PortableApps não serão usados. A imagem administrativa ficará exclusivamente em work/toolchain, sem executar instalação /i, registrar o produto, alterar associações de arquivos, criar serviços ou mudar o PATH global.

Fontes oficiais consultadas:

- https://download.documentfoundation.org/libreoffice/stable/26.8.1/win/x86_64/LibreOffice_26.8.1_Win_x86-64.msi.mirrorlist
- https://learn.microsoft.com/en-us/windows/win32/msi/administrative-installation
- https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html
- https://help.libreoffice.org/latest/en-US/text/shared/optionen/macrosecurity_sl.html

A documentação do Windows Installer distingue a imagem administrativa /a da instalação do produto. Antes de extrair, serão inspecionadas as ações administrativas do MSI. A ajuda oficial do LibreOffice documenta soffice.com para operações headless no Windows e a sintaxe de bootstrap -env:UserInstallation=file:///... com um hífen inicial. O perfil do usuário/sistema não será reutilizado.

Inventário planejado: novo scripts/wordcraft_libreoffice_qa.py para verificar o corpus sintético completo, usar runtime local explicitamente pinado, converter DOCX finais para PDF em saída isolada, extrair métricas/texto e renderizar páginas com PyMuPDF. Novo teste específico validará confinamento, recusa de conteúdo ativo e construção de comandos sem abrir URL ou conectar a banco. Nenhum exportador operacional, workflow ou fixture G1 será alterado.

As entradas devem passar pelo preflight DOCX existente do produto. O perfil próprio terá macros desabilitadas e nenhuma origem confiável, e o runner recusará relacionamentos externos que não sejam hyperlinks meramente declarativos para example.invalid. Os links do corpus são dados de fidelidade, nunca entradas de navegação ou fontes consultadas. Não haverá listener UNO, serviço persistente, LLM ou acesso a produção.

As métricas de texto/páginas não constituem aceite visual. Os PNGs serão evidência para inspeção posterior pelo integrador. Divergências devem permanecer explícitas; nenhum fallback pode se passar por LibreOffice.

## Retomada e extração direta

O download original interrompido foi retomado com HTTP Range no mesmo arquivo, no espelho C3SL listado pela TDF. Os 374.870.016 bytes resultantes conferem com o SHA-256 oficial `c6298b10cfa1748bcbedad94c62ce771e240e5021bfd6d7a967cd571b04b5312`. O HTML oficial de mirrorlist foi preservado em `work/toolchain/libreoffice-26.8.1-qa/official-mirrorlist.html`.

A tabela AdminExecuteSequence foi inspecionada antes de tentar `/a`. As únicas custom actions administrativas são três ações tipo 51 que atribuem propriedades; nenhuma DLL ou comando customizado administrativo. A tentativa `/a /qn /norestart` retornou 1601 e o log registra falha de conexão com o Windows Installer, erro 0x80070005. Nenhum serviço será iniciado para contornar essa restrição.

Foi acrescentado o helper `scripts/wordcraft_libreoffice_extract.py`: ele abre exclusivamente o MSI pinado em modo de leitura, lê o CAB com a API documentada [MsiRecordReadStream](https://learn.microsoft.com/en-us/windows/win32/api/msiquery/nf-msiquery-msirecordreadstream), usa `expand.exe` do Windows e recompõe o layout pelas tabelas File, Component e Directory. Não executa ações MSI, registra arquivos, instala fontes ou escreve em diretórios do Windows. Todos os destinos, inclusive componentes chamados System e Fonts no pacote, ficam dentro da imagem de QA. O helper recusa sobreposição de imagem e confere inventário, tamanho e SHA-256 dos arquivos extraídos em um recibo. Essa é uma extração do mesmo produto oficial, sem exportador PDF substituto.

O MSI inclui runtimes VC AMD64 e ARM64 com os mesmos nomes lógicos em System64. A extração direta preserva as duas arquiteturas em subpastas distintas e só acrescenta a AMD64 ao PATH do processo filho. Isso evita sobrescrita de DLL e não tenta emular as condições de instalação do MSI. Nenhuma DLL é copiada para o sistema.

## Execução confinada e evidência

Com um Python existente que tenha as dependências do projeto e PyMuPDF, executar a partir da raiz do checkout:

```powershell
& $qaPython scripts/wordcraft_libreoffice_extract.py --msi ../toolchain/libreoffice-26.8.1-qa/LibreOffice_26.8.1_Win_x86-64.msi --image ../toolchain/libreoffice-26.8.1-qa/image
& $qaPython scripts/wordcraft_libreoffice_qa.py --inputs ../wordcraft-full-corpus-01 --out ../wordcraft-lo-baseline-01 --runtime-receipt ../toolchain/libreoffice-26.8.1-qa/extraction-receipt.json
```

Ambas as saídas precisam ser novas: o runner não sobrepõe imagem nem PDFs anteriores. A admissão verifica o manifesto sintético dos 12 casos/16 DOCX e seus hashes, reaproveita `preflight_docx` e só permite hyperlinks HTTPS declarativos para `example.invalid`, sem credenciais nem porta. Campos ativos ou desconhecidos são recusados; apenas PAGE é admitido para o caso de rodapé. Os arquivos DOCX finais são convertidos diretamente, sem exportação intermediária de Markdown ou perda silenciosa de mesclas.

Cada invocação de `soffice.com` recebe seu próprio `-env:UserInstallation`, TEMP/APPDATA e ambiente reduzido, sem herdar chaves de providers ou Supabase. O runner confere as propriedades de macro/proxy/atualização contra `main.xcd` e `onlineupdate.xcd` extraídos e desliga a execução geral de macros e o update automático. O proxy do perfil aponta para loopback sem serviço. Não é um firewall do sistema; a garantia de não buscar fontes externas também depende da admissão dos DOCX sintéticos sem recursos externos ativos. Nenhum hyperlink é navegado. Um Windows Job Object encerra somente os processos desta invocação e seus descendentes ao fechar o handle, inclusive em timeout/interrupção. Não se usa listener UNO nem finalização global por nome de processo.

O relatório inclui versão real do LibreOffice, digest do MSI e do recibo, versões do PyMuPDF, hashes de entrada/PDF/PNG, duração, páginas/dimensões A4, fontes reportadas pelo PDF, imagens e hyperlinks. Cada PDF tem texto extraído, projeção textual do DOCX e diferenças em tokens NFC/whitespace. Cabeçalhos repetidos, paginação e campos PAGE permanecem no diff e podem explicar divergências legítimas. Códigos, títulos de cláusulas, marcadores, assinaturas, valores Decimal e total são conferidos contra os oráculos separados. Há também uma janela textual por linha monetária para evitar que um valor repetido em outra linha conte sozinho como preservação. Isso não é um parser semântico de tabelas PDF.

As páginas são renderizadas a 120 DPI pelo PyMuPDF existente; o integrador fará a inspeção visual. As fontes efetivamente usadas são registradas, mas as fontes do Windows não são instaladas nem integralmente pinadas por este helper. A saída é uma referência PDF dos DOCX originais sintéticos. Roundtrip WordCraft, aprovação, isolamento RLS e workflows C09/C11/C12 continuam fora desta prova.

## DOCX reexportados pelo motor nativo

O integrador concluiu uma execução nativa real dos mesmos 16 casos e pediu uma segunda conversão: usar o DOCX reexportado, além da referência original, para avaliar um caminho PDF único. O runner aceita `--roundtrip-docx-root` somente junto de `--roundtrip-comparison-sha256`. O digest externo pinado precisa corresponder ao `comparison.json` dessa execução; seu manifesto de entradas deve ser byte idêntico ao corpus original. A admissão exige as 16 variantes exatas, nenhuma diferença/falha, todas as etapas nativas esperadas PASS e hashes exatos do checkpoint, DOCX e PDF da execução. Reconfere também o preflight, as stories/links ordenados e os oráculos/estruturas existentes do corpus, sem interpretar o checkpoint como outro motor.

Essa prova deriva de uma operação de backend que já foi executada e validada, correlacionada por hashes; não de um testemunho do browser. Um `comparison.json` recém-inventado sem proveniência não certifica execução nativa. Na prova local, a origem é a execução do integrador e o seu digest foi fixado antes de iniciar o segundo runner. Os novos PDFs e perfis ficam em uma saída separada; não se repete a conversão dos DOCX originais nem se escreve na saída nativa.

```powershell
& $qaPython scripts/wordcraft_libreoffice_qa.py --inputs ../wordcraft-full-corpus-01 --out ../wordcraft-lo-roundtrip-a9f-01 --runtime-receipt ../toolchain/libreoffice-26.8.1-qa/extraction-receipt.json --roundtrip-docx-root ../wordcraft-full-roundtrip-a9f-01 --roundtrip-comparison-sha256 183f8a86afbcfd5a5e936eaa792f450abd498a32f99f7116fe2fce8606feb552
```

A primeira passagem do comparador registrou um falso positivo de apresentação: a fonte Decimal `1250,55` é corretamente exibida como `1.250,55`. A comparação de preço unitário agora deriva a apresentação brasileira do Decimal independente. `--refresh-metrics` reanalisa os mesmos PDFs/PNGs após conferir seus hashes e os hashes das entradas, preserva `report-initial.json` e só atualiza as métricas/textos. Não executa LibreOffice nem gera novos PDFs. As diferenças iniciais permanecem auditáveis.

## Primeiro uso e preservação do runtime

A execução original concluiu os 16 PDFs e 70 PNGs. O segundo runner recusou iniciar porque o primeiro uso do LibreOffice criou 39 caches `.pyc` do Python interno e um lock do autoteste OpenCL dentro da imagem extraída. Nenhum arquivo oficial desapareceu ou foi aceito por uma exceção silenciosa: os 40 arquivos adicionais foram movidos, com paths/tamanhos/hashes registrados, para `work/toolchain/libreoffice-26.8.1-qa/first-start-generated-quarantine-01`. Esse material não faz parte dos binários admitidos do fornecedor.

O perfil de QA agora desliga `Common/Misc/UseOpenCL` e `Calc/Formula/Calculation/OpenCLAutoSelect`, propriedades conferidas no registro oficial extraído. O ambiente do filho define `PYTHONDONTWRITEBYTECODE=1` e um `PYTHONPYCACHEPREFIX` próprio. Isso não habilita macros: são módulos internos de UNO/dicionários do produto oficial. A política de runtime continua recusando qualquer arquivo adicional ou mudança nos 19.427 arquivos extraídos. A primeira tentativa de roundtrip falhou antes de criar a saída ou converter DOCX; somente a execução posterior necessária foi iniciada. A referência original não foi reconvertida.

A comparação dos três caminhos pode ser reproduzida sem executar nenhum exportador:

```powershell
& $qaPython scripts/wordcraft_libreoffice_qa.py --inputs ../wordcraft-full-corpus-01 --out ../wordcraft-pdf-three-way-a9f-01 --compare-three-way --baseline-root ../wordcraft-lo-baseline-01 --reexported-pdf-root ../wordcraft-lo-roundtrip-a9f-01
```

Esse modo confere novamente hashes de PDF e de **todas** as páginas PNG, exige os mesmos 16 casos/fontes e o mesmo runtime LibreOffice, correlaciona os DOCX reexportados com a execução nativa pinada e extrai métricas dos três PDFs reais. A tabela de páginas e as comparações textuais permanecem dados para avaliação, sem converter contagem de páginas em aprovação/reprovação visual automática.

## Interrupção e retomada verificável

A primeira conversão do DOCX nativo C03 retornou zero no launcher sem produzir PDF e deixou um minidump de 141.555 bytes no runtime (`617ea7cdf20275b21c5dbb9a5fac7ec4a85a8f3d3bf43a0ac92f2b9b0a4ac90a`). Esse é um crash observado, sem causa atribuída. O mesmo DOCX, com o mesmo hash pinado, converteu depois em um diretório diagnóstico novo e gerou PDF real de três páginas com todos os oráculos preservados. Esse PDF foi copiado byte a byte para o caso C03 e sua invocação/origem/hash foram registrados em `adopted-diagnostic-evidence.json`. C01 e C02 não foram reconvertidos.

O dump permanece privado em `work/toolchain/libreoffice-26.8.1-qa/runtime-crash-quarantine-01`, não foi enviado e não é aceito como binário do fornecedor. O perfil agora desabilita explicitamente o envio de crash reports; `CrashDirectory`, nome conferido no `soffice.ini` oficial, aponta para a pasta própria da invocação. O runner grava a saída do processo antes de extrair métricas e não considera retorno zero suficiente: exige PDF real. O Windows Job aguarda todos os descendentes terminarem dentro do prazo antes de fechar seu handle; em falha/timeout, continua encerrando somente sua árvore.

`--resume` só aceita saída marcada, o mesmo manifesto, recibo do runtime e pin nativo, e um prefixo exato dos casos concluídos. Confere os hashes de fontes/PDF/PNGs já prontos e pula esse prefixo. Perfis de tentativas incompletas ficam preservados; um PDF existente sem evidência registrada é recusado para inspeção, nunca sobrescrito automaticamente. A recuperação de C03 foi baseada na invocação de backend já executada, correlacionada ao DOCX e ao PDF, sem testemunho do browser. O crash e o aviso não fatal do Python interno (`Could not find platform independent libraries <prefix>`) ficam como limites observados deste runtime extraído no Windows, mesmo quando as conversões restantes terminarem.

Houve outra inicialização com retorno zero e saída vazia no C06 sem SRP, também sem PDF. O helper registra agora cada invocação em arquivo exclusivo e faz no máximo duas tentativas com perfis novos **somente enquanto não existe PDF**. Não troca de motor nem repete um PDF pronto; se as duas tentativas não produzirem o arquivo, conserva os logs e falha. Um PDF existente, inclusive incompleto, exige inspeção em vez de sobrescrita. A retomada preserva também o DPI original. Esses comportamentos são testados separadamente da prova real; a conclusão de 16 casos não apaga as inicializações falhas observadas.

## Decisão para prova em Linux

Se o limite de duas tentativas no runtime Windows continuar sem produzir o próximo PDF, a prova restante será executada em runner Linux descartável, com uma série nova e completa. O modo de QA `--institutional-adapter` reutiliza exclusivamente `src.export._docx_em_pdf`; `None` é falha e não habilita `gerar_pdf`/fpdf2. O wrapper local acrescenta perfil privado e limite de processo ao binário da distribuição, sem reimplementar a conversão. Os DOCX admitidos, a pinagem do roundtrip nativo, o render de todas as páginas e os oráculos são os mesmos do runner de QA existente. A versão Linux terá identidade própria e jamais será comparada como se fosse o MSI Windows.

A execução é preparada para Ubuntu 24.04 com [libreoffice-writer da distribuição](https://packages.ubuntu.com/noble/libreoffice-writer). O perfil confere as propriedades de macro/proxy presentes no registro instalado; propriedades opcionais de OpenCL/crash/update ausentes são registradas. O wrapper utiliza [GNU timeout](https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html), sem `--foreground`, com TERM aos 100 segundos e KILL após mais 5, antes dos 120 segundos do adaptador existente. Isso mantém o grupo de processos desta invocação limitado no runner descartável. Este preparo e seus testes locais não constituem execução Linux nem aceite visual.

O modo registra versão real, versões dos quatro pacotes requeridos e SHA-256 do launcher, `soffice.bin`, `timeout` e registros usados. Essa é uma impressão digital do runtime da distribuição; não é o inventário de 19.427 arquivos do MSI nem prova independente da assinatura APT. A origem APT decorre do passo de instalação do runner e seus logs. As duas séries Linux devem usar a mesma identidade registrada; o comparador recusa misturar Linux e Windows. O CLI Linux é sequencial e temporariamente reduz o ambiente e a raiz temporária do próprio processo ao chamar o adaptador; não deve ser importado em um servidor concorrente. Cada caso tem no máximo duas tentativas; uma série interrompida é preservada e não recebe `completed_docx=16`.

Os comandos abaixo estão preparados para um passo **posterior à montagem de `wordcraft-local-qa/`** no workflow existente, sem modificar o workflow neste trabalho. O executor deve preservar as saídas em artifact com `if: always()`. A instalação ocorre somente no runner Ubuntu descartável. `GITHUB_RUN_ID` e `GITHUB_RUN_ATTEMPT` evitam reutilizar saídas antigas. O pin nativo é calculado sobre a execução real desta série Linux, jamais reutiliza o pin Windows de um corpus recém-gerado.

```bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation2
python3 -m venv "$RUNNER_TEMP/wordcraft-qa-venv"
qa_python="$RUNNER_TEMP/wordcraft-qa-venv/bin/python"
"$qa_python" -m pip install streamlit==1.64.0 python-docx pillow markdown-it-py pymupdf pypdf pytest
mkdir -p build-evidence/libreoffice
"$qa_python" -m pip freeze > build-evidence/libreoffice/python-packages.txt
apt-cache policy libreoffice-writer libreoffice-core libreoffice-common coreutils > build-evidence/libreoffice/apt-policy.txt
dpkg-query -W libreoffice-writer libreoffice-core libreoffice-common coreutils > build-evidence/libreoffice/packages.txt
qa_suffix="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
qa_inputs="../wordcraft-ci-corpus-${qa_suffix}"
qa_native="../wordcraft-ci-native-${qa_suffix}"
qa_original="../wordcraft-ci-lo-original-${qa_suffix}"
qa_reexported="../wordcraft-ci-lo-reexported-${qa_suffix}"
qa_comparison="../wordcraft-ci-pdf-three-way-${qa_suffix}"
"$qa_python" -m pytest tests/test_wordcraft_libreoffice_qa.py -q --basetemp "../wordcraft-ci-lo-tests-${qa_suffix}"
"$qa_python" scripts/wordcraft_corpus.py --full-corpus --out "$qa_inputs" > build-evidence/libreoffice/corpus-generation.json
qa_engine_pin="$(sha256sum wordcraft-local-qa/qa-manifest.json | cut -d' ' -f1)"
"$qa_python" scripts/wordcraft_full_roundtrip.py --inputs "$qa_inputs" --out "$qa_native" --node "$(command -v node)" --bundle "$PWD/wordcraft-local-qa" --manifest-sha256 "$qa_engine_pin"
qa_native_pin="$(sha256sum "$qa_native/comparison.json" | cut -d' ' -f1)"
"$qa_python" scripts/wordcraft_libreoffice_qa.py --inputs "$qa_inputs" --out "$qa_original" --institutional-adapter --system-soffice /usr/bin/libreoffice
"$qa_python" scripts/wordcraft_libreoffice_qa.py --inputs "$qa_inputs" --out "$qa_reexported" --institutional-adapter --system-soffice /usr/bin/libreoffice --roundtrip-docx-root "$qa_native" --roundtrip-comparison-sha256 "$qa_native_pin"
"$qa_python" scripts/wordcraft_libreoffice_qa.py --inputs "$qa_inputs" --out "$qa_comparison" --compare-three-way --baseline-root "$qa_original" --reexported-pdf-root "$qa_reexported"
```

Artifact sugerido, no mesmo job, com `if: always()`: `build-evidence/libreoffice/`, `../wordcraft-ci-corpus-*`, `../wordcraft-ci-native-*`, `../wordcraft-ci-lo-original-*`, `../wordcraft-ci-lo-reexported-*` e `../wordcraft-ci-pdf-three-way-*`. O workflow continua sob responsabilidade do integrador. Estes comandos não foram executados em Linux nesta máquina Windows; a prova Linux permanece pendente.

Streamlit é necessário porque o corpus reutiliza as funções puras de contexto institucional no módulo existente, que importa `src.db`. Nenhum cliente de banco é criado: o corpus não chama as funções de persistência ou aprovação. Essa dependência de importação não é um fake de banco e não afirma isolamento multi-tenant.

## Resultado final da retomada Windows em 16/10

A sessão 29772 conferiu o prefixo e executou exatamente duas novas tentativas para `C06/dossie-sem-srp`, sem gerar PDF: PID 6736, código `3221226505`, 15,250 s; PID 7500, mesmo código, 11,359 s. Ambas tiveram saída vazia. Os dois logs estão em `work/wordcraft-lo-roundtrip-a9f-01/C06/dossie-sem-srp/invocation-run-3-attempt-{1,2}.json`; os perfis anteriores e os dois dumps já preservados continuam disponíveis. Não houve novo dump na imagem oficial nesta retomada. Não foi atribuída uma causa ao código de processo e não foram feitas mais tentativas.

O saldo real é **16/16 PDF originais e 70/70 páginas PNG**, **6/16 PDF reexportados e 50/50 páginas PNG**, sem mudanças nos DOCX de entrada nem no `comparison.json` nativo pinado `183f8a86afbcfd5a5e936eaa792f450abd498a32f99f7116fe2fce8606feb552`. `work/wordcraft-lo-windows-review-01/comparison-partial.json` registra os hashes, a tabela dos 16 casos, os seis comparáveis e os dez sem LO derivado. Não é o relatório completo do comparador: `--compare-three-way` continua exigindo 16+16 séries completas e recusando esse prefixo.

A revisão visual abriu as sete folhas de contato que cobrem todas as 70 páginas originais e as duas folhas ampliadas das seis páginas derivadas com diferença de pixels. Das 50 páginas derivadas, **44 são byte idênticas** às PNGs originais. As seis diferentes são DFD p2, Mapa de Riscos p2–3, TR p1–2 e ARP p1; os retângulos de diferença estão restritos às tabelas, em `pixel-differences.json`. As larguras de colunas e quebras de linhas nas células variam apesar da igualdade de texto compacto, paginação e oráculos. É uma diferença de formatação observada e impede afirmar fidelidade visual completa. As outras 35 páginas de ETP e Edital são integralmente idênticas; as nove páginas restantes dos quatro casos também são idênticas.

As folhas de contato originais mostram conteúdo dentro das páginas, totais e links presentes, logo sintético da secretaria, rodapés e tabela aninhada. A quebra inicial de página do Mapa de Riscos é declarada no oráculo da fixture; há cabeçalho mesclado alto nas páginas 2–3 e uma assinatura do DFD continua na página 4. Esses aspectos foram preservados como dados de QA, sem corrigir o corpus para mascarar a renderização. Essa inspeção de visão geral e das diferenças não substitui uma revisão ampliada de cada célula nem a revisão do PDF nativo, que continua com o integrador.

Validação local final do runner: **60 testes passaram em 22,66 s**. Incluem retorno não zero registrado, limite de duas tentativas, preservação de PDFs, árvore Windows própria, propriedades opcionais Linux versus obrigatórias macro/proxy, uso exclusivo do adaptador institucional, ausência de fallback e restauração do ambiente em interrupção. Os testes simulados de Linux verificam contratos; não afirmam conversão real nesse sistema.

## Inventário e decisão do workflow G3 independente

Antes de criar `.github/workflows/wordcraft-fidelity.yml`, foram conferidos o padrão de download/admissão de `.github/workflows/auth-real.yml`, o instalador `scripts/wordcraft_local_assets.py`, o gerador `scripts/wordcraft_corpus.py`, o roundtrip real `scripts/wordcraft_full_roundtrip.py` e o runner LO desta prova. O novo workflow será independente de `auth-real.yml`, `wordcraft-build.yml` e `ci.yml`, sem banco, serviço Auth, dados de cliente ou exportador alternativo.

A entrada executável é exclusivamente o artifact QA 39 de ID `11995992777`, ZIP SHA-256 `a57bdc0b05660afb3ea37e0625e50fc2d33e78fa9e995822210e51580c79221d`, producer commit `39fec20fc5e94590a95cfd9af8d0ce34d07c3e54` e manifesto SHA-256 `bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548`. Reutiliza `install()` e suas verificações de upstream, JS/WASM, notices, paths e destinos. Não reconstrói WordCraft e não aceita um artifact indicado livremente na execução. `github.token` fica explicitamente disponível apenas no passo de download autenticado; o job usa permissões `contents: read` e `actions: read`, checkout sem persistência de credenciais e nenhum secret de aplicação.

O runtime é Ubuntu 24.04, Python 3.11, Node 24 e LibreOffice Writer da distribuição APT. As dependências do produto vêm de `requirements.txt`, com pytest e PyYAML de QA explícitos; versões Python/APT e política de origem ficam nos diagnósticos. O corpus completo é novo a cada run/attempt, derivado apenas dos geradores sintéticos existentes. O fluxo executa o roundtrip WASM real, duas séries LO sob a mesma identidade Linux e a comparação dos três PDFs. Os artefatos são preservados com `if: always()`, inclusive na interrupção de uma etapa, mas sem upload do token, do ambiente herdado ou de dumps privados Windows. Sucesso de execução significa prova produzida: igualdade de texto, diferença de imagem e aceite visual continuam estados separados.

A comparação renderiza também todas as páginas do PDF nativo com o mesmo PyMuPDF/DPI e preserva os PNGs. Cada par registra identidade raster, dimensões diferentes, fração de pixels alterados e páginas sem correspondente; não trunca a comparação em `zip` nem ignora páginas excedentes. Os marcadores ocultos `.synthetic-qa-only` das séries LO precisam acompanhar o artifact para permitir reconferência posterior, portanto o upload dos destinos sintéticos enumerados inclui arquivos ocultos. A comparação de raster é ordinal e não alinha conteúdo que mudou de página; contagens diferentes ficam explícitas e exigem revisão humana.

O workflow implementado registra separadamente as contagens de casos com diferenças raster e problemas dos oráculos textuais. Problemas textuais fazem a etapa falhar depois da gravação de `comparison.json` e do resumo, preservando a prova. Diferenças raster recebem `RASTER_DIFFERENCES_RECORDED_VISUAL_REVIEW_REQUIRED`; até pixels idênticos mantêm `visual_fidelity_approved=false`. Todas as páginas nativas, inclusive as sem correspondente ordinal nas séries LO, ficam renderizadas no artifact.

Validação local desta expansão: os **64 testes do runner** passaram, incluindo os 60 anteriores e quatro testes de raster/comparação completa. Um contrato de teste com PDFs reais inteiramente sintéticos renderizou todas as 32 páginas nativas dos 16 casos e registrou as páginas excedentes, sem afirmar execução de LibreOffice/WASM. Os **9 testes do workflow** passaram em 0,46 s: YAML e AST dos trechos Python, namespace, pinagem passada ao instalador, recusa de manifesto divergente, token limitado ao download, preservação dos marcadores e comportamento do resumo/gate textual. A verificação `bash -n` é obrigatória no Ubuntu e foi pulada no Windows: o parser MSYS local foi recusado pelo sandbox ao criar objetos nomeados (`0xC0000022`). A última execução conjunta antes dos dois testes adicionais de resumo teve 71 positivos e esse único skip em 23,84 s. A revisão independente somente leitura não encontrou outro erro concreto nos comandos finais. **Execução real do novo workflow/LibreOffice Ubuntu, resultados e aceite visual continuam pendentes**; nenhum workflow existente, exportador operacional, commit ou push foi alterado por esta entrega.
