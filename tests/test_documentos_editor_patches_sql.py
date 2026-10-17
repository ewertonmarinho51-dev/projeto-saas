"""Real batch CAS/rollback/audit proofs. Opaque payloads are not native QA."""
import copy
from contextlib import contextmanager
import hashlib
import json
import threading
import time
from uuid import uuid4

import pytest

from src.documentos_editor import _snapshot_bytes
from tests.test_documentos_editor_institucional_sql import database, reconnect_dsn, snapshot
from tests.test_documentos_editor_sql import role, seed_scenario


@contextmanager
def business_conflict():
    import psycopg
    with pytest.raises(psycopg.ProgrammingError) as captured:
        yield
    assert captured.value.sqlstate == 'PT409'


@pytest.fixture(scope='module')
def patch_db():
    with database() as (connection,_): yield connection


def commit_source(connection,scenario,document,kind,*,expected=0,payload=None):
    from psycopg.types.json import Jsonb
    payload=payload or f'opaque source {kind} {expected}'.encode()
    digest=hashlib.sha256(payload).hexdigest()
    previous=connection.execute('select block_index,institutional_snapshot from public.documentos_editor_revisoes '
        'where document_id=%s and revision=%s',(document,expected)).fetchone() if expected else None
    institution=json.loads(snapshot(scenario,revision=expected+1)); institution.update(document_id=str(document),doc_key=kind)
    institution=bytes(previous[1]) if previous else _snapshot_bytes(institution)
    anchor=json.loads(bytes(previous[0]))['blocos'][0] if previous else dict(block_id=str(uuid4()),parte=None,
        indices=[0],story_kind='body',tipo='para',content_hash=digest)
    anchor['content_hash']=digest
    index=_snapshot_bytes(dict(schema='gc-wordcraft-block-index/v1',document_id=str(document),revision=expected+1,
        content_hash=digest,engine_manifest_sha256='a'*64,blocos=[anchor],invalidacoes=[],areas_nao_enderecaveis=[]))
    with role(connection,'service_role'):
        connection.execute('select * from public.documento_editor_checkpoint('+','.join(['%s']*18)+')',
            (document,scenario['process'],kind,expected,uuid4(),payload,digest,Jsonb(scenario['owner']),'a'*64,index,
             hashlib.sha256(index).hexdigest(),'reconciled' if expected else 'initial',None,None,None,None,
             institution,hashlib.sha256(institution).hexdigest()))


@pytest.fixture
def scenario(patch_db):
    value=seed_scenario(patch_db)
    value['documents']={key:uuid4() for key in ('dfd','etp','tr')}
    for key,document in value['documents'].items(): commit_source(patch_db,value,document,key)
    return value


def batch(connection,scenario):
    from psycopg.types.json import Jsonb
    operation=str(uuid4()); process=str(scenario['process'])
    with role(connection,'service_role'):
        context=connection.execute('select public.documento_editor_fontes_patch(%s,%s)',
            (scenario['process'],Jsonb(scenario['owner']))).fetchone()[0]
    sources=[];targets=[];bindings={}
    for kind,document in scenario['documents'].items():
        row=connection.execute('select revision,content_hash,block_index,block_index_sha256,institutional_snapshot,'
            'institutional_snapshot_sha256 from public.documentos_editor_revisoes where document_id=%s order by revision desc limit 1',(document,)).fetchone()
        source=dict(doc_key=kind,document_id=str(document),revision=row[0],content_hash=row[1],engine_build='a'*64,
            index_hash=row[3],institutional_hash=row[5]);sources.append(source)
        bindings[kind]=dict(documentId=str(document),revision=row[0],sourceHash=row[1],engineManifestSha256='a'*64)
        if kind=='tr': continue
        payload=f'opaque native patched {kind}'.encode();digest=hashlib.sha256(payload).hexdigest()
        index=json.loads(bytes(row[2]));index.update(revision=row[0]+1,content_hash=digest)
        index['blocos'][0]['content_hash']=digest; index=_snapshot_bytes(index)
        targets.append(dict(doc_key=kind,document_id=str(document),source_revision=row[0],revision=row[0]+1,
            content_hash=digest,payload='\\x'+payload.hex(),block_index='\\x'+index.hex(),index_hash=hashlib.sha256(index).hexdigest(),
            institutional_snapshot='\\x'+bytes(row[4]).hex(),institutional_hash=row[5],engine_build='a'*64,
            native_commands=dict(schema='gc-wordcraft-native-patch/v1',source_hash=row[1],source_revision=row[0],
                operations=[dict(op='replace_text',story='body',path=[0],start_byte=1,end_byte=2,old_text='x',new_text='y')])))
    before='b'*64;after='c'*64
    plan=dict(patchPlanId=operation,bundleId=process,sourceBundleHash=before,sourceBundleVersion=1,sourceNative=bindings,
        operations=[dict(documentId=t['doc_key'],op='replace',path='fixture-only') for t in targets],unresolvedFindings=[])
    plan_bytes=_snapshot_bytes(plan)
    audit=dict(schema='gc-wordcraft-patch-batch/v1',operation_id=operation,status='REVIEW_COMPLETED',official_emission=False,
        plan=plan,reports=[{'status':'REVIEW_COMPLETED'},{'status':'REVIEW_COMPLETED'}],snapshots=[{'hash':before,'versao':1},{'hash':after,'versao':2}],diff={})
    return dict(schema='gc-wordcraft-patch-batch/v1',operation_id=operation,processo_id=process,actor_id=scenario['owner']['sub'],
        plan_hash=hashlib.sha256(plan_bytes).hexdigest(),plan_payload='\\x'+plan_bytes.hex(),source_bundle_hash=before,
        target_bundle_hash=after,sources=sources,targets=targets,context=context,audit=audit)


