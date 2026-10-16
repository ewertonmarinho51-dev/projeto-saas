-- Rollout único do editor nativo. A migration apenas registra OFF.
-- Ativação de canário/produção é um ato posterior e explicitamente autorizado.
insert into public.config_app (chave, valor)
values ('flag_wordcraft_editor', 'false')
on conflict (chave) do nothing;
