"""Allowlisted FHIR Observation persistence adapter; transactional writes managed by use case."""
from __future__ import annotations
import time

class SqlFhirRepository:
    def __init__(self,store):
        self.s=store
        with self.s._lock:
            self.s.db.executescript('CREATE TABLE IF NOT EXISTS fhir_imports (\n                resource_id TEXT NOT NULL, patient_ref TEXT NOT NULL,\n                fingerprint TEXT NOT NULL, observation_event TEXT NOT NULL,\n                imported_at REAL NOT NULL,\n                PRIMARY KEY(patient_ref,resource_id), UNIQUE(observation_event)\n            );')

    def fingerprint(self,patient_ref,resource_id):
        row=self.s.db.execute('SELECT fingerprint FROM fhir_imports WHERE patient_ref=? AND resource_id=?',(patient_ref,resource_id)).fetchone()
        return row['fingerprint'] if row else None

    def record_import(self,resource_id,patient_ref,digest,event_id):
        self.s.db.execute('INSERT INTO fhir_imports VALUES(?,?,?,?,?)',(resource_id,patient_ref,digest,event_id,time.time()))

    def observation_rows(self,patient_ref,limit):
        with self.s._lock:
            rows=self.s.db.execute('SELECT o.event_id,o.code,o.taken_at,o.payload_cipher\n                FROM observations o WHERE o.patient_ref=? ORDER BY o.taken_at DESC LIMIT ?',(patient_ref,limit)).fetchall()
        return [dict(r) for r in rows]
