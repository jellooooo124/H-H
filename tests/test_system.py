import copy, hashlib, json, pathlib, time
from datetime import datetime,timezone
import jwt, httpx, pytest
from pydantic import ValidationError
from app.main import create_app
from app.config import Settings
from app.schemas import AgentResult, PlannerResponse, SynthesisResponse, Intake
from app.policy import assess

ROOT=pathlib.Path(__file__).resolve().parents[1]
NORMAL=json.loads((ROOT/'examples/normal.json').read_text())
REDFLAG=json.loads((ROOT/'examples/redflag.json').read_text())
INJECTION=json.loads((ROOT/'examples/injection.json').read_text())

class FakeModel:
    """Fake ONLY for deterministic offline tests. App runtime requires real model credentials."""
    def available(self):return True
    def embed(self,text):
        lower=text.lower()
        return [1.0 if 'heart' in lower else 0.1,1.0 if 'diabetes' in lower else 0.1,
                1.0 if 'sensor' in lower else 0.1,0.2]
    def structured(self,system,payload,schema,vision=None):
        if schema is PlannerResponse:
            return PlannerResponse(next_tool=payload['available_tools'][0],rationale='Select next bounded tool')
        if schema is AgentResult:
            return AgentResult(summary='Synthetic observations for clinician review',observations=['No diagnosis'],confidence='medium',needs_clinician_review=True,hydration_direction='none',uncertainties=['Synthetic records'])
        if schema is SynthesisResponse:
            return SynthesisResponse(clinician_summary='Review synthetic trend and source context before deciding.',patient_draft='Your information has been received and is pending clinician review.',cited_source_ids=[payload['retrieved_sources'][0]['source_id']],limitations=['Demo only'])
        raise RuntimeError('Unexpected schema')

@pytest.fixture
def settings(tmp_path):
    import os
    from dataclasses import replace
    return replace(Settings.from_env(),database_path=str(tmp_path/'cases.db'))

@pytest.fixture
async def client(settings):
    async def fake_dispatch(payload): return True
    a=create_app(settings,model=FakeModel(),dispatch=fake_dispatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a),base_url='http://test') as c:
        yield c

def hdr(claims,secret):
    token=jwt.encode({'iss':'hah-course-demo','sub':'test-clinician','exp':int(time.time())+3600,**claims},secret,algorithm='HS256')
    return {'Authorization':'Bearer '+token}

def patient_header(s):return hdr({'role':'patient','patient_ref':'DEMO-P001'},s.jwt_secret)
def clinician_header(s):return hdr({'role':'clinician'},s.jwt_secret)
def internal_header(s):return {'X-Internal-Key':s.internal_key}

async def intake(client,s,record=NORMAL):
    r=await client.post('/v1/intake',json=record,headers=patient_header(s))
    assert r.status_code==202,r.text
    return r.json()

async def process(client,s,case_id):
    head=internal_header(s)
    r=await client.post('/internal/start',json={'case_id':case_id},headers=head)
    assert r.status_code==200,r.text
    tools=[]
    for _ in range(5):
        p=await client.post('/internal/plan',json={'case_id':case_id},headers=head)
        assert p.status_code==200,p.text
        step=p.json()['next_tool']
        if step=='finish':break
        tools.append(step)
        t=await client.post('/internal/tool',json={'case_id':case_id,'tool':step},headers=head)
        assert t.status_code==200,t.text
    else:pytest.fail('Planner did not terminate')
    assert set(tools)=={'nutrition','heart_failure','diabetes','guideline_search'}
    r=await client.post('/internal/finalize',json={'case_id':case_id},headers=head)
    assert r.status_code==200,r.text
    return r.json()

async def claim_case_review(client,s,case_id):
    h=clinician_header(s)
    tasks=(await client.get('/v2/tasks',headers=h)).json()['tasks']
    t=next(x for x in tasks if x['case_id']==case_id and x['kind']=='clinical_review')
    r=await client.post('/v2/tasks/'+t['task_id']+'/claim',headers=h)
    assert r.status_code==200,r.text

async def test_full_case_approval_is_simulated(client,settings):
    await intake(client,settings)
    result=await process(client,settings,'HHC-CASE-0001')
    assert result['status']=='AWAITING_CLINICIAN'
    details=(await client.get('/v1/cases/HHC-CASE-0001',headers=clinician_header(settings))).json()
    assert len(details['state']['sources'])==3
    assert set(details['state']['steps'])=={'nutrition','heart_failure','diabetes','guideline_search'}
    await claim_case_review(client,settings,'HHC-CASE-0001')
    decision={'case_id':'HHC-CASE-0001','choice':'approve','comment':'I reviewed the displayed original observations.','expected_version':details['version']}
    r=await client.post('/v1/decisions',json=decision,headers=clinician_header(settings))
    assert r.status_code==200 and r.json()['sent_to_patient'] is False
    out=(await client.get('/v1/outbox',headers=clinician_header(settings))).json()
    assert len(out)==1 and out[0]['status']=='SIMULATED_ONLY'
    audit=(await client.get('/v1/audit/HHC-CASE-0001',headers=clinician_header(settings))).json()
    assert audit['chain_valid'] is True and len(audit['events'])>=11
    assert 'meal_text' not in json.dumps(audit)

async def test_urgent_safe_stop_cannot_be_approved(client,settings):
    await intake(client,settings,REDFLAG)
    r=await process(client,settings,'HHC-CASE-0002')
    assert r['safe_stop'] is True and r['status']=='ESCALATION_REQUIRED'
    case=(await client.get('/v1/cases/HHC-CASE-0002',headers=clinician_header(settings))).json()
    assert 'REPORTED_URGENT_SYMPTOM' in case['state']['flags']
    await claim_case_review(client,settings,'HHC-CASE-0002')
    approval={'case_id':'HHC-CASE-0002','choice':'approve','comment':'This should be blocked even for a clinician','expected_version':case['version']}
    assert (await client.post('/v1/decisions',json=approval,headers=clinician_header(settings))).status_code==409
    approval['choice']='escalate'
    assert (await client.post('/v1/decisions',json=approval,headers=clinician_header(settings))).status_code==200

