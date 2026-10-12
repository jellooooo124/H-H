"""v2.4 synthetic-only patient engagement and read-only alert grouping."""
import time, jwt, pytest
from test_system import (client,settings,patient_header,clinician_header,internal_header,
                         intake,process,claim_case_review,REDFLAG)

@pytest.mark.asyncio
async def test_patient_portal_default_opt_out_and_private_dashboard(client,settings):
    h=patient_header(settings)
    r=await client.get('/v4/patient/dashboard?days=7',headers=h)
    assert r.status_code==200
    assert r.json()['reminder_preferences']['reminder_opt_in'] is False
    assert r.json()['patient_ref']=='DEMO-P001'
    assert 'warning' in r.json()
    assert (await client.get('/v4/patient/dashboard?days=365',headers=h)).status_code==422
    assert (await client.get('/v4/patient/dashboard',headers=clinician_header(settings))).status_code==403

@pytest.mark.asyncio
async def test_patient_opt_in_prompts_dedupe_and_seen(client,settings):
    h=patient_header(settings);ih=internal_header(settings)
    plan={'patient_ref':'DEMO-P001','observation_code':'weight_kg','review_gap_hours':24,'active':True}
    assert (await client.post('/v2/monitoring-plans',json=plan,headers=clinician_header(settings))).status_code==200
    assert (await client.post('/internal/engagement/watch',headers=ih)).json()['created_count']==0
    body={'reminder_opt_in':True,'reminder_hour_utc':0,'minimum_gap_hours':24}
    p=await client.put('/v4/patient/preferences',json=body,headers=h)
    assert p.status_code==200 and p.json()['reminder_opt_in']
    first=(await client.post('/internal/engagement/watch',headers=ih)).json()
    assert first['created_count']==1 and first['messages_sent']==0
    assert (await client.post('/internal/engagement/watch',headers=ih)).json()['created_count']==0
    prompts=(await client.get('/v4/patient/prompts',headers=h)).json()['prompts']
    assert len(prompts)==1
    x=await client.post('/v4/patient/prompts/'+prompts[0]['prompt_id']+'/seen',headers=h)
    assert x.status_code==200 and x.json()['delivered_to_patient'] is False
    again=(await client.post('/v4/patient/prompts/'+prompts[0]['prompt_id']+'/seen',headers=h)).json()
    assert again['idempotent'] is True
    assert (await client.put('/v4/patient/preferences',json={**body,'reminder_opt_in':False},headers=h)).status_code==200
    assert (await client.get('/v4/patient/prompts',headers=h)).json()['prompts'][0]['state']=='SEEN'
    assert (await client.post('/internal/engagement/watch',headers=ih)).json()['created_count']==0
    assert client._transport.app.state.store.verify_audit() is True

@pytest.mark.asyncio
async def test_reminder_opt_out_for_unenrolled_and_recent_checkin(client,settings):
    h=patient_header(settings);ih=internal_header(settings)
    assert (await client.put('/v4/patient/preferences',json={'reminder_opt_in':True,'reminder_hour_utc':0,'minimum_gap_hours':24},headers=h)).status_code==200
    assert (await client.post('/internal/engagement/watch',headers=ih)).json()['created_count']==0
    assert (await client.post('/v2/monitoring-plans',json={'patient_ref':'DEMO-P001','observation_code':'weight_kg','review_gap_hours':24},headers=clinician_header(settings))).status_code==200
    coord=client._transport.app.state.coordination
    coord.create_checkin('DEMO-P001','CHK-RECENT-0000001',{'symptoms':{}})
    assert (await client.post('/internal/engagement/watch',headers=ih)).json()['created_count']==0

@pytest.mark.asyncio
async def test_invalid_preferences_and_prompt_scope(client,settings):
    h=patient_header(settings)
    assert (await client.put('/v4/patient/preferences',json={'reminder_opt_in':True,'reminder_hour_utc':25,'minimum_gap_hours':24},headers=h)).status_code==422
    assert (await client.post('/v4/patient/prompts/PROMPT-unknown0000000/seen',headers=h)).status_code==404
    other=jwt.encode({'iss':'hah-course-demo','sub':'patient-2','role':'patient','patient_ref':'DEMO-OTHER','exp':int(time.time())+3600},settings.jwt_secret,algorithm='HS256')
    other_h={'Authorization':'Bearer '+other}
    r=await client.get('/v4/patient/dashboard',headers=other_h)
    assert r.status_code==200 and r.json()['patient_ref']=='DEMO-OTHER'
    assert r.json()['in_app_prompts']==[]

