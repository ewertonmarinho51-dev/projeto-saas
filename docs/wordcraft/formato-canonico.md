# Representação escolhida para a fatia G1

Escolha: `gc-wordcraft-snapshot/v1`, bytes UTF-8 produzidos pelo adaptador pinado,
armazenados privadamente em `documentos_editor_revisoes.payload`. DOCX/PDF são
artefatos derivados, não o buffer autoritativo. Não há migração automática do acervo.

O JSON nativo isolado foi recusado: Document ignora media e passthrough no serde.
O contêiner conserva esses campos, limita bytes/profundidade/objetos, rejeita campos
de modelo descartados pelo parser e permite somente as três chaves de bookkeeping
identificadas no DOCX upstream. OLE e gráficos opacos sem representação segura são
recusados; continuam no caminho legado, sem conversão silenciosa.

## Evidência e limites

- Upstream: 533615620ef91ae57fa7aa4cd77fd98b2179e693, versão 0.7.0.
- Build integrado 896ebbc: 12 testes nativos, 401 testes UI + 6 doctests passaram;
  três DOCX sintéticos importados, serializados, reabertos e exportados pelo motor.
- O comparador confirmou texto ordenado, headers/footers/links e os 210 códigos;
  geometria fracionária e bytes preservados são cobertos nos testes do adaptador.
- No navegador local, texto e descrição de célula foram editados, validados no
  servidor, commitados no PostgreSQL e reabertos após reload com o mesmo SHA-256.
- Isso ainda não certifica toda fidelidade visual, imagens institucionais,
  comentários/revisões, exportação de documentos alterados ou performance de 100 páginas.

O DOCX como fonte única exigiria repetir importação/exportação a cada checkpoint
e vincular patches a posições reconstruídas. O contêiner evita esse ciclo para a
edição e permite igualdade do modelo na reabertura. DOCX original permanece fonte
de importação e referência de fidelidade, preservada na migração futura.

## IDs, patches e migração

Posições nativas usam story/path/offset e são vinculadas à revisão. Não há prova de
IDs de bloco estáveis através de inserções/reordenação. Não serão tratadas como
âncoras persistentes de IA. G2/G4 ainda precisam da estratégia de IDs e da tradução
para o aplicador canônico de patches, com hash e revisão, preservando cláusulas fixas.

As tabelas novas não substituem processos, usuários, tenants ou assinaturas.
Cabeça e revisões referenciam processos existentes; permissões reutilizam as funções
de contexto SQL e o perfil atual de usuarios. Revision/operação são transacionais;
revisões anteriores não recebem UPDATE/DELETE nem pelo papel de servidor do app.
O serviço valida pelo motor antes da RPC interna; usuários têm somente leitura RLS.

G1 fornece o mínimo de commit autoritativo que o próprio contrato 02 exige. G2
continua pendente da homologação completa: migração Markdown/DOCX com relatório de
perdas, referências aos originais, snapshots institucionais/aprovações, trilha
canônica, identificação exata do build por revisão e rollback de documentos.
As flags permanecem desligadas e nenhum consumidor operacional foi migrado.
