"""Owner preparation/batch contract. HTTP/native engine stubs are explicit.

Canonical projection, findings, patch policy, diff, lineage and audit run real
Python code. SQL transaction/ACL proofs are in the companion module.
"""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src import documentos_editor as owner
from src.wordcraft_protocol import Checkpoint
from tests.test_patches_nativos import engine, encode, heading, para


class Query:
    def __init__(self, rows): self.rows=rows
    def select(self,*args): return self
    def eq(self,key,value):
        self.rows=[r for r in self.rows if r.get(key)==value]
        return self
    def limit(self,n):
        if isinstance(self.rows,list): self.rows=self.rows[:n]
        return self
    def execute(self):
        if isinstance(self.rows,Exception): raise self.rows
        return SimpleNamespace(data=copy.deepcopy(self.rows))


@pytest.fixture
def patch_owner(engine,monkeypatch):
    calls,_=engine
    service=owner.DocumentoService(node=Path('/test/node'),bundle=Path('/test/bundle'),manifest_sha256='a'*64)
    monkeypatch.setattr(owner,'validar',lambda *a,**k:None)
    actor,tenant,process=(str(uuid4()) for _ in range(3))
    claims={'sub':actor,'role':'authenticated','app_metadata':{'tenant_id':tenant,'papel':'usuario'}}
    process_row={'id':process,'tenant_id':tenant,'secretaria_id':None,'criado_em':'2026-01-20T12:00:00Z','dados':{},'aprovados':[]}
    state={'claims':claims,'heads':[],'rows':[],'rpc_calls':[],'proposals':0,'native_calls':calls,'contexts':0}
    context={'processo':{k:process_row[k] for k in ('id','tenant_id','secretaria_id','dados','aprovados')},'fatos':[]}
    state['context']=context

    class User:
        def rpc(self,name,params):
            assert name=='documento_editor_contexto'
            return Query(state['claims'])
        def table(self,name):
            return Query(copy.deepcopy({'documentos_editor':state['heads'],'documentos_editor_revisoes':state['rows'],
                'processos':[process_row]}.get(name,[])))

    for key in ('memo_a','memo_b','memo_c'):
        document=str(uuid4())
        text=f'Texto placeholder sintético do documento {key}, requer ajuste pontual.'
        payload=encode({'schema':owner.SCHEMA,'document':{'body':[heading('1. OBJETO'),para(text)]+
            [para(f'Parágrafo íntegro {n} preservado no documento {key}.') for n in range(6)],'parts':{}},'media':{},'passthrough':{}})
        digest=hashlib.sha256(payload).hexdigest()
        index=owner.blocos.construir_indice(payload,document_id=document,revision=1,content_hash=digest,**service._native)
        institution=service._capturar_institucional(User(),document_id=document,process_id=process,tipo=key,revision=1)
        state['heads'].append(dict(id=document,processo_id=process,tipo=key,revision=1,content_hash=digest,status='rascunho',tenant_id=tenant))
        state['rows'].append(dict(document_id=document,revision=1,payload='\\x'+payload.hex(),content_hash=digest,
            editor_schema_version=owner.SCHEMA,wordcraft_commit=owner.UPSTREAM,engine_build_sha256='a'*64,
            validation_provenance='server_manifest_sha256',block_index='\\x'+owner.blocos.serializar_indice(index).hex(),
            block_index_sha256=hashlib.sha256(owner.blocos.serializar_indice(index)).hexdigest(),index_mode='initial',
            institutional_snapshot='\\x'+institution.hex(),institutional_snapshot_sha256=hashlib.sha256(institution).hexdigest()))
    stored={}

    class Server:
        def rpc(self,name,params):
            if name=='documento_editor_fontes_patch':
                state['contexts']+=1
                return Query(context)
            assert name=='documento_editor_patch_lote'
            state['rpc_calls'].append(params)
            if state.get('error'): return Query(state['error'])
            batch=json.loads(bytes.fromhex(params['p_batch'][2:]))
            replay=params['p_operation'] in stored
            row=dict(operation_id=params['p_operation'],processo_id=process,audit_id=stored.get(params['p_operation'],str(uuid4())),
                plan_hash=batch['plan_hash'],batch_sha256=params['p_batch_sha256'],replayed=replay,
                documentos=[dict(document_id=t['document_id'],revision=t['revision'],content_hash=t['content_hash'],
                    engine_build_sha256=t['engine_build'],block_index_sha256=t['index_hash'],index_mode='operational_patch',
                    institutional_snapshot_sha256=t['institutional_hash']) for t in batch['targets']])
            stored[params['p_operation']]=row['audit_id']
            if state.get('bad_receipt'): row['documentos'][0]['content_hash']='b'*64
            return Query(row)

    monkeypatch.setattr(owner.db,'cliente_do_usuario',lambda:User())
    monkeypatch.setattr(owner.db,'_cliente',lambda:Server())

    def propose(*,relatorio,snapshot,contexto):
        state['proposals']+=1
        operations=[]
        for finding in relatorio['findings']:
            if finding['documentId']=='memo_c' or not finding['autoCorrectable']: continue
            path=finding['allowedPaths'][0]
            block=next(b for b in snapshot['documentos'][finding['documentId']]['blocos'] if b['path']==path)
            operations.append(dict(findingId=finding['findingId'],documentId=finding['documentId'],op='replace',path=path,
                expectedOldHash=block['hash'],newValue=block['conteudo'].replace('placeholder','revisado'),reason='correção backend',sourceIds=[]))
        return {'operations':operations,'unresolvedFindings':[]}
    state['propose']=propose
    return service,state,process


