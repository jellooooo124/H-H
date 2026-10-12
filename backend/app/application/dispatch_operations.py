"""Operational monitoring and durable dispatch drain, with no web-framework dependency."""
from __future__ import annotations
import time
from ..domain.workflow_rules import WorkflowError

class DispatchOperations:
    def __init__(self,store,coordination,queue,operations,case_dispatcher,checkin_dispatcher,checkin_reader,health_reader,auth_mode):
        self.store,self.coord,self.jobs,self.ops=store,coordination,queue,operations
        self.case_dispatcher,self.checkin_dispatcher=case_dispatcher,checkin_dispatcher
        self.checkin_reader=checkin_reader
        self.health_reader=health_reader
        self.auth_mode=auth_mode

    def audit_health(self):
        if self.store.backend!='postgres':raise WorkflowError('unavailable','POSTGRES_NOT_ACTIVE')
        try:
            chain_ok=self.health_reader.check()
        except Exception:raise WorkflowError('unavailable','DATASTORE_UNAVAILABLE')
        if not chain_ok:raise WorkflowError('unavailable','AUDIT_CHAIN_INVALID')
        return {'ok':True,'db_backend':self.store.backend,'auth_mode':self.auth_mode,
                'audit_chain_valid':True,'synthetic_only':True}

    def dispatch_health(self):
        counts=self.jobs.counts()
        if counts.get('DEAD',0)>0:
            raise WorkflowError('unavailable','DISPATCH_DEAD_LETTER_REQUIRES_OPERATOR_REVIEW')
        return {'healthy':True,'counts':counts,'synthetic_only':True,
                'webhook_ack_is_not_completion':True}

    def error(self,code):
        self.store.audit('SYSTEM','N8N_EXECUTION_ERROR','n8n',{'error_code':code[:40]})
        return {'recorded':True}

    def handoff_watch(self):return self.ops.watch()

    def _dispatch_failed_task(self,ref):
        try:
            case=self.store.get(ref)
            self.coord.new_task('dispatch-failed:'+ref,ref,case['patient_ref'],
                'technical_dispatch_review','review','DISPATCH_DEAD_LETTER',900)
        except KeyError:pass

    async def drain(self):
        expired=self.jobs.reap_exhausted_leases()
        for job in expired:
            if job['job_kind']=='CASE_DISPATCH':self._dispatch_failed_task(job['reference_id'])
        recovered=self.jobs.recover_accepted()
        for _,ref in recovered['dead']:self._dispatch_failed_task(ref)
        processed=[];errors=[];skipped=[]
        for _ in range(10):
            job=self.jobs.claim()
            if not job:break
            kind,ref=job['job_kind'],job['reference_id']
            try:
                if kind=='CASE_DISPATCH':
                    case=self.store.get(ref)
                    if case['status']!='RECEIVED':
                        self.jobs.delivered(kind,ref);skipped.append(job['job_id']);continue
                    await self.case_dispatcher.dispatch_case(ref)
                elif kind=='CHECKIN_DISPATCH':
                    status=self.checkin_reader.checkin_status(ref)
                    if status is None:raise KeyError('Missing checkin')
                    if status=='TRIAGED':
                        self.jobs.delivered(kind,ref);skipped.append(job['job_id']);continue
                    await self.checkin_dispatcher.dispatch_checkin(ref)
                else:raise KeyError('Unsupported job type')
                self.jobs.delivered(kind,ref)
                processed.append(job['job_id'])
            except Exception as exc:
                result=self.jobs.failed(job['job_id'], 'BAD_REFERENCE' if isinstance(exc,KeyError) else 'WEBHOOK_UNAVAILABLE')
                errors.append({'job_id':job['job_id'],'status':result['status'] if result else 'UNKNOWN'})
                if result and result['status']=='DEAD' and kind=='CASE_DISPATCH':
                    self._dispatch_failed_task(ref)
        return {'delivered_job_ids':processed,'skipped_job_ids':skipped,'failed_jobs':errors,
                'counts':self.jobs.counts(),'rearmed_count':len(recovered['rearmed']),
                'dead_recovery_count':len(recovered['dead']),'expired_lease_count':len(expired),
                'at_least_once':True,'clinical_notifications_sent':False}

    async def retry_pending(self):
        # Retained as a compatibility endpoint. Prefer the durable queue drain.
        attempted=[];failed=[];now=time.time()
        for item in self.store.list_cases():
            if len(attempted)>=20:break
            if item['status']!='RECEIVED' or now-item['created_at']<30:continue
            attempted.append(item['case_id'])
            try:
                await self.case_dispatcher.dispatch_case(item['case_id'])
                self.store.audit(item['case_id'],'ORCHESTRATOR_RETRY','watchdog',{'accepted_by_webhook':True})
            except Exception:
                failed.append(item['case_id'])
                self.store.audit(item['case_id'],'ORCHESTRATOR_RETRY','watchdog',{'accepted_by_webhook':False})
        return {'attempted_case_ids':attempted,'failed_case_ids':failed,
                'warning':'Accepted webhook does not prove successful execution; clinical monitoring not guaranteed'}
