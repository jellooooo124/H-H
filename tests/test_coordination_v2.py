import copy, json, time
from datetime import datetime, timezone, timedelta
import jwt, httpx, pytest
from test_system import (NORMAL,REDFLAG,client,settings,intake,process,internal_header,patient_header,
                         clinician_header,claim_case_review,ROOT)

async def new_obs(c,s,id='OBS-SAMPLE-0001',value=70.0,code='weight_kg',unit='kg',when=None):
    return await c.post('/v2/observations',json={
      'event_id':id,'patient_ref':'DEMO-P001','is_synthetic':True,
      'code':code,'value':value,'unit':unit,
      'taken_at':when or datetime.now(timezone.utc).isoformat()},headers=patient_header(s))

@pytest.mark.asyncio
async def test_observations_encrypted_trends_and_idempotent(client,settings):
    t=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    assert (await new_obs(client,settings,'OBS-WEIGHT-0001',70,t and 'weight_kg', 'kg', t)).status_code==201
    assert (await new_obs(client,settings,'OBS-WEIGHT-0002',72,when=datetime.now(timezone.utc).isoformat())).status_code==201
    t2=(await client.get('/v2/patients/DEMO-P001/trends',headers=patient_header(settings))).json()
    assert t2['measurements']['weight_kg']['delta']==2
    assert (await new_obs(client,settings,'OBS-WEIGHT-0002',72)).status_code==409
    assert (await new_obs(client,settings,'OBS-BADUNIT-0001',72,unit='lb')).status_code==422
    raw=client._transport.app.state.store.db.execute('SELECT payload_cipher FROM observations LIMIT 1').fetchone()['payload_cipher']
    assert '70.0' not in raw and 'taken_at' not in raw

@pytest.mark.asyncio
async def test_patient_scoping_and_rejection(client,settings):
    bad={'event_id':'CHK-TEST-000111','patient_ref':'DEMO-OTHER','is_synthetic':True,'symptoms':{}}
    assert (await client.post('/v2/checkins',json=bad,headers=patient_header(settings))).status_code==403
    assert (await client.get('/v2/patients/DEMO-OTHER/trends',headers=patient_header(settings))).status_code==403
    assert (await client.post('/v2/observations',json={'event_id':'OBS-TEST-000111','patient_ref':'DEMO-OTHER','is_synthetic':True,'code':'weight_kg','value':70,'unit':'kg','taken_at':datetime.now(timezone.utc).isoformat()},headers=patient_header(settings))).status_code==403
    assert (await client.post('/v2/monitoring-plans',json={'patient_ref':'DEMO-P001','observation_code':'weight_kg','review_gap_hours':3},headers=patient_header(settings))).status_code==403

