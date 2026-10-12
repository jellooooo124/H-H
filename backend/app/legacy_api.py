"""Legacy 2.4 HTTP adapter (retained for backward-compatible n8n API contracts).

New features live behind the communications domain/application/infrastructure/API boundary.
This compatibility module will be split into bounded routers in future refactors.
"""
import hmac, json, logging, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Body, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx, jwt
from .config import Settings
from .schemas import Intake, Decision, ObservationIn, CheckinIn, MonitoringPlanIn, TaskResolveIn, ReceiptIn
from .store import Store
from .rag import Rag
from .agents import LLMClient, TOOLS, plan_next, run_agent, synthesize
from .policy import assess
from .coordination import Coordinator
from .fhir_bridge import FHIRBridge, FHIRConflict, PATIENT_REF
from .identity import TokenVerifier
from .operations23 import ShiftHandoff, QueueJob, ShiftIn, HandoffIn
from .engagement24 import Engagement
from .communications.service import CommunicationService
from .communications.api import build_router

log=logging.getLogger('hah')
logging.basicConfig(level=logging.WARNING)

class AssignmentIn(BaseModel):
    clinician_sub: str
    patient_ref: str
    active: bool = True

class CaseRef(BaseModel):
    case_id: str

class ExecuteTool(CaseRef):
    tool: str

class PatientPreferenceIn(BaseModel):
    reminder_opt_in: bool = False
    reminder_hour_utc: int = Field(ge=0,le=23)
    minimum_gap_hours: int = Field(ge=24,le=168)

class ErrorNotice(BaseModel):
    workflow_name: str = 'n8n'
    error_code: str = 'EXECUTION_FAILED'


