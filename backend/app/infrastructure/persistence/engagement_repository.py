"""SQL-only adapter for opt-in engagement, in-app prompts and aggregate operational metrics.
This module deliberately has no FastAPI, n8n, or patient-facing policy decisions.
"""
from __future__ import annotations
import time, json

class SqlEngagementRepository:
    def __init__(self, store):
        self.s = store
        with store._lock:
            store.db.executescript("""
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
            """)
            store.db.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)',(24,time.time()))

    def preference_row(self,patient_ref):
        with self.s._lock:
            r=self.s.db.execute('''SELECT reminder_opt_in,reminder_hour_utc,minimum_gap_hours,updated_at
                 FROM patient_engagement_preferences WHERE patient_ref=?''',(patient_ref,)).fetchone()
        return dict(r) if r else None

    def save_preferences(self,patient_ref,opt_in,hour,gap,now):
        self.s.db.execute('''INSERT INTO patient_engagement_preferences VALUES(?,?,?,?,?)
            ON CONFLICT(patient_ref) DO UPDATE SET reminder_opt_in=excluded.reminder_opt_in,
            reminder_hour_utc=excluded.reminder_hour_utc,minimum_gap_hours=excluded.minimum_gap_hours,
            updated_at=excluded.updated_at''',(patient_ref,int(opt_in),hour,gap,now))

    def cancel_pending(self,patient_ref):
        self.s.db.execute("UPDATE simulated_prompts SET state='CANCELLED' WHERE patient_ref=? AND state='PENDING_SIMULATED'",(patient_ref,))

    def prompts(self,patient_ref):
        with self.s._lock:
            rows=self.s.db.execute('''SELECT prompt_id,kind,state,created_at,seen_at FROM simulated_prompts
                WHERE patient_ref=? ORDER BY created_at DESC LIMIT 30''',(patient_ref,)).fetchall()
        return [dict(r) for r in rows]

    def prompt(self,prompt_id):
        r=self.s.db.execute('SELECT patient_ref,state FROM simulated_prompts WHERE prompt_id=?',(prompt_id,)).fetchone()
        return dict(r) if r else None

    def mark_seen(self,prompt_id,at):
        return self.s.db.execute("UPDATE simulated_prompts SET state='SEEN',seen_at=? WHERE prompt_id=? AND state='PENDING_SIMULATED'",(at,prompt_id)).rowcount==1

    def dashboard_rows(self,patient_ref,cutoff):
        with self.s._lock:
            checkins=self.s.db.execute('''SELECT event_id,status,created_at,triaged_at FROM checkins
              WHERE patient_ref=? AND created_at>=? ORDER BY created_at DESC LIMIT 20''',(patient_ref,cutoff)).fetchall()
            plan=self.s.db.execute('''SELECT observation_code,review_gap_hours,active,updated_at
               FROM monitoring_plans WHERE patient_ref=?''',(patient_ref,)).fetchone()
            receipts=self.s.db.execute('''SELECT case_id,acknowledged_at FROM patient_receipts
               WHERE patient_ref=? AND acknowledged_at>=? ORDER BY acknowledged_at DESC LIMIT 20''',(patient_ref,cutoff)).fetchall()
        return [dict(x) for x in checkins],dict(plan) if plan else None,[dict(x) for x in receipts]

    def opted_in_plans(self):
        rows=self.s.db.execute('''SELECT p.patient_ref,p.reminder_hour_utc,p.minimum_gap_hours
          FROM patient_engagement_preferences p JOIN monitoring_plans m ON m.patient_ref=p.patient_ref
          WHERE p.reminder_opt_in=1 AND m.active=1''').fetchall()
        return [dict(r) for r in rows]

    def latest_checkin(self,patient_ref):
        row=self.s.db.execute('SELECT MAX(created_at) AS ts FROM checkins WHERE patient_ref=?',(patient_ref,)).fetchone()
        return row['ts']

    def insert_prompt(self,prompt_id,key,patient_ref,now):
        return self.s.db.execute('''INSERT OR IGNORE INTO simulated_prompts VALUES(?,?,?,?,?,?,?)''',
            (prompt_id,key,patient_ref,'DAILY_CHECKIN','PENDING_SIMULATED',now,None)).rowcount==1

    def evaluation_rows(self,patient_ref,cutoff):
        with self.s._lock:
            rows=self.s.db.execute('''SELECT status,priority,created_at,acknowledged_at,resolved_at,due_at,kind
                FROM care_tasks WHERE patient_ref=? AND created_at>=?''',(patient_ref,cutoff)).fetchall()
            obs=self.s.db.execute('SELECT COUNT(*) n FROM observations WHERE patient_ref=? AND received_at>=?',(patient_ref,cutoff)).fetchone()['n']
            checks=self.s.db.execute('SELECT COUNT(*) n FROM checkins WHERE patient_ref=? AND created_at>=?',(patient_ref,cutoff)).fetchone()['n']
        return [dict(r) for r in rows],obs,checks

    def snapshot_counts(self):
        counts=self.s.db.execute('SELECT priority,status,COUNT(*) n FROM care_tasks GROUP BY priority,status').fetchall()
        prefs=self.s.db.execute('SELECT COUNT(*) n FROM patient_engagement_preferences WHERE reminder_opt_in=1').fetchone()['n']
        prompts=self.s.db.execute('SELECT COUNT(*) n FROM simulated_prompts').fetchone()['n']
        return {r['priority']+':'+r['status']:r['n'] for r in counts},prefs,prompts

    def insert_snapshot(self,hour,now,meta):
        self.s.db.execute('INSERT OR IGNORE INTO operational_snapshots VALUES(?,?,?)',(hour,now,json.dumps(meta,sort_keys=True)))
