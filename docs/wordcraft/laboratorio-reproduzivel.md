# Laboratório versionado — sem ativação operacional

`scripts/wordcraft_lab.py` substitui o runner avulso usado na prova G1. Reutiliza
o schema/HTTP do ensaio canônico e o `DocumentoService`. Não oferece GoTrue nem
produção: cria somente uma identidade sintética, três processos sintéticos e um
banco próprio com nome aleatório num cluster portátil **descartável e dedicado**.
O bootstrap canônico estabelece papéis globais nesse cluster; por isso não basta
usar um banco vazio num cluster de trabalho. O runner exige marcador, diretório
real de dados, bind IPv4 e porta coincidentes antes de qualquer bootstrap.

## Preparação

1. Usar PostgreSQL local com pgvector e PostgREST compatível com o ensaio. O
   cluster precisa ter sido criado para os testes desta missão. Conferir seu
   diretório de dados e bind antes de escrever `.wordcraft-local-qa` nesse
   diretório, com conteúdo exato `LOCAL_WORDCRAFT_QA_ONLY` e uma quebra de linha.
2. Obter ZIP/commit/SHA do artefato QA de um build aprovado. Instalar os assets
   com `wordcraft_local_assets.py` em laboratório novo marcado. Não instalar
   checkpoints no namespace estático.
3. Usar os três checkpoints extraídos da evidência de corpus do build aprovado.
   O runner revalida todos pelo worker nativo antes de criar usuários/bancos.
4. Informar runtimes absolutos, hash confiável do manifest, diretório do cluster
   e DSN administrativo IPv4 em loopback. Variáveis herdadas `PG*`, inclusive
   `PGHOSTADDR`/`PGSERVICE`/`PGRST_*`, são recusadas. O endereço efetivo libpq é
   fixado explicitamente em `127.0.0.1` e na porta declarada.

Exemplo PowerShell, com os valores locais já conferidos pelo operador:

```powershell
& $python scripts/wordcraft_lab.py `
  --dsn $env:GOVDOCS_LAB_DSN `
  --cluster-data $clusterData `
  --lab $lab `
  --corpus $corpusRoundtrip `
  --node $node `
  --postgrest $postgrest `
  --pg-bin $pgBin `
  --manifest-sha256 $manifestSha256
```

Portas padrão: app 8884, PostgREST 55450 e gateway 55451, todas em loopback.
Porta ocupada causa recusa; nenhum processo existente é encerrado para liberá-la.
O namespace público serve somente os JS/WASM e avisos inventariados. Arquivos
extras causam recusa no preflight e não entram na allowlist da rota.

## Retomada e desligamento

`qa-state.json`, fora de `static`, contém UUIDs, nome do banco e hashes, sem
senhas/tokens. A retomada confere comentário de propriedade do banco, perfil
sintético e fingerprint das migrations. Não reseta nem migra banco existente
silenciosamente; alteração de schema exige um laboratório novo ou upgrade local
explicitamente ensaiado. Um checkpoint confirmado permanece no banco após restart.

Enviar `stop` seguido de Enter ao stdin encerra o runner passando pelo cleanup
dos próprios filhos e do login efêmero, preservando o banco para reabertura. Isso
também permite desligamento por API de terminal sem depender de um Ctrl+C forçado
do host. Fora desse caminho, queda/kill pode deixar login efêmero; verificar o nome
e ausência de conexões antes de limpar, sem varrer ou apagar objetos alheios.

JWTs sintéticos expiram em seis horas, conforme o helper canônico. Não há refresh
GoTrue neste laboratório. Reiniciar o runner renova os tokens em memória; não
estender a validade nem contar uma edição recusada como gravação. A abertura
mostra erro controlado quando a sessão não pode ser usada. Reabrir/trocar um
documento exige sempre confirmação de descarte, pois o estado dirty do backend
pode atrasar em relação ao canvas.

## Limites

A API nativa de importação ainda exige o build que exporta `import_docx`. Sucesso
dos testes de admission/IPC não substitui essa compilação. O índice de blocos é
derivado e ainda precisa de persistência atômica e vínculo com operações reais.
Este laboratório não aprova emissão, identidade institucional real, corte do
legado, comparação LibreOffice, Auth hospedado ou a homologação G7.
