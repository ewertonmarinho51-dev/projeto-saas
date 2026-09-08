# Runbook — vínculo de usuários ao Supabase Auth

Este procedimento é uma migração administrativa de identidade. Ele não cria
contas, não decide quem é quem e não liga a feature flag `price_research`.

## Estado obrigatório antes da execução

- `price_research` permanece `off`;
- migrations 0020 e 0021 estão aplicadas;
- `SUPABASE_URL` aponta explicitamente para o projeto de produção;
- `SUPABASE_SECRET_KEY` existe apenas no ambiente servidor;
- cada titular foi identificado e teve o vínculo aprovado;
- a suíte, em especial `tests/test_vinculo_contas_auth.py`, está verde;
- não há outra execução do script em andamento.

## Criação das contas

Crie uma conta Auth individual por usuário. Confirme o e-mail e grave os
atributos de autorização em `app_metadata`, nunca em `user_metadata`:

```json
{
  "papel": "admin",
  "tenant_id": "11111111-1111-1111-1111-111111111111",
  "secretaria_id": "22222222-2222-2222-2222-222222222222",
  "papel_governanca": "admin_municipal"
}
```

Os quatro valores devem ser idênticos aos de `public.usuarios`. Campo vazio
ou ausente só é aceito quando também estiver vazio na tabela. Não vincule
usuário inativo.

## Mapa aprovado

Prefira UID, pois o e-mail pode mudar:

```json
[
  {
    "usuario_id": "679d43c6-0000-0000-0000-000000000001",
    "auth_uid": "23e8148e-0000-0000-0000-000000000001"
  }
]
```

`auth_email` pode substituir `auth_uid`, mas nunca coexistir com ele.
Não inclua senhas, metadados ou chaves. O mapa não deve ser commitado.

## Conferência sem escrita

```bash
python scripts/vincular_contas_auth.py --mapa vinculos.json
```

Um operador e um revisor devem conferir:

1. projeto Supabase de destino;
2. pessoa, `usuarios.id`, e-mail e Auth UID;
3. papel, tenant, secretaria e papel de governança;
4. quantidade de processos por titular;
5. ausência de usuários inativos e contas compartilhadas;
6. `SOBRARIAM 0 processos sem dono`, salvo exceção formal documentada.

Qualquer `RECUSADO` encerra a rodada. Não corrija dados por tentativa.

## Preservação anterior

Antes de gravar, exporte:

```sql
select id, auth_user_id from public.usuarios order by id;
select id, usuario_id, auth_user_id from public.processos order by id;
```

Registre o hash do mapa aprovado e impeça execuções concorrentes.

## Aplicação

Faça primeiro um mapa com um usuário-canário:

```bash
python scripts/vincular_contas_auth.py --mapa vinculo-canario.json --aplicar
```

Valide o canário e só depois execute o mapa restante. Uma interrupção pode
deixar o usuário já vinculado e os processos ainda nulos; isso é retomável.
Nunca ignore uma recusa durante a aplicação.

## Validação posterior

As consultas abaixo devem retornar zero:

```sql
select p.id, p.usuario_id, p.auth_user_id, u.auth_user_id
from public.processos p
join public.usuarios u on u.id = p.usuario_id
where p.auth_user_id is distinct from u.auth_user_id;

select id from public.processos where auth_user_id is null;

select auth_user_id, count(*)
from public.usuarios
where auth_user_id is not null
group by auth_user_id
having count(*) > 1;
```

Depois, autentique como o canário, renove a sessão para obter JWT atual e
prove que:

- `sub`, papel, tenant e secretaria estão corretos;
- o usuário vê e altera apenas os dados permitidos;
- outro tenant/secretaria é negado pelo RLS;
- logs não contêm senha, JWT ou chave administrativa.

Somente após essa validação deve existir uma mudança separada para ligar
`price_research`.