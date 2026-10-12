"""2.0 closed-loop coordination on encrypted synthetic SQLite storage.

This module is a teaching reference, NOT a clinically validated triage engine.
All threshold values below are demo scheduling / data quality examples, not clinical thresholds.
"""
from __future__ import annotations
import time, uuid
from datetime import datetime, timezone
from statistics import median

ALLOWED_CODES = {'weight_kg':(15,400,'kg'), 'glucose_mg_dl':(10,800,'mg/dL'),
                 'heart_rate_bpm':(20,250,'beats/min'), 'spo2_pct':(50,100,'%')}
URGENT_SYMPTOMS=('chest_pain','severe_breathlessness','fainting','confusion')


def timestamp(value: str) -> float:
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00'))
        if d.tzinfo is None:raise ValueError('UTC offset is mandatory')
        t=d.timestamp()
        if t>time.time()+300 or t<time.time()-90*86400:raise ValueError('Outside 90-day window / future timestamp')
        return t
    except (TypeError,ValueError) as e:
        raise ValueError('Invalid timezone-aware measurement timestamp') from e


class Coordinator:
    def __init__(self, store, repository=None):
        self.s=store
        if repository is None:
            from .infrastructure.persistence.coordination_repository import SqlCoordinationRepository
            repository=SqlCoordinationRepository(store)
        self.repo=repository

    def add_observation(self, patient_ref, event_id, code, value, unit, taken_at):
        lo,hi,expected=ALLOWED_CODES[code]
        if unit!=expected or not (lo<=value<=hi):raise ValueError('Unit or value outside accepted SYNTHETIC envelope')
        t=timestamp(taken_at)
        with self.s._lock:
            try:
                self.repo.insert_observation(event_id,patient_ref,code,t,
                                             self.s.enc({'value':value,'unit':unit,'taken_at':taken_at}),time.time())
            except self.s.integrity_errors as e: raise ValueError('DUPLICATE_EVENT') from e
            self.s.audit('MONITORING','OBSERVATION_RECORDED',patient_ref,{'code':code,'synthetic':True})
        return {'event_id':event_id,'accepted':True,'patient_ref':patient_ref,'code':code}

    def summary(self,patient_ref, days=7):
        since=time.time()-days*86400
        rows=self.repo.observation_rows(patient_ref,since)
        grouped={}
        for r in rows:
            grouped.setdefault(r['code'],[]).append({'at':r['taken_at'],'value':self.s.dec(r['payload_cipher'])['value']})
        results={}
        for code,arr in grouped.items():
            vals=[x['value'] for x in arr]
            results[code]={'count':len(vals),'first':vals[0],'latest':vals[-1],
                           'delta':round(vals[-1]-vals[0],3) if len(vals)>1 else None,
                           'median':round(median(vals),3),'points':arr[-30:]}
        return {'patient_ref':patient_ref,'window_days':days,'measurements':results,
                'warning':'Observed measurements only; missingness is not imputed and trends are not diagnoses.'}

    def set_plan(self, patient_ref, code, gap, actor, active=True):
        if code not in ALLOWED_CODES:raise ValueError('Unsupported measurement code')
        now=time.time()
        with self.s._lock:
            self.repo.save_plan(patient_ref,code,gap,active,actor,now)
            self.s.audit('MONITORING','MONITORING_PLAN_SET',actor,{'code':code,'active':active})
        return {'patient_ref':patient_ref,'code':code,'review_gap_hours':gap,'active':active,'approved_by':actor}

    def create_checkin(self, patient_ref, event_id, data):
        now=time.time()
        with self.s._lock:
            try:
                self.repo.insert_checkin(event_id,patient_ref,self.s.enc(data),now)
            except self.s.integrity_errors as e:raise ValueError('DUPLICATE_EVENT') from e
            self.s.audit('CHECKIN','CHECKIN_RECEIVED',patient_ref,{'synthetic':True})
        return {'event_id':event_id,'status':'PENDING'}

    def triage_checkin(self, event_id):
        with self.s._lock:
            row=self.repo.checkin(event_id)
            if not row:raise KeyError('CHECKIN_NOT_FOUND')
            if row['status']!='PENDING':return {'event_id':event_id,'status':row['status'],'idempotent':True}
            data=self.s.dec(row['payload_cipher']);symptoms=data.get('symptoms',{})
            if any(symptoms.get(s) for s in URGENT_SYMPTOMS):
                kind='reported_symptom_review'; priority='urgent'; reason='REPORTED_URGENT_SYMPTOM'
                self.new_task('checkin:'+event_id,None,row['patient_ref'],kind,priority,reason,300)
            else:
                priority='review';reason='CHECKIN_RECORDED'
            self.repo.triage_checkin(event_id,time.time())
            self.s.audit('CHECKIN','CHECKIN_TRIAGED','policy',{'priority':priority,'reason':reason})
        return {'event_id':event_id,'status':'TRIAGED','priority':priority,'reason_code':reason}

    def new_task(self, source_key,case_id,patient_ref,kind,priority,reason,deadline_seconds):
        now=time.time(); tid='TASK-'+uuid.uuid4().hex[:16].upper()
        with self.s._lock:
            actual=self.repo.create_task(tid,source_key,case_id,patient_ref,kind,priority,reason,now,deadline_seconds)
            if actual==tid:
                self.s.audit(case_id or 'MONITORING','TASK_CREATED','system',{'kind':kind,'priority':priority,'reason':reason})
            return actual

    def task_for_case(self,case_id):
        return self.repo.task_for_source('review:'+case_id)

    def tasks(self,limit=100,patient_refs=None):
        return self.repo.tasks(limit,patient_refs)

    def get_task(self,task_id):
        row=self.repo.task(task_id)
        if not row:raise KeyError('TASK_NOT_FOUND')
        return {k:v for k,v in row.items() if k!='disposition_note_cipher'}

    def claim(self, task_id, actor):
        with self.s._lock:
            t=self.get_task(task_id)
            if t['status'] not in ('OPEN','OVERDUE','ACKNOWLEDGED'):raise ValueError('TASK_NOT_CLAIMABLE')
            if t['assigned_to'] and t['assigned_to']!=actor:raise ValueError('TASK_ASSIGNED_TO_SOMEONE_ELSE')
            if not t['assigned_to']:
                if not self.repo.claim_task(task_id,actor,time.time()):raise ValueError('TASK_STATE_CONFLICT')
                self.s.audit(t['case_id'] or 'MONITORING','TASK_ACKNOWLEDGED',actor,{'kind':t['kind']})
            return self.get_task(task_id)

    def require_review_claim(self,case_id,actor):
        t=self.task_for_case(case_id)
        if not t or t['assigned_to']!=actor or t['status'] not in ('ACKNOWLEDGED','OVERDUE'):
            raise ValueError('REVIEW_TASK_MUST_BE_ACKNOWLEDGED_BY_ACTOR')
        return t

    def complete_review(self,case_id,actor,choice):
        t=self.require_review_claim(case_id,actor)
        with self.s._lock:
            self.repo.complete_review(t['task_id'],actor,choice,time.time())
            self.s.audit(case_id,'REVIEW_TASK_COMPLETED',actor,{'outcome':choice})

    def resolve(self,task_id,actor,outcome,note):
        with self.s._lock:
            t=self.get_task(task_id)
            if t['kind']=='clinical_review':raise ValueError('Clinical review task must use case decision endpoint')
            if t['assigned_to']!=actor or t['status'] not in ('ACKNOWLEDGED','OVERDUE'):
                raise ValueError('Only acknowledged task owner may resolve')
            # Unable to reach is not a closed-loop completed care outcome.
            state='OPEN' if outcome=='unable_to_reach' else 'COMPLETED'
            self.repo.dispose(task_id,state,actor,outcome,self.s.enc({'note':note}),time.time())
            self.s.audit(t['case_id'] or 'MONITORING','TASK_DISPOSITION',actor,{'outcome':outcome,'closed':state=='COMPLETED'})
            return self.get_task(task_id)

    def acknowledge_simulated(self,case_id,patient_ref):
        c=self.s.get(case_id)
        if c['patient_ref']!=patient_ref or c['status']!='APPROVED_SIMULATED':raise ValueError('No approved simulated message for patient')
        with self.s._lock:
            try:
                self.repo.insert_receipt(case_id,patient_ref,time.time())
            except self.s.integrity_errors as e:raise ValueError('Already acknowledged') from e
            self.s.audit(case_id,'PATIENT_SIMULATED_ACK',patient_ref,{'synthetic':True})
        return {'case_id':case_id,'acknowledged':True,'message_delivered':False}

    def watch(self):
        """Reconcile after workflow downtime. Returns IDs/status only, no PHI."""
        now=time.time();pending=[];due=[];overdue=[];recovered_reviews=[]
        with self.s._lock:
            for event_id in self.repo.pending_checkins():
                self.triage_checkin(event_id);pending.append(event_id)
            for case in self.repo.unfinished_review_cases():
                key='review:'+case['case_id']
                if not self.repo.task_for_source(key):
                    p='urgent' if case['status']=='ESCALATION_REQUIRED' else 'review'
                    tid=self.new_task(key,case['case_id'],case['patient_ref'],'clinical_review',p,
                                      'RECOVERED_UNASSIGNED_REVIEW',300 if p=='urgent' else 1800)
                    recovered_reviews.append(tid)
            for plan in self.repo.active_plans():
                last=self.repo.most_recent_reading(plan['patient_ref'],plan['observation_code'])
                age=now-(last or plan['updated_at'])
                if age>plan['review_gap_hours']*3600:
                    day=datetime.now(timezone.utc).strftime('%Y%m%d')
                    key='gap:'+plan['patient_ref']+':'+plan['observation_code']+':'+day
                    due.append(self.new_task(key,None,plan['patient_ref'],'missing_measurement_review',
                                             'review','MISSING_EXPECTED_DATA',3600))
            for row in self.repo.newly_overdue(now):
                self.repo.mark_overdue(row['task_id'],now)
                self.s.audit(row['case_id'] or 'MONITORING','TASK_SLA_EXCEEDED','watchdog',{'kind':row['kind']})
                overdue.append(row['task_id'])
        return {'reconciled_checkins':pending,'recovered_review_task_ids':recovered_reviews,
                'missing_data_task_ids':sorted(set(due)),
                'newly_overdue_task_ids':overdue,'warning':'Dashboard escalation only; no actual notification or paging.'}

    def metrics(self):
        tasks,checked,readings=self.repo.metrics()
        return {'task_counts':tasks,'triaged_checkins':checked,
                'observation_count':readings,'no_clinical_performance_claim':True}
