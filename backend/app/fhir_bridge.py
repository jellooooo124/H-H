"""Synthetic-only, strict FHIR R4 Observation bridge.

Not an EHR interface. Supports four allowlisted quantitative LOINC observations,
rejects free text/extensions and all non-DEMO patient IDs. n8n never receives
resource bodies: it only invokes the internal scheduled synchronization API.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from .coordination import ALLOWED_CODES, timestamp

RESOURCE_ID = re.compile(r'^[A-Za-z0-9.\-]{1,64}$')
PATIENT_REF = re.compile(r'^DEMO-[A-Za-z0-9_-]{3,45}$')
# Code => internal code, UCUM code, expected display unit.
LOINC = {
    '29463-7': ('weight_kg', 'kg', 'kg'),
    '2339-0': ('glucose_mg_dl', 'mg/dL', 'mg/dL'),
    '8867-4': ('heart_rate_bpm', '/min', 'beats/min'),
    '59408-5': ('spo2_pct', '%', '%'),
}
REVERSE = {code: (loinc, ucum) for loinc, (code, ucum, _) in LOINC.items()}

class FHIRConflict(ValueError):
    pass


def _keys(obj, expected):
    if not isinstance(obj, dict) or (set(obj) - set(expected)):
        raise ValueError('FHIR resource has unsupported fields (synthetic allowlist only)')


def normalise_resource(resource, patient_ref):
    _keys(resource, {'resourceType', 'id', 'status', 'subject', 'code', 'effectiveDateTime', 'valueQuantity'})
    if resource.get('resourceType') != 'Observation' or resource.get('status') != 'final':
        raise ValueError('Only final FHIR R4 Observation supported')
    rid=resource.get('id')
    if not isinstance(rid, str) or not RESOURCE_ID.fullmatch(rid):
        raise ValueError('Missing or invalid synthetic Observation.id')
    subject=resource.get('subject')
    _keys(subject, {'reference'})
    if subject.get('reference') != 'Patient/' + patient_ref:
        raise ValueError('FHIR subject must match authorized DEMO patient')
    code=resource.get('code')
    _keys(code, {'coding'})
    coding=code.get('coding')
    if not isinstance(coding, list) or len(coding)!=1:
        raise ValueError('Exactly one LOINC coding is required')
    _keys(coding[0], {'system','code'})
    if coding[0].get('system')!='http://loinc.org' or coding[0].get('code') not in LOINC:
        raise ValueError('Non-allowlisted LOINC code')
    internal_code, ucum, unit = LOINC[coding[0]['code']]
    value=resource.get('valueQuantity')
    _keys(value, {'value','system','code'})
    if value.get('system')!='http://unitsofmeasure.org' or value.get('code')!=ucum:
        raise ValueError('Unexpected UCUM unit; automatic conversions disabled')
    val=value.get('value')
    if type(val) not in (int,float):
        raise ValueError('FHIR valueQuantity.value must be finite number')
    import math
    if not math.isfinite(val): raise ValueError('Nonfinite FHIR value')
    lo,hi,_=ALLOWED_CODES[internal_code]
    if not lo<=val<=hi: raise ValueError('Measurement outside synthetic envelope')
    taken=resource.get('effectiveDateTime')
    if not isinstance(taken,str): raise ValueError('effectiveDateTime missing')
    timestamp(taken)
    # Fingerprint only allowed fields, not source JSON (which may contain malicious extras).
    canonical={'id':rid,'patient_ref':patient_ref,'code':internal_code,'value':float(val),
               'unit':unit,'effectiveDateTime':taken,'status':'final'}
    digest=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    event_id='OBS-FHIR-'+hashlib.sha256((patient_ref+'|'+rid).encode()).hexdigest()[:24].upper()
    return {'id':rid, 'event_id':event_id, 'hash':digest, 'internal_code':internal_code,
            'value':float(val),'unit':unit,'taken_at':taken}


class FHIRBridge:
    def __init__(self, store, coordinator):
        self.s=store
        self.coordinator=coordinator
        with self.s._lock:
            self.s.db.executescript('''
                CREATE TABLE IF NOT EXISTS fhir_imports (
                  resource_id TEXT NOT NULL, patient_ref TEXT NOT NULL,
                  fingerprint TEXT NOT NULL, observation_event TEXT NOT NULL,
                  imported_at REAL NOT NULL,
                  PRIMARY KEY(patient_ref,resource_id),
                  UNIQUE(observation_event)
                );
            ''')

    def import_bundle(self, patient_ref, bundle, actor='clinician'):
        if not isinstance(patient_ref,str) or not PATIENT_REF.fullmatch(patient_ref):
            raise ValueError('DEMO patient required')
        _keys(bundle, {'resourceType','type','entry'})
        if bundle.get('resourceType')!='Bundle' or bundle.get('type')!='collection':
            raise ValueError('Only FHIR collection Bundle supported')
        entries=bundle.get('entry')
        if not isinstance(entries,list) or not 1<=len(entries)<=50:
            raise ValueError('FHIR Bundle must contain 1-50 observations')
        normalized=[]
        local_ids=set()
        for item in entries:
            _keys(item, {'resource'})
            r=normalise_resource(item.get('resource'),patient_ref)
            if r['id'] in local_ids: raise FHIRConflict('Repeated resource ID inside Bundle')
            local_ids.add(r['id'])
            normalized.append(r)
        added=[]; skipped=[]
        # All-or-nothing DB writes, including derived observations and audit entries.
        with self.s._lock:
            self.s.db.execute('BEGIN IMMEDIATE')
            try:
                for r in normalized:
                    existing=self.s.db.execute('SELECT fingerprint FROM fhir_imports WHERE patient_ref=? AND resource_id=?',
                                               (patient_ref,r['id'])).fetchone()
                    if existing:
                        if existing['fingerprint']!=r['hash']:
                            raise FHIRConflict('FHIR resource already imported with different content')
                        skipped.append(r['id'])
                        continue
                    self.coordinator.add_observation(patient_ref,r['event_id'],r['internal_code'],r['value'],r['unit'],r['taken_at'])
                    self.s.db.execute('INSERT INTO fhir_imports VALUES(?,?,?,?,?)',
                                      (r['id'],patient_ref,r['hash'],r['event_id'],time.time()))
                    added.append(r['id'])
                self.s.audit('FHIR','FHIR_BUNDLE_IMPORT',actor,{'added_count':len(added),'skipped_count':len(skipped),'synthetic':True})
                self.s.db.execute('COMMIT')
            except Exception:
                self.s.db.execute('ROLLBACK')
                raise
        return {'patient_ref':patient_ref,'imported':len(added),'unchanged':len(skipped),
                'resource_ids':added,'synthetic_only':True}

    def export_observations(self, patient_ref,limit=50):
        if not isinstance(patient_ref,str) or not PATIENT_REF.fullmatch(patient_ref):
            raise ValueError('DEMO patient required')
        if not isinstance(limit,int) or not 1<=limit<=100:raise ValueError('Limit 1-100 required')
        with self.s._lock:
            rows=self.s.db.execute('''SELECT o.event_id,o.code,o.taken_at,o.payload_cipher
                FROM observations o WHERE o.patient_ref=? ORDER BY o.taken_at DESC LIMIT ?''',(patient_ref,limit)).fetchall()
        items=[]
        for row in rows:
            code,ucum=REVERSE[row['code']]
            val=self.s.dec(row['payload_cipher'])['value']
            dt=datetime.fromtimestamp(row['taken_at'],timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
            items.append({'resource':{'resourceType':'Observation','id':row['event_id'],'status':'final',
                'subject':{'reference':'Patient/'+patient_ref},
                'code':{'coding':[{'system':'http://loinc.org','code':code}]},
                'effectiveDateTime':dt,
                'valueQuantity':{'value':val,'system':'http://unitsofmeasure.org','code':ucum}}})
        return {'resourceType':'Bundle','type':'collection','total':len(items),'entry':items}

    def sync_demo(self,patient_ref='DEMO-P001'):
        """Deterministic local FHIR sandbox fixture; no external hospital requests."""
        if patient_ref!='DEMO-P001':raise ValueError('Only approved fixture patient')
        day=datetime.now(timezone.utc).strftime('%Y%m%d')
        # Fingerprint stability on repeated runs within a day: use midnight timestamp.
        effective=day[:4]+'-'+day[4:6]+'-'+day[6:]+'T00:00:00Z'
        measures=[('W', '29463-7', 72.4, 'kg'),('G','2339-0',122.0,'mg/dL'),('H','8867-4',78.0,'/min')]
        entries=[]
        for prefix,loinc,val,unit in measures:
            entries.append({'resource':{'resourceType':'Observation','id':f'{prefix}-{day}',
                'status':'final','subject':{'reference':'Patient/'+patient_ref},
                'code':{'coding':[{'system':'http://loinc.org','code':loinc}]},
                'effectiveDateTime':effective,
                'valueQuantity':{'value':val,'system':'http://unitsofmeasure.org','code':unit}}})
        result=self.import_bundle(patient_ref,{'resourceType':'Bundle','type':'collection','entry':entries},actor='sandbox-sync')
        # Return no raw values to n8n.
        return {'imported':result['imported'],'unchanged':result['unchanged'],'synced_patient_count':1,
                'synthetic_only':True,'remote_ehr_connected':False,'run_date_utc':day}
