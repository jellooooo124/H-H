"""SQL adapter for clinician shifts, handoff state, and non-PHI task timeline."""
from __future__ import annotations
import json,time
class SqlHandoffRepository:
    def __init__(self,store):
        self.s=store
        with self.s._lock:
            self.s.db.executescript('''
            CREATE TABLE IF NOT EXISTS duty_shifts(
              shift_id TEXT PRIMARY KEY, clinician_sub TEXT NOT NULL, patient_ref TEXT NOT NULL,
              starts_at REAL NOT NULL, ends_at REAL NOT NULL, created_at REAL NOT NULL, cancelled_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_duty ON duty_shifts(patient_ref,ends_at);
            CREATE TABLE IF NOT EXISTS task_handoffs(
              handoff_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, patient_ref TEXT NOT NULL,
              from_sub TEXT NOT NULL, to_sub TEXT NOT NULL, reason_cipher TEXT NOT NULL,
              status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_handoff_queue ON task_handoffs(status,expires_at);
            CREATE TABLE IF NOT EXISTS care_timeline(
              event_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL, task_id TEXT,
              event_code TEXT NOT NULL, actor TEXT NOT NULL, occurred_at REAL NOT NULL, metadata TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_care_timeline ON care_timeline(patient_ref,occurred_at);
            ''')
            self.s.db.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)',(23,time.time()))

    def record(self,event_id,patient_ref,task_id,event_code,actor,at,metadata):
        self.s.db.execute('INSERT INTO care_timeline VALUES(?,?,?,?,?,?,?)',
                          (event_id,patient_ref,task_id,event_code,actor,at,json.dumps(metadata or {})))

    def insert_shift(self,sid,sub,patient_ref,begin,end,now):
        self.s.db.execute('INSERT INTO duty_shifts VALUES(?,?,?,?,?,?,?)',(sid,sub,patient_ref,begin,end,now,None))

    def shift(self,shift_id):
        row=self.s.db.execute('SELECT * FROM duty_shifts WHERE shift_id=?',(shift_id,)).fetchone()
        return dict(row) if row else None

    def cancel_shift(self,shift_id,now):
        self.s.db.execute('UPDATE duty_shifts SET cancelled_at=? WHERE shift_id=?',(now,shift_id))

    def roster(self,patient_ref,now):
        with self.s._lock:
            rows=self.s.db.execute('''SELECT shift_id,clinician_sub,starts_at,ends_at FROM duty_shifts
                WHERE patient_ref=? AND cancelled_at IS NULL AND ends_at>? ORDER BY starts_at LIMIT 100''',(patient_ref,now)).fetchall()
        return [dict(r) for r in rows]

    def on_shift(self,sub,patient_ref,now):
        row=self.s.db.execute('''SELECT shift_id FROM duty_shifts WHERE clinician_sub=? AND patient_ref=?
                AND starts_at<=? AND ends_at>? AND cancelled_at IS NULL LIMIT 1''',(sub,patient_ref,now,now)).fetchone()
        return row is not None

    def pending(self,task_id):
        return self.s.db.execute("SELECT 1 FROM task_handoffs WHERE task_id=? AND status='OFFERED'",(task_id,)).fetchone() is not None

    def offer(self,hid,task_id,patient_ref,from_sub,to_sub,reason,now,expires):
        self.s.db.execute('INSERT INTO task_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)',
             (hid,task_id,patient_ref,from_sub,to_sub,self.s.enc({'reason':reason}), 'OFFERED',now,now,expires))

    def handoff(self,hid):
        with self.s._lock:
            row=self.s.db.execute('''SELECT handoff_id,task_id,patient_ref,from_sub,to_sub,
                status,created_at,updated_at,expires_at FROM task_handoffs WHERE handoff_id=?''',(hid,)).fetchone()
        return dict(row) if row else None

    def inbox(self,sub,patient_refs):
        with self.s._lock:
            params=[sub];scope=''
            if patient_refs is not None:
                if not patient_refs:return []
                scope=' AND patient_ref IN ('+','.join('?' for _ in patient_refs)+')'
                params.extend(sorted(patient_refs))
            rows=self.s.db.execute('''SELECT handoff_id,task_id,patient_ref,from_sub,to_sub,status,
                created_at,expires_at FROM task_handoffs WHERE to_sub=? AND status='OFFERED' '''+scope+
                ' ORDER BY created_at ASC LIMIT 100',tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def transfer_task(self,task_id,from_sub,to_sub,now):
        return self.s.db.execute('''UPDATE care_tasks SET assigned_to=?,updated_at=? WHERE task_id=?
             AND assigned_to=? AND status IN ('ACKNOWLEDGED','OVERDUE')''',
             (to_sub,now,task_id,from_sub)).rowcount==1

    def update_handoff(self,hid,state,now):
        self.s.db.execute('UPDATE task_handoffs SET status=?,updated_at=? WHERE handoff_id=?',(state,now,hid))

    def expired(self,now):
        rows=self.s.db.execute("SELECT handoff_id,patient_ref,task_id FROM task_handoffs WHERE status='OFFERED' AND expires_at<?",(now,)).fetchall()
        return [dict(r) for r in rows]

    def timeline(self,patient_ref,limit):
        with self.s._lock:
            rows=self.s.db.execute('''SELECT event_id,task_id,event_code,actor,occurred_at,metadata
                FROM care_timeline WHERE patient_ref=? ORDER BY occurred_at DESC LIMIT ?''',(patient_ref,limit)).fetchall()
        return [{**dict(r),'metadata':json.loads(r['metadata'])} for r in rows]
