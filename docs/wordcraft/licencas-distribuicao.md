# Avisos de distribuição da árvore conservadora WASM

Registro anterior à implementação de `scripts/wordcraft_distribution_notices.py`.
O coletor complementa os 13 avisos upstream/fontes existentes; não altera seu
workflow ou instalador, não copia fontes/binários e não declara aprovação jurídica.

Entrada: Cargo metadata produzido com `--locked --filter-platform
wasm32-unknown-unknown`, checkout WordCraft pinado e fontes locais já resolvidas.
Percorrer somente arestas `normal` e `build` a partir de `wordcraft-web`; excluir
arestas exclusivamente `dev`. A resolução filtrada pode unificar features de outros
membros do workspace e incluir ferramentas de build/proc-macro. É uma aproximação
conservadora para avisos, não um link map que prove os crates presentes no WASM.
O JSON Cargo não atesta sozinho o comando que o produziu: registrar essa limitação.

Confinar toda leitura a três raízes explícitas: checkout upstream,
`cargo/registry/src` e `cargo/git/checkouts`. Para crates do registry, não herdar
licenças de crates vizinhos. Para workspace e Git, buscar arquivos de licença nos
pais apenas até a raiz do repositório autorizado. Symlinks resolvidos devem continuar
na raiz declarada. Arquivos ausentes, não textuais, excessivos ou fora do escopo
viram pendência explícita; nunca copiar arquivos de código como substituição.

Coletar textos LICENSE/LICENCE/COPYING/NOTICE/COPYRIGHT/ATTRIBUTION e os avisos de
fontes conhecidos, mantendo bytes e hashes. Relacionar cada pacote/version/source,
SPDX declarado, textos encontrados, copyright nos próprios avisos e pendências.
Licença desconhecida/ausente, expressão não reconhecida, alternativa copyleft e
termos especiais de fontes recebem `REVIEW`. Não escolher silenciosamente um ramo
de `OR`, nem inferir MIT a partir de um nome ou de um arquivo vizinho.

Saída nova: manifesto JSON e textos de licença por hash, sem fontes, executáveis,
metadados pessoais de caminhos locais ou arquivos documentais. O pacote continua
requerendo revisão de distribuição e marcas/fontes. A ausência de pendências
técnicas do coletor não equivale a aceite legal ou autorização para publicação.

## Execução local observada

Entrada `cargo-metadata-wasm-local.json`, SHA-256
`5e7ee85caa35eb7348da8abec681e9753cc579caee0b0a357e15b9c8d7fa31a5`.
O SHA WordCraft foi reconciliado com `upstream.lock.json`; o Cargo.lock normalizado
para LF permaneceu `4cd08e46c389033f3f3d031026c3f674f74765899790e9f05b475557377bff68`.

| Medida | Resultado |
|---|---:|
| Pacotes na closure normal/build | 251 |
| Registry / workspace / Git | 235 / 15 / 1 |
| Textos únicos coletados | 185 |
| Bytes dos textos | 672.932 |
| Pacotes com pendência explícita | 17 |
| Pacotes sem qualquer texto de licença/aviso | 12 |
| Pacotes sem texto da licença do código | 14 |

O artefato local `work/wordcraft-distribution-notices-wasm-03` contém somente
`manifest.json` e `licenses/<sha256>.txt`. Todos os 185 textos foram relidos e
seus hashes/tamanhos conferidos. SHA-256 do manifesto:
`56ad667e9fae736ee40a7a0dacc1e1de65178f8316dac858944e9a4b68bc5c9e`.
São avisos para revisão; o diretório não foi incorporado ao build vivo.

Pendências factuais:

- `self_cell 1.3.0` declara `Apache-2.0 OR GPL-2.0-only` e contém ambos os textos.
  O coletor conserva as duas alternativas e exige registrar a escolha aplicável;
  não afirma que o binário está sob GPL nem que houve aprovação legal.
- `epaint_default_fonts 0.36.2` declara `(MIT OR Apache-2.0) AND OFL-1.1 AND
  Ubuntu-font-1.0`. Foram coletados quatro textos de fontes. O aviso Hack também
  contém termos Bitstream Vera e nomes reservados; OFL/UFL contêm condições para
  fontes modificadas/nomes. Não foram copiados ou alterados arquivos de fonte.
- `subsetter 0.2.6` tem `NOTICE` com atribuições de código e licença de fontes
  utilizadas por seu projeto. O coletor preserva o aviso e marca aplicabilidade
  para revisão, sem inferir que suas fontes de teste estão no WASM.
