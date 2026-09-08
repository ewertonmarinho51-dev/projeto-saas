# Runbook — criação e vínculo de usuários ao Supabase Auth

Este procedimento é uma migração administrativa de identidade. Ele cria as
contas pelo Supabase Auth, confere o vínculo institucional e só então preenche
`usuarios.auth_user_id` e `processos.auth_user_id`. Ele **não** liga a feature
flag `price_research`.

## Estado obrigatório antes da execução

- `price_research` permanece `off`;
- migrations 0020 e 0021 estão aplicadas;
- `SUPABASE_URL` aponta explicitamente para o projeto correto;
- `SUPABASE_SECRET_KEY` existe apenas no ambiente servidor;
- cada titular e seu e-mail foram identificados e aprovados;
- a suíte, em especial `tests/test_vinculo_contas_auth.py` e
  `tests/test_auth_migracao_gates.py`, está verde;
- não há outra execução dos scripts de migração em andamento.

O project ref de produção deve ser informado explicitamente aos scripts. A
checagem compara esse valor com o host de `SUPABASE_URL`; divergência é erro
fatal, não aviso.

## 1. Arquivo para criação das contas

O arquivo contém somente identidade declarada. Não coloque papel, tenant,
secretaria, senha ou metadados no JSON:

```json
[
  {
    "usuario_id": "679d43c6-0000-0000-0000-000000000001",
    "auth_email": "servidor@example.org"
  }
]
```

`criar_contas_auth.py` deriva `app_metadata` diretamente de `public.usuarios`.
Isso impede que um mapa digitado à mão promova usuário, troque tenant ou
secretaria.

Campo institucional nulo **não deve ser inventado**. Se
`papel_governanca` estiver `NULL` em `public.usuarios`, a chave deve ficar
ausente no `app_metadata`. O mesmo vale para `secretaria_id` quando nulo.

Os mapas reais são ignorados pelo Git (`contas-auth*.json`, `vinculos*.json` e
`vinculo-*.json`). Não force o commit desses arquivos.

## 2. Dry-run da criação

```bash
python scripts/criar_contas_auth.py \
  --mapa contas-auth.json \
  --projeto-ref <PROJECT_REF>
```

O operador e o revisor devem conferir pessoa, e-mail, `usuarios.id` e todos os
atributos derivados. Qualquer `RECUSADO` encerra a rodada.

## 3. Criação das contas

Depois do dry-run aprovado:

```bash
python scripts/criar_contas_auth.py \
  --mapa contas-auth.json \
  --projeto-ref <PROJECT_REF> \
  --aplicar
```

O script usa a Admin API suportada pela SDK: envia convite por e-mail e grava
`app_metadata` logo depois. Nunca grava autorização em `user_metadata`.

Se o convite for criado e a atualização de metadata falhar, **não vincule a
conta**. Corrija o `app_metadata` e rode a conferência novamente. O script de
vínculo recusa escopo divergente, portanto essa falha parcial permanece
fechada.

Anote privadamente os Auth UIDs retornados. Não publique a saída em issue, PR
ou chat de terceiros.

## 4. Mapa aprovado de vínculos

Depois que as contas existirem, prefira UID porque o e-mail pode mudar:

```json
[
  {
    "usuario_id": "679d43c6-0000-0000-0000-000000000001",
    "auth_uid": "23e8148e-0000-0000-0000-000000000001"
  }
]
```

`auth_email` ainda é aceito pelo motor legado, mas nunca coexistindo com
`auth_uid`. Não inclua senhas, metadados ou chaves.

## 5. Conferência do vínculo sem escrita

Use o gate operacional, não o motor diretamente:

```bash
python scripts/aplicar_vinculos_auth.py \
  --mapa vinculos.json \
  --projeto-ref <PROJECT_REF>
```

O gate exige:

1. projeto Supabase correto;
2. `flag_price_research = off`;
3. pessoa, `usuarios.id`, e-mail e Auth UID coerentes;
4. `app_metadata` idêntico a papel, tenant, secretaria e papel de governança;
5. ausência de usuários inativos ou contas compartilhadas;
6. nenhum processo previamente ligado a outra conta;
7. **zero processos sobrando sem `auth_user_id`** numa aplicação completa.

Qualquer `RECUSADO` encerra a rodada. Não corrija dados por tentativa.

## 6. Preservação anterior

Antes de gravar, exporte:

```sql
select id, auth_user_id from public.usuarios order by id;
select id, usuario_id, auth_user_id from public.processos order by id;
```

Registre o hash do mapa aprovado e impeça execuções concorrentes.

## 7. Canário

O primeiro teste deve usar um usuário comum de escopo restrito, não o admin.
Monte um arquivo com **um único vínculo** e execute:

```bash
python scripts/aplicar_vinculos_auth.py \
  --mapa vinculo-canario.json \
  --projeto-ref <PROJECT_REF> \
  --canario
```

Depois do relatório aprovado:

```bash
python scripts/aplicar_vinculos_auth.py \
  --mapa vinculo-canario.json \
  --projeto-ref <PROJECT_REF> \
  --canario \
  --aplicar
```

`--canario` é a única situação em que processos sem dono podem permanecer de
propósito, e ele exige mapa de exatamente um usuário.

Valide login, JWT e RLS do canário antes de prosseguir.

## 8. Aplicação completa

```bash
python scripts/aplicar_vinculos_auth.py \
  --mapa vinculos.json \
  --projeto-ref <PROJECT_REF> \
  --aplicar
```

Sem `--canario`, se o mapa não cobrir todos os processos ainda sem
`auth_user_id`, o comando recusa **antes de escrever**.

Uma interrupção ainda pode deixar um usuário já vinculado e seus processos
parcialmente preenchidos porque o PostgREST não oferece uma transação única
para essa sequência. As escritas do motor são condicionais e idempotentes;
reexecutar retoma o que falta. Nunca ignore uma recusa durante a aplicação.

## 9. Validação posterior

As consultas abaixo devem retornar zero linhas:

```sql
select p.id, p.usuario_id, p.auth_user_id, u.auth_user_id
from public.processos p
join public.usuarios u on u.id = p.usuario_id
where p.auth_user_id is distinct from u.auth_user_id;

select id from public.processos where auth_user_id is null;

select id from public.usuarios
where ativo and auth_user_id is null;

select auth_user_id, count(*)
from public.usuarios
where auth_user_id is not null
group by auth_user_id
having count(*) > 1;
```

Depois autentique como o canário, renove a sessão para obter JWT atual e
prove que:

- `sub`, papel, tenant e secretaria estão corretos;
- o usuário vê e altera apenas dados permitidos;
- outro tenant/secretaria é negado pelo RLS;
- logs não contêm senha, JWT ou chave administrativa.

## 10. Fechamento da transição

Somente depois de **todos** os usuários ativos estarem vinculados e os testes
de login/JWT/RLS passarem deve-se avaliar `GOVDOCS_EXIGIR_SUPABASE_AUTH=1`.
Essa mudança fecha o caminho de senha legado e deve ser separada da criação e
do vínculo das contas.

`price_research` também continua `off` nessa etapa. A ativação do módulo é uma
mudança posterior e independente, feita somente depois de um smoke test com o
Supabase Auth obrigatório e o RLS efetivamente exercido.
