"""2.3 synthetic-only on-call handoff and durable orchestration dispatch.

No on-call paging, clinical advice, or patient notification. n8n only receives opaque IDs.
Database CAS is used for state transitions; demo single-worker PostgresCompat isn't a cluster queue.
"""
from __future__ import annotations
import json, time, uuid
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


def parse_clock(v: str) -> float:
    try:
        d=datetime.fromisoformat(v.replace('Z','+00:00'))
        if d.tzinfo is None:raise ValueError('Timezone offset required')
        return d.timestamp()
    except (TypeError, ValueError) as e:raise ValueError('Invalid timezone-aware clock') from e

class ShiftIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    patient_ref:str=Field(pattern=r'^DEMO-[A-Za-z0-9_-]{3,45}$')
    starts_at:str=Field(max_length=40)
    ends_at:str=Field(max_length=40)

class HandoffIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    to_clinician_sub:str=Field(min_length=2,max_length=150,pattern=r'^[A-Za-z0-9_.:@-]+$')
    reason:str=Field(min_length=12,max_length=500)

class QueueJob:
    MAX_ATTEMPTS=4
    def __init__(self,store):
        self.s=store
        with self.s._lock:self.s.db.executescript('''
        CREATE TABLE IF NOT EXISTS dispatch_jobs(
            job_id TEXT PRIMARY KEY, job_key TEXT NOT NULL UNIQUE,
            job_kind TEXT NOT NULL, reference_id TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            next_run_at REAL NOT NULL, lease_until REAL, last_error_code TEXT,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dispatch_due ON dispatch_jobs(status,next_run_at);
        ''')

    def enqueue(self,kind,ref):
        if kind not in ('CASE_DISPATCH','CHECKIN_DISPATCH'):raise ValueError('INVALID_JOB_KIND')
        # Identifier is already validated by the respective external Pydantic schema.
        key=kind+':'+ref; now=time.time();jid='JOB-'+uuid.uuid4().hex[:16].upper()
        with self.s.transaction():
            self.s.db.execute('''INSERT OR IGNORE INTO dispatch_jobs(job_id,job_key,job_kind,reference_id,status,
                attempts,next_run_at,lease_until,last_error_code,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (jid,key,kind,ref,'PENDING',0,now,None,None,now,now))
            row=self.s.db.execute('SELECT job_id FROM dispatch_jobs WHERE job_key=?',(key,)).fetchone()
            if row['job_id']==jid:self.s.audit('SYSTEM','DELIVERY_JOB_ENQUEUED','queue',{'kind':kind})
        return row['job_id']

    def delivered(self,kind,ref):
        with self.s.transaction():
            self.s.db.execute("""UPDATE dispatch_jobs SET status='DELIVERED',lease_until=NULL,updated_at=?
             WHERE job_key=? AND status IN ('PENDING','LEASED')""",(time.time(),kind+':'+ref))

    def claim(self):
        # Lease is reclaimable; at-least-once, NOT exactly-once delivery.
        now=time.time()
        with self.s.transaction():
            row=self.s.db.execute('''SELECT * FROM dispatch_jobs WHERE
                 (status='PENDING' AND next_run_at<=?) OR (status='LEASED' AND lease_until<=? AND attempts<?)
                 ORDER BY next_run_at,created_at LIMIT 1''',(now,now,self.MAX_ATTEMPTS)).fetchone()
            if not row:return None
            cur=self.s.db.execute('''UPDATE dispatch_jobs SET status='LEASED', lease_until=?,attempts=attempts+1,
                updated_at=? WHERE job_id=? AND ((status='PENDING' AND next_run_at<=?) OR
                (status='LEASED' AND lease_until<=?))''',(now+120,now,row['job_id'],now,now))
            if cur.rowcount!=1:return None
            return dict(self.s.db.execute('SELECT * FROM dispatch_jobs WHERE job_id=?',(row['job_id'],)).fetchone())

    def failed(self,jid,code):
        if code not in ('WEBHOOK_UNAVAILABLE','DISPATCH_EXCEPTION','LEASE_EXPIRED','BAD_REFERENCE'):
            code='DISPATCH_EXCEPTION'
        now=time.time()
        with self.s.transaction():
            row=self.s.db.execute('SELECT * FROM dispatch_jobs WHERE job_id=?',(jid,)).fetchone()
            if not row or row['status']!='LEASED':return None
            dead=row['attempts']>=self.MAX_ATTEMPTS
            newstatus='DEAD' if dead else 'PENDING'
            # 1,2,4 minute bounded backoff; no plaintext exception is stored.
            delay=min(240,60*(2**max(0,row['attempts']-1)))
            self.s.db.execute('''UPDATE dispatch_jobs SET status=?,next_run_at=?,lease_until=NULL,last_error_code=?,updated_at=?
                WHERE job_id=?''',(newstatus,now+delay,code,now,jid))
            self.s.audit('SYSTEM','DISPATCH_JOB_DEAD' if dead else 'DISPATCH_JOB_RETRY','queue',{'kind':row['job_kind'],'attempts':row['attempts']})
            return {'status':newstatus,'attempts':row['attempts'],'kind':row['job_kind'],'reference_id':row['reference_id']}

    def reap_exhausted_leases(self):
        """Crashed worker after its final attempt must not silently loop forever."""
        now=time.time();dead=[]
        with self.s.transaction():
            rows=self.s.db.execute("""SELECT job_id,job_kind,reference_id FROM dispatch_jobs
              WHERE status='LEASED' AND lease_until<=? AND attempts>=? LIMIT 40""",
              (now,self.MAX_ATTEMPTS)).fetchall()
            for r in rows:
                self.s.db.execute("""UPDATE dispatch_jobs SET status='DEAD',lease_until=NULL,
                    last_error_code='LEASE_EXPIRED',updated_at=? WHERE job_id=?""",(now,r['job_id']))
                dead.append(dict(r))
                self.s.audit('SYSTEM','DISPATCH_LEASE_EXHAUSTED','queue',{'kind':r['job_kind']})
        return dead

    def recover_accepted(self, min_age=600):
        now=time.time();rearmed=[];dead=[]
        with self.s.transaction():
            rows=self.s.db.execute('''SELECT j.job_id,j.reference_id,j.attempts
                FROM dispatch_jobs j JOIN cases c ON c.case_id=j.reference_id
                WHERE j.job_kind='CASE_DISPATCH' AND j.status='DELIVERED'
                    AND c.status='RECEIVED' AND j.updated_at<? LIMIT 20''',(now-min_age,)).fetchall()
            for r in rows:
                exhausted=r['attempts']>=self.MAX_ATTEMPTS
                self.s.db.execute('''UPDATE dispatch_jobs SET status=?,next_run_at=?,updated_at=?
                    WHERE job_id=?''',('DEAD' if exhausted else 'PENDING',now,now,r['job_id']))
                (dead if exhausted else rearmed).append((r['job_id'],r['reference_id']))
                self.s.audit('SYSTEM','WEBHOOK_ACK_NOT_COMPLETED','queue',{'exhausted':exhausted})
        return {'rearmed':rearmed,'dead':dead}

    def counts(self):
        with self.s._lock:rows=self.s.db.execute('SELECT status,COUNT(*) n FROM dispatch_jobs GROUP BY status').fetchall()
        return {r['status']:r['n'] for r in rows}

    def list_jobs(self,limit=40):
        with self.s._lock:rows=self.s.db.execute('''SELECT job_id,job_kind,status,attempts,next_run_at,
          last_error_code,updated_at FROM dispatch_jobs ORDER BY updated_at DESC LIMIT ?''',(limit,)).fetchall()
        return [dict(r) for r in rows] # no reference IDs/case metadata

class ShiftHandoff:
    def __init__(self,store,coordinator):
        self.s=store;self.c=coordinator
        with self.s._lock:self.s.db.executescript('''
        CREATE TABLE IF NOT EXISTS duty_shifts(
          shift_id TEXT PRIMARY KEY, clinician_sub TEXT NOT NULL, patient_ref TEXT NOT NULL,
          starts_at REAL NOT NULL, ends_at REAL NOT NULL, created_at REAL NOT NULL,
          cancelled_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_duty ON duty_shifts(patient_ref,ends_at);
        CREATE TABLE IF NOT EXISTS task_handoffs(
          handoff_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, patient_ref TEXT NOT NULL,
          from_sub TEXT NOT NULL, to_sub TEXT NOT NULL, reason_cipher TEXT NOT NULL,
          status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
          expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_handoff_queue ON task_handoffs(status,expires_at);
        CREATE TABLE IF NOT EXISTS care_timeline(
          event_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL, task_id TEXT,
          event_code TEXT NOT NULL, actor TEXT NOT NULL, occurred_at REAL NOT NULL,
          metadata TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_care_timeline ON care_timeline(patient_ref,occurred_at);
        ''')
        with self.s._lock:
            self.s.db.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)',(23,time.time()))

    def record(self, patient_ref, task_id, event_code, actor, metadata=None):
        # metadata must contain no PHI, reason text or clinical interpretation.
        allowed={'HANDOFF_OFFERED','HANDOFF_ACCEPTED','HANDOFF_REJECTED',
                 'HANDOFF_EXPIRED','SHIFT_REGISTERED','SHIFT_CANCELLED','TASK_CLAIMED',
                 'TASK_RESOLVED','CASE_DECISION','PATIENT_RECEIPT','TASK_SLA_VISIBLE'}
        if event_code not in allowed:raise ValueError('Unsupported timeline event')
        with self.s.transaction():
            self.s.db.execute('INSERT INTO care_timeline VALUES(?,?,?,?,?,?,?)',
                ('EVT-'+uuid.uuid4().hex[:16].upper(),patient_ref,task_id,event_code,actor,time.time(),json.dumps(metadata or {})))
            self.s.audit('OPERATIONS',event_code,actor,{'synthetic':True})

    def shift(self,sub,patient_ref,starts_at,ends_at):
        begin=parse_clock(starts_at);end=parse_clock(ends_at);now=time.time()
        if begin>now+14*86400 or end<=now or end-begin>24*3600 or end-begin<900:
            raise ValueError('SHIFT_OUTSIDE_DEMO_LIMITS')
        sid='SHIFT-'+uuid.uuid4().hex[:16].upper()
        with self.s.transaction():
            self.s.db.execute('INSERT INTO duty_shifts VALUES(?,?,?,?,?,?,?)',
                (sid,sub,patient_ref,begin,end,now,None))
            self.record(patient_ref,None,'SHIFT_REGISTERED',sub)
        return {'shift_id':sid,'patient_ref':patient_ref,'starts_at':begin,'ends_at':end,'synthetic_only':True}

    def cancel_shift(self,shift_id,actor):
        with self.s.transaction():
            r=self.s.db.execute('SELECT * FROM duty_shifts WHERE shift_id=?',(shift_id,)).fetchone()
            if not r:raise KeyError('SHIFT_NOT_FOUND')
            if r['clinician_sub']!=actor:raise ValueError('SHIFT_OWNER_ONLY')
            if r['cancelled_at'] is not None:raise ValueError('SHIFT_ALREADY_CANCELLED')
            self.s.db.execute('UPDATE duty_shifts SET cancelled_at=? WHERE shift_id=?',(time.time(),shift_id))
            self.record(r['patient_ref'],None,'SHIFT_CANCELLED',actor)
        return {'shift_id':shift_id,'cancelled':True,
                'warning':'Cancelling a shift does not automatically transfer any existing tasks.'}

    def roster(self,patient_ref):
        with self.s._lock:rows=self.s.db.execute('''SELECT shift_id,clinician_sub,starts_at,ends_at
          FROM duty_shifts WHERE patient_ref=? AND cancelled_at IS NULL AND ends_at>? ORDER BY starts_at LIMIT 100''',
          (patient_ref,time.time())).fetchall()
        return [dict(r) for r in rows]

    def on_shift(self,sub,patient_ref):
        now=time.time()
        row=self.s.db.execute('''SELECT shift_id FROM duty_shifts WHERE clinician_sub=? AND patient_ref=?
          AND starts_at<=? AND ends_at>? AND cancelled_at IS NULL LIMIT 1''',(sub,patient_ref,now,now)).fetchone()
        return row is not None

    def offer(self,task_id,actor,target,reason):
        with self.s.transaction():
            task=self.c.get_task(task_id)
            if task['assigned_to']!=actor or task['status'] not in ('ACKNOWLEDGED','OVERDUE'):
                raise ValueError('HANDOFF_REQUIRES_CURRENT_OWNER')
            if target==actor:raise ValueError('CANNOT_TRANSFER_TO_SELF')
            if not self.on_shift(target,task['patient_ref']):raise ValueError('TARGET_NOT_ON_SHIFT')
            pending=self.s.db.execute("SELECT 1 FROM task_handoffs WHERE task_id=? AND status='OFFERED'",(task_id,)).fetchone()
            if pending:raise ValueError('HANDOFF_ALREADY_PENDING')
            now=time.time();hid='HOF-'+uuid.uuid4().hex[:16].upper()
            self.s.db.execute('INSERT INTO task_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)',
                (hid,task_id,task['patient_ref'],actor,target,self.s.enc({'reason':reason}),
                 'OFFERED',now,now,now+900))
            self.record(task['patient_ref'],task_id,'HANDOFF_OFFERED',actor)
            return {'handoff_id':hid,'task_id':task_id,'from_sub':actor,'to_sub':target,
                    'status':'OFFERED','expires_at':now+900,'original_owner_retained':True}

    def get_handoff(self,hid):
        with self.s._lock:row=self.s.db.execute('''SELECT handoff_id,task_id,patient_ref,from_sub,to_sub,
           status,created_at,updated_at,expires_at FROM task_handoffs WHERE handoff_id=?''',(hid,)).fetchone()
        if not row:raise KeyError('HANDOFF_NOT_FOUND')
        return dict(row)

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

    def decide(self,hid,actor,action):
        if action not in ('accept','reject'):raise ValueError('INVALID_HANDOFF_ACTION')
        with self.s.transaction():
            h=self.get_handoff(hid)
            if h['to_sub']!=actor:raise ValueError('NOT_HANDOFF_RECIPIENT')
            if h['status']!='OFFERED':raise ValueError('HANDOFF_NOT_PENDING')
            if h['expires_at']<=time.time():raise ValueError('HANDOFF_EXPIRED')
            task=self.c.get_task(h['task_id'])
            if task['assigned_to']!=h['from_sub'] or task['status'] not in ('ACKNOWLEDGED','OVERDUE'):
                raise ValueError('ORIGINAL_OWNER_CHANGED')
            if action=='accept':
                if not self.on_shift(actor,h['patient_ref']):raise ValueError('SHIFT_NOT_ACTIVE')
                cur=self.s.db.execute('''UPDATE care_tasks SET assigned_to=?,updated_at=? WHERE task_id=?
                    AND assigned_to=? AND status IN ('ACKNOWLEDGED','OVERDUE')''',
                    (actor,time.time(),h['task_id'],h['from_sub']))
                if cur.rowcount!=1:raise ValueError('TASK_OWNER_CONFLICT')
            new='ACCEPTED' if action=='accept' else 'REJECTED'
            self.s.db.execute('UPDATE task_handoffs SET status=?,updated_at=? WHERE handoff_id=?',(new,time.time(),hid))
            self.record(h['patient_ref'],h['task_id'],'HANDOFF_'+new,actor)
            return {'handoff_id':hid,'status':new,'task_id':h['task_id'],
                    'assigned_to':actor if action=='accept' else h['from_sub']}

    def watch(self):
        now=time.time();expired=[]
        with self.s.transaction():
            rows=self.s.db.execute("SELECT handoff_id,patient_ref,task_id FROM task_handoffs WHERE status='OFFERED' AND expires_at<?",(now,)).fetchall()
            for r in rows:
                self.s.db.execute("UPDATE task_handoffs SET status='EXPIRED',updated_at=? WHERE handoff_id=?",(now,r['handoff_id']))
                self.record(r['patient_ref'],r['task_id'],'HANDOFF_EXPIRED','handoff-watch')
                expired.append(r['handoff_id'])
        return {'expired_handoff_ids':expired,'count':len(expired),
                'warning':'No actual paging. Original owner retained; manual escalation required.'}

    def timeline(self,patient_ref,limit=80):
        with self.s._lock:rows=self.s.db.execute('''SELECT event_id,task_id,event_code,actor,occurred_at,metadata
          FROM care_timeline WHERE patient_ref=? ORDER BY occurred_at DESC LIMIT ?''',(patient_ref,limit)).fetchall()
        return [{**dict(r),'metadata':json.loads(r['metadata'])} for r in rows]

