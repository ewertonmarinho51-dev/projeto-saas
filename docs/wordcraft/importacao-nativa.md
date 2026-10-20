# Importação DOCX pelo motor nativo pinado

Registro anterior à implementação do G2. A importação amplia os módulos existentes
`govconnect.rs`, `govconnect_browser.rs`, `wordcraft_native.py` e `validate.mjs`;
não cria outro modelo, parser documental, cadastro ou sistema de persistência.

O backend recebe somente bytes de DOCX; nome de arquivo, caminho, URL, tenant e
comandos não fazem parte da API. Antes de iniciar o processo Node/WASM, o Python
valida o ZIP/OPC em memória: limite de 8 MiB compactados, 1.024 partes, 8 MiB por
parte, 32 MiB expandidos, compressão apenas stored/deflate, nomes únicos e seguros,
ausência de criptografia, macros/OLE/altChunk e partes fora da allowlist. XML não
aceita DTD/entidades. Relationships internos devem resolver a partes presentes;
externos são limitados a hyperlinks HTTP(S)/mailto sem buscar a URL. Não há extração
no filesystem nem fetch de imagens/fontes. Recursos recusados preservam o original
para o caminho legado e exigem relatório de incompatibilidade, sem conversão parcial.

Depois do preflight, a API pura `import_docx` chama o `engine::io::open_bytes` já
existente, serializa pelo codec `gc-wordcraft-snapshot/v1` e verifica o roundtrip
do mesmo modelo. A saída também tem limite de 8 MiB. Node e Python verificam o
contrato fechado; a configuração do bundle e seu manifesto é exclusivamente do
servidor. Importar não autoriza acesso, não salva, não aprova e não emite.

Integração pelo owner: autorizar o processo/usuário com o mecanismo atual, chamar
`wordcraft_native.importar_docx(bytes, node=..., bundle=..., manifest_sha256=...)`,
preservar bytes/hash originais e submeter o checkpoint retornado ao caminho CAS já
existente. O owner não deve copiar as regras ZIP nem aceitar configuração do cliente.

Provas previstas: negativos antes de spawn para ZIP hostil/ambíguo; testes IPC e
Node; testes Rust do codec/importador; CI com os três DOCX sintéticos de hash
verificado, importação WASM via IPC, reabertura nativa e exportação DOCX/PDF. Esses
testes não substituem homologação visual, migração em lote ou corte do legado.