def persist(connection,scenario,body,*,claims=None,db_role='service_role'):
    from psycopg.types.json import Jsonb
    raw=_snapshot_bytes(body)
    with role(connection,db_role,claims):
        result=connection.execute('select public.documento_editor_patch_lote(%s,%s,%s,%s,%s)',
            (scenario['process'],body['operation_id'],raw,hashlib.sha256(raw).hexdigest(),Jsonb(claims or scenario['owner']))).fetchone()[0]
        assert connection.execute("select auth.jwt()->>'role'").fetchone()==(db_role,)
        return result


def state(connection,scenario):
    heads=connection.execute('select tipo,revision,status from public.documentos_editor where processo_id=%s order by tipo',(scenario['process'],)).fetchall()
    audits=connection.execute('select count(*) from public.revisoes where processo_id=%s and native_patch_operation is not null',(scenario['process'],)).fetchone()[0]
    return heads,audits


def test_two_targets_one_atomic_cycle_and_retry_without_history_rewrite(patch_db,scenario):
    body=batch(patch_db,scenario);first=persist(patch_db,scenario,body);again=persist(patch_db,scenario,body)
    assert first['audit_id']==again['audit_id'] and again['replayed'] and not first['replayed']
    assert state(patch_db,scenario)==([('dfd',2,'rascunho'),('etp',2,'rascunho'),('tr',1,'rascunho')],1)
    assert all(r['index_mode']=='operational_patch' for r in first['documentos'])
    rows=patch_db.execute('select r.block_index,r.institutional_snapshot,b.block_index,b.institutional_snapshot,r.patch_audit_id,r.patch_proof '
        'from public.documentos_editor_revisoes r join public.documentos_editor_revisoes b on b.document_id=r.document_id and b.revision=1 '
        'where r.patch_audit_id=%s',(first['audit_id'],)).fetchall()
    assert len(rows)==2
    for new,institution,old,original,audit,proof in rows:
        assert bytes(institution)==bytes(original)
        assert json.loads(bytes(new))['blocos'][0]['block_id']==json.loads(bytes(old))['blocos'][0]['block_id']
        assert proof['content_hash'] and str(audit)==first['audit_id']
    ledger=patch_db.execute('select status,eventos,native_patch_manifest from public.revisoes where id=%s',(first['audit_id'],)).fetchone()
    assert ledger[0]=='REVIEW_COMPLETED' and [e['para'] for e in ledger[1]]==['CORRECTION_APPLIED','REVALIDATING','REVIEW_COMPLETED']
    assert all(e['ator']==scenario['owner']['sub'] and e['operation_id']==body['operation_id'] for e in ledger[1])
    assert patch_db.execute('select documentos,aprovados from public.processos where id=%s',(scenario['process'],)).fetchone()==({'dfd':'legacy untouched'},[])