def prepare(patch_owner):
    service,state,process=patch_owner
    return service.preparar_patches(process,operation_id=str(uuid4()),propor_plano=state['propose'])


def test_backend_prepares_native_sources_exact_compiled_commands_and_reaudits(patch_owner):
    service,state,process=patch_owner
    prep=prepare(patch_owner)
    assert len(prep.fontes)==3 and len(prep.resultados)==len(prep.comandos)==2 and not state['rpc_calls']
    assert {r.fonte.doc_key for r in prep.resultados}=={'memo_a','memo_b'}
    assert len(state['native_calls'])==2
    sent={json.loads(payload)['document']['body'][1]['text']:plan for payload,_,plan in state['native_calls']}
    for command in prep.comandos:
        assert command.plano_nativo() in sent.values() and command.operation_id==prep.operation_id
        copy_plan=command.plano_nativo(); copy_plan['operations'].clear()
        assert command.plano_nativo()['operations']
    audit=prep.auditoria()
    assert audit['status']=='REVIEW_COMPLETED' and audit['official_emission'] is False
    assert all(r['status']=='REVIEW_COMPLETED' for r in audit['reports'])
    before=[f for f in audit['reports'][0]['findings'] if f['categoria']=='texto_placeholder']
    after=[f for f in audit['reports'][1]['findings'] if f['categoria']=='texto_placeholder']
    assert len(before)==3 and len(after)==1 and after[0]['documentId']=='memo_c'
    for result in prep.resultados:
        original=next(r for r in state['rows'] if r['document_id']==result.fonte.document_id)
        old=owner.blocos.desserializar_indice(bytes.fromhex(original['block_index'][2:]))
        assert [b.block_id for b in old.blocos]==[b.block_id for b in result.index.blocos]
        assert result.institutional_snapshot==bytes.fromhex(original['institutional_snapshot'][2:])
    assert all(h['revision']==1 for h in state['heads'])
    assert service.preparar_patches(process,operation_id=prep.operation_id,propor_plano=state['propose']) is prep
    assert state['proposals']==1


def test_contextual_capability_uses_the_same_owner_preparation_without_writing(patch_owner):
    from src.wordcraft_capacidades import Capacidade, CorrecaoContextual, propositor
    service,state,process=patch_owner

    def contextual(*,relatorio,snapshot,contexto):
        finding=next(f for f in relatorio['findings']
                     if f['documentId']=='memo_a' and f['autoCorrectable'])
        path=finding['allowedPaths'][0]
        block=next(b for b in snapshot['documentos']['memo_a']['blocos']
                   if b['path']==path)
        correction=CorrecaoContextual(Capacidade.AUDITORIA,finding['findingId'],
            block['conteudo'].replace('placeholder','contextual revisado'),
            'correção da auditoria central')
        return propositor(correction)(relatorio=relatorio,snapshot=snapshot,
                                      contexto=contexto)

    prep=service.preparar_patches(process,operation_id=str(uuid4()),
                                   propor_plano=contextual)
    assert [r.fonte.doc_key for r in prep.resultados]==['memo_a']
    assert prep.auditoria()['plan']['operations'][0]['reason']==\
        'correção da auditoria central'
    assert not state['rpc_calls']


def test_one_batch_rpc_returns_only_a_correlated_receipt_and_exact_retry(patch_owner):
    service,state,_=patch_owner
    prep=prepare(patch_owner)
    first=service.confirmar_patches(prep)
    second=service.confirmar_patches(prep)
    assert first.audit_id==second.audit_id and second.replayed and not first.replayed
    assert not first.canvas_confirmado and len(first.documentos)==2
    assert state['rpc_calls'][0]==state['rpc_calls'][1]
    assert all(r.index_mode=='operational_patch' for r in first.documentos)
    assert {r.document_id for r in first.documentos}=={r.fonte.document_id for r in prep.resultados}


