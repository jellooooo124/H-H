"""SQL adapter for synthetic observations, check-ins, monitoring plans, care tasks and receipts.

This adapter owns all SQL queries; application Coordinator owns policy decisions and audits.
All transactions are controlled by the existing Store unit of work to preserve atomic behavior.
"""
from __future__ import annotations
import time
class SqlCoordinationRepository:
    def __init__(self,store):
        self.s=store
        with store._lock:
            store.db.executescript('''
            CREATE TABLE IF NOT EXISTS observations(
                event_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL, code TEXT NOT NULL,
                taken_at REAL NOT NULL, payload_cipher TEXT NOT NULL, received_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_obs_patient_time ON observations(patient_ref,taken_at);
            CREATE TABLE IF NOT EXISTS checkins(
                event_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL,
                payload_cipher TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,triaged_at REAL
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
                acknowledged_at REAL, resolved_at REAL, outcome TEXT, disposition_note_cipher TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_task_queue ON care_tasks(status,due_at);
            CREATE INDEX IF NOT EXISTS idx_task_patient ON care_tasks(patient_ref,created_at);
            CREATE TABLE IF NOT EXISTS patient_receipts(
                case_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL, acknowledged_at REAL NOT NULL
            );
            ''')

    def insert_observation(self,event_id,patient_ref,code,t,encrypted,now):
        self.s.db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?)',(event_id,patient_ref,code,t,encrypted,now))

    def observation_rows(self,patient_ref,since):
        with self.s._lock:
            rows=self.s.db.execute('SELECT code,taken_at,payload_cipher FROM observations WHERE patient_ref=? AND taken_at>=? ORDER BY taken_at',(patient_ref,since)).fetchall()
        return [dict(r) for r in rows]

    def save_plan(self,patient_ref,code,gap,active,actor,now):
        self.s.db.execute('''INSERT INTO monitoring_plans VALUES(?,?,?,?,?,?)
          ON CONFLICT(patient_ref) DO UPDATE SET observation_code=excluded.observation_code,
          review_gap_hours=excluded.review_gap_hours,active=excluded.active,
          approved_by=excluded.approved_by,updated_at=excluded.updated_at''',
          (patient_ref,code,gap,int(active),actor,now))

    def insert_checkin(self,event_id,patient_ref,encrypted,now):
        self.s.db.execute('INSERT INTO checkins VALUES(?,?,?,?,?,?)',(event_id,patient_ref,encrypted,'PENDING',now,None))

    def checkin(self,event_id):
        row=self.s.db.execute('SELECT * FROM checkins WHERE event_id=?',(event_id,)).fetchone()
        return dict(row) if row else None

    def triage_checkin(self,event_id,now):
        self.s.db.execute("UPDATE checkins SET status='TRIAGED',triaged_at=? WHERE event_id=?",(now,event_id))

    def create_task(self,tid,source_key,case_id,patient_ref,kind,priority,reason,now,deadline_seconds):
        self.s.db.execute('''INSERT OR IGNORE INTO care_tasks
             (task_id,source_key,case_id,patient_ref,kind,priority,status,assigned_to,reason_code,due_at,created_at,updated_at)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
             (tid,source_key,case_id,patient_ref,kind,priority,'OPEN',None,reason,now+deadline_seconds,now,now))
        row=self.s.db.execute('SELECT task_id FROM care_tasks WHERE source_key=?',(source_key,)).fetchone()
        return row['task_id']

    def task_for_source(self,key):
        with self.s._lock:
            row=self.s.db.execute('SELECT * FROM care_tasks WHERE source_key=?',(key,)).fetchone()
        return dict(row) if row else None

    def tasks(self,limit,patient_refs):
        with self.s._lock:
            where='';args=[]
            if patient_refs is not None:
                if not patient_refs:return []
                where=' WHERE patient_ref IN ('+','.join('?' for _ in patient_refs)+')'
                args.extend(sorted(patient_refs))
            sql='''SELECT task_id,case_id,patient_ref,kind,priority,status,assigned_to,reason_code,
             due_at,created_at,updated_at,acknowledged_at,resolved_at,outcome FROM care_tasks'''+where+'''
             ORDER BY CASE WHEN status IN ('OPEN','OVERDUE') THEN 0 ELSE 1 END,
             CASE priority WHEN 'urgent' THEN 0 WHEN 'review' THEN 1 ELSE 2 END,due_at ASC LIMIT ?'''
            rows=self.s.db.execute(sql,tuple(args+[limit])).fetchall()
        return [dict(r) for r in rows]

    def task(self,task_id):
        with self.s._lock:
            row=self.s.db.execute('SELECT * FROM care_tasks WHERE task_id=?',(task_id,)).fetchone()
        return dict(row) if row else None

    def claim_task(self,task_id,actor,now):
        return self.s.db.execute('''UPDATE care_tasks SET status='ACKNOWLEDGED',assigned_to=?,
          acknowledged_at=?,updated_at=? WHERE task_id=? AND assigned_to IS NULL AND status IN ('OPEN','OVERDUE')''',
          (actor,now,now,task_id)).rowcount==1

    def complete_review(self,task_id,actor,choice,now):
        return self.s.db.execute('''UPDATE care_tasks SET status='COMPLETED',resolved_at=?,updated_at=?,outcome=?
          WHERE task_id=? AND status IN ('ACKNOWLEDGED','OVERDUE') AND assigned_to=?''',
          (now,now,choice,task_id,actor)).rowcount==1

    def dispose(self,task_id,state,actor,outcome,note_cipher,now):
        self.s.db.execute('''UPDATE care_tasks SET status=?,assigned_to=?,resolved_at=?,outcome=?,
           disposition_note_cipher=?,updated_at=? WHERE task_id=?''',
           (state,None if state=='OPEN' else actor,None if state=='OPEN' else now,outcome,note_cipher,now,task_id))

    def insert_receipt(self,case_id,patient_ref,now):
        self.s.db.execute('INSERT INTO patient_receipts VALUES(?,?,?)',(case_id,patient_ref,now))

    def pending_checkins(self):
        return [r['event_id'] for r in self.s.db.execute("SELECT event_id FROM checkins WHERE status='PENDING' LIMIT 100").fetchall()]

    def unfinished_review_cases(self):
        rows=self.s.db.execute("SELECT case_id,patient_ref,status FROM cases WHERE status IN ('AWAITING_CLINICIAN','ESCALATION_REQUIRED','TECHNICAL_REVIEW')").fetchall()
        return [dict(r) for r in rows]

    def active_plans(self):
        return [dict(r) for r in self.s.db.execute('SELECT * FROM monitoring_plans WHERE active=1').fetchall()]

    def most_recent_reading(self,patient_ref,code):
        return self.s.db.execute('SELECT MAX(taken_at) AS ts FROM observations WHERE patient_ref=? AND code=?',(patient_ref,code)).fetchone()['ts']

    def newly_overdue(self,now):
        return [dict(r) for r in self.s.db.execute("SELECT task_id,case_id,kind FROM care_tasks WHERE status IN ('OPEN','ACKNOWLEDGED') AND due_at<?",(now,)).fetchall()]

    def mark_overdue(self,task_id,now):
        self.s.db.execute("UPDATE care_tasks SET status='OVERDUE',updated_at=? WHERE task_id=?",(now,task_id))

    def metrics(self):
        with self.s._lock:
            rows=self.s.db.execute('SELECT status,COUNT(*) n FROM care_tasks GROUP BY status').fetchall()
            triaged=self.s.db.execute("SELECT COUNT(*) n FROM checkins WHERE status='TRIAGED'").fetchone()['n']
            observations=self.s.db.execute('SELECT COUNT(*) n FROM observations').fetchone()['n']
        return {r['status']:r['n'] for r in rows},triaged,observations
