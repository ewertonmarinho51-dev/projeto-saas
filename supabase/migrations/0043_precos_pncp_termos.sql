-- ## 0043 — Busca NACIONAL do PNCP pelos itens cotados (índice por termo)
-- ## ESTADO: NÃO APLICADA em produção. Aplicar só com o aceite do dono.
-- ## ENSAIO: CI (`tests/test_migracao_0043.py`, PostgreSQL) e projeto
-- ##   descartável `uslaxaxomjawydqtbwkb` em 11/11/2026 (registros
-- ##   `m0043_precos_pncp_termos` e, depois da revisão do
-- ##   `revisor-de-banco-e-seguranca`, `m0043_precos_pncp_termos_revisao`):
-- ##   conferência passou; 51 → 52 tabelas; políticas `precos_pncp_%`
-- ##   seguem 1; ACL da tabela nova `service_role=arwd` (sem MAINTAIN no
-- ##   PG17). Comportamento, num bloco DO que termina em RAISE:
-- ##   `authenticated` recusado; servidor apaga termo, TRUNCATE recusado;
-- ##   `parcial` aceito, estado inválido recusado. (LOCK ACCESS EXCLUSIVE
-- ##   segue possível ao servidor: vem do UPDATE, como em toda tabela que
-- ##   ele escreve, não do MAINTAIN.)
--
-- O PROBLEMA (11/11/2026)
--   O dono comparou "analisador bioquímico" no Banco de Preços (dezenas de
--   resultados de 9 UFs) com o nosso sistema (nenhum). O índice da 0042 tinha
--   141 resultados, todos do Pará. Ampliar a coleta por UF para o Brasil não
--   cabe: ~32,5 mil pregões por mês, uma chamada POR ITEM para ler o
--   resultado. E a busca nacional do portal no clique do usuário reprovou
--   sob carga: o PNCP recusa conexão, 18 de 41 itens com a fonte em falha.
--
-- O QUE FAZ
--   O indexador passa a buscar no portal, FORA do clique, os itens que os
--   usuários cotam (`pncp_indice_servico.rodada_por_termos`), e grava no
--   MESMO índice da 0042, pela mesma conferência. A cotação não muda: a
--   fonte do índice, já ligada, passa a achar resultados de todo o Brasil.
--   * `precos_pncp_termos` — cada NÚCLEO de descrição (as primeiras palavras
--     significativas, sem acento: "analisador bioquimico") e quando ele foi
--     e quando volta a ser buscado;
--   * estado `parcial` em `precos_pncp_contratacoes` — contratação achada
--     pela busca por termo, da qual só os itens que casaram foram lidos.
--
-- DECISÕES
--   * O núcleo é derivado da descrição do item cotado, mas não diz de QUEM
--     é: sem `tenant_id`, sem processo, sem órgão. Mesmo assim, só a
--     credencial de servidor lê e escreve — o usuário não precisa da tabela;
--   * a LEITURA que alimenta a tabela cruza órgãos por desenho: o indexador,
--     com a credencial de servidor, lê `pesquisa_preco_itens.descricao` de
--     todos os tenants (30 dias, até 2.000 linhas, só a coluna `descricao`).
--     O texto inteiro fica na memória do processo; sai dele só o núcleo —
--     gravado aqui e mandado à busca PÚBLICA do PNCP, sem órgão nem pessoa.
--     O núcleo descarta número puro, palavra com e-mail, formato longo com
--     dígitos (CPF/CNPJ colado a letra) e palavras genéricas de compra
--     ("aquisição", "contratação", "empresa"), que viriam antes do objeto
--     (revisão de 11/11/2026: nome próprio em descrição de serviço);
--   * sem política: RLS ligado e nenhum papel além de `service_role` (que
--     ignora RLS) alcança a tabela — a contagem de políticas da 0042 segue 1;
--   * `service_role` PODE apagar termo (e só isso: `TRUNCATE`, `REFERENCES`,
--     `TRIGGER` e, no PG17, `MAINTAIN` revogados). A tabela é fila de
--     trabalho, não trilha: um termo gravado por engano tem de poder sair
--     sem nova migração. As tabelas da 0042 seguem sem `DELETE`;
--   * o tamanho é limitado pela entrada: um núcleo tem de 3 a 120 caracteres.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não busca nada: o indexador precisa rodar (`ciclo --banco`), e a busca
--     por termo é ligada por padrão nele (`--sem-termos` desliga);
--   * resultado já indexado continua legível por SELECT direto mesmo com
--     `vigente = false` (política `using (true)` da 0042); a busca (RPC) os
--     esconde. Restringir a política é outra migração.