@pytest.mark.parametrize('change',['second_hash','second_index_id','institution','source_build','plan_hash','command_type','target_scope'])
def test_any_bad_target_or_proof_rolls_back_the_whole_batch(patch_db,scenario,change):
    import psycopg
    body=batch(patch_db,scenario); second=sorted(body['targets'],key=lambda t:t['document_id'])[1]
    if change=='second_hash': second['content_hash']='d'*64
    elif change=='second_index_id':
        index=json.loads(bytes.fromhex(second['block_index'][2:]));index['blocos'][0]['block_id']=str(uuid4())
        raw=_snapshot_bytes(index);second.update(block_index='\\x'+raw.hex(),index_hash=hashlib.sha256(raw).hexdigest())
    elif change=='institution':
        value=json.loads(bytes.fromhex(second['institutional_snapshot'][2:]));value['identity']={'forged':'x'}
        raw=_snapshot_bytes(value);second.update(institutional_snapshot='\\x'+raw.hex(),institutional_hash=hashlib.sha256(raw).hexdigest())
    elif change=='source_build': body['sources'][0]['engine_build']='e'*64
    elif change=='plan_hash': body['plan_hash']='d'*64
    elif change=='command_type': second['native_commands']['operations'][0]['op']='delete'
    elif change=='target_scope': second['document_id']=str(uuid4())
    if change == 'source_build':
        with business_conflict(): persist(patch_db,scenario,body)
    else:
        with pytest.raises((psycopg.errors.InvalidParameterValue,psycopg.errors.InsufficientPrivilege)):
            persist(patch_db,scenario,body)
    assert state(patch_db,scenario)==([('dfd',1,'rascunho'),('etp',1,'rascunho'),('tr',1,'rascunho')],0)


@pytest.mark.parametrize('change',['untouched','new_source','facts','process','revoked','moved','approved','legacy'])
def test_stale_or_unauthorized_source_never_produces_partial_result(patch_db,scenario,change):
    import psycopg
    from psycopg.types.json import Jsonb
    body=batch(patch_db,scenario)
    if change=='untouched': commit_source(patch_db,scenario,scenario['documents']['tr'],'tr',expected=1)
    elif change=='new_source': commit_source(patch_db,scenario,uuid4(),'memo')
    elif change=='facts': patch_db.execute("insert into public.fatos_canonicos(tenant_id,processo_id,path) values(%s,%s,'new.fact')",(scenario['owner']['app_metadata']['tenant_id'],scenario['process']))
    elif change=='process': patch_db.execute('update public.processos set dados=%s where id=%s',(Jsonb({'new':'value'}),scenario['process']))
    elif change=='revoked': patch_db.execute('update public.usuarios set ativo=false where auth_user_id=%s',(scenario['owner']['sub'],))
    elif change=='moved': patch_db.execute('update public.usuarios set secretaria_id=null where auth_user_id=%s',(scenario['owner']['sub'],))
    elif change=='approved': patch_db.execute("update public.documentos_editor set status='aprovado' where id=%s",(scenario['documents']['etp'],))
    elif change=='legacy': patch_db.execute("update public.processos set aprovados=array['etp'] where id=%s",(scenario['process'],))
    if change in {'untouched','new_source','facts','process','legacy'}:
        with business_conflict(): persist(patch_db,scenario,body)
    else:
        with pytest.raises(psycopg.errors.InsufficientPrivilege): persist(patch_db,scenario,body)
    assert patch_db.execute('select count(*) from public.documentos_editor_revisoes where patch_audit_id is not null '
        'and document_id in (select id from public.documentos_editor where processo_id=%s)',(scenario['process'],)).fetchone()==(0,)
    assert state(patch_db,scenario)[1]==0


def test_retry_collision_and_actor_mismatch_do_not_duplicate_or_overwrite(patch_db,scenario):
    import psycopg
    body=batch(patch_db,scenario);persist(patch_db,scenario,body)
    different=copy.deepcopy(body);different['audit']['diff']={'changed':True}
    with business_conflict(): persist(patch_db,scenario,different)
    with pytest.raises(psycopg.errors.InsufficientPrivilege): persist(patch_db,scenario,body,claims=scenario['colleague'])
    assert state(patch_db,scenario)[1]==1


def test_native_cycle_and_operational_proof_are_immutable_and_user_cannot_forge_rpc(patch_db,scenario):
    import psycopg
    from psycopg.types.json import Jsonb
    body=batch(patch_db,scenario)
    with pytest.raises(psycopg.errors.InsufficientPrivilege): persist(patch_db,scenario,body,db_role='authenticated',claims=scenario['owner'])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with role(patch_db,'authenticated',scenario['owner']):
            patch_db.execute('insert into public.revisoes(tenant_id,processo_id,native_patch_operation,native_patch_actor,native_patch_sha256,native_patch_manifest,status) '
                "values(%s,%s,%s,%s,%s,%s,'REVIEW_COMPLETED')",(scenario['owner']['app_metadata']['tenant_id'],scenario['process'],uuid4(),scenario['owner']['sub'],'a'*64,Jsonb({})))
    receipt=persist(patch_db,scenario,body)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with role(patch_db,'service_role'):
            patch_db.execute("update public.revisoes set eventos='[]' where id=%s",(receipt['audit_id'],))
    with role(patch_db,'authenticated',scenario['other']):
        assert not patch_db.execute('select id from public.revisoes where id=%s',(receipt['audit_id'],)).fetchall()


