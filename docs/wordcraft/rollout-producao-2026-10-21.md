# Evidência de implantação e canário WordCraft — 21/10/2026

Este registro atualiza o estado externo do relatório integral de 19/10/2026.
Ele separa publicação, CI, merge, migrations, implantação, saúde, flag e
canário. Evidência local ou CI não é usada como substituto de uma prova em
produção.

## Release servido

| Sinal | Estado observado |
|---|---|
| Pull request da integração | `#65`, mesclado |
| Merge da integração | `16b4b71740ef540e07b59752f8c66b2df175a0b6` |
| Release inicial | `v1.10.0` |
| Pull request do canário por tenant | `#67`, mesclado |
| Merge do canário | `c1cf87d6859aa43a0e904d78c3d1374c1a401572` |
| Release atualmente promovido | `v1.10.1` |
| Checkout e imagem informados pelo host | `v1.10.1` / `c1cf87d6859aa43a0e904d78c3d1374c1a401572` |
| Aplicação | contêiner `app` saudável |
| Proxy | contêiner `caddy` em execução |
| Health público | `https://govconect.com/_stcore/health` respondeu `ok` |
| Entrada pública | tela de login carregada e sessão Auth real confirmada |

A promoção foi executada pelo procedimento existente
`/opt/govdocs/implantacao/promover.sh v1.10.1`. A verificação posterior usou o
próprio script em modo `--atual`, `git status`, `docker compose ps` e o endpoint
de saúde público.

## Banco e rollout

As dez migrations WordCraft foram aplicadas ao projeto Supabase de produção.
As tabelas `documentos_editor`, `documentos_editor_revisoes` e
`documentos_editor_emissoes` estavam vazias antes do canário. RLS estava ativa
e havia política nas três tabelas.

O rollout mantém `config_app.flag_wordcraft_editor=false`. A admissão explícita
foi registrada somente para o tenant canário `paragominas`:

```text
tenant_modulos.modulo = wordcraft_editor
tenant_modulos.habilitado = true
```

No momento da ativação, o tenant possuía dois usuários ativos, ambos vinculados
ao Auth e com `app_metadata.tenant_id` alinhado. As contagens WordCraft após a
ativação permaneciam em `0 / 0 / 0` para documentos, revisões e emissões.

## Evidência de CI

Os dois runs do commit do canário concluíram com sucesso:

- push: `39541608320`;
- pull request: `39541650675`.

A revisão automatizada não publicou achados antes do merge e não era check
obrigatório da branch. O merge foi condicionado ao SHA esperado e ocorreu em
21/10/2026 às 04:14:29 UTC.

## Roteiro canário

A sessão Auth real foi confirmada na interface de produção. O inventário atual
tem seis processos e nenhum está identificado como fixture de teste. O processo
menos avançado contém dados reais e exigiria enviar seu conteúdo à geração por
IA. Por isso, o ensaio destrutivo ou representativo permanece separado da prova
de login.

O aceite operacional ainda deve provar, com dados sintéticos:

1. criação de um processo identificado como canário;
2. abertura exclusiva do WordCraft;
3. edição, commit e reload;
4. rejeição de conflito CAS;
5. aplicação de patch, Undo e Redo;
6. aprovação e emissão imutáveis;
7. exportação e download de DOCX/PDF;
8. hashes, contagens e ausência de erro no navegador;
9. rollback por `tenant_modulos.habilitado=false`, sem apagar histórico;
10. isolamento de uma sessão ou tenant sem admissão, quando houver uma segunda
    unidade real disponível.

Até esse aceite, a flag global deve permanecer desligada e o legado não pode
ser removido. A ausência de um segundo tenant em produção impede tratar o
isolamento entre dois tenants como comprovado pelo canário atual; essa prova
continua coberta apenas pelos ensaios locais/CI.

## Reversão registrada

O rollback do canário não apaga documentos:

```sql
update public.tenant_modulos
set habilitado = false
where tenant_id = '<TENANT_CANARIO_UUID>'
  and modulo = 'wordcraft_editor';
```

O rollback da release é a promoção da tag anterior `v1.10.0`, depois de
registrar o commit servido. Não executar down migration nem converter snapshots
nativos de volta para Markdown.

## Veredito atual

**CANÁRIO ATIVO, ACEITE FUNCIONAL PENDENTE.** A release e a infraestrutura estão
saudáveis, Auth real foi confirmado e o escopo do tenant está correto. Corte
global, retirada do legado e conclusão do Gate 7 continuam bloqueados até o
roteiro funcional acima produzir evidência em produção.
