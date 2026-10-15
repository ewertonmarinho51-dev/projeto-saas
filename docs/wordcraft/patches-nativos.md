# Aplicação nativa de substituições autorizadas — contrato inicial G4

Registro anterior ao código. A API pura WASM será
`apply_patch(checkpoint_bytes, current_revision: u32, plan_json: string) -> checkpoint_bytes`.
Ela não autentica, aprova, salva ou confirma ACK. O backend mantém autorização,
block_id/block_hash, políticas FIXED, allowlist, diff, aprovação e CAS no aplicador
canônico. O servidor resolve IDs pelo índice da revisão; nunca aceitar endereços
documentais sugeridos pela LLM como autorização.

Plano fechado, com campos obrigatórios e sem chaves duplicadas:

```json
{
  "schema": "gc-wordcraft-native-patch/v1",
  "source_hash": "sha256 dos bytes exatos do checkpoint",
  "source_revision": 1,
  "operations": [{
    "op": "replace_text",
    "story": "body",
    "path": [0],
    "start_byte": 0,
    "end_byte": 5,
    "old_text": "Texto",
    "new_text": "Trecho"
  }]
}
```

`story` também pode ser `{"part": 1}`. `path` é um `wordcraft_doc::Path`, com
`[bloco, linha, célula, bloco, ...]` em tabela; não é caminho de filesystem.
Offsets são bytes UTF-8 e precisam coincidir com limites de caracteres.
Máximos: plano 1 MiB, 32 operações, 100 KiB de texto novo total e checkpoint 8 MiB.
O `source_hash` é SHA-256 dos bytes recebidos e a revisão deve coincidir com o
argumento confiável do servidor. O motor não conhece a revisão do banco por si só.

Allowlist inicial: substituir trecho não vazio dentro de um parágrafo de
formatação uniforme. Recusar operação desconhecida, ranges sobrepostos,
parágrafos/tabelas ausentes, mistura de estilos, objetos inline no parágrafo,
tracked changes ou proteção ativa, quebras/tabulações/caracteres de controle,
stale/hash/texto original divergente. Texto novo vazio permite apagar somente o
trecho. Strings permanecem texto inerte; não há comandos/URLs/paths executáveis.

Validar todas as pré-condições contra a origem antes de editar. Ordenar ranges
de trás para frente dentro do mesmo parágrafo para evitar deslocamento. Aplicar
na cópia da Session pelo registro e comandos nativos `select.range` +
`text.insert(raw: true)`. Conferir texto final, propriedades do parágrafo/runs,
tabelas, outros blocos/stories, metadados e assets antes de serializar. Nenhum
patch modifica JSON diretamente como motor de edição.

O lote é um único comando de Session e deve ser um único undo nessa Session de
trabalho. A API pura retorna somente os bytes novos: ela não transmite a pilha de
undo e não altera a Session aberta no navegador. Preservar undo na Session ativa
exigirá integração e prova próprias; este incremento não alegará esse resultado.

Adicionar dependências diretas `serde` (campos fechados/duplicados) e `sha2` do
workspace já pinado ao overlay; sem resolver novas versões. O integrador aprovou
um delta explícito do Cargo.lock que acrescenta somente esses dois nomes à lista
de dependências de `wordcraft-web`. O baseline anterior ao overlay continua com
SHA-256 LF `4cd08e46c389033f3f3d031026c3f674f74765899790e9f05b475557377bff68`;
o lock integrado tem SHA-256 LF
`e6b2bae022650e4fdc2dacdcb3ba90e7f3037e6a8cfa2a87dfa6b25be2883170`.
O overlay verifica os dois hashes e a diferença TOML: nenhum outro pacote, versão,
source ou checksum pode mudar. CI registra hashes/metadata integrados e verifica
esse lock depois das operações. O coletor de licenças aceita somente esse delta
aprovado e exige metadata filtrado regenerado a partir do manifesto integrado.
Erros públicos fechados, sem conteúdo documental ou logs. Testes Rust cobrirão
atomicidade, hashes/revisão, UTF-8, ranges, estilos/tabela, objetos, formatos
mistos e undo/redo do lote, executados no CI Linux porque falta linker MSVC local.

Foram acrescentados dez testes Rust específicos de patches ao adaptador, além dos
testes anteriores. Rustfmt passou localmente. Os testes de overlay/coleção Python
passaram (28). Os testes Rust e a prova da API pura nas três fixtures estão
preparados no workflow e aguardam execução no CI. Não confundir teste preparado
com resultado de compilação, undo no navegador ou G4 completo.