@pytest.mark.parametrize('change',['revoked','moved'])
def test_native_audit_reconciles_current_profile_before_select_with_stale_jwt(patch_db,scenario,change):
    receipt=persist(patch_db,scenario,batch(patch_db,scenario))
    legacy=patch_db.execute('insert into public.revisoes(tenant_id,processo_id) values(%s,%s) returning id',
        (scenario['owner']['app_metadata']['tenant_id'],scenario['process'])).fetchone()[0]
    with role(patch_db,'authenticated',scenario['owner']):
        assert patch_db.execute('select id from public.revisoes where id=%s',(receipt['audit_id'],)).fetchone()
    if change=='revoked':
        patch_db.execute('update public.usuarios set ativo=false where auth_user_id=%s',(scenario['owner']['sub'],))
    else:
        patch_db.execute('update public.usuarios set secretaria_id=null where auth_user_id=%s',(scenario['owner']['sub'],))
    with role(patch_db,'authenticated',scenario['owner']):
        assert not patch_db.execute('select id from public.revisoes where id=%s',(receipt['audit_id'],)).fetchall()
        assert not patch_db.execute('select id from public.documentos_editor where processo_id=%s',(scenario['process'],)).fetchall()
        # The native-only restrictive policy preserves historical row semantics.
        assert patch_db.execute('select id from public.revisoes where id=%s',(legacy,)).fetchone()


def test_second_checkpoint_runtime_failure_reverts_first_and_cycle_event(patch_db,scenario):
    import psycopg
    body=batch(patch_db,scenario); second=sorted(body['targets'],key=lambda t:t['document_id'])[1]['document_id']
    try:
        patch_db.execute("create function public.qa_fail_second_patch() returns trigger language plpgsql as $$ begin "
            "if new.document_id::text='"+second+"' and new.revision=2 then raise exception 'QA second target unavailable' using errcode='40001'; end if; return new; end $$")
        patch_db.execute('create trigger qa_fail_second_patch before insert on public.documentos_editor_revisoes for each row execute function public.qa_fail_second_patch()')
        with pytest.raises(psycopg.errors.SerializationFailure): persist(patch_db,scenario,body)
        assert state(patch_db,scenario)==([('dfd',1,'rascunho'),('etp',1,'rascunho'),('tr',1,'rascunho')],0)
    finally:
        patch_db.execute('drop trigger if exists qa_fail_second_patch on public.documentos_editor_revisoes')
        patch_db.execute('drop function if exists public.qa_fail_second_patch()')


def test_retry_is_historical_after_an_untouched_source_has_advanced(patch_db,scenario):
    body=batch(patch_db,scenario);first=persist(patch_db,scenario,body)
    commit_source(patch_db,scenario,scenario['documents']['tr'],'tr',expected=1)
    again=persist(patch_db,scenario,body)
    assert again['audit_id']==first['audit_id'] and again['replayed'] and again['documentos']==first['documentos']
    assert state(patch_db,scenario)[1]==1


@pytest.mark.parametrize('foreign_tenant',[False,True])
def test_foreign_process_or_tenant_source_is_never_accepted(patch_db,scenario,foreign_tenant):
    import psycopg
    body=batch(patch_db,scenario)
    if foreign_tenant: other=seed_scenario(patch_db)
    else:
        process=patch_db.execute('insert into public.processos(tenant_id,secretaria_id,auth_user_id) values(%s,%s,%s) returning id',
            (scenario['owner']['app_metadata']['tenant_id'],scenario['owner']['app_metadata']['secretaria_id'],scenario['owner']['sub'])).fetchone()[0]
        other={**scenario,'process':process}
    document=uuid4();commit_source(patch_db,other,document,'memo')
    body['sources'][2]['document_id']=str(document)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):persist(patch_db,scenario,body)
    assert state(patch_db,scenario)[1]==0
    assert patch_db.execute('select revision from public.documentos_editor where id=%s',(document,)).fetchone()==(1,)


