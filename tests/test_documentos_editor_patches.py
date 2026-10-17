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
    def __init__(self, rows): self.rows=rows; self.columns=None
    def select(self,*args):
        if len(args)==1 and args[0] != '*':
            self.columns=tuple(item.strip() for item in args[0].split(','))
        return self
    def eq(self,key,value):
        self.rows=[r for r in self.rows if r.get(key)==value]
        return self
    def limit(self,n):
        if isinstance(self.rows,list): self.rows=self.rows[:n]
        return self
    def execute(self):
        if isinstance(self.rows,Exception): raise self.rows
        rows=copy.deepcopy(self.rows)
        if self.columns and isinstance(rows,list):
            rows=[{key:row[key] for key in self.columns} for row in rows]
        return SimpleNamespace(data=rows)


@pytest.fixture
def patch_owner(engine,monkeypatch):
    calls,_=engine
    service=owner.DocumentoService(node=Path('/test/node'),bundle=Path('/test/bundle'),manifest_sha256='a'*64)
    monkeypatch.setattr(owner,'validar',lambda *a,**k:None)
    actor,tenant,process=(str(uuid4()) for _ in range(3))
    claims={'sub':actor,'role':'authenticated','app_metadata':{'tenant_id':tenant,'papel':'usuario'}}
    process_row={'id':process,'tenant_id':tenant,'secretaria_id':None,'criado_em':'2026-01-20T12:00:00Z','dados':{},'aprovados':[]}
    state={'claims':claims,'heads':[],'rows':[],'opinions':[],'opinion_findings':[],
           'rpc_calls':[],'proposals':0,'native_calls':calls,'contexts':0}
    context={'processo':{k:process_row[k] for k in ('id','tenant_id','secretaria_id','dados','aprovados')},'fatos':[]}
    state['context']=context

    class User:
        def rpc(self,name,params):
            assert name=='documento_editor_contexto'
            return Query(state['claims'])
        def table(self,name):
            return Query(copy.deepcopy({'documentos_editor':state['heads'],'documentos_editor_revisoes':state['rows'],
                'pareceres':state['opinions'],'parecer_achados':state['opinion_findings'],
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


def test_current_audit_is_read_only_and_bound_to_native_heads(patch_owner):
    service,state,process=patch_owner
    current=service.auditoria_atual(process)
    assert current.keys()=={'report','snapshot'}
    assert current['report']['bundleHash']==current['snapshot']['hash']
    assert set(current['report']['sourceNative'])=={'memo_a','memo_b','memo_c'}
    assert all(binding['revision']==1 for binding in current['report']['sourceNative'].values())
    assert not state['rpc_calls'] and all(head['revision']==1 for head in state['heads'])


def test_current_fact_evidence_is_read_only_and_bound_to_native_heads(patch_owner):
    from src import governanca
    service,state,process=patch_owner
    fact={'id':str(uuid4()),'path':'valor.total','tipo':'numero','valor':'10.00',
        'fonte':'pesquisa_preco:qa-1','status':'confirmado','versao':1,'hash':'',
        'processo_id':process,'tenant_id':state['claims']['app_metadata']['tenant_id']}
    fact['hash']=governanca.hash_canonico({key:fact[key]
        for key in ('path','tipo','valor','versao')})
    state['context']['fatos']=[fact]
    current=service.evidencias_atuais(process)
    assert current['schema']=='gc-wordcraft-evidence-panel/v1'
    assert current['evidencias'][0]['estado']=='VERIFICADO'
    assert current['evidencias'][0]['source_ref']=='pesquisa_preco:qa-1'
    assert current['bundleHash'] and set(current['sourceNative'])=={'memo_a','memo_b','memo_c'}
    assert not state['rpc_calls'] and all(head['revision']==1 for head in state['heads'])


def test_current_structure_reuses_revision_institution_and_decimal_items(patch_owner):
    service,state,process=patch_owner
    state['context']['processo']['dados']={'itens':[
        {'codigo':'A','descricao':'Item A','quantidade':'0.1','valor_unitario':'0.2'},
        {'codigo':'B','descricao':'Item B','quantidade':'3','valor_unitario':'10.00'}]}
    current=service.estrutura_atual(process,'memo_a')
    assert current['schema']=='gc-wordcraft-structure-panel/v1'
    assert current['docKey']=='memo_a' and current['documentId']==state['heads'][0]['id']
    assert current['institucional']['document_id']==state['heads'][0]['id']
    assert current['institucional']['phase']=='draft_reference'
    assert current['montagem']['quantidade_itens']==2
    assert current['montagem']['valor_total']=='30.02'
    assert current['bundleHash'] and not state['rpc_calls']


def test_persisted_legal_opinion_is_classified_and_bound_read_only(patch_owner):
    service,state,process=patch_owner
    opinion, finding = str(uuid4()), str(uuid4())
    state['opinions']=[dict(id=opinion,nome_arquivo='parecer.pdf',
        hash_origem='f'*64,status='NORMALIZED',processo_id=process)]
    state['opinion_findings']=[dict(id=finding,parecer_id=opinion,
        categoria='operacional',gravidade='HIGH',
        problema='Redação imprecisa.',documento_afetado='memo_a',
        clausula_afetada='1',fundamento='art. 1',
        correcao_solicitada='Substituir por redação objetiva.',causa='',
        sistemico=False,confianca=.9,
        evidencias=['Texto placeholder sintético do documento memo_a, requer ajuste pontual.'])]
    current=service.pareceres_atuais(process)
    assert current['schema']=='gc-wordcraft-legal-opinions/v1'
    assert len(current['pareceres'])==len(current['findings'])==1
    item=current['findings'][0]
    assert item['findingId']==f'PJ:{opinion}:{finding}'
    assert item['autoCorrectable'] is True
    assert item['allowedPaths'][0].startswith('memo_a/clausula/1/')
    assert item['sourceIds']==[f'parecer:{opinion}',f'parecer_achado:{finding}']
    assert not state['rpc_calls'] and all(head['revision']==1 for head in state['heads'])


def test_legal_opinion_without_one_literal_native_target_stays_manual(patch_owner):
    service,state,process=patch_owner
    opinion, finding = str(uuid4()), str(uuid4())
    state['opinions']=[dict(id=opinion,nome_arquivo='parecer.pdf',
        hash_origem='e'*64,status='NORMALIZED',processo_id=process)]
    state['opinion_findings']=[dict(id=finding,parecer_id=opinion,
        categoria='operacional',gravidade='MEDIUM',problema='Revisar a cláusula.',
        documento_afetado='memo_a',clausula_afetada='1',fundamento='',
        correcao_solicitada='Melhorar a redação.',causa='',sistemico=False,
        confianca=.8,evidencias=['trecho que não pertence ao documento'])]
    item=service.pareceres_atuais(process)['findings'][0]
    assert item['parecerStatus']=='CORRECAO_AUTOMATICA'
    assert item['autoCorrectable'] is False and item['allowedPaths']==[]
    assert 'citação única' in item['blockingReason']
    assert not state['rpc_calls']


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


def test_consistency_finding_maps_exactly_to_native_anchor_and_reaudits(patch_owner, monkeypatch):
    from src import consistencia
    service,state,process=patch_owner

    def consistency(facts, documents):
        assert facts == [{'path':'valor.total','valor':'10.00'}]
        text=documents['memo_a']
        if 'placeholder' not in text:
            return []
        return [dict(findingId='C001',documentId='memo_a',clauseId=None,
            categoria='consistencia_valor',severity='HIGH',descricao='valor divergente',
            evidencia=['R$ 9,00'],regraViolada='fato canônico',resultadoEsperado='R$ 10,00',
            autoCorrectable=True,allowedPaths=['memo_a/clausula/1/1'],blockedPaths=[],
            sourceIds=['valor.total'],blockingReason=None)]

    state['context']['fatos']=[{'path':'valor.total','valor':'10.00'}]
    monkeypatch.setattr(consistencia,'verificar',consistency)

    def proposal(*,relatorio,snapshot,contexto):
        finding=next(item for item in relatorio['findings'] if item['findingId']=='C001')
        assert finding['autoCorrectable'] is True
        assert finding['allowedPaths'][0].startswith('memo_a/clausula/1/')
        assert finding['allowedPaths'][0] != 'memo_a/clausula/1/1'
        path=finding['allowedPaths'][0]
        block=next(item for item in snapshot['documentos']['memo_a']['blocos']
                   if item['path']==path)
        return {'operations':[dict(findingId='C001',documentId='memo_a',op='replace',
            path=path,expectedOldHash=block['hash'],
            newValue=block['conteudo'].replace('placeholder','corrigido'),
            reason='alinhar ao fato canônico',sourceIds=['valor.total'])],
            'unresolvedFindings':[]}

    prep=service.preparar_patches(process,operation_id=str(uuid4()),propor_plano=proposal)
    assert [item.fonte.doc_key for item in prep.resultados]==['memo_a']
    before,after=prep.auditoria()['reports']
    assert any(item['findingId']=='C001' for item in before['findings'])
    assert not any(item['findingId']=='C001' for item in after['findings'])
    assert not state['rpc_calls']


@pytest.mark.parametrize('case',['duplicate','blocked','no_source','different_text'])
def test_consistency_mapping_fails_closed_when_native_parity_is_not_unique(case):
    from src.documentos_editor import _vincular_achado_nativo
    path='tr/clausula/7/11111111-1111-1111-1111-111111111111'
    block=SimpleNamespace(path=path,clausula=7,conteudo='Valor estimado R$ 10,00.',bloqueio=None)
    blocks=[block]
    if case=='duplicate':
        blocks.append(SimpleNamespace(path=path[:-1]+'2',clausula=7,
            conteudo=block.conteudo,bloqueio=None))
    if case=='blocked': block.bloqueio='clausula_bloqueada'
    if case=='different_text': block.conteudo='Outro valor.'
    finding=dict(documentId='tr',autoCorrectable=True,
        allowedPaths=['tr/clausula/7/1'],blockedPaths=[],
        sourceIds=[] if case=='no_source' else ['valor.total'])
    result=_vincular_achado_nativo(finding,
        {'tr':SimpleNamespace(blocos=blocks)},
        {'tr':'## 7. VALOR\n\nValor estimado R$ 10,00.'})
    assert result['autoCorrectable'] is False
    assert result['allowedPaths']==[]


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
