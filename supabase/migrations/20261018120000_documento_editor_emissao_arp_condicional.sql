-- Independent database guard for the conditional ARP instrument. The owner
-- already derives the complete package; this trigger prevents a privileged RPC
-- call from adding an obsolete ARP or omitting the required ARP.
begin;

create function public.documento_editor_emissao_confere_arp()
returns trigger
language plpgsql security invoker set search_path='' as $$
declare
  v_data jsonb;
  v_srp boolean;
  v_has_arp boolean;
begin
  select p.dados into v_data from public.processos p where p.id=new.processo_id;
  if not found or jsonb_typeof(v_data)<>'object' then
    raise exception 'process form unavailable for native emission' using errcode='PT409';
  end if;
  v_srp:=position('registro de preços' in lower(coalesce(v_data->>'modelo_execucao','')))>0;
  select coalesce(bool_or(item->>'tipo'='arp'),false) into v_has_arp
    from jsonb_array_elements(new.documentos) item;
  if v_has_arp is distinct from v_srp then
    raise exception 'conditional ARP differs from process form' using errcode='PT409';
  end if;
  return new;
end $$;

revoke all on function public.documento_editor_emissao_confere_arp()
  from public,anon,authenticated,service_role;

create trigger documento_editor_emissao_confere_arp
before insert on public.documentos_editor_emissoes
for each row execute function public.documento_editor_emissao_confere_arp();

commit;
