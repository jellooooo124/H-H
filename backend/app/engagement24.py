"""v2.4 synthetic patient engagement and alert-operations layer.

No patient-facing messages are sent. Prompts are in-app simulation records only.
Alerts are READ-ONLY views of care tasks: never suppress, downgrade or merge clinical work.
Times are UTC. This module is not clinically validated.
"""
from __future__ import annotations
import json, statistics, time, uuid
from datetime import datetime, timezone

class Engagement:
    def __init__(self,store,coordinator):
        self.s=store;self.c=coordinator
        with self.s._lock:
            self.s.db.executescript('''
            CREATE TABLE IF NOT EXISTS patient_engagement_preferences(
              patient_ref TEXT PRIMARY KEY, reminder_opt_in INTEGER NOT NULL,
              reminder_hour_utc INTEGER NOT NULL, minimum_gap_hours INTEGER NOT NULL,
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS simulated_prompts(
              prompt_id TEXT PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE,
              patient_ref TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
              created_at REAL NOT NULL, seen_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_prompt_patient ON simulated_prompts(patient_ref,created_at);
            CREATE TABLE IF NOT EXISTS operational_snapshots(
              snapshot_hour TEXT PRIMARY KEY, created_at REAL NOT NULL, payload_json TEXT NOT NULL
            );
            ''')
            self.s.db.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)',(24,time.time()))

    def preferences(self,patient_ref):
        with self.s._lock:
            row=self.s.db.execute('''SELECT reminder_opt_in,reminder_hour_utc,minimum_gap_hours,updated_at
                 FROM patient_engagement_preferences WHERE patient_ref=?''',(patient_ref,)).fetchone()
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
            self.s.db.execute('''INSERT INTO patient_engagement_preferences VALUES(?,?,?,?,?)
               ON CONFLICT(patient_ref) DO UPDATE SET reminder_opt_in=excluded.reminder_opt_in,
               reminder_hour_utc=excluded.reminder_hour_utc,minimum_gap_hours=excluded.minimum_gap_hours,
               updated_at=excluded.updated_at''',(patient_ref,int(opt_in),hour,gap,now))
            if not opt_in:
                self.s.db.execute('''UPDATE simulated_prompts SET state='CANCELLED'
                   WHERE patient_ref=? AND state='PENDING_SIMULATED' ''',(patient_ref,))
            self.s.audit('ENGAGEMENT','PATIENT_PREFERENCE_UPDATED','synthetic-patient',{'opt_in':opt_in})
        return self.preferences(patient_ref)

    def prompts(self,patient_ref):
        with self.s._lock:
            rows=self.s.db.execute('''SELECT prompt_id,kind,state,created_at,seen_at FROM simulated_prompts
                  WHERE patient_ref=? ORDER BY created_at DESC LIMIT 30''',(patient_ref,)).fetchall()
        return [dict(x) for x in rows]

    def mark_seen(self,patient_ref,prompt_id):
        with self.s.transaction():
            row=self.s.db.execute('SELECT patient_ref,state FROM simulated_prompts WHERE prompt_id=?',(prompt_id,)).fetchone()
            if not row or row['patient_ref']!=patient_ref:raise KeyError('PROMPT_NOT_FOUND')
            if row['state']=='SEEN':return {'prompt_id':prompt_id,'state':'SEEN','idempotent':True}
            if row['state']!='PENDING_SIMULATED':raise ValueError('PROMPT_NO_LONGER_ACTIVE')
            self.s.db.execute('UPDATE simulated_prompts SET state=?,seen_at=? WHERE prompt_id=? AND state=?',
                              ('SEEN',time.time(),prompt_id,'PENDING_SIMULATED'))
            self.s.audit('ENGAGEMENT','SIMULATED_PROMPT_SEEN','synthetic-patient',{'synthetic':True})
        return {'prompt_id':prompt_id,'state':'SEEN','delivered_to_patient':False}

    def dashboard(self,patient_ref,days=7):
        now=time.time(); cutoff=now-days*86400
        trends=self.c.summary(patient_ref,days)
        with self.s._lock:
            checkins=self.s.db.execute('''SELECT event_id,status,created_at,triaged_at FROM checkins
              WHERE patient_ref=? AND created_at>=? ORDER BY created_at DESC LIMIT 20''',(patient_ref,cutoff)).fetchall()
            plan=self.s.db.execute('''SELECT observation_code,review_gap_hours,active,updated_at
                   FROM monitoring_plans WHERE patient_ref=?''',(patient_ref,)).fetchone()
            receipts=self.s.db.execute('''SELECT case_id,acknowledged_at FROM patient_receipts
                   WHERE patient_ref=? AND acknowledged_at>=? ORDER BY acknowledged_at DESC LIMIT 20''',(patient_ref,cutoff)).fetchall()
        return {'patient_ref':patient_ref,'window_days':days,'observations':trends['measurements'],
                'checkins':[dict(x) for x in checkins], 'monitoring_plan':dict(plan) if plan else None,
                'simulated_receipts':[dict(x) for x in receipts],
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
            prefs=self.s.db.execute('''SELECT p.patient_ref,p.reminder_hour_utc,p.minimum_gap_hours
                FROM patient_engagement_preferences p JOIN monitoring_plans m ON m.patient_ref=p.patient_ref
                WHERE p.reminder_opt_in=1 AND m.active=1''').fetchall()
            for p in prefs:
                if hour<p['reminder_hour_utc']:continue
                latest=self.s.db.execute('SELECT MAX(created_at) AS ts FROM checkins WHERE patient_ref=?',
                                         (p['patient_ref'],)).fetchone()['ts']
                if latest is not None and now-latest<p['minimum_gap_hours']*3600:continue
                key='checkin:'+p['patient_ref']+':'+today
                pid='PROMPT-'+uuid.uuid4().hex[:16].upper()
                cur=self.s.db.execute('''INSERT OR IGNORE INTO simulated_prompts VALUES(?,?,?,?,?,?,?)''',
                   (pid,key,p['patient_ref'],'DAILY_CHECKIN','PENDING_SIMULATED',now,None))
                if cur.rowcount==1:
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
        with self.s._lock:
            rows=self.s.db.execute('''SELECT status,priority,created_at,acknowledged_at,resolved_at,due_at,kind
                 FROM care_tasks WHERE patient_ref=? AND created_at>=?''',(patient_ref,cutoff)).fetchall()
            obs=self.s.db.execute('SELECT COUNT(*) n FROM observations WHERE patient_ref=? AND received_at>=?',
                                  (patient_ref,cutoff)).fetchone()['n']
            check=self.s.db.execute('SELECT COUNT(*) n FROM checkins WHERE patient_ref=? AND created_at>=?',
                                    (patient_ref,cutoff)).fetchone()['n']
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
            counts=self.s.db.execute('''SELECT priority,status,COUNT(*) n FROM care_tasks GROUP BY priority,status''').fetchall()
            prefs=self.s.db.execute('SELECT COUNT(*) n FROM patient_engagement_preferences WHERE reminder_opt_in=1').fetchone()['n']
            prompt_count=self.s.db.execute('SELECT COUNT(*) n FROM simulated_prompts').fetchone()['n']
            meta={'task_buckets':{r['priority']+':'+r['status']:r['n'] for r in counts},
                  'opted_in_patient_count':prefs,'simulated_prompt_count':prompt_count,
                  'actual_message_delivery_count':0,'clinical_utility_validated':False}
            self.s.db.execute('INSERT OR IGNORE INTO operational_snapshots VALUES(?,?,?)',
                              (hour,now,json.dumps(meta,sort_keys=True)))
        return {'snapshot_hour':hour,'captured':True,'aggregate_only':True,'metrics':meta}