@pytest.mark.asyncio
async def test_urgent_checkin_offline_reconciles_and_creates_task(client,settings):
    p={'event_id':'CHK-URGENT-0001','patient_ref':'DEMO-P001','is_synthetic':True,
       'symptoms':{'severe_breathlessness':True,'notes':'Synthetic patient urgent symptom'},'device_problem':True}
    # Dispatcher will not reach n8n in offline tests; pending is reconciled by watchdog.
    r=await client.post('/v2/checkins',json=p,headers=patient_header(settings))
    # Urgent check-in is routed immediately, independent from n8n.
    assert r.status_code==202 and r.json()['status']=='TRIAGED'
    j=(await client.post('/internal/coordination/watch',headers=internal_header(settings))).json()
    assert p['event_id'] not in j['reconciled_checkins']
    tasks=(await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks']
    assert any(t['kind']=='reported_symptom_review' and t['priority']=='urgent' for t in tasks)
    again=(await client.post('/internal/checkin/triage',json={'event_id':p['event_id']},headers=internal_header(settings))).json()
    assert again['idempotent'] is True
    assert len((await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks'])==1

@pytest.mark.asyncio
async def test_unclaimed_reviewer_cannot_approve(client,settings):
    await intake(client,settings)
    await process(client,settings,'HHC-CASE-0001')
    details=(await client.get('/v1/cases/HHC-CASE-0001',headers=clinician_header(settings))).json()
    d={'case_id':'HHC-CASE-0001','choice':'approve','comment':'Try to bypass the task ownership gate','expected_version':details['version']}
    assert (await client.post('/v1/decisions',json=d,headers=clinician_header(settings))).status_code==409
    await claim_case_review(client,settings,'HHC-CASE-0001')
    assert (await client.post('/v1/decisions',json=d,headers=clinician_header(settings))).status_code==200
    tasks=(await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks']
    assert next(t for t in tasks if t['kind']=='clinical_review')['status']=='COMPLETED'

@pytest.mark.asyncio
async def test_double_claim_other_clinician_blocked(client,settings):
    await intake(client,settings);await process(client,settings,'HHC-CASE-0001')
    task=next(t for t in (await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks'] if t['kind']=='clinical_review')
    assert (await client.post('/v2/tasks/'+task['task_id']+'/claim',headers=clinician_header(settings))).status_code==200
    other=jwt.encode({'iss':'hah-course-demo','sub':'clinician-B','role':'clinician','exp':int(time.time())+1000},settings.jwt_secret,algorithm='HS256')
    assert (await client.post('/v2/tasks/'+task['task_id']+'/claim',headers={'Authorization':'Bearer '+other})).status_code==409

@pytest.mark.asyncio
async def test_escalation_creates_separate_followup_not_auto_closed(client,settings):
    await intake(client,settings,REDFLAG);await process(client,settings,'HHC-CASE-0002')
    await claim_case_review(client,settings,'HHC-CASE-0002')
    details=(await client.get('/v1/cases/HHC-CASE-0002',headers=clinician_header(settings))).json()
    d={'case_id':'HHC-CASE-0002','choice':'escalate','comment':'Critical symptom requires human followup and traceability','expected_version':details['version']}
    r=await client.post('/v1/decisions',json=d,headers=clinician_header(settings))
    assert r.status_code==200
    tasks=(await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks']
    assert any(t['kind']=='clinical_review' and t['status']=='COMPLETED' for t in tasks)
    follow=next(t for t in tasks if t['kind']=='escalation_followup')
    assert follow['status']=='OPEN'
    claim=await client.post('/v2/tasks/'+follow['task_id']+'/claim',headers=clinician_header(settings))
    assert claim.status_code==200
    bad=await client.post('/v2/tasks/'+follow['task_id']+'/resolve',headers=clinician_header(settings),json={'outcome':'unable_to_reach','note':'No one answered this synthetic followup attempt'})
    assert bad.status_code==200 and bad.json()['status']=='OPEN'
    await client.post('/v2/tasks/'+follow['task_id']+'/claim',headers=clinician_header(settings))
    good=await client.post('/v2/tasks/'+follow['task_id']+'/resolve',headers=clinician_header(settings),json={'outcome':'handoff_documented','note':'Synthetic handoff to on-call team documented'})
    assert good.status_code==200 and good.json()['status']=='COMPLETED'

@pytest.mark.asyncio
async def test_missing_reading_generates_only_one_task_per_day(client,settings):
    h=clinician_header(settings)
    assert (await client.post('/v2/monitoring-plans',json={'patient_ref':'DEMO-P001','observation_code':'weight_kg','review_gap_hours':2},headers=h)).status_code==200
    coordinator=client._transport.app.state.coordination
    with coordinator.s._lock:
        coordinator.s.db.execute('UPDATE monitoring_plans SET updated_at=? WHERE patient_ref=?',(time.time()-3*3600,'DEMO-P001'))
    j=(await client.post('/internal/coordination/watch',headers=internal_header(settings))).json()
    assert len(j['missing_data_task_ids'])==1
    j=(await client.post('/internal/coordination/watch',headers=internal_header(settings))).json()
    assert len(j['missing_data_task_ids'])==1
    tasks=(await client.get('/v2/tasks',headers=h)).json()['tasks']
    assert len(tasks)==1 and tasks[0]['kind']=='missing_measurement_review'

@pytest.mark.asyncio
async def test_task_sla_once_and_audit_integrity(client,settings):
    coord=client._transport.app.state.coordination
    tid=coord.new_task('test-sla-key',None,'DEMO-P001','missing_measurement_review','review','TEST_SLA',3)
    with coord.s._lock:coord.s.db.execute('UPDATE care_tasks SET due_at=? WHERE task_id=?',(time.time()-10,tid))
    j=(await client.post('/internal/coordination/watch',headers=internal_header(settings))).json()
    assert tid in j['newly_overdue_task_ids']
    j=(await client.post('/internal/coordination/watch',headers=internal_header(settings))).json()
    assert tid not in j['newly_overdue_task_ids']
    assert coord.get_task(tid)['status']=='OVERDUE'
    assert coord.s.verify_audit() is True

@pytest.mark.asyncio
async def test_simulated_receipt_not_real_delivery(client,settings):
    await intake(client,settings);await process(client,settings,'HHC-CASE-0001')
    await claim_case_review(client,settings,'HHC-CASE-0001')
    c=(await client.get('/v1/cases/HHC-CASE-0001',headers=clinician_header(settings))).json()
    await client.post('/v1/decisions',headers=clinician_header(settings),json={'case_id':c['case_id'],'expected_version':c['version'],'choice':'approve','comment':'Reviewed synthetic clinical data and confirmed safe gate'})
    body={'case_id':'HHC-CASE-0001','patient_ref':'DEMO-P001'}
    r=await client.post('/v2/patient/receipt',headers=patient_header(settings),json=body)
    assert r.status_code==200 and r.json()['message_delivered'] is False
    assert (await client.post('/v2/patient/receipt',headers=patient_header(settings),json=body)).status_code==409

@pytest.mark.asyncio
async def test_metrics_aggregated_and_no_patient_token_access(client,settings):
    assert (await client.get('/v2/metrics',headers=patient_header(settings))).status_code==403
    m=(await client.get('/v2/metrics',headers=clinician_header(settings))).json()
    assert m['no_clinical_performance_claim'] is True
    assert 'patient_ref' not in str(m)

@pytest.mark.asyncio
async def test_routine_checkin_event_reconciles_after_n8n_outage(client,settings):
    body={'event_id':'CHK-NORMAL-0001','patient_ref':'DEMO-P001','is_synthetic':True,'symptoms':{},'patient_note':'Synthetic check-in'}
    r=await client.post('/v2/checkins',json=body,headers=patient_header(settings))
    assert r.status_code==202 and r.json()['status']=='PENDING'
    out=(await client.post('/internal/coordination/watch',headers=internal_header(settings))).json()
    assert body['event_id'] in out['reconciled_checkins']
    assert (await client.post('/v2/checkins',json=body,headers=patient_header(settings))).status_code==409

@pytest.mark.asyncio
async def test_overdue_claimed_followup_still_resolvable(client,settings):
    coord=client._transport.app.state.coordination
    tid=coord.new_task('test-overdue-assigned',None,'DEMO-P001','missing_measurement_review','review','SLA',60)
    await client.post('/v2/tasks/'+tid+'/claim',headers=clinician_header(settings))
    with coord.s._lock:coord.s.db.execute('UPDATE care_tasks SET due_at=? WHERE task_id=?',(time.time()-20,tid))
    await client.post('/internal/coordination/watch',headers=internal_header(settings))
    assert coord.get_task(tid)['status']=='OVERDUE'
    r=await client.post('/v2/tasks/'+tid+'/resolve',json={'outcome':'demo_documented','note':'Synthetic resolution even after overdue'},headers=clinician_header(settings))
    assert r.status_code==200,r.text

@pytest.mark.asyncio
async def test_reconciler_restores_lost_review_task_and_technical_review(client,settings):
    await intake(client,settings)
    await process(client,settings,'HHC-CASE-0001')
    coord=client._transport.app.state.coordination
    with coord.s._lock:coord.s.db.execute('DELETE FROM care_tasks WHERE source_key=?',('review:HHC-CASE-0001',))
    j=(await client.post('/internal/coordination/watch',headers=internal_header(settings))).json()
    assert len(j['recovered_review_task_ids'])==1
    assert coord.task_for_case('HHC-CASE-0001')['status']=='OPEN'
    # Reconciler is idempotent; do not generate another task on second run.
    j=(await client.post('/internal/coordination/watch',headers=internal_header(settings))).json()
    assert j['recovered_review_task_ids']==[]

@pytest.mark.asyncio
async def test_urgent_case_pretriage_without_model_or_n8n(client,settings):
    await intake(client,settings,REDFLAG)
    tasks=(await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks']
    assert any(t['kind']=='reported_symptom_review' and t['case_id']=='HHC-CASE-0002' and t['priority']=='urgent' for t in tasks)
    assert (await client.get('/v1/cases/HHC-CASE-0002',headers=clinician_header(settings))).json()['status']=='RECEIVED'
