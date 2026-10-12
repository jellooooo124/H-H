"""Shift and handoff use cases: responsibility changes only after acceptance."""

class HandoffUseCases:
    def __init__(self,operations,coordination,dispatch_queue,settings):
        self.ops=operations
        self.coordination=coordination
        self.jobs=dispatch_queue
        self.settings=settings

    def shift(self,clinician_sub,patient_ref,starts_at,ends_at):
        return self.ops.shift(clinician_sub,patient_ref,starts_at,ends_at)
    def cancel(self,shift_id,clinician_sub):
        return self.ops.cancel_shift(shift_id,clinician_sub)
    def roster(self,patient_ref):
        return {'shifts':self.ops.roster(patient_ref),'synthetic_only':True}
    def task(self,task_id):
        return self.coordination.get_task(task_id)
    def offer(self,task_id,clinician_sub,to_clinician_sub,reason):
        return self.ops.offer(task_id,clinician_sub,to_clinician_sub,reason)
    def inbox(self,clinician_sub,refs):
        return {'handoffs':self.ops.inbox(clinician_sub,refs),
                'warning':'Recipients must explicitly accept; old owner remains until then.'}
    def get_handoff(self,handoff_id):
        return self.ops.get_handoff(handoff_id)
    def decide(self,handoff_id,clinician_sub,choice):
        return self.ops.decide(handoff_id,clinician_sub,choice)
    def timeline(self,patient_ref):
        return {'patient_ref':patient_ref,'events':self.ops.timeline(patient_ref),
                'synthetic_only':True,'coverage':'Handoff events from v2.3 forward; not a complete EHR history'}
    def dispatch_status(self):
        if self.settings.auth_mode=='oidc':
            raise PermissionError('Cross-patient operational metrics require separate reporting privileges')
        return {'jobs':self.jobs.list_jobs(),'counts':self.jobs.counts(),
                'warning':'Webhook acceptance is not workflow success; no clinical message delivery'}
