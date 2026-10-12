"""Synthetic operational test matrix. Not a validation of clinical safety/performance."""
import time
from datetime import datetime,timezone,timedelta
import jwt, httpx, pytest
from app.main import create_app
from test_system import (FakeModel,NORMAL,settings,client,intake,process,clinician_header,
                         patient_header,internal_header,claim_case_review)


def staff(settings,sub):
    t=jwt.encode({'iss':'hah-course-demo','sub':sub,'role':'clinician',
                  'exp':int(time.time())+3600},settings.jwt_secret,algorithm='HS256')
    return {'Authorization':'Bearer '+t}

async def register_shift(c,s,sub='staff-B'):
    now=datetime.now(timezone.utc)
    r=await c.post('/v3/shifts',json={'patient_ref':'DEMO-P001',
        'starts_at':(now-timedelta(minutes=1)).isoformat(),
        'ends_at':(now+timedelta(hours=3)).isoformat()},headers=staff(s,sub))
    assert r.status_code==201,r.text
    return r.json()['shift_id']

async def setup_review(c,s):
    await intake(c,s);await process(c,s,'HHC-CASE-0001')
    await claim_case_review(c,s,'HHC-CASE-0001')
    tasks=(await c.get('/v2/tasks',headers=clinician_header(s))).json()['tasks']
    return next(x for x in tasks if x['kind']=='clinical_review')

