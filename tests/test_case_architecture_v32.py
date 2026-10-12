"""Behavioral parity and fail-closed boundaries for migrated case use cases."""
import json
import time
import pytest
from test_system import NORMAL, REDFLAG, intake, internal_header, patient_header, clinician_header, FakeModel, client, settings
from app.domain.workflow_rules import WorkflowError, approval_evidence, reviewable, urgent_reported
from app.application.clinical_cases import ClinicalCases
from app.application.agent_execution import AgentExecution
from app.application.dispatch_operations import DispatchOperations
from app.infrastructure.persistence.checkin_reader import SqlCheckinReader


def test_pure_domain_validation_has_no_web_framework_dependency():
    assert urgent_reported(REDFLAG['symptoms'])
    assert not urgent_reported(NORMAL['symptoms'])
    with pytest.raises(WorkflowError) as err:
        reviewable({'status':'PROCESSING'},'approve')
    assert err.value.kind=='conflict'


async def test_finalize_task_failure_rolls_back_policy_and_enters_review(client,settings,monkeypatch):
    await intake(client,settings)
    internal=internal_header(settings)
    case_id=NORMAL['case_id']
    app=client._transport.app
    assert (await client.post('/internal/start',json={'case_id':case_id},headers=internal)).status_code==200
    for _ in range(5):
        plan=(await client.post('/internal/plan',json={'case_id':case_id},headers=internal)).json()
        if plan['done']:break
        assert (await client.post('/internal/tool',json={'case_id':case_id,'tool':plan['next_tool']},headers=internal)).status_code==200
    saved_before=app.state.store.get(case_id)['version']
    original=app.state.coordination.new_task
    first=[True]
    def fail_once(*args,**kwargs):
        if first[0]:
            first[0]=False
            raise RuntimeError('INJECTED_TASK_WRITE_FAILURE')
        return original(*args,**kwargs)
    monkeypatch.setattr(app.state.coordination,'new_task',fail_once)
    r=await client.post('/internal/finalize',json={'case_id':case_id},headers=internal)
    assert r.status_code==503
    after=app.state.store.get(case_id)
    assert after['status']=='TECHNICAL_REVIEW'
    assert after['version']==saved_before+1  # fail-close only; finalized save rolled back
    assert not any(e['event']=='POLICY_FINALIZED' for e in app.state.store.audit_events(case_id))
    assert app.state.coordination.task_for_case(case_id)['kind']=='clinical_review'
    assert app.state.store.verify_audit()


async def test_urgent_intake_rolls_back_if_care_task_creation_fails(client,settings,monkeypatch):
    app=client._transport.app
    def fail(*args,**kwargs):raise RuntimeError('INJECTED_TASK_FAILURE')
    monkeypatch.setattr(app.state.coordination,'new_task',fail)
    with pytest.raises(RuntimeError,match='INJECTED_TASK_FAILURE'):
        await client.post('/v1/intake',json=REDFLAG,headers=patient_header(settings))
    with pytest.raises(KeyError):app.state.store.get(REDFLAG['case_id'])
    assert app.state.dispatch_queue.counts().get('PENDING',0)==0
    assert app.state.store.verify_audit()


async def test_planner_failure_creates_explicit_human_review(client,settings,monkeypatch):
    await intake(client,settings)
    app=client._transport.app
    internal=internal_header(settings)
    ref={'case_id':NORMAL['case_id']}
    assert (await client.post('/internal/start',json=ref,headers=internal)).status_code==200
    def fail(*args,**kwargs):raise RuntimeError('MODEL_TEMPORARILY_UNAVAILABLE')
    monkeypatch.setattr(app.state.model,'structured',fail)
    assert (await client.post('/internal/plan',json=ref,headers=internal)).status_code==503
    assert app.state.store.get(ref['case_id'])['status']=='TECHNICAL_REVIEW'
    task=app.state.coordination.task_for_case(ref['case_id'])
    assert task['status'] in ('OPEN','ACKNOWLEDGED')
    assert task['kind']=='clinical_review'


async def test_watchdog_escalates_and_creates_review_task(client,settings):
    await intake(client,settings)
    app=client._transport.app
    # No n8n run: simulate stale workflow and require a real durable review task.
    with app.state.store.transaction():
        app.state.store.db.execute('UPDATE cases SET updated_at=? WHERE case_id=?',
            (time.time()-7200,NORMAL['case_id']))
    r=await client.post('/internal/watchdog',headers=internal_header(settings))
    assert r.status_code==200 and r.json()['count']==1
    assert app.state.store.get(NORMAL['case_id'])['status']=='ESCALATION_REQUIRED'
    assert app.state.coordination.task_for_case(NORMAL['case_id'])['kind']=='clinical_review'
    assert (await client.post('/internal/watchdog',headers=internal_header(settings))).json()['count']==0


def test_sql_checkin_adapter_reads_only_needed_status(client):
    app=client._transport.app
    reader=SqlCheckinReader(app.state.store)
    assert reader.checkin_status('CHK-UNKNOWN000') is None


def test_migrated_application_layers_have_no_http_or_raw_sql():
    from pathlib import Path
    app_root=Path(__file__).resolve().parents[1]/'backend'/'app'
    for path in (app_root/'application').glob('*.py'):
        body=path.read_text()
        for forbidden in ('import fastapi','from fastapi','import httpx',"execute('SELECT",'sqlite3.connect('):
            assert forbidden not in body,(path.name,forbidden)
    assert 'APIRouter' not in (app_root/'legacy_api.py').read_text()

def test_frozen_v31_http_contract():
    from pathlib import Path
    import json
    root=Path(__file__).resolve().parents[1]
    from app.main import create_app
    app=create_app()
    routes=sorted(set((next(iter(r.methods)),r.path) for r in app.routes
                      if hasattr(r,'methods') and r.path not in
                      ('/openapi.json','/docs','/docs/oauth2-redirect','/redoc')))
    expected=json.loads((root/'contracts/api_routes_v3_1.json').read_text())
    assert len(routes)==len(expected)==59
    assert [list(r) for r in routes]==expected