@pytest.mark.asyncio
async def test_read_only_alert_groups_urgent_never_collapsed(client,settings):
    coord=client._transport.app.state.coordination
    coord.new_task('test-urg1',None,'DEMO-P001','reported_symptom_review','urgent','REPORTED_URGENT_SYMPTOM',100)
    coord.new_task('test-urg2',None,'DEMO-P001','reported_symptom_review','urgent','REPORTED_URGENT_SYMPTOM',100)
    coord.new_task('test-info1',None,'DEMO-P001','missing_measurement_review','review','MISSING_EXPECTED_DATA',100)
    coord.new_task('test-info2',None,'DEMO-P001','missing_measurement_review','review','MISSING_EXPECTED_DATA',100)
    groups=(await client.get('/v4/clinician/alert-groups',headers=clinician_header(settings))).json()
    assert groups['raw_active_task_count']==4 and groups['display_group_count']==3
    assert groups['suppressed_task_count']==0
    assert sorted(len(x['task_ids']) for x in groups['groups'])==[1,1,2]
    assert groups['groups'][0]['priority']=='urgent'
    tasks=(await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks']
    assert len(tasks)==4
    assert (await client.get('/v4/clinician/alert-groups',headers=patient_header(settings))).status_code==403

@pytest.mark.asyncio
async def test_quality_snapshot_aggregate_only_and_deduplicated_hour(client,settings):
    ih=internal_header(settings)
    assert (await client.post('/internal/ops/quality-snapshot')).status_code==401
    a=(await client.post('/internal/ops/quality-snapshot',headers=ih)).json()
    b=(await client.post('/internal/ops/quality-snapshot',headers=ih)).json()
    assert a['aggregate_only'] and a['metrics']['actual_message_delivery_count']==0
    assert a['snapshot_hour']==b['snapshot_hour']
    db=client._transport.app.state.store.db
    assert db.execute('SELECT COUNT(*) n FROM operational_snapshots').fetchone()['n']==1
    assert 'DEMO-' not in str(a)

@pytest.mark.asyncio
async def test_scoped_evaluation_and_ground_truth_limitations(client,settings):
    h=clinician_header(settings)
    r=await client.get('/v4/clinician/evaluation/DEMO-P001?days=7',headers=h)
    assert r.status_code==200 and 'clinical_effectiveness_claim' in str(r.json())
    assert (await client.get('/v4/clinician/evaluation/DEMO-P001?days=180',headers=h)).status_code==422
    assert (await client.get('/v4/clinician/evaluation/DEMO-P001',headers=patient_header(settings))).status_code==403

@pytest.mark.asyncio
async def test_opt_out_cancels_pending_and_cannot_acknowledge(client,settings):
    h=patient_header(settings);ih=internal_header(settings)
    await client.post('/v2/monitoring-plans',json={'patient_ref':'DEMO-P001','observation_code':'weight_kg','review_gap_hours':24},headers=clinician_header(settings))
    body={'reminder_opt_in':True,'reminder_hour_utc':0,'minimum_gap_hours':24}
    await client.put('/v4/patient/preferences',json=body,headers=h)
    assert (await client.post('/internal/engagement/watch',headers=ih)).json()['created_count']==1
    pid=(await client.get('/v4/patient/prompts',headers=h)).json()['prompts'][0]['prompt_id']
    await client.put('/v4/patient/preferences',json={**body,'reminder_opt_in':False},headers=h)
    prompt=(await client.get('/v4/patient/prompts',headers=h)).json()['prompts'][0]
    assert prompt['state']=='CANCELLED'
    assert (await client.post('/v4/patient/prompts/'+pid+'/seen',headers=h)).status_code==409