create table if not exists public.precos_pncp_termos (
  nucleo text primary key
    check (char_length(nucleo) between 3 and 120),
  buscado_em timestamptz,
  proxima_busca timestamptz not null default now(),
  contratacoes integer not null default 0,
  resultados integer not null default 0,
  falhas integer not null default 0,
  erro text not null default '',
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create index if not exists precos_pncp_termos_fila_idx
  on public.precos_pncp_termos (proxima_busca, buscado_em nulls first);

alter table public.precos_pncp_termos enable row level security;
revoke all on public.precos_pncp_termos from anon, authenticated, public;
grant select, insert, update, delete on public.precos_pncp_termos to service_role;
revoke truncate, references, trigger on public.precos_pncp_termos from service_role;
-- MAINTAIN (VACUUM, REINDEX, LOCK…) existe a partir do PG17 — produção é 17,
-- o ensaio do CI é 16. O default ACL de `postgres` o concede (`arwdxtm`).
do $$
begin
  if current_setting('server_version_num')::int >= 170000 then
    execute 'revoke maintain on public.precos_pncp_termos from service_role';
  end if;
end
$$;

alter table public.precos_pncp_contratacoes
  drop constraint if exists precos_pncp_contratacoes_estado_check;
alter table public.precos_pncp_contratacoes
  add constraint precos_pncp_contratacoes_estado_check check (estado in
    ('pendente', 'coletada', 'sem_resultado', 'fora_do_piloto', 'falha',
     'parcial'));

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
begin
  if not (select relrowsecurity from pg_class
           where oid = 'public.precos_pncp_termos'::regclass) then
    faltou := faltou || ' rls_desligado';
  end if;
  if has_any_column_privilege('anon', 'public.precos_pncp_termos',
                              'select, insert, update, references')
     or has_table_privilege('anon', 'public.precos_pncp_termos', 'delete, truncate') then
    faltou := faltou || ' anon_alcanca';
  end if;
  if has_any_column_privilege('authenticated', 'public.precos_pncp_termos',
                              'select, insert, update, references')
     or has_table_privilege('authenticated', 'public.precos_pncp_termos',
                            'delete, truncate') then
    faltou := faltou || ' authenticated_alcanca';
  end if;
  if has_table_privilege('service_role', 'public.precos_pncp_termos',
                         'truncate, references, trigger') then
    faltou := faltou || ' service_role_trunca_ou_amarra';
  end if;
  -- IF aninhado: o PG16 recusa o nome `maintain`, e o AND do SQL não
  -- garante a ordem de avaliação
  if current_setting('server_version_num')::int >= 170000 then
    if has_table_privilege('service_role', 'public.precos_pncp_termos', 'maintain') then
      faltou := faltou || ' service_role_maintain';
    end if;
  end if;
  if not (has_table_privilege('service_role', 'public.precos_pncp_termos', 'select')
          and has_table_privilege('service_role', 'public.precos_pncp_termos', 'insert')
          and has_table_privilege('service_role', 'public.precos_pncp_termos', 'update')
          and has_table_privilege('service_role', 'public.precos_pncp_termos', 'delete')) then
    faltou := faltou || ' service_role_sem_escrita';
  end if;
  if exists (select 1 from pg_policies
              where schemaname = 'public' and tablename = 'precos_pncp_termos') then
    faltou := faltou || ' politica_inesperada';
  end if;
  if not exists (
       select 1 from pg_constraint
        where conname = 'precos_pncp_contratacoes_estado_check'
          and conrelid = 'public.precos_pncp_contratacoes'::regclass
          and pg_get_constraintdef(oid) like '%parcial%'
          and pg_get_constraintdef(oid) like '%fora_do_piloto%') then
    faltou := faltou || ' estado_parcial_ausente';
  end if;
  if faltou <> '' then
    raise exception 'A 0043 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
