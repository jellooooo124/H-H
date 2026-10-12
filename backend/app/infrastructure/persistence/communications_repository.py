"""Infrastructure persistence adapter: DB storage and encryption belong outside domain rules."""
from __future__ import annotations
import time, uuid

class CommunicationsRepository:
    def __init__(self, store):
        self.store=store
        with store._lock:
            store.db.executescript('''
              CREATE TABLE IF NOT EXISTS in_app_communications (
                message_id TEXT PRIMARY KEY,
                request_key TEXT UNIQUE NOT NULL,
                patient_ref TEXT NOT NULL,
                case_id TEXT,
                template_code TEXT NOT NULL,
                content_cipher TEXT NOT NULL,
                state TEXT NOT NULL,
                clinician_sub TEXT NOT NULL,
                created_at REAL NOT NULL,
                published_at REAL,
                acknowledged_at REAL,
                due_at REAL NOT NULL
              );
              CREATE INDEX IF NOT EXISTS idx_communication_patient ON in_app_communications(patient_ref,created_at);
              CREATE INDEX IF NOT EXISTS idx_communication_due ON in_app_communications(state,due_at);
            ''')

    @staticmethod
    def public(row, decrypt=None, include_content=False):
        d=dict(row)
        content=d.pop('content_cipher')
        d.pop('request_key',None)
        if include_content:
            d['content']=decrypt(content)['text']
        return d

    def get(self,message_id):
        with self.store._lock:
            row=self.store.db.execute('SELECT * FROM in_app_communications WHERE message_id=?',(message_id,)).fetchone()
        if row is None:raise KeyError('MESSAGE_NOT_FOUND')
        return dict(row)

    def by_request(self,request_key):
        with self.store._lock:
            row=self.store.db.execute('SELECT * FROM in_app_communications WHERE request_key=?',(request_key,)).fetchone()
        return dict(row) if row else None

    def create(self,request_key,patient_ref,case_id,template_code,text,actor,due_at):
        now=time.time(); message_id='MSG-'+uuid.uuid4().hex[:20].upper()
        self.store.db.execute('''INSERT INTO in_app_communications
           (message_id,request_key,patient_ref,case_id,template_code,content_cipher,state,clinician_sub,created_at,due_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)''',
           (message_id,request_key,patient_ref,case_id,template_code,self.store.enc({'text':text}),
            'DRAFT',actor,now,due_at))
        return self.get(message_id)

    def transition(self,message_id,from_state,to_state,at_field=None,at=None):
        if at_field not in (None,'published_at','acknowledged_at'):raise ValueError('INVALID_FIELD')
        if at_field:
            cursor=self.store.db.execute(f'UPDATE in_app_communications SET state=?,{at_field}=? WHERE message_id=? AND state=?',
                                         (to_state,at,message_id,from_state))
        else:
            cursor=self.store.db.execute('UPDATE in_app_communications SET state=? WHERE message_id=? AND state=?',
                                         (to_state,message_id,from_state))
        return cursor.rowcount==1

    def list_patient(self,patient_ref,include_drafts=False):
        cond='' if include_drafts else " AND state!='DRAFT'"
        with self.store._lock:
            rows=self.store.db.execute('SELECT * FROM in_app_communications WHERE patient_ref=?'+cond+' ORDER BY created_at DESC LIMIT 100',(patient_ref,)).fetchall()
        return [self.public(row,self.store.dec,include_content=True) for row in rows]

    def expired(self,at):
        with self.store._lock:
            rows=self.store.db.execute("SELECT * FROM in_app_communications WHERE state='PUBLISHED_IN_APP' AND due_at<? ORDER BY due_at LIMIT 100",(at,)).fetchall()
        return [dict(row) for row in rows]

    def counts(self):
        with self.store._lock:
            rows=self.store.db.execute('SELECT state,COUNT(*) AS n FROM in_app_communications GROUP BY state').fetchall()
        return {r['state']:r['n'] for r in rows}
