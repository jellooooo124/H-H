"""ONE-TIME OFFLINE demo data migration (encrypted payloads remain encrypted).

USAGE (after stopping API; PostgreSQL already initialized by version 2.2 API):
  SQLITE_SOURCE=/appdata/cases.db DATABASE_URL=... python scripts/migrate_sqlite_to_postgres.py
Do not execute this for clinical data. Target tables MUST ALL be empty.
"""
import os,sys,sqlite3,hashlib,hmac,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import Settings
from app.store import Store
from app.postgres_compat import PostgresCompat

TABLES={
 'cases':['case_id','patient_ref','status','version','payload_cipher','state_cipher','created_at','updated_at'],
 'audit':['seq','case_id','event','actor','metadata','event_at','prev_hash','hash'],
 'knowledge':['source_id','version','title','content','sha256','embedded_json','indexed_at'],
 'outbox':['id','case_id','recipient_ref','content_cipher','status','created_at'],
 'observations':['event_id','patient_ref','code','taken_at','payload_cipher','received_at'],
 'checkins':['event_id','patient_ref','payload_cipher','status','created_at','triaged_at'],
 'monitoring_plans':['patient_ref','observation_code','review_gap_hours','active','approved_by','updated_at'],
 'care_tasks':['task_id','source_key','case_id','patient_ref','kind','priority','status','assigned_to','reason_code','due_at','created_at','updated_at','acknowledged_at','resolved_at','outcome','disposition_note_cipher'],
 'patient_receipts':['case_id','patient_ref','acknowledged_at'],
 'fhir_imports':['resource_id','patient_ref','fingerprint','observation_event','imported_at'],
 'clinician_assignments':['clinician_sub','patient_ref','active','assigned_at'],
 'duty_shifts':['shift_id','clinician_sub','patient_ref','starts_at','ends_at','created_at','cancelled_at'],
 'task_handoffs':['handoff_id','task_id','patient_ref','from_sub','to_sub','reason_cipher','status','created_at','updated_at','expires_at'],
 'care_timeline':['event_id','patient_ref','task_id','event_code','actor','occurred_at','metadata'],
 'dispatch_jobs':['job_id','job_key','job_kind','reference_id','status','attempts','next_run_at','lease_until','last_error_code','created_at','updated_at'],
}

def verify_chain(rows,secret):
    prior='GENESIS'
    for r in rows:
        if r['prev_hash']!=prior:return False
        body=json.dumps([r['case_id'],r['event'],r['actor'],json.loads(r['metadata']),r['event_at'],prior],sort_keys=True,separators=(',',':'))
        digest=hmac.new(secret.encode(),body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest,r['hash']):return False
        prior=r['hash']
    return True

def run():
    settings=Settings.from_env();settings.validate()
    if not settings.database_url:raise RuntimeError('DATABASE_URL is required; refusing SQLite migration target')
    path=os.getenv('SQLITE_SOURCE','')
    if not path or not Path(path).is_file():raise RuntimeError('Explicit existing SQLITE_SOURCE is required')
    src=sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True)
    src.row_factory=sqlite3.Row
    tables={}
    for table,cols in TABLES.items():
        if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
            rows=src.execute('SELECT '+','.join(cols)+' FROM '+table).fetchall()
            tables[table]=[dict(r) for r in rows]
    if not verify_chain(tables.get('audit',[]),settings.jwt_secret):
        raise RuntimeError('Source audit HMAC chain invalid: APP_TOKEN_SECRET mismatch or tampered database')
    dest=PostgresCompat(settings.database_url)
    for table in TABLES:
        if dest.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
            raise RuntimeError('Target must be empty: '+table)
    # Single atomic PostgreSQL transaction; rollback on any failure.
    dest.execute('BEGIN')
    try:
        for table,rows in tables.items():
            cols=TABLES[table]
            sql='INSERT INTO '+table+'('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')'
            for r in rows:dest.execute(sql,tuple(r.get(c) for c in cols))
        for table,cols in TABLES.items():
            found=dest.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n']
            if found!=len(tables.get(table,[])):raise RuntimeError('Row count mismatch: '+table)
        audit=dest.execute('SELECT * FROM audit ORDER BY seq').fetchall()
        if not verify_chain(audit,settings.jwt_secret):raise RuntimeError('Destination HMAC chain mismatch')
        # Explicit IDs were copied for identity columns.
        for table,column in [('audit','seq'),('outbox','id')]:
            dest.execute("SELECT setval(pg_get_serial_sequence('"+table+"','"+column+"'),GREATEST((SELECT COALESCE(MAX("+column+"),0) FROM "+table+"),1), (SELECT COUNT(*)>0 FROM "+table+"))")
        dest.execute('COMMIT')
    except Exception:
        dest.execute('ROLLBACK');raise
    finally:
        dest.close();src.close()
    print(json.dumps({'migrated':{k:len(v) for k,v in tables.items()},'audit_verified':True,'synthetic_only':True},sort_keys=True))

if __name__=='__main__':run()