- Não há texto da licença do código no pacote local de `accesskit`, `alloc-stdlib`,
  `ecolor`, `eframe`, `egui`, `egui-wgpu`, `egui_glow`, `emath`, `epaint`,
  `epaint_default_fonts`, `krilla`, `profiling`, `spirv` e `wuff`. Os doze sem texto
  algum são esse conjunto excluindo `epaint_default_fonts` e `krilla`, que têm
  avisos adicionais. SPDX permissivo declarado não preenche essa ausência.
- `docs/brand/LICENSE-brand.txt` não está no checkout filtrado usado neste ensaio.
  A lacuna foi registrada, sem buscar a rede ou copiar de outra raiz silenciosamente.
- Não foi encontrado identificador SPDX MPL na closure de 251 pacotes. Isso não
  descreve toda a árvore multiplataforma/dev nem prova o conteúdo final linkado.

O coletor passou 11 testes: closure normal/build/dev, SPDX desconhecido/copyleft,
separadores históricos, nomes de arquivos, limites de herança por repositório,
recusa de licença de pacote vizinho, hashes e proteção contra sobrescrita. A coleta
real foi executada localmente, sem rede adicional.

## Lock da integração G4

O incremento de patches adiciona dependências diretas `serde` e `sha2` a
`wordcraft-web`. Ambas já pertenciam à closure conservadora de 251 pacotes; não
há nova versão/source/checksum proposta. A alteração da lista direta exige um
delta explícito no lock, aprovado pelo integrador e validado pelo overlay:
SHA-256 LF integrado
`e6b2bae022650e4fdc2dacdcb3ba90e7f3037e6a8cfa2a87dfa6b25be2883170`.

O coletor preserva o hash do baseline upstream separado e aceita somente esse
delta exato. Ao encontrar o lock integrado, exige metadata filtrado regenerado
com `serde` e `sha2` nas dependências diretas do root; recusa silenciosamente
reutilizar metadata anterior. A contagem após integração deve ser observada de
novo, ainda que os dois nós já existam. O workflow prepara
`cargo-metadata-wasm-integration.json`, a nova coleta e os hashes integrados;
sua execução precisava ser observada novamente. O artefato `wasm-03` acima
permanece evidência do lock upstream anterior, sem ser renomeado como resultado
da integração G4. A reprodução integrada está registrada na seção seguinte.

## Coleta integrada reproduzida em 19/10/2026

A metadata filtrada da integração, SHA-256
`8c146289fee50310583ed0878d918309a8321f6301911edb3237c240dde84438`,
foi reconciliada com o checkout exato que a produziu. O coletor atual aceitou
somente o modo `APPROVED_INTEGRATION_DIRECT_DEPENDENCY_DELTA` e o Cargo.lock LF
`e6b2bae022650e4fdc2dacdcb3ba90e7f3037e6a8cfa2a87dfa6b25be2883170`.
A reprodução em destino novo gerou exatamente o mesmo manifesto da execução
integrada anterior, SHA-256
`3a69505c2beaeb70be351e4259b91b3108823a9bb0666b39672a94c26d3ecf41`.

O resultado conserva 251 pacotes, 186 textos únicos e 675.195 bytes; os 186
arquivos foram relidos, e seus tamanhos e SHA-256 conferem com o manifesto.
Permanecem 17 pacotes com revisão, 12 sem qualquer texto e 14 sem texto da
licença do código. Portanto a coleta integrada deixou de ser uma pendência de
execução, mas o estado continua `DISTRIBUTION_REVIEW_REQUIRED`: nenhuma escolha
entre ramos SPDX, revisão de fonte/marca ou aprovação jurídica foi inferida.

Os 11 testes do coletor passaram novamente. A tentativa inicial no diretório
temporário protegido do sandbox falhou apenas ao criar o repositório Git da
fixture; a repetição com `--basetemp` confinado ao workspace passou 11/11.

Comando reproduzível, a partir da raiz do produto, com destino novo:

```powershell
python scripts/wordcraft_distribution_notices.py `
  --metadata ../cargo-metadata-wasm-local.json `
  --upstream ../wordcraft-filtered `
  --registry-src ../toolchain/cargo/registry/src `
  --git-checkouts ../toolchain/cargo/git/checkouts `
  --out ../wordcraft-distribution-notices-wasm-NOVO
```
