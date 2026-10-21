# Rollout canário do WordCraft

O WordCraft permanece desligado globalmente por
`config_app.flag_wordcraft_editor=false`. O canário usa as tabelas de módulos
já existentes; não cria uma segunda flag nem aceita `tenant_id` vindo do
navegador.

## Pré-condições

- release implantado com manifesto `GOVCONNECT_WORDCRAFT_DEPLOY_APPROVED`;
- migrations aditivas aplicadas e RLS validada;
- usuário de teste autenticado com `tenant_id` em `app_metadata`;
- tenant vazio de documentos WordCraft ou com fixtures descartáveis;
- versão anterior e comando de promoção registrados para rollback.

## Ativação de um tenant

Com a flag global ainda `false`, grave uma única admissão explícita:

```sql
insert into public.tenant_modulos (tenant_id, modulo, habilitado)
values ('<TENANT_CANARIO_UUID>', 'wordcraft_editor', true)
on conflict (tenant_id, modulo)
do update set habilitado = excluded.habilitado;
```

O runtime só monta o editor quando existe usuário autenticado e o tenant da
sessão possui essa linha. Tenant ausente, linha ausente, `habilitado=false`,
secretaria explicitamente desabilitada ou erro de leitura mantêm o editor
fechado. A superfície legada continua exclusiva para os demais tenants.

## Aceite

No tenant canário, provar abertura, edição, commit, reload, conflito CAS,
aprovação, emissão DOCX/PDF e download do original. Em outra sessão/tenant,
provar que a UI legada continua ativa e que nenhum documento, revisão ou evento
do canário é legível. Registrar contagens antes/depois, hashes dos artefatos,
commit servido, console do navegador, uso de memória e latência.

## Rollback

O rollback imediato não apaga dados:

```sql
update public.tenant_modulos
set habilitado = false
where tenant_id = '<TENANT_CANARIO_UUID>'
  and modulo = 'wordcraft_editor';
```

Revisões, originais, auditoria e emissões nativas permanecem preservados. Não
executar down migration nem converter snapshots nativos de volta para Markdown.
Se o release inteiro precisar voltar, promover a tag anterior somente depois de
registrar o commit atualmente servido.

## Corte global

Somente após o aceite do canário, alterar `flag_wordcraft_editor` para `true`.
Nesse estado, a resolução normal de módulos volta a valer: ausência de linha no
tenant herda a flag global e recusas explícitas do tenant/secretaria continuam
respeitadas.
