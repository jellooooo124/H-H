"""Backward-compatible composition root for still-unmigrated clinical case workflows.

59 existing HTTP method/path contracts are preserved. New monitoring, handoff, FHIR,
engagement and case-query routers live under presentation/routers; persistence lives
under infrastructure/persistence. Remaining endpoints stay here until transactions
and fail-closed clinical transitions can be migrated with equivalence tests.
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
from .application.access_control import AccessControl
from .application.case_queries import CaseQueries
from .application.fhir_use_cases import FHIRUseCases
from .application.engagement_use_cases import EngagementUseCases
from .presentation.auth import make_dependencies
from .presentation.routers.case_queries import build_router as build_case_queries_router
from .presentation.routers.fhir import build_router as build_fhir_router
from .presentation.routers.engagement import build_router as build_engagement_router
from .presentation.routers.handoffs import build_router as build_handoffs_router
from .application.handoffs import HandoffUseCases
from .application.monitoring import MonitoringUseCases
from .presentation.routers.monitoring import build_router as build_monitoring_router
from .infrastructure.checkin_dispatcher import N8NCheckinDispatcher

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
    app=FastAPI(title='Hospital-at-Home Care Coordination (Synthetic Research Platform)',version='3.1.0')
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

    access_policy=AccessControl(store,settings.auth_mode)
    auth_http,clinician,patient,admin=make_dependencies(settings,verifier,access_policy)
    internal=auth_http.internal
    auth=auth_http.auth
    access=auth_http.require_patient
    allowed_patient_refs=auth_http.allowed_patient_refs

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

    app.include_router(build_monitoring_router(MonitoringUseCases(store,coordination,operations,dispatch_queue,settings,N8NCheckinDispatcher(settings,checkin_dispatch)),patient,clinician,auth,internal,access,allowed_patient_refs))
    app.include_router(build_handoffs_router(HandoffUseCases(operations,coordination,dispatch_queue,settings),clinician,access,allowed_patient_refs))
    app.include_router(build_case_queries_router(CaseQueries(store),clinician,access,allowed_patient_refs))
    app.include_router(build_fhir_router(FHIRUseCases(fhir_bridge),clinician,internal,access))
    app.include_router(build_engagement_router(EngagementUseCases(engagement),clinician,patient,internal,access,allowed_patient_refs))
    app.include_router(build_router(communications,clinician,patient,internal,access))
    return app

# Module app object uses runtime secrets; unit tests should import factory after setting env.
app=create_app()
