"""Intake, human decision and case SLA use cases. No FastAPI or HTTP dependencies."""
from __future__ import annotations
import time
from ..domain.workflow_rules import WorkflowError, urgent_reported, reviewable, approval_evidence
from .ports import ClinicalCaseRepository, CaseEventDispatcher, ClinicalTaskCoordinator

class ClinicalCases:
    def __init__(self, store: ClinicalCaseRepository, coordination: ClinicalTaskCoordinator,
                 operations, queue, dispatcher: CaseEventDispatcher, policy):
        self.store, self.coordination, self.operations = store, coordination, operations
        self.queue, self.dispatcher, self.policy = queue, dispatcher, policy

    def get(self, case_id):
        try: return self.store.get(case_id)
        except KeyError as exc: raise WorkflowError('not_found', 'Case not found') from exc

    async def intake(self, data):
        with self.store.transaction():
            self.store.create(data['case_id'], data['patient_ref'], data)
            self.queue.enqueue('CASE_DISPATCH', data['case_id'])
            # Avoid silently losing urgent tasks if later DB operations fail.
            if urgent_reported(data['symptoms']):
                self.coordination.new_task('urgent-intake:' + data['case_id'], data['case_id'],
                    data['patient_ref'], 'reported_symptom_review', 'urgent', 'REPORTED_URGENT_SYMPTOM', 300)
        try:
            await self.dispatcher.dispatch_case(data['case_id'])
            self.queue.delivered('CASE_DISPATCH', data['case_id'])
        except Exception:
            self.store.audit(data['case_id'], 'ORCHESTRATOR_UNAVAILABLE', 'system', {'retry_needed': True})
        return {'case_id':data['case_id'], 'status':'RECEIVED',
                'message':'Accepted for educational workflow; no clinical monitoring guarantee'}

    def decide(self, data, actor):
        # Lock/transaction encompasses re-read, version check, task ownership and all writes.
        with self.store.transaction():
            c = self.get(data.case_id)
            if c['version'] != data.expected_version:
                raise WorkflowError('conflict', 'Stale version; refresh case')
            try: self.coordination.require_review_claim(data.case_id, actor)
            except ValueError as exc: raise WorkflowError('conflict', str(exc)) from exc
            reviewable(c, data.choice)
            if data.choice == 'approve':
                approval_evidence(c, self.policy(c))
                c['status'] = 'APPROVED_SIMULATED'
            elif data.choice == 'reject': c['status'] = 'REJECTED'
            else: c['status'] = 'ESCALATED'
            c['state']['review'] = {'actor':actor, 'choice':data.choice,
                                    'comment':data.comment, 'at':time.time()}
            c = self.store.save(c, 'CLINICIAN_DECISION', actor, {'choice':data.choice})
            self.coordination.complete_review(data.case_id, actor, data.choice)
            self.operations.record(c['patient_ref'], self.coordination.task_for_case(data.case_id)['task_id'],
                                   'CASE_DECISION', actor, {'choice':data.choice})
            if data.choice == 'escalate':
                self.coordination.new_task('followup:' + data.case_id, data.case_id, c['patient_ref'],
                    'escalation_followup', 'urgent' if c['state'].get('priority') == 'urgent' else 'review',
                    'CLINICIAN_ESCALATED', 900)
            if data.choice == 'approve':
                self.store.outbox_insert(c, c['state']['synthesis']['patient_draft'])
        return {'case_id':c['case_id'], 'status':c['status'], 'version':c['version'], 'sent_to_patient':False}

    def fail_closed(self, case_id, reason):
        with self.store.transaction():
            c = self.get(case_id)
            if c['status'] in ('RECEIVED','PROCESSING'):
                c['status'] = 'TECHNICAL_REVIEW'
                c['state']['flags'] = sorted(set(c['state']['flags'] + ['INFERENCE_OR_TOOL_FAILURE']))
                self.store.remove_image(c)
                self.store.save(c, 'FAIL_CLOSED', 'system', {'reason':reason[:60]})
                # Explicit human review task, including cases that fail before finalize.
                self.coordination.new_task('review:' + case_id, case_id, c['patient_ref'],
                    'clinical_review', 'review', 'TECHNICAL_FAILURE_REQUIRES_REVIEW', 900)

    def watchdog(self):
        now=time.time();changed=[]
        for item in self.store.list_cases():
            age=now-item['updated_at']
            with self.store.transaction():
                c=self.get(item['case_id'])
                if ((c['status'] in ('RECEIVED','PROCESSING') and now-c['updated_at']>600) or
                    (c['status']=='AWAITING_CLINICIAN' and now-c['updated_at']>1800)):
                    c['status']='ESCALATION_REQUIRED'
                    c['state']['flags']=sorted(set(c['state']['flags']+['SLA_EXCEEDED']))
                    self.store.remove_image(c)
                    self.store.save(c,'WATCHDOG_ESCALATION','watchdog',{'age_seconds':int(now-c['updated_at'])})
                    self.coordination.new_task('review:' + c['case_id'], c['case_id'], c['patient_ref'],
                        'clinical_review', 'review', 'SLA_EXCEEDED', 900)
                    changed.append(c['case_id'])
        return {'escalated_case_ids':changed,'count':len(changed)}