def test_event_failure_prevents_every_document_change(patch_db,scenario):
    import psycopg
    body=batch(patch_db,scenario)
    try:
        patch_db.execute("create function public.qa_fail_patch_event() returns trigger language plpgsql as $$ begin "
            "if new.native_patch_operation is not null then raise exception 'QA event failure' using errcode='40001'; end if; return new; end $$")
        patch_db.execute('create trigger qa_fail_patch_event before insert on public.revisoes for each row execute function public.qa_fail_patch_event()')
        with pytest.raises(psycopg.errors.SerializationFailure):persist(patch_db,scenario,body)
        assert state(patch_db,scenario)==([('dfd',1,'rascunho'),('etp',1,'rascunho'),('tr',1,'rascunho')],0)
    finally:
        patch_db.execute('drop trigger if exists qa_fail_patch_event on public.revisoes')
        patch_db.execute('drop function if exists public.qa_fail_patch_event()')


def connect_again(connection):
    import psycopg
    return psycopg.connect(reconnect_dsn(connection),autocommit=True)


def wait_locked(observer,pid):
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        row=observer.execute('select wait_event_type from pg_stat_activity where pid=%s',(pid,)).fetchone()
        if row and row[0]=='Lock':return
        threading.Event().wait(0.01)
    pytest.fail('batch did not contend on the live writer')


@pytest.mark.parametrize('change',['untouched','new_source','facts','revoked'])
def test_concurrent_source_or_revocation_is_rechecked_after_wait(patch_db,scenario,change):
    import psycopg
    from concurrent.futures import ThreadPoolExecutor
    body=batch(patch_db,scenario)
    with connect_again(patch_db) as writer,connect_again(patch_db) as executor:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with writer.transaction():
                if change=='untouched':commit_source(writer,scenario,scenario['documents']['tr'],'tr',expected=1)
                elif change=='new_source':commit_source(writer,scenario,uuid4(),'new_memo')
                elif change=='facts':writer.execute("insert into public.fatos_canonicos(tenant_id,processo_id,path) values(%s,%s,'concurrent.fact')",(scenario['owner']['app_metadata']['tenant_id'],scenario['process']))
                else:writer.execute('update public.usuarios set ativo=false where auth_user_id=%s',(scenario['owner']['sub'],))
                future=pool.submit(persist,executor,scenario,body)
                wait_locked(patch_db,executor.info.backend_pid)
            if change == 'revoked':
                with pytest.raises(psycopg.errors.InsufficientPrivilege): future.result(timeout=5)
            else:
                with business_conflict(): future.result(timeout=5)
    assert state(patch_db,scenario)[1]==0


def test_concurrent_exact_retry_commits_one_cycle_only(patch_db,scenario):
    from concurrent.futures import ThreadPoolExecutor
    body=batch(patch_db,scenario);barrier=threading.Barrier(2)
    def run():
        with connect_again(patch_db) as connection:
            barrier.wait(timeout=3)
            return persist(connection,scenario,body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run) for _ in range(2)];results=[f.result(timeout=5) for f in futures]
    assert results[0]['audit_id']==results[1]['audit_id'] and {r['replayed'] for r in results}=={False,True}
    assert state(patch_db,scenario)[1]==1


def test_process_fence_lock_timeout_rolls_back_without_cycle(patch_db,scenario):
    import psycopg
    body=batch(patch_db,scenario)
    with connect_again(patch_db) as writer,connect_again(patch_db) as executor:
        with writer.transaction():
            writer.execute('update public.processos set atualizado_em=now() where id=%s',(scenario['process'],))
            started=time.monotonic()
            with pytest.raises(psycopg.errors.LockNotAvailable):persist(executor,scenario,body)
            assert 1.5<=time.monotonic()-started<4
    assert state(patch_db,scenario)[1]==0


def test_process_competence_is_checked_before_waiting_for_any_lock(patch_db,scenario):
    import psycopg
    body=batch(patch_db,scenario)
    body['actor_id']=scenario['colleague']['sub']
    with connect_again(patch_db) as writer,connect_again(patch_db) as executor:
        with writer.transaction():
            writer.execute('update public.processos set atualizado_em=now() where id=%s',(scenario['process'],))
            # A current colleague can read the process but cannot patch it. The
            # permission error must precede the contended process lock timeout.
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                persist(executor,scenario,body,claims=scenario['colleague'])
    assert state(patch_db,scenario)[1]==0
