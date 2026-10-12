"""2.0 closed-loop coordination on encrypted synthetic SQLite storage.

This module is a teaching reference, NOT a clinically validated triage engine.
All threshold values below are demo scheduling / data quality examples, not clinical thresholds.
"""
from __future__ import annotations
import json, sqlite3, time, uuid
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
    def __init__(self, store):
        self.s=store
        with self.s._lock:
            self.s.db.executescript('''
            CREATE TABLE IF NOT EXISTS observations(
                event_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL, code TEXT NOT NULL,
                taken_at REAL NOT NULL, payload_cipher TEXT NOT NULL, received_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_obs_patient_time ON observations(patient_ref,taken_at);
            CREATE TABLE IF NOT EXISTS checkins(
                event_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL,
                payload_cipher TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
                triaged_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_checkin_status ON checkins(status,created_at);
            CREATE TABLE IF NOT EXISTS monitoring_plans(
                patient_ref TEXT PRIMARY KEY, observation_code TEXT NOT NULL,
                review_gap_hours INTEGER NOT NULL, active INTEGER NOT NULL,
                approved_by TEXT NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS care_tasks(
                task_id TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE,
                case_id TEXT, patient_ref TEXT NOT NULL, kind TEXT NOT NULL,
                priority TEXT NOT NULL, status TEXT NOT NULL,
                assigned_to TEXT, reason_code TEXT NOT NULL,
                due_at REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                acknowledged_at REAL, resolved_at REAL, outcome TEXT,
                disposition_note_cipher TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_task_queue ON care_tasks(status,due_at);
            CREATE INDEX IF NOT EXISTS idx_task_patient ON care_tasks(patient_ref,created_at);
            CREATE TABLE IF NOT EXISTS patient_receipts(
                case_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL,
                acknowledged_at REAL NOT NULL
            );
            ''')

    def add_observation(self, patient_ref, event_id, code, value, unit, taken_at):
        lo,hi,expected=ALLOWED_CODES[code]
        if unit!=expected or not (lo<=value<=hi):raise ValueError('Unit or value outside accepted SYNTHETIC envelope')
        t=timestamp(taken_at)
        with self.s._lock:
            try:
                self.s.db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?)',
                   (event_id,patient_ref,code,t,self.s.enc({'value':value,'unit':unit,'taken_at':taken_at}),time.time()))
            except self.s.integrity_errors as e: raise ValueError('DUPLICATE_EVENT') from e
            self.s.audit('MONITORING','OBSERVATION_RECORDED',patient_ref,{'code':code,'synthetic':True})
        return {'event_id':event_id,'accepted':True,'patient_ref':patient_ref,'code':code}

    def summary(self,patient_ref, days=7):
        since=time.time()-days*86400
        with self.s._lock:
            rows=self.s.db.execute('SELECT code,taken_at,payload_cipher FROM observations WHERE patient_ref=? AND taken_at>=? ORDER BY taken_at',
                (patient_ref,since)).fetchall()
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
            self.s.db.execute('''INSERT INTO monitoring_plans VALUES(?,?,?,?,?,?)
            ON CONFLICT(patient_ref) DO UPDATE SET observation_code=excluded.observation_code,
            review_gap_hours=excluded.review_gap_hours,active=excluded.active,
            approved_by=excluded.approved_by,updated_at=excluded.updated_at''',
            (patient_ref,code,gap,int(active),actor,now))
            self.s.audit('MONITORING','MONITORING_PLAN_SET',actor,{'code':code,'active':active})
        return {'patient_ref':patient_ref,'code':code,'review_gap_hours':gap,'active':active,'approved_by':actor}

    def create_checkin(self, patient_ref, event_id, data):
        now=time.time()
        with self.s._lock:
            try:
                self.s.db.execute('INSERT INTO checkins VALUES(?,?,?,?,?,?)',
                    (event_id,patient_ref,self.s.enc(data),'PENDING',now,None))
            except self.s.integrity_errors as e:raise ValueError('DUPLICATE_EVENT') from e
            self.s.audit('CHECKIN','CHECKIN_RECEIVED',patient_ref,{'synthetic':True})
        return {'event_id':event_id,'status':'PENDING'}

    def triage_checkin(self, event_id):
        with self.s._lock:
            row=self.s.db.execute('SELECT * FROM checkins WHERE event_id=?',(event_id,)).fetchone()
            if not row:raise KeyError('CHECKIN_NOT_FOUND')
            if row['status']!='PENDING':return {'event_id':event_id,'status':row['status'],'idempotent':True}
            data=self.s.dec(row['payload_cipher']);symptoms=data.get('symptoms',{})
            if any(symptoms.get(s) for s in URGENT_SYMPTOMS):
                kind='reported_symptom_review'; priority='urgent'; reason='REPORTED_URGENT_SYMPTOM'
                self.new_task('checkin:'+event_id,None,row['patient_ref'],kind,priority,reason,300)
            else:
                priority='review';reason='CHECKIN_RECORDED'
            self.s.db.execute('UPDATE checkins SET status=?,triaged_at=? WHERE event_id=?',('TRIAGED',time.time(),event_id))
            self.s.audit('CHECKIN','CHECKIN_TRIAGED','policy',{'priority':priority,'reason':reason})
        return {'event_id':event_id,'status':'TRIAGED','priority':priority,'reason_code':reason}

    def new_task(self, source_key,case_id,patient_ref,kind,priority,reason,deadline_seconds):
        now=time.time(); tid='TASK-'+uuid.uuid4().hex[:16].upper()
        with self.s._lock:
            self.s.db.execute('''INSERT OR IGNORE INTO care_tasks
                (task_id,source_key,case_id,patient_ref,kind,priority,status,assigned_to,reason_code,due_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (tid,source_key,case_id,patient_ref,kind,priority,'OPEN',None,reason,now+deadline_seconds,now,now))
            row=self.s.db.execute('SELECT task_id FROM care_tasks WHERE source_key=?',(source_key,)).fetchone()
            if row['task_id']==tid:
                self.s.audit(case_id or 'MONITORING','TASK_CREATED','system',{'kind':kind,'priority':priority,'reason':reason})
            return row['task_id']

    def task_for_case(self,case_id):
        with self.s._lock:
            r=self.s.db.execute('SELECT * FROM care_tasks WHERE source_key=?',('review:'+case_id,)).fetchone()
        return dict(r) if r else None

    def tasks(self,limit=100,patient_refs=None):
        with self.s._lock:
            where=''
            args=[]
            if patient_refs is not None:
                if not patient_refs:return []
                where=' WHERE patient_ref IN ('+','.join('?' for _ in patient_refs)+')'
                args.extend(sorted(patient_refs))
            sql='''SELECT task_id,case_id,patient_ref,kind,priority,status,assigned_to,reason_code,
                due_at,created_at,updated_at,acknowledged_at,resolved_at,outcome
                FROM care_tasks'''+where+''' ORDER BY CASE WHEN status IN ('OPEN','OVERDUE') THEN 0 ELSE 1 END,
                CASE priority WHEN 'urgent' THEN 0 WHEN 'review' THEN 1 ELSE 2 END, due_at ASC LIMIT ?'''
            rows=self.s.db.execute(sql,tuple(args+[limit])).fetchall()
        return [dict(r) for r in rows]

    def get_task(self,task_id):
        with self.s._lock:
            r=self.s.db.execute('SELECT * FROM care_tasks WHERE task_id=?',(task_id,)).fetchone()
        if not r:raise KeyError('TASK_NOT_FOUND')
        return {k:v for k,v in dict(r).items() if k!='disposition_note_cipher'}

    def claim(self, task_id, actor):
        with self.s._lock:
            t=self.get_task(task_id)
            if t['status'] not in ('OPEN','OVERDUE','ACKNOWLEDGED'):raise ValueError('TASK_NOT_CLAIMABLE')
            if t['assigned_to'] and t['assigned_to']!=actor:raise ValueError('TASK_ASSIGNED_TO_SOMEONE_ELSE')
            if not t['assigned_to']:
                cur=self.s.db.execute('''UPDATE care_tasks SET status='ACKNOWLEDGED',assigned_to=?,
                    acknowledged_at=?,updated_at=? WHERE task_id=? AND assigned_to IS NULL AND status IN ('OPEN','OVERDUE')''',
                    (actor,time.time(),time.time(),task_id))
                if cur.rowcount!=1:raise ValueError('TASK_STATE_CONFLICT')
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
            self.s.db.execute('''UPDATE care_tasks SET status='COMPLETED',resolved_at=?,updated_at=?,outcome=?
               WHERE task_id=? AND status IN ('ACKNOWLEDGED','OVERDUE') AND assigned_to=?''',
               (time.time(),time.time(),choice,t['task_id'],actor))
            self.s.audit(case_id,'REVIEW_TASK_COMPLETED',actor,{'outcome':choice})

    def resolve(self,task_id,actor,outcome,note):
        with self.s._lock:
            t=self.get_task(task_id)
            if t['kind']=='clinical_review':raise ValueError('Clinical review task must use case decision endpoint')
            if t['assigned_to']!=actor or t['status'] not in ('ACKNOWLEDGED','OVERDUE'):
                raise ValueError('Only acknowledged task owner may resolve')
            # Unable to reach is not a closed-loop completed care outcome.
            state='OPEN' if outcome=='unable_to_reach' else 'COMPLETED'
            self.s.db.execute('''UPDATE care_tasks SET status=?,assigned_to=?,resolved_at=?,outcome=?,
                disposition_note_cipher=?,updated_at=? WHERE task_id=?''',
                (state,None if state=='OPEN' else actor,None if state=='OPEN' else time.time(),outcome,
                 self.s.enc({'note':note}),time.time(),task_id))
            self.s.audit(t['case_id'] or 'MONITORING','TASK_DISPOSITION',actor,{'outcome':outcome,'closed':state=='COMPLETED'})
            return self.get_task(task_id)

    def acknowledge_simulated(self,case_id,patient_ref):
        c=self.s.get(case_id)
        if c['patient_ref']!=patient_ref or c['status']!='APPROVED_SIMULATED':raise ValueError('No approved simulated message for patient')
        with self.s._lock:
            try:
                self.s.db.execute('INSERT INTO patient_receipts VALUES(?,?,?)',(case_id,patient_ref,time.time()))
            except self.s.integrity_errors as e:raise ValueError('Already acknowledged') from e
            self.s.audit(case_id,'PATIENT_SIMULATED_ACK',patient_ref,{'synthetic':True})
        return {'case_id':case_id,'acknowledged':True,'message_delivered':False}

    def watch(self):
        """Reconcile after workflow downtime. Returns IDs/status only, no PHI."""
        now=time.time();pending=[];due=[];overdue=[];recovered_reviews=[]
        with self.s._lock:
            for row in self.s.db.execute("SELECT event_id FROM checkins WHERE status='PENDING' LIMIT 100").fetchall():
                self.triage_checkin(row['event_id']);pending.append(row['event_id'])
            # Recover the human-review task even if the original finalization task insert failed,
            # or an older workflow failed into TECHNICAL_REVIEW / ESCALATION_REQUIRED.
            final_cases=self.s.db.execute("SELECT case_id,patient_ref,status FROM cases WHERE status IN ('AWAITING_CLINICIAN','ESCALATION_REQUIRED','TECHNICAL_REVIEW')").fetchall()
            for case in final_cases:
                key='review:'+case['case_id']
                existing=self.s.db.execute('SELECT task_id FROM care_tasks WHERE source_key=?',(key,)).fetchone()
                if not existing:
                    p='urgent' if case['status']=='ESCALATION_REQUIRED' else 'review'
                    reason='RECOVERED_UNASSIGNED_REVIEW'
                    tid=self.new_task(key,case['case_id'],case['patient_ref'],'clinical_review',p,reason,300 if p=='urgent' else 1800)
                    recovered_reviews.append(tid)
            plans=self.s.db.execute('SELECT * FROM monitoring_plans WHERE active=1').fetchall()
            for plan in plans:
                last=self.s.db.execute('SELECT MAX(taken_at) AS ts FROM observations WHERE patient_ref=? AND code=?',
                    (plan['patient_ref'],plan['observation_code'])).fetchone()['ts']
                age=now-(last or plan['updated_at'])
                if age>plan['review_gap_hours']*3600:
                    day=datetime.now(timezone.utc).strftime('%Y%m%d')
                    k='gap:'+plan['patient_ref']+':'+plan['observation_code']+':'+day
                    tid=self.new_task(k,None,plan['patient_ref'],'missing_measurement_review','review','MISSING_EXPECTED_DATA',3600)
                    due.append(tid)
            rows=self.s.db.execute("SELECT task_id,case_id,kind FROM care_tasks WHERE status IN ('OPEN','ACKNOWLEDGED') AND due_at<?",(now,)).fetchall()
            for row in rows:
                self.s.db.execute("UPDATE care_tasks SET status='OVERDUE',updated_at=? WHERE task_id=?",(now,row['task_id']))
                self.s.audit(row['case_id'] or 'MONITORING','TASK_SLA_EXCEEDED','watchdog',{'kind':row['kind']})
                overdue.append(row['task_id'])
        return {'reconciled_checkins':pending,'recovered_review_task_ids':recovered_reviews,
                'missing_data_task_ids':sorted(set(due)),
                'newly_overdue_task_ids':overdue,'warning':'Dashboard escalation only; no actual notification or paging.'}

    def metrics(self):
        with self.s._lock:
            tasks=self.s.db.execute('SELECT status,COUNT(*) n FROM care_tasks GROUP BY status').fetchall()
            checked=self.s.db.execute("SELECT COUNT(*) n FROM checkins WHERE status='TRIAGED'").fetchone()['n']
            readings=self.s.db.execute('SELECT COUNT(*) n FROM observations').fetchone()['n']
        return {'task_counts':{r['status']:r['n'] for r in tasks},'triaged_checkins':checked,
                'observation_count':readings,'no_clinical_performance_claim':True}