def create_app(settings=None, model=None, store=None, dispatch=None, checkin_dispatch=None):
    settings=settings or Settings.from_env()
    settings.validate()
    store=store or Store(settings)
    model=model or LLMClient(settings)
    rag=Rag(store,model,settings.knowledge_dir)
    coordination=Coordinator(store)
    fhir_bridge=FHIRBridge(store,coordination)
    verifier=TokenVerifier(settings)
    operations=ShiftHandoff(store,coordination)
    dispatch_queue=QueueJob(store)
    engagement=Engagement(store,coordination)
    communications=CommunicationService(store,coordination)
    app=FastAPI(title='Hospital-at-Home Care Coordination (Synthetic Research Platform)',version='3.0.0')
    app.state.communications=communications
    app.state.store=store
    app.state.rag=rag
    app.state.model=model
    app.state.coordination=coordination
    app.state.fhir_bridge=fhir_bridge
    app.state.verifier=verifier
    app.state.operations=operations
    app.state.dispatch_queue=dispatch_queue
    app.state.engagement=engagement
    # CORS must be explicitly set if a frontend runs on another origin; default same origin/Swagger.

    def internal(x_internal_key: str | None=Header(default=None)):
        if not x_internal_key or not hmac.compare_digest(x_internal_key,settings.internal_key):
            raise HTTPException(status_code=401,detail='Internal authorization required')
        return True

    def auth(authorization: str | None=Header(default=None)):
        return verifier.verify(authorization)

    def access(claim,patient_ref):
        if not isinstance(patient_ref,str) or not PATIENT_REF.fullmatch(patient_ref):
            raise HTTPException(403,'Invalid synthetic patient scope')
        if claim['role']=='patient':
            allowed=claim.get('patient_ref')==patient_ref
        elif settings.auth_mode=='oidc':
            # Never use a claim-provided patient_refs list for OIDC clinician authorization.
            allowed=store.is_assigned(claim['sub'],patient_ref)
        else:
            permitted=claim.get('patient_refs')
            allowed=permitted is None or (isinstance(permitted,list) and patient_ref in permitted)
        if not allowed:raise HTTPException(403,'Patient scope not assigned')
        return True

    def allowed_patient_refs(claim):
        return store.assignments(claim['sub']) if settings.auth_mode=='oidc' else None

    def clinician(claim=Depends(auth)):
        if claim['role']!='clinician':raise HTTPException(403,'Clinician only')
        return claim

    def patient(claim=Depends(auth)):
        if claim['role']!='patient':raise HTTPException(403,'Patient only')
        return claim

    def admin(x_admin_key: str | None=Header(default=None)):
        if settings.auth_mode!='oidc' or not x_admin_key or not hmac.compare_digest(x_admin_key,settings.admin_key):
            raise HTTPException(403,'Access administrator permission required')
        return True

    # Assignment is controlled by independent APP_ADMIN_KEY, never the n8n service key.
    @app.post('/admin/assignments')
    def assign(data: AssignmentIn, ok=Depends(admin)):
        if not 1<=len(data.clinician_sub)<=150 or not PATIENT_REF.fullmatch(data.patient_ref):
            raise HTTPException(422,'Invalid synthetic assignment')
        store.set_assignment(data.clinician_sub,data.patient_ref,data.active,'access-admin')
        return {'assignment_updated':True,'active':data.active,'synthetic_only':True}

    def get_case(case_id):
        try: return store.get(case_id)
        except KeyError: raise HTTPException(404,'Case not found')

    def require_processing(c):
        if c['status']!='PROCESSING':raise HTTPException(409,'Case is not processing')

    def fail_closed(case_id,reason):
        c=store.get(case_id)
        if c['status'] in ('RECEIVED','PROCESSING'):
            c['status']='TECHNICAL_REVIEW'
            c['state']['flags']=sorted(set(c['state']['flags']+['INFERENCE_OR_TOOL_FAILURE']))
            store.remove_image(c)
            store.save(c,'FAIL_CLOSED','system',{'reason':reason[:60]})

    @app.get('/health')
    def health():return {'ok':True,'synthetic_only':True,'llm_configured':model.available(), 'db_backend':store.backend,'auth_mode':settings.auth_mode}

    @app.post('/v1/intake',status_code=202)
    async def intake(data: Intake, claim=Depends(patient)):
        access(claim,data.patient_ref)
        try:
            with store.transaction():
                store.create(data.case_id,data.patient_ref,data.model_dump())
                dispatch_queue.enqueue('CASE_DISPATCH',data.case_id)
        except ValueError:raise HTTPException(409,'Case already exists')
        # Synchronous deterministic urgent routing is independent of model / n8n availability.
        # A synthetic task is NOT a clinical page; production on-call operations are absent.
        if any(getattr(data.symptoms,key) for key in ('chest_pain','severe_breathlessness','fainting','confusion')):
            coordination.new_task('urgent-intake:'+data.case_id,data.case_id,data.patient_ref,
              'reported_symptom_review','urgent','REPORTED_URGENT_SYMPTOM',300)
        # Durable DB outbox; webhook contains ONLY opaque ID, and delivery is at-least-once.
        payload={'case_id':data.case_id}
        try:
            if dispatch is not None:
                await dispatch(payload)
            else:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    response=await client.post(settings.webhook_url,json=payload)
                    response.raise_for_status()
            dispatch_queue.delivered('CASE_DISPATCH',data.case_id)
        except Exception:
            # No silent loss: case stays RECEIVED, visible in overdue watcher.
            store.audit(data.case_id,'ORCHESTRATOR_UNAVAILABLE','system',{'retry_needed':True})
        return {'case_id':data.case_id,'status':'RECEIVED','message':'Accepted for educational workflow; no clinical monitoring guarantee'}

    @app.get('/v1/cases')
    def list_cases(claim=Depends(clinician)):
        return store.list_cases(allowed_patient_refs(claim))

    @app.get('/v1/cases/{case_id}')
    def case_details(case_id:str,claim=Depends(clinician)):
        c=get_case(case_id)
        access(claim,c['patient_ref'])
        # Return synthetic data only to a clinician; data URL omitted to limit accidental exposure.
        c['payload']['meal_image_data_url']=None
        return c

    @app.get('/v1/audit/{case_id}')
    def audit(case_id:str,claim=Depends(clinician)):
        access(claim,get_case(case_id)['patient_ref'])
        return {'events':store.audit_events(case_id),'chain_valid':store.verify_audit()}

    @app.get('/v1/outbox')
    def outbox(claim=Depends(clinician)):
        return store.list_outbox(allowed_patient_refs(claim))

    @app.post('/v1/decisions')
    def decision(data:Decision,claim=Depends(clinician)):
        c=get_case(data.case_id)
        access(claim,c['patient_ref'])
        if c['version']!=data.expected_version:raise HTTPException(409,'Stale version; refresh case')
        try:coordination.require_review_claim(data.case_id,claim['sub'])
        except ValueError as e:raise HTTPException(409,str(e))
        if c['status'] not in ('AWAITING_CLINICIAN','ESCALATION_REQUIRED','TECHNICAL_REVIEW'):
            raise HTTPException(409,'Case not reviewable')
        if data.choice=='approve':
            if c['status']!='AWAITING_CLINICIAN':raise HTTPException(409,'Safe-stop: only escalate/reject')
            result=assess(c)  # NEVER trust UI approval alone.
            if result['safe_stop'] or not c['state']['synthesis']:
                raise HTTPException(409,'Policy blocks approval')
            if not set(TOOLS).issubset(set(c['state']['steps'])):
                raise HTTPException(409,'Missing mandatory tool evidence')
            c['status']='APPROVED_SIMULATED'
            # OUTBOX is not an actual send; patient communication does not occur.
        elif data.choice=='reject': c['status']='REJECTED'
        else:c['status']='ESCALATED'
        c['state']['review']={'actor':claim['sub'],'choice':data.choice,'comment':data.comment,'at':time.time()}
        # Case state, task disposition, and handoff timeline must commit atomically.
        with store.transaction():
            c=store.save(c,'CLINICIAN_DECISION',claim['sub'],{'choice':data.choice})
            coordination.complete_review(data.case_id,claim['sub'],data.choice)
            operations.record(c['patient_ref'],coordination.task_for_case(data.case_id)['task_id'],'CASE_DECISION',claim['sub'],{'choice':data.choice})
            if data.choice=='escalate':
                coordination.new_task('followup:'+data.case_id,data.case_id,c['patient_ref'],'escalation_followup','urgent' if c['state'].get('priority')=='urgent' else 'review','CLINICIAN_ESCALATED',900)
            if data.choice=='approve':
                store.outbox_insert(c,c['state']['synthesis']['patient_draft'])
        return {'case_id':c['case_id'],'status':c['status'],'version':c['version'],'sent_to_patient':False}

    @app.post('/internal/start')
    def start(ref:CaseRef,ok=Depends(internal)):
        c=get_case(ref.case_id)
        if c['status']!='RECEIVED':raise HTTPException(409,'Case already started')
        c['status']='PROCESSING'
        c['state']['monitoring_context']=coordination.summary(c['patient_ref'])
        c=store.save(c,'WORKFLOW_STARTED','n8n')
        return {'case_id':c['case_id'],'status':c['status']}

    @app.post('/internal/plan')
    def plan(ref:CaseRef,ok=Depends(internal)):
        c=get_case(ref.case_id);require_processing(c)
        try: recommendation=plan_next(model,c)
        except Exception:
            fail_closed(ref.case_id,'PLANNER_FAILURE')
            raise HTTPException(503,'Planner failed closed')
        if len(c['state']['steps'])>len(TOOLS):
            fail_closed(ref.case_id,'TOOL_LIMIT');raise HTTPException(409,'Step limit exceeded')
        c['state']['plan'].append({'tool':recommendation['next_tool'],'forced':recommendation['forced']})
        c['state']['planned_next']=recommendation['next_tool']
        store.save(c,'PLANNER_DECISION','planner',{'tool':recommendation['next_tool'],'forced':recommendation['forced']})
        return {'case_id':ref.case_id,'next_tool':recommendation['next_tool'],'done':recommendation['next_tool']=='finish'}

    @app.post('/internal/tool')
    def tool(data:ExecuteTool,ok=Depends(internal)):
        c=get_case(data.case_id);require_processing(c)
        if data.tool not in TOOLS or data.tool!=c['state'].get('planned_next'):
            raise HTTPException(403,'Tool is not authorized by latest plan')
        if data.tool in c['state']['steps']:
            raise HTTPException(409,'Duplicate tool execution prevented')
        try:
            if data.tool=='guideline_search':
                v=c['payload']['vitals']; symptoms=c['payload']['symptoms']
                parts=['home monitoring','heart failure','diabetes','clinician review','educational local protocol']
                if not v.get('last_sensor_at'):parts.extend(['sensor missingness','data quality'])
                if symptoms.get('swelling') or symptoms.get('severe_breathlessness'):parts.append('heart failure symptoms and body weight')
                if v.get('glucose_mg_dl') is not None:parts.append('glucose measurement')
                query=' '.join(parts)
                result=rag.retrieve(query)
                if not result:raise RuntimeError('EMPTY_RETRIEVAL')
                c['state']['sources']=result
            else:
                result=run_agent(model,c,data.tool)
                c['state']['agents'][data.tool]=result
                if data.tool=='nutrition':store.remove_image(c)
            c['state']['steps'].append(data.tool)
            c['state']['planned_next']=None
            store.save(c,'TOOL_COMPLETED',data.tool,{'tool':data.tool})
            return {'case_id':data.case_id,'completed_tool':data.tool,'steps_completed':len(c['state']['steps'])}
        except Exception:
            fail_closed(data.case_id,f'TOOL_FAILURE_{data.tool}')
            raise HTTPException(503,'Tool failed closed')

    @app.post('/internal/finalize')
    def finalize(ref:CaseRef,ok=Depends(internal)):
        c=get_case(ref.case_id);require_processing(c)
        if set(c['state']['steps'])!=set(TOOLS):raise HTTPException(409,'Mandatory evidence is incomplete')
        if c['state'].get('planned_next')!='finish':raise HTTPException(409,'Planner has not stopped')
        try:
            c['state']['synthesis']=synthesize(model,c)
            result=assess(c)
            c['state']['flags']=result['flags']; c['state']['priority']=result['priority']
            c['state']['stop_reasons']=result['stop_reasons']
            c['status']='ESCALATION_REQUIRED' if result['safe_stop'] else 'AWAITING_CLINICIAN'
            store.remove_image(c)
            c=store.save(c,'POLICY_FINALIZED','policy',{'safe_stop':result['safe_stop'],'priority':result['priority'],'flag_count':len(result['flags'])})
            coordination.new_task('review:'+ref.case_id,ref.case_id,c['patient_ref'],'clinical_review',
                result['priority'],'SAFE_STOP' if result['safe_stop'] else 'CLINICIAN_REVIEW_REQUIRED',
                300 if result['priority']=='urgent' else 1800)
        except Exception:
            fail_closed(ref.case_id,'SYNTHESIS_OR_POLICY_FAILURE')
            raise HTTPException(503,'Finalization failed closed')
        return {'case_id':ref.case_id,'status':c['status'],'safe_stop':result['safe_stop'],'priority':result['priority']}

    @app.post('/internal/watchdog')
    def watchdog(ok=Depends(internal)):
        now=time.time();changed=[]
        for item in store.list_cases():
            age=now-item['updated_at']
            c=store.get(item['case_id'])
            if (c['status'] in ('RECEIVED','PROCESSING') and age>600) or (c['status']=='AWAITING_CLINICIAN' and age>1800):
                c['status']='ESCALATION_REQUIRED'
                c['state']['flags']=sorted(set(c['state']['flags']+['SLA_EXCEEDED']))
                store.remove_image(c)
                store.save(c,'WATCHDOG_ESCALATION','watchdog',{'age_seconds':int(age)})
                changed.append(item['case_id'])
        return {'escalated_case_ids':changed,'count':len(changed)}

    @app.post('/internal/knowledge/reindex')
    def index(ok=Depends(internal)):
        if store.list_cases() and any(c['status']=='PROCESSING' for c in store.list_cases()):
            raise HTTPException(409,'Index changes are blocked during active processing')
        try:return rag.reindex()
        except Exception:raise HTTPException(503,'Embedding index unavailable')

    @app.post('/internal/error')
    def error(notice:ErrorNotice,ok=Depends(internal)):
        # No case id / PHI from the workflow error. This is operational-only reporting.
        store.audit('SYSTEM','N8N_EXECUTION_ERROR','n8n',{'error_code':notice.error_code[:40]})
        return {'recorded':True}

    # ---- 2.0 longitudinal observations: patient-scoped synthetic measurements ----
    @app.post('/v2/observations',status_code=201)
    def observation(data:ObservationIn, claim=Depends(patient)):
        access(claim,data.patient_ref)
        try:return coordination.add_observation(data.patient_ref,data.event_id,data.code,data.value,data.unit,data.taken_at)
        except ValueError as e:raise HTTPException(409 if str(e)=='DUPLICATE_EVENT' else 422,str(e))

    @app.get('/v2/patients/{patient_ref}/trends')
    def trends(patient_ref:str,days:int=7, claim=Depends(auth)):
        access(claim,patient_ref)
        if not 1<=days<=30:raise HTTPException(422,'days must be 1..30')
        return coordination.summary(patient_ref,days)

    @app.post('/v2/monitoring-plans')
    def monitoring_plan(data:MonitoringPlanIn,claim=Depends(clinician)):
        access(claim,data.patient_ref)
        return coordination.set_plan(data.patient_ref,data.observation_code,data.review_gap_hours,
                                     claim['sub'],data.active)

    @app.post('/v2/checkins',status_code=202)
    async def checkin(data:CheckinIn,claim=Depends(patient)):
        access(claim,data.patient_ref)
        try:
            with store.transaction():
                created=coordination.create_checkin(data.patient_ref,data.event_id,data.model_dump())
                dispatch_queue.enqueue('CHECKIN_DISPATCH',data.event_id)
        except ValueError as e:raise HTTPException(409,str(e))
        # Urgent symptom flags are triaged synchronously, independently of n8n availability.
        # This is a synthetic task only; it does NOT page a clinical service.
        if any(data.symptoms.model_dump().get(k) for k in ('chest_pain','severe_breathlessness','fainting','confusion')):
            created=coordination.triage_checkin(data.event_id)
        # Persist a retryable event before contacting n8n; no patient content in the job.
        try:
            if checkin_dispatch is not None:await checkin_dispatch({'event_id':data.event_id})
            else:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    r=await client.post(settings.webhook_url.replace('hah-case-intake','hah-checkin-intake'),
                                        json={'event_id':data.event_id})
                    r.raise_for_status()
            dispatch_queue.delivered('CHECKIN_DISPATCH',data.event_id)
        except Exception:
            store.audit('CHECKIN','CHECKIN_ORCHESTRATOR_UNAVAILABLE','system',{'pending_reconcile':True})
        return created

    @app.get('/v2/tasks')
    def tasks(claim=Depends(clinician)):
        return {'tasks':coordination.tasks(patient_refs=allowed_patient_refs(claim)),'warning':'Synthetic care tasks; not linked to an actual paging service'}

    @app.post('/v2/tasks/{task_id}/claim')
    def task_claim(task_id:str,claim=Depends(clinician)):
        try:access(claim,coordination.get_task(task_id)['patient_ref'])
        except KeyError:raise HTTPException(404,'Task not found')
        try:
            with store.transaction():
                result=coordination.claim(task_id,claim['sub'])
                operations.record(result['patient_ref'],task_id,'TASK_CLAIMED',claim['sub'])
            return result
        except KeyError:raise HTTPException(404,'Task not found')
        except ValueError as e:raise HTTPException(409,str(e))

    @app.post('/v2/tasks/{task_id}/resolve')
    def task_resolve(task_id:str,data:TaskResolveIn,claim=Depends(clinician)):
        try:access(claim,coordination.get_task(task_id)['patient_ref'])
        except KeyError:raise HTTPException(404,'Task not found')
        try:
            with store.transaction():
                result=coordination.resolve(task_id,claim['sub'],data.outcome,data.note)
                operations.record(result['patient_ref'],task_id,'TASK_RESOLVED',claim['sub'],{'closed':result['status']=='COMPLETED'})
            return result
        except KeyError:raise HTTPException(404,'Task not found')
        except ValueError as e:raise HTTPException(409,str(e))

    @app.post('/v2/patient/receipt')
    def patient_receipt(data:ReceiptIn,claim=Depends(patient)):
        access(claim,data.patient_ref)
        try:
            with store.transaction():
                result=coordination.acknowledge_simulated(data.case_id,data.patient_ref)
                operations.record(data.patient_ref,None,'PATIENT_RECEIPT',claim['sub'])
            return result
        except KeyError:raise HTTPException(404,'Case not found')
        except ValueError as e:raise HTTPException(409,str(e))

    @app.post('/internal/checkin/triage')
    def internal_triage_checkin(data:dict=Body(...),ok=Depends(internal)):
        if not isinstance(data.get('event_id'),str):raise HTTPException(422,'event_id required')
        try:return coordination.triage_checkin(data['event_id'])
        except KeyError:raise HTTPException(404,'Check-in not found')

    @app.post('/internal/coordination/watch')
    def coordination_watch(ok=Depends(internal)):
        return coordination.watch()

    @app.post('/internal/retry-pending')
    async def retry_pending(ok=Depends(internal)):
        """Re-dispatch accepted cases if n8n intake was unavailable. Idempotent start protects against replay."""
        attempted=[];failed=[];now=time.time()
        for item in store.list_cases():
            if len(attempted)>=20:break
            if item['status']!='RECEIVED' or now-item['created_at']<30:continue
            attempted.append(item['case_id'])
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r=await client.post(settings.webhook_url,json={'case_id':item['case_id']})
                    r.raise_for_status()
                store.audit(item['case_id'],'ORCHESTRATOR_RETRY','watchdog',{'accepted_by_webhook':True})
            except Exception:
                failed.append(item['case_id'])
                store.audit(item['case_id'],'ORCHESTRATOR_RETRY','watchdog',{'accepted_by_webhook':False})
        return {'attempted_case_ids':attempted,'failed_case_ids':failed,
                'warning':'Accepted webhook does not prove successful execution; clinical monitoring not guaranteed'}

    @app.get('/v2/metrics')
    def metrics(claim=Depends(clinician)):
        if settings.auth_mode=='oidc':
            raise HTTPException(403,'Aggregate cross-patient metrics require a separate authorized reporting role')
        return coordination.metrics()

    # FHIR R4 synthetic sandbox interoperability. No real EHR/OAuth integration.
    @app.post('/v3/fhir/import',status_code=200)
    def fhir_import(data:dict=Body(...),claim=Depends(clinician)):
        if len(json.dumps(data,ensure_ascii=False)) > 256_000:
            raise HTTPException(413,'Synthetic FHIR payload too large')
        if set(data)!={'patient_ref','is_synthetic','bundle'} or data.get('is_synthetic') is not True:
            raise HTTPException(422,'Synthetic FHIR wrapper is required')
        patient_ref=data['patient_ref']
        access(claim,patient_ref)
        try: return fhir_bridge.import_bundle(patient_ref,data['bundle'],actor=claim['sub'])
        except FHIRConflict as e: raise HTTPException(409,str(e))
        except (ValueError,TypeError,KeyError) as e: raise HTTPException(422,str(e))

    @app.get('/v3/fhir/Observation')
    def fhir_export(patient_ref:str,limit:int=50,claim=Depends(clinician)):
        access(claim,patient_ref)
        try: return fhir_bridge.export_observations(patient_ref,limit)
        except ValueError as e: raise HTTPException(422,str(e))

    @app.post('/internal/ops/audit-health')
    def audit_health(ok=Depends(internal)):
        if store.backend!='postgres':
            raise HTTPException(503,'POSTGRES_NOT_ACTIVE')
        # Synthetic-only. n8n receives no individual patient/case data.
        try:
            store.db.execute('SELECT 1')
            chain_ok=store.verify_audit()
        except Exception:
            raise HTTPException(503,'DATASTORE_UNAVAILABLE')
        if not chain_ok:raise HTTPException(503,'AUDIT_CHAIN_INVALID')
        return {'ok':True,'db_backend':store.backend,'auth_mode':settings.auth_mode,
                'audit_chain_valid':True,'synthetic_only':True}

    @app.post('/internal/fhir/sandbox-sync')
    def internal_fhir_sync(ok=Depends(internal)):
        try:return fhir_bridge.sync_demo()
        except (FHIRConflict,ValueError) as e:raise HTTPException(409,str(e))


    # ---- V2.3 bounded clinician shift + acceptance-based handoff ----
    @app.post('/v3/shifts',status_code=201)
    def register_shift(data:ShiftIn,claim=Depends(clinician)):
        access(claim,data.patient_ref)
        try:return operations.shift(claim['sub'],data.patient_ref,data.starts_at,data.ends_at)
        except ValueError as e:raise HTTPException(422,str(e))

    @app.post('/v3/shifts/{shift_id}/cancel')
    def cancel_shift(shift_id:str,claim=Depends(clinician)):
        try:return operations.cancel_shift(shift_id,claim['sub'])
        except KeyError:raise HTTPException(404,'Shift not found')
        except ValueError as e:raise HTTPException(409,str(e))

    @app.get('/v3/shifts/{patient_ref}')
    def get_roster(patient_ref:str,claim=Depends(clinician)):
        access(claim,patient_ref)
        return {'shifts':operations.roster(patient_ref),'synthetic_only':True}

    @app.post('/v3/tasks/{task_id}/handoff',status_code=201)
    def offer_handoff(task_id:str,data:HandoffIn,claim=Depends(clinician)):
        try:t=coordination.get_task(task_id)
        except KeyError:raise HTTPException(404,'Task not found')
        access(claim,t['patient_ref'])
        try:return operations.offer(task_id,claim['sub'],data.to_clinician_sub,data.reason)
        except ValueError as e:raise HTTPException(409,str(e))

    @app.get('/v3/handoffs/inbox')
    def handoff_inbox(claim=Depends(clinician)):
        return {'handoffs':operations.inbox(claim['sub'],allowed_patient_refs(claim)),
                'warning':'Recipients must explicitly accept; old owner remains until then.'}

    @app.post('/v3/handoffs/{handoff_id}/accept')
    def accept_handoff(handoff_id:str,claim=Depends(clinician)):
        try:h=operations.get_handoff(handoff_id)
        except KeyError:raise HTTPException(404,'Handoff not found')
        access(claim,h['patient_ref'])
        try:return operations.decide(handoff_id,claim['sub'],'accept')
        except ValueError as e:raise HTTPException(409,str(e))

    @app.post('/v3/handoffs/{handoff_id}/reject')
    def reject_handoff(handoff_id:str,claim=Depends(clinician)):
        try:h=operations.get_handoff(handoff_id)
        except KeyError:raise HTTPException(404,'Handoff not found')
        access(claim,h['patient_ref'])
        try:return operations.decide(handoff_id,claim['sub'],'reject')
        except ValueError as e:raise HTTPException(409,str(e))

    @app.get('/v3/patients/{patient_ref}/timeline')
    def clinical_timeline(patient_ref:str,claim=Depends(clinician)):
        access(claim,patient_ref)
        return {'patient_ref':patient_ref,'events':operations.timeline(patient_ref),
                'synthetic_only':True,'coverage':'Handoff events from v2.3 forward; not a complete EHR history'}

    @app.get('/v3/ops/dispatch-jobs')
    def dispatch_job_status(claim=Depends(clinician)):
        if settings.auth_mode=='oidc':
            raise HTTPException(403,'Cross-patient operational metrics require separate reporting privileges')
        return {'jobs':dispatch_queue.list_jobs(),'counts':dispatch_queue.counts(),
                'warning':'Webhook acceptance is not workflow success; no clinical message delivery'}

    @app.post('/internal/ops/dispatch-health')
    def internal_dispatch_health(ok=Depends(internal)):
        counts=dispatch_queue.counts()
        if counts.get('DEAD',0)>0:
            # Fail visibly in monitoring, but no data/patient identities are returned.
            raise HTTPException(503,'DISPATCH_DEAD_LETTER_REQUIRES_OPERATOR_REVIEW')
        return {'healthy':True,'counts':counts,'synthetic_only':True,
                'webhook_ack_is_not_completion':True}

    @app.post('/internal/ops/handoff-watch')
    def internal_handoff_watch(ok=Depends(internal)):
        return operations.watch()

    @app.post('/internal/ops/dispatch-drain')
    async def internal_dispatch_drain(ok=Depends(internal)):
        expired_leases=dispatch_queue.reap_exhausted_leases()
        for job in expired_leases:
            if job['job_kind']=='CASE_DISPATCH':
                try:
                    case=store.get(job['reference_id'])
                    coordination.new_task('dispatch-failed:'+job['reference_id'],job['reference_id'],
                        case['patient_ref'],'technical_dispatch_review','review','DISPATCH_DEAD_LETTER',900)
                except KeyError:pass
        recovered=dispatch_queue.recover_accepted()
        for jid,ref in recovered['dead']:
            try:
                case=store.get(ref)
                coordination.new_task('dispatch-failed:'+ref,ref,case['patient_ref'],
                    'technical_dispatch_review','review','DISPATCH_DEAD_LETTER',900)
            except KeyError:pass
        processed=[];errors=[];skipped=[]
        # Fixed batch avoids n8n timeouts and limits resource consumption.
        for _ in range(10):
            job=dispatch_queue.claim()
            if not job:break
            kind=job['job_kind'];ref=job['reference_id']
            try:
                if kind=='CASE_DISPATCH':
                    case=store.get(ref)
                    if case['status']!='RECEIVED':
                        dispatch_queue.delivered(kind,ref);skipped.append(job['job_id']);continue
                    payload={'case_id':ref};url=settings.webhook_url;fn=dispatch
                elif kind=='CHECKIN_DISPATCH':
                    with store._lock:
                        checkin=store.db.execute('SELECT status FROM checkins WHERE event_id=?',(ref,)).fetchone()
                    if not checkin:raise KeyError('Missing checkin')
                    if checkin['status']=='TRIAGED':
                        dispatch_queue.delivered(kind,ref);skipped.append(job['job_id']);continue
                    payload={'event_id':ref};url=settings.webhook_url.replace('hah-case-intake','hah-checkin-intake');fn=checkin_dispatch
                else:raise KeyError('Unsupported job type')
                if fn is not None:await fn(payload)
                else:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response=await client.post(url,json=payload);response.raise_for_status()
                dispatch_queue.delivered(kind,ref)
                processed.append(job['job_id'])
            except Exception as e:
                result=dispatch_queue.failed(job['job_id'],'BAD_REFERENCE' if isinstance(e,KeyError) else 'WEBHOOK_UNAVAILABLE')
                errors.append({'job_id':job['job_id'],'status':result['status'] if result else 'UNKNOWN'})
                # Dead-letter jobs remain visible; no automatic patient-facing action.
                if result and result['status']=='DEAD' and kind=='CASE_DISPATCH':
                    try:
                        case=store.get(ref)
                        coordination.new_task('dispatch-failed:'+ref,ref,case['patient_ref'],
                            'technical_dispatch_review','review','DISPATCH_DEAD_LETTER',900)
                    except KeyError:pass
        return {'delivered_job_ids':processed,'skipped_job_ids':skipped,'failed_jobs':errors,
                'counts':dispatch_queue.counts(),'rearmed_count':len(recovered['rearmed']),
                'dead_recovery_count':len(recovered['dead']),'expired_lease_count':len(expired_leases),'at_least_once':True,'clinical_notifications_sent':False}

    # ---- V2.4 patient-owned simulated engagement; no outbound messages ----
    @app.get('/v4/patient/dashboard')
    def patient_dashboard(days:int=7,claim=Depends(patient)):
        if days not in (7,14,30):raise HTTPException(422,'Only 7,14,30 days allowed')
        patient_ref=claim['patient_ref']
        access(claim,patient_ref)
        return engagement.dashboard(patient_ref,days)

    @app.get('/v4/patient/preferences')
    def get_patient_preferences(claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        return engagement.preferences(claim['patient_ref'])

    @app.put('/v4/patient/preferences')
    def change_patient_preferences(data:PatientPreferenceIn,claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        return engagement.set_preferences(claim['patient_ref'],data.reminder_opt_in,data.reminder_hour_utc,data.minimum_gap_hours)

    @app.get('/v4/patient/prompts')
    def get_patient_prompts(claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        return {'prompts':engagement.prompts(claim['patient_ref']),'real_notifications_sent':False}

    @app.post('/v4/patient/prompts/{prompt_id}/seen')
    def patient_prompt_seen(prompt_id:str,claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        try:return engagement.mark_seen(claim['patient_ref'],prompt_id)
        except KeyError:raise HTTPException(404,'Prompt not found')
        except ValueError:raise HTTPException(409,'Prompt no longer active')

    @app.get('/v4/clinician/alert-groups')
    def clinician_alert_groups(claim=Depends(clinician)):
        return engagement.alert_groups(allowed_patient_refs(claim))

    @app.get('/v4/clinician/evaluation/{patient_ref}')
    def clinician_evaluation(patient_ref:str,days:int=7,claim=Depends(clinician)):
        access(claim,patient_ref)
        if days not in (7,14,30):raise HTTPException(422,'Only 7,14,30 days allowed')
        return engagement.evaluation(patient_ref,days)

    @app.post('/internal/engagement/watch')
    def internal_engagement_watch(ok=Depends(internal)):
        return engagement.reminder_watch()

    @app.post('/internal/ops/quality-snapshot')
    def internal_quality_snapshot(ok=Depends(internal)):
        return engagement.snapshot()

    app.include_router(build_router(communications,clinician,patient,internal,access))
    return app

# Module app object uses runtime secrets; unit tests should import factory after setting env.
app=create_app()
