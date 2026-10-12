"""Encrypted demo persistence. SQLite is deliberately NOT a production EHR store."""
import hashlib, hmac, json, os, sqlite3, threading, time
from contextlib import contextmanager
from cryptography.fernet import Fernet

class Store:
    def __init__(self, settings):
        self.settings = settings
        self._lock = threading.RLock()
        self.fernet = Fernet(settings.encryption_key.encode())
        if settings.database_url:
            from .postgres_compat import PostgresCompat
            self.db=PostgresCompat(settings.database_url)
            self.backend='postgres'
            import psycopg
            self.integrity_errors=(sqlite3.IntegrityError,psycopg.IntegrityError)
        else:
            os.makedirs(os.path.dirname(os.path.abspath(settings.database_path)), exist_ok=True)
            self.db=sqlite3.connect(settings.database_path, check_same_thread=False, isolation_level=None)
            self.db.row_factory=sqlite3.Row
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA busy_timeout=5000')
            self.backend='sqlite'
            self.integrity_errors=(sqlite3.IntegrityError,)
        with self._lock:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS cases(
                case_id TEXT PRIMARY KEY, patient_ref TEXT NOT NULL,
                status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                payload_cipher TEXT NOT NULL, state_cipher TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
                event TEXT NOT NULL, actor TEXT NOT NULL, metadata TEXT NOT NULL,
                event_at REAL NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge(
                source_id TEXT PRIMARY KEY, version TEXT NOT NULL, title TEXT NOT NULL,
                content TEXT NOT NULL, sha256 TEXT NOT NULL, embedded_json TEXT NOT NULL,
                indexed_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS clinician_assignments(
                clinician_sub TEXT NOT NULL, patient_ref TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, assigned_at REAL NOT NULL,
                PRIMARY KEY(clinician_sub,patient_ref)
            );
            CREATE INDEX IF NOT EXISTS idx_assignments_patient ON clinician_assignments(patient_ref);
            CREATE TABLE IF NOT EXISTS schema_migrations(
                version INTEGER PRIMARY KEY, applied_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL UNIQUE, recipient_ref TEXT NOT NULL,
                content_cipher TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL
            );
            ''')

        with self._lock:
            self.db.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)',(22,time.time()))

    @contextmanager
    def transaction(self):
        """Atomic case mutation + audit, supports nesting under FHIR transactions."""
        with self._lock:
            already=self.db.in_transaction
            if not already:self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                if not already:self.db.execute('COMMIT')
            except Exception:
                if not already:self.db.execute('ROLLBACK')
                raise

    def is_assigned(self,clinician_sub,patient_ref):
        with self._lock:
            row=self.db.execute('SELECT 1 FROM clinician_assignments WHERE clinician_sub=? AND patient_ref=? AND active=1',
                                (clinician_sub,patient_ref)).fetchone()
        return row is not None

    def assignments(self,clinician_sub):
        with self._lock:
            rows=self.db.execute('SELECT patient_ref FROM clinician_assignments WHERE clinician_sub=? AND active=1',
                                 (clinician_sub,)).fetchall()
        return {r['patient_ref'] for r in rows}

    def set_assignment(self,clinician_sub,patient_ref,active,actor):
        with self.transaction():
            self.db.execute('''INSERT INTO clinician_assignments(clinician_sub,patient_ref,active,assigned_at)
                VALUES(?,?,?,?) ON CONFLICT(clinician_sub,patient_ref)
                DO UPDATE SET active=excluded.active,assigned_at=excluded.assigned_at''',
                (clinician_sub,patient_ref,int(active),time.time()))
            self.audit('ACCESS','CLINICIAN_ASSIGNMENT_CHANGED',actor,
                       {'active':active,'clinician_sub':clinician_sub,'synthetic':True})

    def enc(self, obj):
        return self.fernet.encrypt(json.dumps(obj, ensure_ascii=False).encode()).decode()

    def dec(self, payload):
        return json.loads(self.fernet.decrypt(payload.encode()))

    def audit(self, case_id, event, actor, metadata=None):
        # Tamper-evident HMAC chain, not an externally anchored immutable log.
        metadata = metadata or {}
        if any(key in metadata for key in ('raw_image', 'vitals', 'patient_name', 'token')):
            raise ValueError('Audit must not include PHI')
        with self._lock:
            # PostgreSQL uses a transaction-scoped advisory lock to serialize
            # the tamper-evident hash chain across API workers.
            started = self.backend=='postgres' and not self.db.in_transaction
            if started:self.db.execute('BEGIN')
            try:
                if self.backend=='postgres': self.db.execute('SELECT pg_advisory_xact_lock(71172022)')
                row = self.db.execute('SELECT hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
                prev = row['hash'] if row else 'GENESIS'
                at = round(time.time(), 6)
                body = json.dumps([case_id, event, actor, metadata, at, prev], sort_keys=True, separators=(',', ':'))
                digest = hmac.new(self.settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
                self.db.execute('INSERT INTO audit(case_id,event,actor,metadata,event_at,prev_hash,hash) VALUES(?,?,?,?,?,?,?)',
                                (case_id,event,actor,json.dumps(metadata,sort_keys=True),at,prev,digest))
                if started:self.db.execute('COMMIT')
            except Exception:
                if started:self.db.execute('ROLLBACK')
                raise

    def verify_audit(self):
        with self._lock:
            rows = self.db.execute('SELECT * FROM audit ORDER BY seq').fetchall()
        prev = 'GENESIS'
        for row in rows:
            if row['prev_hash'] != prev:
                return False
            body = json.dumps([row['case_id'], row['event'], row['actor'], json.loads(row['metadata']), row['event_at'], prev], sort_keys=True, separators=(',', ':'))
            digest = hmac.new(self.settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(digest, row['hash']):
                return False
            prev = row['hash']
        return True

    def create(self, case_id, patient_ref, payload):
        now = time.time()
        with self.transaction():
            if self.db.execute('SELECT 1 FROM cases WHERE case_id=?',(case_id,)).fetchone():
                raise ValueError('DUPLICATE_CASE_ID')
            state={'steps':[], 'agents':{}, 'sources':[], 'plan':[], 'synthesis':None,
                   'flags':[], 'priority':'routine', 'review':None}
            self.db.execute('INSERT INTO cases VALUES(?,?,?,?,?,?,?,?)',
                            (case_id,patient_ref,'RECEIVED',0,self.enc(payload),self.enc(state),now,now))
            self.audit(case_id,'CASE_RECEIVED','patient',{'synthetic': True})

    def get(self, case_id):
        with self._lock:
            row=self.db.execute('SELECT * FROM cases WHERE case_id=?',(case_id,)).fetchone()
        if not row: raise KeyError('CASE_NOT_FOUND')
        return dict(case_id=row['case_id'],patient_ref=row['patient_ref'], status=row['status'],
                    version=row['version'],payload=self.dec(row['payload_cipher']),state=self.dec(row['state_cipher']),
                    created_at=row['created_at'],updated_at=row['updated_at'])

    def save(self, c, event, actor='system', metadata=None):
        with self.transaction():
            # optimistic concurrency on ALL mutations. Each n8n case processes serially.
            cur=self.db.execute('UPDATE cases SET status=?, version=version+1, state_cipher=?, payload_cipher=?, updated_at=? WHERE case_id=? AND version=?',
                (c['status'], self.enc(c['state']),self.enc(c['payload']),time.time(),c['case_id'],c['version']))
            if cur.rowcount != 1: raise ValueError('STATE_CONFLICT')
            self.audit(c['case_id'],event,actor,metadata)
        return self.get(c['case_id'])

    def remove_image(self, c):
        c['payload']['meal_image_data_url'] = None

    def audit_events(self, case_id):
        with self._lock:
            rows=self.db.execute('SELECT seq,event,actor,metadata,event_at,hash FROM audit WHERE case_id=? ORDER BY seq',(case_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_cases(self,patient_refs=None):
        with self._lock:
            if patient_refs is not None:
                if not patient_refs:return []
                qs=','.join('?' for _ in patient_refs)
                rows=self.db.execute('SELECT case_id,patient_ref,status,version,created_at,updated_at FROM cases WHERE patient_ref IN ('+qs+') ORDER BY updated_at DESC LIMIT 100',tuple(sorted(patient_refs))).fetchall()
            else:
                rows=self.db.execute('SELECT case_id,patient_ref,status,version,created_at,updated_at FROM cases ORDER BY updated_at DESC LIMIT 100').fetchall()
        return [dict(r) for r in rows]

    def outbox_insert(self, c, draft):
        with self._lock:
            self.db.execute('INSERT OR IGNORE INTO outbox(case_id,recipient_ref,content_cipher,status,created_at) VALUES(?,?,?,?,?)',
                            (c['case_id'],c['patient_ref'],self.enc({'draft':draft}), 'SIMULATED_ONLY',time.time()))

    def list_outbox(self,patient_refs=None):
        with self._lock:
            if patient_refs is not None:
                if not patient_refs:return []
                qs=','.join('?' for _ in patient_refs)
                rows=self.db.execute('SELECT id,case_id,recipient_ref,status,created_at FROM outbox WHERE recipient_ref IN ('+qs+') ORDER BY id DESC',tuple(sorted(patient_refs))).fetchall()
            else:
                rows=self.db.execute('SELECT id,case_id,recipient_ref,status,created_at FROM outbox ORDER BY id DESC').fetchall()
        return [dict(r) for r in rows]
