"""Acceptance tests for closed-loop simulated communications."""
import pytest, time, jwt
from test_system import client,settings,patient_header,clinician_header,internal_header,intake,REDFLAG

def draft(patient_ref='DEMO-P001',key='REQ-DEMO-UNIQUE-0001',case_id=None):
    return {'patient_ref':patient_ref,'request_key':key,'template_code':'CHECKIN_REQUEST','due_hours':1,'case_id':case_id}

@pytest.mark.asyncio
async def test_draft_publish_ack_and_idempotency(client,settings):
    ch=clinician_header(settings);ph=patient_header(settings)
    r=await client.post('/v5/communications/drafts',headers=ch,json=draft())
    assert r.status_code==201,r.text
    msg=r.json();mid=msg['message_id'];assert msg['state']=='DRAFT'
    assert (await client.post('/v5/communications/drafts',headers=ch,json=draft())).json()['idempotent'] is True
    assert (await client.get('/v5/patient/communications',headers=ph)).json()['messages']==[]
    p=await client.post(f'/v5/communications/{mid}/publish',headers=ch)
    assert p.status_code==200,p.text
    assert p.json()['external_messages_sent']==0
    received=(await client.get('/v5/patient/communications',headers=ph)).json()['messages']
    assert len(received)==1 and 'synthetic' in received[0]['content'].lower()
    a=await client.post(f'/v5/patient/communications/{mid}/acknowledge',headers=ph)
    assert a.status_code==200 and not a.json()['clinical_completion']
    assert (await client.post(f'/v5/patient/communications/{mid}/acknowledge',headers=ph)).json()['idempotent']
    assert (await client.post('/internal/communications/watch',headers=internal_header(settings))).json()['overdue_count']==0
    assert client._transport.app.state.store.verify_audit()

@pytest.mark.asyncio
async def test_scoping_and_clinician_only(client,settings):
    ph=patient_header(settings);ch=clinician_header(settings)
    assert (await client.post('/v5/communications/drafts',headers=ph,json=draft())).status_code==403
    assert (await client.post('/v5/communications/drafts',headers=ch,json=draft('DEMO-OTHER'))).status_code==201
    msg=(await client.post('/v5/communications/drafts',headers=ch,json=draft(key='REQ-DEMO-UNIQUE-0002'))).json()
    mid=msg['message_id']
    assert (await client.post(f'/v5/patient/communications/{mid}/acknowledge',headers=ph)).status_code==409
    assert (await client.post('/v5/communications/'+mid+'/publish',headers=ph)).status_code==403
    assert (await client.get('/v5/clinician/communications/DEMO-P001',headers=ph)).status_code==403
    assert (await client.post('/internal/communications/metrics')).status_code==401
    assert (await client.post('/v5/communications/drafts',headers=ch,json={**draft(),'template_code':'CUSTOM_MEDICATION'})).status_code==422
    collision={**draft(key='REQ-DEMO-UNIQUE-0002'),'patient_ref':'DEMO-OTHER'}
    assert (await client.post('/v5/communications/drafts',headers=ch,json=collision)).status_code==409

@pytest.mark.asyncio
async def test_overdue_generates_once_only_task_and_no_external_message(client,settings):
    ch=clinician_header(settings);ih=internal_header(settings)
    mid=(await client.post('/v5/communications/drafts',headers=ch,json=draft())).json()['message_id']
    await client.post(f'/v5/communications/{mid}/publish',headers=ch)
    result=client._transport.app.state.communications.watch(at=time.time()+7200)
    assert result['overdue_count']==1 and result['external_notifications_sent']==0
    assert client._transport.app.state.communications.watch(at=time.time()+7200)['overdue_count']==0
    tasks=(await client.get('/v2/tasks',headers=ch)).json()['tasks']
    assert len([t for t in tasks if t['kind']=='communication_followup'])==1
    assert (await client.post(f'/v5/patient/communications/{mid}/acknowledge',headers=patient_header(settings))).status_code==409

@pytest.mark.asyncio
async def test_unapproved_case_cannot_publish(client,settings):
    await intake(client,settings,REDFLAG)
    ch=clinician_header(settings)
    body=draft(case_id='HHC-CASE-0002')
    r=await client.post('/v5/communications/drafts',headers=ch,json=body)
    assert r.status_code==201,r.text
    assert (await client.post('/v5/communications/'+r.json()['message_id']+'/publish',headers=ch)).status_code==409
    assert (await client.post('/v5/communications/drafts',headers=ch,json=draft(key='REQ-DEMO-OTHER-0002',case_id='HHC-CASE-1234'))).status_code==404

@pytest.mark.asyncio
async def test_comm_token_scope_prevents_cross_patient_ack(client,settings):
    ch=clinician_header(settings)
    mid=(await client.post('/v5/communications/drafts',headers=ch,json=draft('DEMO-OTHER'))).json()['message_id']
    await client.post('/v5/communications/'+mid+'/publish',headers=ch)
    assert (await client.post('/v5/patient/communications/'+mid+'/acknowledge',headers=patient_header(settings))).status_code==404
    assert (await client.get('/v5/patient/communications',headers=patient_header(settings))).json()['messages']==[]

@pytest.mark.asyncio
async def test_comms_metrics_are_aggregated(client,settings):
    c=client._transport.app.state.communications
    await client.post('/v5/communications/drafts',headers=clinician_header(settings),json=draft())
    metrics=(await client.post('/internal/communications/metrics',headers=internal_header(settings))).json()
    assert metrics['by_state']['DRAFT']==1
    assert metrics['external_notifications_sent']==0 and 'DEMO-' not in str(metrics)
