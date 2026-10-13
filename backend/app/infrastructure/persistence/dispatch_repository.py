"""SQL dispatch queue adapter. Business retry policy lives in operations23.QueueJob.

Statements are scoped to bounded opaque reference IDs, no patient content in queue.
PostgreSQL claims are atomic across connections; end-to-end dispatch remains at-least-once.
"""
from __future__ import annotations

class SqlDispatchRepository:
    def __init__(self,store):
        self.s=store
        with store._lock:
            store.db.executescript('''
            CREATE TABLE IF NOT EXISTS dispatch_jobs(
                job_id TEXT PRIMARY KEY, job_key TEXT NOT NULL UNIQUE,
                job_kind TEXT NOT NULL, reference_id TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                next_run_at REAL NOT NULL, lease_until REAL, last_error_code TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dispatch_due ON dispatch_jobs(status,next_run_at);
            ''')

    def enqueue(self,jid,kind,ref,key,now):
        self.s.db.execute('''INSERT OR IGNORE INTO dispatch_jobs(job_id,job_key,job_kind,reference_id,status,
            attempts,next_run_at,lease_until,last_error_code,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (jid,key,kind,ref,'PENDING',0,now,None,None,now,now))
        return self.s.db.execute('SELECT job_id FROM dispatch_jobs WHERE job_key=?',(key,)).fetchone()['job_id']

    def delivered(self,key,now):
        self.s.db.execute("""UPDATE dispatch_jobs SET status='DELIVERED',lease_until=NULL,updated_at=?
            WHERE job_key=? AND status IN ('PENDING','LEASED')""",(now,key))

    def claim(self,now,max_attempts,lease_seconds):
        if self.s.backend == 'postgres':
            # PostgreSQL needs a single atomic cross-connection claim.
            # QueueJob.claim() already holds the transaction until this returns.
            # SKIP LOCKED prevents competing workers from waiting on / claiming
            # the same candidate when another worker owns its row lock.
            row = self.s.db.execute('''WITH candidate AS (
                SELECT job_id FROM dispatch_jobs WHERE
                    (status='PENDING' AND next_run_at<=?) OR
                    (status='LEASED' AND lease_until<=? AND attempts<?)
                ORDER BY next_run_at,created_at
                FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE dispatch_jobs AS job
               SET status='LEASED',lease_until=?,attempts=attempts+1,
                   updated_at=?
              FROM candidate WHERE job.job_id=candidate.job_id
            RETURNING job.*''',
                (now, now, max_attempts, now + lease_seconds, now)).fetchone()
            return dict(row) if row else None
        # SQLite demo adapter still uses a conditional single-worker CAS.
        row=self.s.db.execute('''SELECT * FROM dispatch_jobs WHERE
            (status='PENDING' AND next_run_at<=?) OR (status='LEASED' AND lease_until<=? AND attempts<?)
            ORDER BY next_run_at,created_at LIMIT 1''',(now,now,max_attempts)).fetchone()
        if not row:return None
        cur=self.s.db.execute('''UPDATE dispatch_jobs SET status='LEASED',lease_until=?,attempts=attempts+1,
            updated_at=? WHERE job_id=? AND ((status='PENDING' AND next_run_at<=?) OR
            (status='LEASED' AND lease_until<=?))''',(now+lease_seconds,now,row['job_id'],now,now))
        if cur.rowcount!=1:return None
        return dict(self.s.db.execute('SELECT * FROM dispatch_jobs WHERE job_id=?',(row['job_id'],)).fetchone())

    def leased_row(self,jid):
        row=self.s.db.execute('SELECT * FROM dispatch_jobs WHERE job_id=?',(jid,)).fetchone()
        return dict(row) if row else None

    def reschedule(self,jid,new_status,next_time,error,now):
        self.s.db.execute('''UPDATE dispatch_jobs SET status=?,next_run_at=?,lease_until=NULL,last_error_code=?,updated_at=?
            WHERE job_id=?''',(new_status,next_time,error,now,jid))

    def exhausted_leases(self,now,max_attempts):
        rows=self.s.db.execute("""SELECT job_id,job_kind,reference_id FROM dispatch_jobs
           WHERE status='LEASED' AND lease_until<=? AND attempts>=? LIMIT 40""",(now,max_attempts)).fetchall()
        return [dict(r) for r in rows]

    def mark_exhausted(self,jid,now):
        self.s.db.execute("""UPDATE dispatch_jobs SET status='DEAD',lease_until=NULL,
           last_error_code='LEASE_EXPIRED',updated_at=? WHERE job_id=?""",(now,jid))

    def accepted_without_completion(self,before):
        rows=self.s.db.execute('''SELECT j.job_id,j.reference_id,j.attempts FROM dispatch_jobs j
           JOIN cases c ON c.case_id=j.reference_id WHERE j.job_kind='CASE_DISPATCH'
             AND j.status='DELIVERED' AND c.status='RECEIVED' AND j.updated_at<? LIMIT 20''',(before,)).fetchall()
        return [dict(r) for r in rows]

    def rearm(self,jid,status,now):
        self.s.db.execute('''UPDATE dispatch_jobs SET status=?,next_run_at=?,updated_at=?
            WHERE job_id=?''',(status,now,now,jid))

    def counts(self):
        with self.s._lock:rows=self.s.db.execute('SELECT status,COUNT(*) n FROM dispatch_jobs GROUP BY status').fetchall()
        return {r['status']:r['n'] for r in rows}

    def list_jobs(self,limit):
        with self.s._lock:
            rows=self.s.db.execute('''SELECT job_id,job_kind,status,attempts,next_run_at,last_error_code,updated_at
               FROM dispatch_jobs ORDER BY updated_at DESC LIMIT ?''',(limit,)).fetchall()
        return [dict(r) for r in rows]
