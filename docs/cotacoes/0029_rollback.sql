-- Rollback da 0029 (Cotações unificadas). NÃO aplicar sem autorização.
--
-- Ordem: desligar a flag ANTES (a tela volta à Pesquisa de Preços, que
-- não lê nenhuma coluna nova), depois desfazer o schema.
--
-- Perda de dado: `lote`, `uf`, `removido_em` e `revisao` dos itens e o
-- registro de emissões. Antes de rodar, exportar:
--   copy (select id, lote, uf, removido_em, revisao
--           from public.pesquisa_preco_itens) to stdout with csv header;
--   copy (select * from public.pesquisa_preco_emissoes) to stdout with csv header;
-- Eventos com os tipos novos ficam na trilha (append-only): o CHECK
-- antigo é recriado como NOT VALID para não recusar o histórico.

update public.config_app set valor = 'off'
 where chave = 'flag_unified_quotations';

-- Revisão volta à versão da 0021 (sem as colunas novas): reaplicar o
-- bloco `revisar_pesquisa_preco` de supabase/migrations/0021_pesquisa_precos.sql.

drop table if exists public.pesquisa_preco_emissoes;
drop function if exists public.trg_pesquisa_preco_emissor();

alter table public.pesquisa_preco_eventos
  drop constraint if exists pesquisa_preco_eventos_tipo_check;
alter table public.pesquisa_preco_eventos
  add constraint pesquisa_preco_eventos_tipo_check
  check (tipo in ('pesquisa_criada', 'pesquisa_revisada',
                  'busca_iniciada', 'busca_concluida', 'busca_falhou',
                  'referencia_incluida', 'referencia_excluida',
                  'metodo_alterado', 'preco_arbitrado',
                  'item_concluido', 'item_incompleto',
                  'pesquisa_concluida', 'pesquisa_aplicada',
                  'pesquisa_arquivada')) not valid;

alter table public.pesquisa_preco_itens
  drop constraint if exists pesquisa_preco_itens_uf_valida;
alter table public.pesquisa_preco_itens
  drop constraint if exists pesquisa_preco_itens_revisao_positiva;
alter table public.pesquisa_preco_itens drop column if exists removido_em;
alter table public.pesquisa_preco_itens drop column if exists uf;
alter table public.pesquisa_preco_itens drop column if exists lote;
alter table public.pesquisa_preco_itens drop column if exists revisao;

delete from public.config_app where chave = 'flag_unified_quotations';
