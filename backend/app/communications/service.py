"""Application use-cases: policies + transactions, without HTTP or workflow concerns."""
from __future__ import annotations
import time
from .domain import Template, TEMPLATES, Status, WorkflowConflict, can_publish_for_case
from .repository import CommunicationsRepository

class CommunicationService:
    def __init__(self,store,coordinator):
        self.store=store
        self.coordinator=coordinator
        self.repo=CommunicationsRepository(store)

    def draft(self,*,request_key,patient_ref,template_code,actor,due_hours,case_id=None):
        template=Template(template_code)
        with self.store.transaction():
            previous=self.repo.by_request(request_key)
            if previous:
                if (previous['patient_ref'],previous['template_code'],previous['clinician_sub'],previous['case_id']) != (patient_ref,template.value,actor,case_id):
                    raise WorkflowConflict('IDEMPOTENCY_CONFLICT')
                return {**self.repo.public(previous), 'idempotent':True}
            if case_id is not None:
                c=self.store.get(case_id)
                if c['patient_ref']!=patient_ref:raise WorkflowConflict('CASE_PATIENT_MISMATCH')
            message=self.repo.create(request_key,patient_ref,case_id,template.value,TEMPLATES[template],actor,
                                     time.time()+due_hours*3600)
            self.store.audit('COMMUNICATION','MESSAGE_DRAFTED',actor,{'template':template.value,'synthetic':True})
            return {**self.repo.public(message),'idempotent':False}

    def publish(self,message_id,actor):
        with self.store.transaction():
            message=self.repo.get(message_id)
            if message['state']==Status.PUBLISHED_IN_APP.value:
                return {**self.repo.public(message),'idempotent':True}
            if message['state']!=Status.DRAFT.value:raise WorkflowConflict('INVALID_MESSAGE_STATE')
            if message['case_id']:
                c=self.store.get(message['case_id'])
                if c['patient_ref']!=message['patient_ref'] or not can_publish_for_case(c['status']):
                    raise WorkflowConflict('CASE_NOT_SAFE_TO_PUBLISH')
            if not self.repo.transition(message_id,Status.DRAFT.value,Status.PUBLISHED_IN_APP.value,'published_at',time.time()):
                raise WorkflowConflict('MESSAGE_RACE')
            self.store.audit('COMMUNICATION','IN_APP_MESSAGE_PUBLISHED',actor,{'template':message['template_code'],'synthetic':True})
            return {**self.repo.public(self.repo.get(message_id)),'idempotent':False,'external_messages_sent':0}

    def acknowledge(self,message_id,patient_ref):
        with self.store.transaction():
            message=self.repo.get(message_id)
            if message['patient_ref']!=patient_ref:raise KeyError('MESSAGE_NOT_FOUND')
            if message['state']==Status.ACKNOWLEDGED.value:
                return {'message_id':message_id,'state':'ACKNOWLEDGED','idempotent':True}
            if message['state']!=Status.PUBLISHED_IN_APP.value:
                raise WorkflowConflict('MESSAGE_NOT_ACTIVE')
            if not self.repo.transition(message_id,Status.PUBLISHED_IN_APP.value,Status.ACKNOWLEDGED.value,'acknowledged_at',time.time()):
                raise WorkflowConflict('MESSAGE_RACE')
            self.store.audit('COMMUNICATION','PATIENT_IN_APP_ACK','synthetic-patient',{'synthetic':True})
            return {'message_id':message_id,'state':'ACKNOWLEDGED','idempotent':False,'clinical_completion':False}

    def watch(self,at=None):
        now=time.time() if at is None else at
        expired=[]
        with self.store.transaction():
            for row in self.repo.expired(now):
                if not self.repo.transition(row['message_id'],'PUBLISHED_IN_APP','OVERDUE'):continue
                self.coordinator.new_task('message-overdue:'+row['message_id'],None,row['patient_ref'],
                     'communication_followup','review','IN_APP_MESSAGE_UNACKNOWLEDGED',3600)
                self.store.audit('COMMUNICATION','MESSAGE_SLA_EXCEEDED','scheduler',{'synthetic':True})
                expired.append(row['message_id'])
        return {'overdue_count':len(expired),'external_notifications_sent':0,'no_clinical_escalation_guarantee':True}

    def metrics(self):
        return {'by_state':self.repo.counts(),'external_notifications_sent':0,'ground_truth_sensitivity_claim':False}
