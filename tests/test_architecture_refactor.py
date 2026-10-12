"""Regression contract for the first Clean Architecture migration slice."""
import json
from pathlib import Path
import copy
import pytest
from fastapi import HTTPException
from app.application.access_control import AccessControl
from app.application.case_queries import CaseQueries
from app.application.engagement_use_cases import EngagementUseCases
from app.domain.patient_scope import PatientScopeDenied, assert_patient_access
from app.infrastructure.persistence.sql_store import Store as CanonicalStore
from app.store import Store as LegacyStore
from app.infrastructure.persistence.postgres_compat import PostgresCompat as CanonicalPg
from app.postgres_compat import PostgresCompat as LegacyPg
from app.main import create_app
from test_system import FakeModel, patient_header, clinician_header, internal_header, NORMAL, client, settings

ROOT=Path(__file__).resolve().parents[1]


def test_legacy_imports_are_compatibility_shims():
    assert LegacyStore is CanonicalStore
    assert LegacyPg is CanonicalPg


def test_domains_do_not_accept_claim_injected_patient_access():
    ref='DEMO-P001'
    with pytest.raises(PatientScopeDenied):
        assert_patient_access({'sub':'x','role':'clinician','patient_refs':[ref]},ref,oidc=True,assigned=False)
    with pytest.raises(PatientScopeDenied):
        assert_patient_access({'sub':'x','role':'patient','patient_ref':'DEMO-P002'},ref,oidc=True,assigned=False)
    with pytest.raises(PatientScopeDenied):
        assert_patient_access({'sub':'x','role':'patient','patient_ref':ref},'REAL-P123',oidc=False,assigned=False)
    with pytest.raises(PatientScopeDenied):
        assert_patient_access({'sub':'x','role':'anonymous'},ref,oidc=False,assigned=True)
    assert_patient_access({'sub':'x','role':'clinician'},ref,oidc=True,assigned=True) is None


def test_access_control_rechecks_oidc_assignments_each_time():
    class Assignments:
        calls=0
        active=False
        def is_assigned(self,sub,ref):
            self.calls+=1
            return self.active
        def assignments(self,sub):return {'DEMO-P001'} if self.active else set()
    db=Assignments()
    access=AccessControl(db,'oidc')
    claim={'sub':'dr-x','role':'clinician','patient_refs':['DEMO-P001']}
    with pytest.raises(PatientScopeDenied):access.require(claim,'DEMO-P001')
    db.active=True
    access.require(claim,'DEMO-P001')
    db.active=False
    with pytest.raises(PatientScopeDenied):access.require(claim,'DEMO-P001')
    assert db.calls==3


def test_baseline_http_contract_paths_and_methods_unchanged(settings):
    app=create_app(settings,model=FakeModel(),dispatch=lambda payload:None)
    current=[]
    for route in app.routes:
        if not hasattr(route,'methods'):continue
        for method in sorted(route.methods):
            if method in ('GET','POST','PUT','DELETE','PATCH') and route.path not in ('/openapi.json','/docs','/docs/oauth2-redirect','/redoc'):
                current.append(method+' '+route.path)
    expected=json.loads((ROOT/'docs/API_CONTRACT_3_0.json').read_text())['routes']
    assert sorted(current)==expected
    assert len(current)==len(set(current)), 'Ambiguous duplicate HTTP routes are forbidden'


@pytest.mark.asyncio
async def test_extracted_case_query_and_v4_engagement_auth_stays_strict(client,settings):
    patient=patient_header(settings)
    clinician=clinician_header(settings)
    r=await client.get('/v1/cases',headers=patient)
    assert r.status_code==403
    r=await client.get('/v4/clinician/alert-groups',headers=patient)
    assert r.status_code==403
    r=await client.get('/v4/patient/dashboard',headers=clinician)
    assert r.status_code==403
    r=await client.get('/v4/patient/dashboard?days=999',headers=patient)
    assert r.status_code==422
    r=await client.get('/v4/patient/preferences',headers=patient)
    assert r.status_code==200 and r.json()['reminder_opt_in'] is False
    r=await client.get('/v3/fhir/Observation?patient_ref=DEMO-P002',headers=clinician)
    assert r.status_code==200  # Demo clinicians retain demo-mode compatibility.


@pytest.mark.asyncio
async def test_fhir_synthetic_wrapper_and_internal_auth_on_refactor(client,settings):
    headers=clinician_header(settings)
    r=await client.post('/v3/fhir/import',headers=headers,json={'patient_ref':'DEMO-P001','is_synthetic':False,'bundle':{}})
    assert r.status_code==422
    r=await client.post('/internal/fhir/sandbox-sync',json={})
    assert r.status_code==401
    r=await client.post('/internal/engagement/watch',json={})
    assert r.status_code==401


def test_case_queries_redact_without_editing_persisted_case(settings):
    store=CanonicalStore(settings)
    payload=copy.deepcopy(NORMAL)
    store.create(payload['case_id'],payload['patient_ref'],payload)
    cq=CaseQueries(store)
    retrieved=cq.details(payload['case_id'])
    assert retrieved['payload']['meal_image_data_url'] is None
    assert store.get(payload['case_id'])['payload']['meal_image_data_url']==payload['meal_image_data_url']