async def test_prompt_injection_stopped(client,settings):
    await intake(client,settings,INJECTION)
    r=await process(client,settings,'HHC-CASE-0003')
    assert r['safe_stop'] is True
    c=(await client.get('/v1/cases/HHC-CASE-0003',headers=clinician_header(settings))).json()
    assert 'POTENTIAL_PROMPT_INJECTION' in c['state']['flags']

async def test_boundary_auth_idempotency_and_tools(client,settings):
    r=await client.post('/v1/intake',json=NORMAL)
    assert r.status_code==401
    assert (await client.get('/v1/cases',headers=patient_header(settings))).status_code==403
    assert (await client.post('/internal/start',json={'case_id':'HHC-CASE-0001'})).status_code==401
    await intake(client,settings)
    assert (await client.post('/v1/intake',json=NORMAL,headers=patient_header(settings))).status_code==409
    assert (await client.post('/internal/start',json={'case_id':'HHC-CASE-0001'},headers=internal_header(settings))).status_code==200
    assert (await client.post('/internal/tool',json={'case_id':'HHC-CASE-0001','tool':'dangerous_webhook'},headers=internal_header(settings))).status_code==403
    assert (await client.post('/internal/tool',json={'case_id':'HHC-CASE-0001','tool':'nutrition'},headers=internal_header(settings))).status_code==403

async def test_invalid_and_real_key_missing_fail_closed(client,settings):
    bad=dict(NORMAL);bad['case_id']='HHC-CASE-9090';bad['is_synthetic']=False
    assert (await client.post('/v1/intake',json=bad,headers=patient_header(settings))).status_code==422
    bad=dict(NORMAL);bad['case_id']='HHC-CASE-9091';bad['meal_image_data_url']='https://evil.org/ssrf'
    assert (await client.post('/v1/intake',json=bad,headers=patient_header(settings))).status_code==422
    async def fake_dispatch(payload): return True
    app=create_app(settings,dispatch=fake_dispatch) # real LLMClient without OPENAI_API_KEY
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        fresh=dict(NORMAL);fresh['case_id']='HHC-CASE-9092'
        await intake(c,settings,fresh)
        await c.post('/internal/start',json={'case_id':fresh['case_id']},headers=internal_header(settings))
        assert (await c.post('/internal/plan',json={'case_id':fresh['case_id']},headers=internal_header(settings))).status_code==503
        state=(await c.get('/v1/cases/HHC-CASE-9092',headers=clinician_header(settings))).json()
        assert state['status']=='TECHNICAL_REVIEW'

def test_policy_missingness_conflict_and_injection():
    base={'payload':NORMAL,'state':{'agents':{},'sources':[],'synthesis':None}}
    no_read=copy.deepcopy(base);no_read['payload']['vitals']={}
    r=assess(no_read)
    assert 'NO_ACTIVE_VITALS' in r['flags'] and not r['safe_stop']
    conflict=copy.deepcopy(base)
    conflict['state']['agents']={'heart_failure':{'hydration_direction':'restrict'},'diabetes':{'hydration_direction':'increase'}}
    assert assess(conflict)['safe_stop']
    badcite=copy.deepcopy(base);badcite['state']['synthesis']={'patient_draft':'We received your data','cited_source_ids':['FORGED-123']}
    assert 'MISSING_OR_INVALID_CITATIONS' in assess(badcite)['flags']

def test_workflows_well_formed_and_do_not_expose_private_data():
    names=[]
    for path in (ROOT/'workflows').glob('*.json'):
        doc=json.loads(path.read_text());names.append(doc['name'])
        assert doc['active'] is False
        assert len({n['name'] for n in doc['nodes']})==len(doc['nodes'])
        assert all(n['type'].startswith('n8n-nodes-base.') for n in doc['nodes'])
        nodes={n['name'] for n in doc['nodes']}
        for conn in doc['connections'].values():
            for arr in conn['main']:
                for edge in arr: assert edge['node'] in nodes
        assert 'OPENAI_API_KEY' not in path.read_text()
        assert 'sk-' not in path.read_text()
    assert len(names)==15

def test_n8n_webhook_extracts_body_case_id():
    doc=json.loads((ROOT/'workflows/01_agentic_case_loop.json').read_text())
    start=next(x for x in doc['nodes'] if x['name']=='Start Case State')
    assert '$json.body.case_id' in start['parameters']['jsonBody']
    planner=next(x for x in doc['nodes'] if x['name']=='Planner (Real LLM)')
    assert '$json.case_id' in planner['parameters']['jsonBody']

@pytest.mark.asyncio
async def test_duplicate_decisions_and_bad_clinician_token(client,settings):
    await intake(client,settings)
    await process(client,settings,'HHC-CASE-0001')
    d=(await client.get('/v1/cases/HHC-CASE-0001',headers=clinician_header(settings))).json()
    await claim_case_review(client,settings,'HHC-CASE-0001')
    body={'case_id':'HHC-CASE-0001','choice':'reject','comment':'Test repeated/stale clinician action','expected_version':d['version']}
    assert (await client.post('/v1/decisions',json=body,headers=clinician_header(settings))).status_code==200
    assert (await client.post('/v1/decisions',json=body,headers=clinician_header(settings))).status_code==409
    assert (await client.get('/v1/outbox',headers=patient_header(settings))).status_code==403