def test_preparation_cannot_be_serialized_as_a_portable_commit_capability(patch_owner):
    import pickle
    prep=prepare(patch_owner)
    with pytest.raises(TypeError,match='owner'): pickle.dumps(prep)


def test_completed_batches_release_pending_capacity_and_keep_live_retry(patch_owner):
    service,state,_=patch_owner
    completed=[]
    for _ in range(7):
        prep=prepare(patch_owner)
        service.confirmar_patches(prep)
        completed.append(prep)
    assert len(service._patch_pendentes)==0
    assert service.confirmar_patches(completed[0]).replayed
    assert state['proposals']==7


def test_pending_capacity_is_bounded_and_explicit_discard_revokes_preparation(patch_owner):
    service,state,_=patch_owner
    pending=[prepare(patch_owner) for _ in range(4)]
    with pytest.raises(owner.ErroDocumento,match='quatro'): prepare(patch_owner)
    service.descartar_patches(pending[0])
    with pytest.raises(owner.ErroDocumento): service.confirmar_patches(pending[0])
    prepare(patch_owner)
    assert len(service._patch_pendentes)==4 and not state['rpc_calls']


def test_completed_payloads_are_not_retained_when_session_drops_preparation(patch_owner):
    import gc
    import weakref
    service,_,_=patch_owner
    prep=prepare(patch_owner)
    operation=prep.operation_id
    reference=weakref.ref(prep)
    service.confirmar_patches(prep)
    del prep
    gc.collect()
    assert reference() is None and operation not in service._preparacoes


def test_host_confirmation_must_match_every_target_operation_revision_hash_and_byte(patch_owner):
    service,state,_=patch_owner
    prep=prepare(patch_owner)
    checkpoints={r.fonte.doc_key:Checkpoint(prep.operation_id,r.fonte.revision,r.content_hash,r.payload) for r in prep.resultados}
    assert service.confirmar_patches(prep,checkpoints=checkpoints).canvas_confirmado
    state['rpc_calls'].clear()
    for change in ('missing','hash','operation','revision','bytes'):
        altered=dict(checkpoints)
        key=next(iter(altered)); cp=altered[key]
        if change=='missing': altered.pop(key)
        else:
            field,value={'hash':('content_hash','b'*64),'operation':('request_id',str(uuid4())),
                'revision':('expected_revision',7),'bytes':('content',b'forged')}[change]
            altered[key]=replace(cp,**{field:value})
        with pytest.raises(owner.ErroDocumento): service.confirmar_patches(prep,checkpoints=altered)
    assert not state['rpc_calls']


@pytest.mark.parametrize('forgery',['copied','result','index','hash','commands','actor','owner'])
def test_preparation_is_owner_scoped_and_immutable_before_any_write(patch_owner,forgery):
    service,state,_=patch_owner
    prep=prepare(patch_owner)
    candidate=prep
    if forgery=='copied': candidate=replace(prep)
    elif forgery=='owner': service=owner.DocumentoService(**service._native)
    elif forgery=='actor': state['claims']['sub']=str(uuid4())
    elif forgery=='result': object.__setattr__(prep.resultados[0],'payload',b'forged')
    elif forgery=='index': object.__setattr__(prep.resultados[0],'index',replace(prep.resultados[0].index,revision=99))
    elif forgery=='hash': object.__setattr__(prep.resultados[0],'content_hash','b'*64)
    elif forgery=='commands': object.__setattr__(prep.comandos[0],'_plano_json',b'{}')
    with pytest.raises(owner.ErroDocumento): service.confirmar_patches(candidate)
    assert not state['rpc_calls']


@pytest.mark.parametrize("conflict_code", ["PT409", "40001"])
def test_error_or_wrong_receipt_is_not_success(patch_owner, conflict_code):
    service,state,_=patch_owner
    prep=prepare(patch_owner)
    state['bad_receipt']=True
    with pytest.raises(owner.ErroDocumento,match='Recibo'): service.confirmar_patches(prep)
    class Stale(Exception): code=conflict_code
    state['error']=Stale('private body must not leak')
    with pytest.raises(owner.ConflitoDocumento) as result: service.confirmar_patches(prep)
    assert 'private' not in str(result.value)


def test_approved_or_legacy_target_never_reaches_native_application(patch_owner):
    service,state,_=patch_owner
    next(h for h in state['heads'] if h['tipo']=='memo_a')['status']='aprovado'
    with pytest.raises(owner.AcessoNegado): prepare(patch_owner)
    assert not state['native_calls'] and not state['rpc_calls']
