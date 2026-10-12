"""v2.4 synthetic patient engagement and alert-operations layer.

No patient-facing messages are sent. Prompts are in-app simulation records only.
Alerts are READ-ONLY views of care tasks: never suppress, downgrade or merge clinical work.
Times are UTC. This module is not clinically validated.
"""
from __future__ import annotations
import statistics, time, uuid
from datetime import datetime, timezone

class Engagement:
    def __init__(self,store,coordinator,repository=None):
        self.s=store;self.c=coordinator
        if repository is None:
            from .infrastructure.persistence.engagement_repository import SqlEngagementRepository
            repository=SqlEngagementRepository(store)
        self.repo=repository

    def preferences(self,patient_ref):
        row=self.repo.preference_row(patient_ref)
        if not row:
            return {'patient_ref':patient_ref,'reminder_opt_in':False,'reminder_hour_utc':8,'minimum_gap_hours':24,
                    'default_opt_out':True,'synthetic_only':True}
        return {'patient_ref':patient_ref,'reminder_opt_in':bool(row['reminder_opt_in']),
                'reminder_hour_utc':row['reminder_hour_utc'],'minimum_gap_hours':row['minimum_gap_hours'],
                'updated_at':row['updated_at'],'synthetic_only':True}

    def set_preferences(self,patient_ref,opt_in,hour,gap):
        if not (0<=hour<=23 and 24<=gap<=168):raise ValueError('INVALID_REMINDER_PREFERENCE')
        now=time.time()
        with self.s.transaction():
            self.repo.save_preferences(patient_ref,opt_in,hour,gap,now)
            if not opt_in:self.repo.cancel_pending(patient_ref)
            self.s.audit('ENGAGEMENT','PATIENT_PREFERENCE_UPDATED','synthetic-patient',{'opt_in':opt_in})
        return self.preferences(patient_ref)

    def prompts(self,patient_ref):
        return self.repo.prompts(patient_ref)

    def mark_seen(self,patient_ref,prompt_id):
        with self.s.transaction():
            row=self.repo.prompt(prompt_id)
            if not row or row['patient_ref']!=patient_ref:raise KeyError('PROMPT_NOT_FOUND')
            if row['state']=='SEEN':return {'prompt_id':prompt_id,'state':'SEEN','idempotent':True}
            if row['state']!='PENDING_SIMULATED':raise ValueError('PROMPT_NO_LONGER_ACTIVE')
            if not self.repo.mark_seen(prompt_id,time.time()):raise ValueError('PROMPT_STATE_CONFLICT')
            self.s.audit('ENGAGEMENT','SIMULATED_PROMPT_SEEN','synthetic-patient',{'synthetic':True})
        return {'prompt_id':prompt_id,'state':'SEEN','delivered_to_patient':False}

    def dashboard(self,patient_ref,days=7):
        now=time.time(); cutoff=now-days*86400
        trends=self.c.summary(patient_ref,days)
        checkins,plan,receipts=self.repo.dashboard_rows(patient_ref,cutoff)
        return {'patient_ref':patient_ref,'window_days':days,'observations':trends['measurements'],
                'checkins':checkins, 'monitoring_plan':plan,
                'simulated_receipts':receipts,
                'reminder_preferences':self.preferences(patient_ref),'in_app_prompts':self.prompts(patient_ref),
                'warning':'SYNTHETIC ONLY. No diagnoses, recommendations, actual messages, or clinical escalation guarantees.'}

    def reminder_watch(self,at=None):
        """Materialize opt-in in-app prompts, once per UTC calendar date.

        Explicit opt-in AND an active monitoring plan AND no recent check-in required.
        No network dispatch, SMS, email or clinical escalation. Safe on repeated calls.
        """
        now=at if at is not None else time.time()
        today=datetime.fromtimestamp(now,timezone.utc).strftime('%Y%m%d')
        hour=datetime.fromtimestamp(now,timezone.utc).hour
        created=0
        with self.s.transaction():
            prefs=self.repo.opted_in_plans()
            for p in prefs:
                if hour<p['reminder_hour_utc']:continue
                latest=self.repo.latest_checkin(p['patient_ref'])
                if latest is not None and now-latest<p['minimum_gap_hours']*3600:continue
                key='checkin:'+p['patient_ref']+':'+today
                pid='PROMPT-'+uuid.uuid4().hex[:16].upper()
                if self.repo.insert_prompt(pid,key,p['patient_ref'],now):
                    created+=1
                    self.s.audit('ENGAGEMENT','IN_APP_PROMPT_CREATED','scheduler',{'synthetic':True})
        return {'created_count':created,'messages_sent':0,'synthetic_only':True,'personal_data_in_response':False}

    def alert_groups(self,patient_refs=None):
        """Display-only coalescing: every original task stays actionable in the task queue."""
        tasks=self.c.tasks(limit=500,patient_refs=patient_refs)
        active=[t for t in tasks if t['status'] in ('OPEN','ACKNOWLEDGED','OVERDUE')]
        grouped={}
        for t in active:
            # URGENT tasks never coalesce, nor any task under an escalation.
            key=(t['task_id'],) if t['priority']=='urgent' or t['kind'] in ('clinical_review','escalation_followup') else (t['patient_ref'],t['kind'],t['reason_code'])
            if key not in grouped:
                grouped[key]={'patient_ref':t['patient_ref'],'kind':t['kind'],'reason_code':t['reason_code'],
                              'priority':t['priority'],'earliest_due_at':t['due_at'],'task_ids':[],
                              'overdue':False}
            v=grouped[key]
            v['task_ids'].append(t['task_id']);v['earliest_due_at']=min(v['earliest_due_at'],t['due_at'])
            v['overdue']=v['overdue'] or t['status']=='OVERDUE'
        result=list(grouped.values())
        result.sort(key=lambda v:(0 if v['priority']=='urgent' else 1,0 if v['overdue'] else 1,v['earliest_due_at']))
        return {'groups':result,'raw_active_task_count':len(active),'display_group_count':len(result),
                'suppressed_task_count':0,'grouping_is_display_only':True,
                'result_window_limit':500,'potentially_truncated':len(tasks)>=500,
                'warning':'Not an AI clinical risk score. All original tasks remain visible and actionable.'}

    def evaluation(self,patient_ref,days=7):
        now=time.time();cutoff=now-days*86400
        rows,obs,check=self.repo.evaluation_rows(patient_ref,cutoff)
        latency=[r['acknowledged_at']-r['created_at'] for r in rows if r['acknowledged_at'] is not None]
        m={'window_days':days,'task_created_count':len(rows),'task_completed_count':sum(r['status']=='COMPLETED' for r in rows),
           'task_overdue_current_count':sum(r['status']=='OVERDUE' for r in rows),
           'urgent_task_count':sum(r['priority']=='urgent' for r in rows),
           'median_ack_minutes':round(statistics.median(latency)/60,2) if latency else None,
           'observations_received':obs,'checkins_received':check,
           'no_sensitivity_specificity_or_clinical_effectiveness_claim':True}
        return {'patient_ref':patient_ref,'metrics':m,'limitations':['Synthetic records only','Counts are not adjusted for patient-days, case-mix, or missing ground truth',
                'Urgent is a demo workflow priority, not a validated diagnosis']}

    def snapshot(self,at=None):
        now=at if at is not None else time.time()
        hour=datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%dT%H:00Z')
        with self.s.transaction():
            buckets,prefs,prompt_count=self.repo.snapshot_counts()
            meta={'task_buckets':buckets,
                  'opted_in_patient_count':prefs,'simulated_prompt_count':prompt_count,
                  'actual_message_delivery_count':0,'clinical_utility_validated':False}
            self.repo.insert_snapshot(hour,now,meta)
        return {'snapshot_hour':hour,'captured':True,'aggregate_only':True,'metrics':meta}