@pytest.mark.asyncio
async def test_transfer_requires_acceptance_and_case_decision_new_owner(client,settings):
    t=await setup_review(client,settings)
    await register_shift(client,settings)
    old=await client.post('/v3/tasks/'+t['task_id']+'/handoff',json={
        'to_clinician_sub':'staff-B','reason':'Synthetic shift change and human oversight'},headers=clinician_header(settings))
    assert old.status_code==201,old.text
    hid=old.json()['handoff_id']
    assert old.json()['original_owner_retained'] is True
    assert (await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks'][0]['assigned_to']=='test-clinician'
    assert (await client.post('/v3/handoffs/'+hid+'/accept',headers=clinician_header(settings))).status_code==409
    inbox=(await client.get('/v3/handoffs/inbox',headers=staff(settings,'staff-B'))).json()['handoffs']
    assert inbox[0]['handoff_id']==hid
    ack=await client.post('/v3/handoffs/'+hid+'/accept',headers=staff(settings,'staff-B'))
    assert ack.status_code==200,ack.text
    assert ack.json()['assigned_to']=='staff-B'
    assert (await client.post('/v3/handoffs/'+hid+'/accept',headers=staff(settings,'staff-B'))).status_code==409
    case=(await client.get('/v1/cases/HHC-CASE-0001',headers=clinician_header(settings))).json()
    dec={'case_id':'HHC-CASE-0001','choice':'reject',
         'comment':'Reviewed the original synthetic source and uncertainties',
         'expected_version':case['version']}
    assert (await client.post('/v1/decisions',json=dec,headers=clinician_header(settings))).status_code==409
    assert (await client.post('/v1/decisions',json=dec,headers=staff(settings,'staff-B'))).status_code==200
    events=(await client.get('/v3/patients/DEMO-P001/timeline',headers=staff(settings,'staff-B'))).json()['events']
    assert {'HANDOFF_OFFERED','HANDOFF_ACCEPTED','CASE_DECISION'} <= {e['event_code'] for e in events}

@pytest.mark.asyncio
async def test_handoff_without_active_shift_blocked(client,settings):
    t=await setup_review(client,settings)
    r=await client.post('/v3/tasks/'+t['task_id']+'/handoff',json={
        'to_clinician_sub':'staff-B','reason':'A deliberate unauthorized demo handoff'},headers=clinician_header(settings))
    assert r.status_code==409 and 'TARGET_NOT_ON_SHIFT' in r.text
    assert (await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks'][0]['assigned_to']=='test-clinician'

@pytest.mark.asyncio
async def test_handoff_reject_and_expiry_preserve_owner(client,settings):
    t=await setup_review(client,settings);await register_shift(client,settings)
    url='/v3/tasks/'+t['task_id']+'/handoff';payload={'to_clinician_sub':'staff-B','reason':'Continuity of care requires manual review'}
    first=(await client.post(url,json=payload,headers=clinician_header(settings))).json()['handoff_id']
    assert (await client.post(url,json=payload,headers=clinician_header(settings))).status_code==409
    assert (await client.post('/v3/handoffs/'+first+'/reject',headers=staff(settings,'staff-B'))).status_code==200
    second=(await client.post(url,json=payload,headers=clinician_header(settings))).json()['handoff_id']
    ops=client._transport.app.state.operations
    with ops.s._lock:ops.s.db.execute('UPDATE task_handoffs SET expires_at=? WHERE handoff_id=?',(time.time()-1,second))
    assert (await client.post('/v3/handoffs/'+second+'/accept',headers=staff(settings,'staff-B'))).status_code==409
    assert (await client.post('/internal/ops/handoff-watch',headers=internal_header(settings))).json()['count']==1
    assert (await client.post('/internal/ops/handoff-watch',headers=internal_header(settings))).json()['count']==0
    assert ops.c.get_task(t['task_id'])['assigned_to']=='test-clinician'

@pytest.mark.asyncio
async def test_shift_cancel_disallows_accept_and_no_auto_unassign(client,settings):
    t=await setup_review(client,settings)
    shift=await register_shift(client,settings)
    h=(await client.post('/v3/tasks/'+t['task_id']+'/handoff',json={
        'to_clinician_sub':'staff-B','reason':'Synthetic outgoing duty shift change'},headers=clinician_header(settings))).json()['handoff_id']
    assert (await client.post('/v3/shifts/'+shift+'/cancel',headers=clinician_header(settings))).status_code==409
    assert (await client.post('/v3/shifts/'+shift+'/cancel',headers=staff(settings,'staff-B'))).status_code==200
    assert (await client.post('/v3/handoffs/'+h+'/accept',headers=staff(settings,'staff-B'))).status_code==409
    assert (await client.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks'][0]['assigned_to']=='test-clinician'

@pytest.mark.asyncio
async def test_scope_and_no_reasons_in_timeline(client,settings):
    t=await setup_review(client,settings);await register_shift(client,settings)
    sensitive='Synthetic private reason written only to encrypted DB'
    r=await client.post('/v3/tasks/'+t['task_id']+'/handoff',json={
        'to_clinician_sub':'staff-B','reason':sensitive},headers=clinician_header(settings))
    assert r.status_code==201
    db=client._transport.app.state.store.db
    row=db.execute('SELECT reason_cipher FROM task_handoffs').fetchone()
    assert sensitive not in row['reason_cipher']
    denied=(await client.get('/v3/patients/DEMO-OTHER/timeline',headers=patient_header(settings)))
    assert denied.status_code==403
    timeline=(await client.get('/v3/patients/DEMO-P001/timeline',headers=clinician_header(settings))).text
    assert sensitive not in timeline
    assert (await client.get('/v3/handoffs/inbox',headers=patient_header(settings))).status_code==403

@pytest.mark.asyncio
async def test_queue_failure_bounded_retry_dead_letter(settings):
    async def fail_dispatch(payload):raise ConnectionError('simulated no orchestration')
    app=create_app(settings,model=FakeModel(),dispatch=fail_dispatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        await intake(c,settings)
        q=app.state.dispatch_queue
        assert q.counts()['PENDING']==1
        for n in range(4):
            with app.state.store._lock:app.state.store.db.execute("UPDATE dispatch_jobs SET next_run_at=? WHERE status='PENDING'",(time.time()-1,))
            r=await c.post('/internal/ops/dispatch-drain',headers=internal_header(settings))
            assert r.status_code==200,r.text
        assert q.counts()['DEAD']==1
        assert (await c.post('/internal/ops/dispatch-drain',headers=internal_header(settings))).json()['failed_jobs']==[]
        tasks=(await c.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks']
        assert any(t['reason_code']=='DISPATCH_DEAD_LETTER' for t in tasks)
        assert (await c.get('/v3/ops/dispatch-jobs',headers=patient_header(settings))).status_code==403
        assert app.state.store.verify_audit()

@pytest.mark.asyncio
async def test_webhook_ack_does_not_equal_processing(settings):
    sent=[]
    async def accept(payload):sent.append(payload)
    app=create_app(settings,model=FakeModel(),dispatch=accept)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        await intake(c,settings)
        assert app.state.dispatch_queue.counts()['DELIVERED']==1
        with app.state.store._lock:app.state.store.db.execute('UPDATE dispatch_jobs SET updated_at=?',(time.time()-700,))
        r=await c.post('/internal/ops/dispatch-drain',headers=internal_header(settings))
        assert r.status_code==200,r.text
        assert r.json()['rearmed_count']==1
        assert len(sent)==2 and sent==[{'case_id':'HHC-CASE-0001'}]*2
        assert app.state.dispatch_queue.counts()['DELIVERED']==1

@pytest.mark.asyncio
async def test_traced_task_resolution(client,settings):
    coord=client._transport.app.state.coordination
    tid=coord.new_task('v23:tracking',None,'DEMO-P001','escalation_followup','review','FOLLOW_UP_TEST',300)
    assert (await client.post('/v2/tasks/'+tid+'/claim',headers=clinician_header(settings))).status_code==200
    r=await client.post('/v2/tasks/'+tid+'/resolve',json={'outcome':'demo_documented',
        'note':'Synthetic safe follow up documented by simulated clinician'},headers=clinician_header(settings))
    assert r.status_code==200
    timeline=(await client.get('/v3/patients/DEMO-P001/timeline',headers=clinician_header(settings))).json()['events']
    assert {'TASK_CLAIMED','TASK_RESOLVED'} <= {e['event_code'] for e in timeline}

@pytest.mark.asyncio
async def test_exhausted_expired_lease_creates_visible_manual_task(settings):
    async def offline(payload):raise ConnectionError('synthetic network outage')
    app=create_app(settings,model=FakeModel(),dispatch=offline)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        await intake(c,settings)
        store=app.state.store
        with store._lock:
            store.db.execute('''UPDATE dispatch_jobs SET status='LEASED',attempts=4,lease_until=?''',
              (time.time()-1,))
        r=await c.post('/internal/ops/dispatch-drain',headers=internal_header(settings))
        assert r.status_code==200 and r.json()['expired_lease_count']==1
        assert app.state.dispatch_queue.counts()['DEAD']==1
        tasks=(await c.get('/v2/tasks',headers=clinician_header(settings))).json()['tasks']
        assert any(x['reason_code']=='DISPATCH_DEAD_LETTER' for x in tasks)
        assert (await c.post('/internal/ops/dispatch-health',headers=internal_header(settings))).status_code==503

@pytest.mark.asyncio
async def test_case_decision_rolls_back_if_timeline_fails(client,settings,monkeypatch):
    await setup_review(client,settings)
    app=client._transport.app
    case=app.state.store.get('HHC-CASE-0001')
    def fail(*args,**kwargs):raise RuntimeError('simulate timeline write failure')
    monkeypatch.setattr(app.state.operations,'record',fail)
    with pytest.raises(RuntimeError):
        await client.post('/v1/decisions',json={'case_id':'HHC-CASE-0001','choice':'reject',
            'comment':'Reviewed all original facts in synthetic case',
            'expected_version':case['version']},headers=clinician_header(settings))
    after=app.state.store.get('HHC-CASE-0001')
    assert after['status']==case['status'] and after['version']==case['version']
    assert app.state.coordination.task_for_case('HHC-CASE-0001')['status']=='ACKNOWLEDGED'
    assert app.state.store.verify_audit()
