"""Synthetic monitoring workflows and clinical task transactions. No FastAPI dependency."""
from __future__ import annotations
from .ports import CheckinEventDispatcher

class MonitoringUseCases:
    def __init__(self,store,coordination,operations,dispatch_queue,settings,dispatcher: CheckinEventDispatcher):
        self.store=store
        self.coord=coordination
        self.operations=operations
        self.jobs=dispatch_queue
        self.settings=settings
        self.dispatcher=dispatcher

    def observation(self,patient_ref,event_id,code,value,unit,taken_at):
        return self.coord.add_observation(patient_ref,event_id,code,value,unit,taken_at)

    def trends(self,patient_ref,days):
        if not 1<=days<=30:raise ValueError('days must be 1..30')
        return self.coord.summary(patient_ref,days)

    def monitoring_plan(self,patient_ref,observation_code,review_gap_hours,actor,active):
        return self.coord.set_plan(patient_ref,observation_code,review_gap_hours,actor,active)

    async def checkin(self,patient_ref,event_id,payload):
        # Store the event before dispatch. n8n is untrusted to complete the work.
        with self.store.transaction():
            created=self.coord.create_checkin(patient_ref,event_id,payload)
            self.jobs.enqueue('CHECKIN_DISPATCH',event_id)
        if any(payload['symptoms'].get(k) for k in ('chest_pain','severe_breathlessness','fainting','confusion')):
            created=self.coord.triage_checkin(event_id)
        try:
            await self.dispatcher.dispatch_checkin(event_id)
            self.jobs.delivered('CHECKIN_DISPATCH',event_id)
        except Exception:
            self.store.audit('CHECKIN','CHECKIN_ORCHESTRATOR_UNAVAILABLE','system',{'pending_reconcile':True})
        return created

    def tasks(self,patient_refs):
        return {'tasks':self.coord.tasks(patient_refs=patient_refs),
                'warning':'Synthetic care tasks; not linked to an actual paging service'}

    def get_task(self,task_id):
        return self.coord.get_task(task_id)

    def claim_task(self,task_id,actor):
        with self.store.transaction():
            result=self.coord.claim(task_id,actor)
            self.operations.record(result['patient_ref'],task_id,'TASK_CLAIMED',actor)
        return result

    def resolve_task(self,task_id,outcome,note,actor):
        with self.store.transaction():
            result=self.coord.resolve(task_id,actor,outcome,note)
            self.operations.record(result['patient_ref'],task_id,'TASK_RESOLVED',actor,{'closed':result['status']=='COMPLETED'})
        return result

    def patient_receipt(self,case_id,patient_ref,actor):
        with self.store.transaction():
            result=self.coord.acknowledge_simulated(case_id,patient_ref)
            self.operations.record(patient_ref,None,'PATIENT_RECEIPT',actor)
        return result

    def triage_checkin(self,event_id):
        return self.coord.triage_checkin(event_id)

    def watch(self):
        return self.coord.watch()

    def metrics(self):
        if self.settings.auth_mode=='oidc':
            raise PermissionError('Aggregate cross-patient metrics require a separate authorized reporting role')
        return self.coord.metrics()
