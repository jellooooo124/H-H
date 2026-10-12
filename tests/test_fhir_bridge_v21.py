"""FHIR R4 synthetic interoperability regression and security gates."""
import copy
import time
from datetime import datetime,timezone
import jwt,pytest
from httpx import ASGITransport,AsyncClient
from test_system import client,settings

PATIENT='DEMO-P001'

def entry(resource_id='fhir-001',loinc='29463-7',value=71.8,unit='kg',patient=PATIENT):
    return {'resource':{
        'resourceType':'Observation','id':resource_id,'status':'final',
        'subject':{'reference':'Patient/'+patient},
        'code':{'coding':[{'system':'http://loinc.org','code':loinc}]},
        'effectiveDateTime':datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'valueQuantity':{'value':value,'system':'http://unitsofmeasure.org','code':unit}}}

def packet(entries=None,patient=PATIENT):
    return {'patient_ref':patient,'is_synthetic':True,
            'bundle':{'resourceType':'Bundle','type':'collection','entry':entries or [entry()]}}

def hdr(settings,role='clinician',patient_refs=None):
    payload={'iss':'hah-course-demo','sub':'fhir-'+role,'role':role,'exp':int(time.time())+3600}
    if role=='patient': payload['patient_ref']=PATIENT
    if patient_refs is not None:payload['patient_refs']=patient_refs
    return {'Authorization':'Bearer '+jwt.encode(payload,settings.jwt_secret,algorithm='HS256')}

@pytest.mark.asyncio
async def test_valid_bundle_duplicate_is_noop(client,settings):
    body=packet()
    r=await client.post('/v3/fhir/import',json=body,headers=hdr(settings))
    assert r.status_code==200,r.text
    d=await client.post('/v3/fhir/import',json=body,headers=hdr(settings))
    assert d.status_code==200 and d.json()['imported']==0 and d.json()['unchanged']==1
    exp=await client.get('/v3/fhir/Observation',params={'patient_ref':PATIENT},headers=hdr(settings))
    assert exp.status_code==200 and exp.json()['total']==1
    out=exp.json()['entry'][0]['resource']
    assert out['code']['coding'][0]['code']=='29463-7'
    assert out['valueQuantity']['value']==71.8
    assert client._transport.app.state.store.verify_audit() is True

@pytest.mark.asyncio
async def test_fhir_reuse_id_changed_measurement_returns_409(client,settings):
    body=packet()
    assert (await client.post('/v3/fhir/import',json=body,headers=hdr(settings))).status_code==200
    changed=copy.deepcopy(body);changed['bundle']['entry'][0]['resource']['valueQuantity']['value']=77.0
    r=await client.post('/v3/fhir/import',json=changed,headers=hdr(settings))
    assert r.status_code==409,r.text
    assert (await client.get('/v3/fhir/Observation',params={'patient_ref':PATIENT},headers=hdr(settings))).json()['total']==1

@pytest.mark.asyncio
async def test_atomic_import_rollback_and_wrong_patient(client,settings):
    body=packet([entry('fhir-001'),entry('fhir-002',loinc='2339-0',unit='mg/dL',value=123)])
    assert (await client.post('/v3/fhir/import',json=body,headers=hdr(settings))).status_code==200
    fail=packet([entry('fhir-003'),entry('fhir-002',loinc='2339-0',unit='mg/dL',value=145)])
    r=await client.post('/v3/fhir/import',json=fail,headers=hdr(settings))
    assert r.status_code==409
    res=(await client.get('/v3/fhir/Observation',params={'patient_ref':PATIENT},headers=hdr(settings))).json()
    assert res['total']==2
    other=packet([entry('fhir-different',patient='DEMO-P999')]);r=await client.post('/v3/fhir/import',json=other,headers=hdr(settings))
    assert r.status_code==422

@pytest.mark.asyncio
@pytest.mark.parametrize('mutation',[
    lambda e:e['resource']['valueQuantity'].update({'code':'g'}),
    lambda e:e['resource']['code']['coding'][0].update({'code':'fake'}),
    lambda e:e['resource'].update({'note':[{'text':'Free text must not be accepted'}]}),
    lambda e:e['resource'].update({'status':'preliminary'}),
    lambda e:e['resource']['valueQuantity'].update({'value':True}),
])
async def test_untrusted_fhir_rejected(client,settings,mutation):
    e=entry();mutation(e)
    r=await client.post('/v3/fhir/import',json=packet([e]),headers=hdr(settings))
    assert r.status_code==422,r.text

@pytest.mark.asyncio
async def test_auth_internal_auth_and_patient_scope(client,settings):
    assert (await client.post('/v3/fhir/import',json=packet())).status_code==401
    assert (await client.post('/v3/fhir/import',json=packet(),headers=hdr(settings,role='patient'))).status_code==403
    assert (await client.post('/v3/fhir/import',json=packet(),headers=hdr(settings,patient_refs=['DEMO-P777']))).status_code==403
    assert (await client.get('/v3/fhir/Observation',params={'patient_ref':PATIENT},headers=hdr(settings,patient_refs=['DEMO-P777']))).status_code==403
    assert (await client.post('/internal/fhir/sandbox-sync')).status_code==401
    assert (await client.post('/v3/fhir/import',json={'patient_ref':PATIENT,'bundle':packet()['bundle']},headers=hdr(settings))).status_code==422

@pytest.mark.asyncio
async def test_scheduled_sync_sandbox_is_repeatable(client,settings):
    h={'X-Internal-Key':settings.internal_key}
    first=await client.post('/internal/fhir/sandbox-sync',headers=h)
    assert first.status_code==200,first.text
    assert first.json()['imported']==3 and first.json()['remote_ehr_connected'] is False
    second=await client.post('/internal/fhir/sandbox-sync',headers=h)
    assert second.status_code==200 and second.json()['imported']==0 and second.json()['unchanged']==3
    out=await client.get('/v3/fhir/Observation',params={'patient_ref':PATIENT},headers=hdr(settings))
    assert out.json()['total']==3
    assert client._transport.app.state.store.verify_audit()
