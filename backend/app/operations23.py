"""2.3 synthetic-only on-call handoff and durable orchestration dispatch.

No on-call paging, clinical advice, or patient notification. n8n only receives opaque IDs.
PostgreSQL claims use row-level SKIP LOCKED; the overall dispatch protocol remains at-least-once, not exactly-once.
"""
from __future__ import annotations
import time, uuid
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
    """Application retry policy; SQL state/lease operations delegated to a repository."""
    MAX_ATTEMPTS=4
    def __init__(self,store,repository=None):
        if repository is None:
            from .infrastructure.persistence.dispatch_repository import SqlDispatchRepository
            repository=SqlDispatchRepository(store)
        self.s=store
        self.repo=repository

    def enqueue(self,kind,ref):
        if kind not in ('CASE_DISPATCH','CHECKIN_DISPATCH'):raise ValueError('INVALID_JOB_KIND')
        key=kind+':'+ref;now=time.time();jid='JOB-'+uuid.uuid4().hex[:16].upper()
        with self.s.transaction():
            actual=self.repo.enqueue(jid,kind,ref,key,now)
            if actual==jid:self.s.audit('SYSTEM','DELIVERY_JOB_ENQUEUED','queue',{'kind':kind})
        return actual

    def delivered(self,kind,ref):
        with self.s.transaction():self.repo.delivered(kind+':'+ref,time.time())

    def claim(self):
        now=time.time()
        with self.s.transaction():return self.repo.claim(now,self.MAX_ATTEMPTS,120)

    def failed(self,jid,code):
        if code not in ('WEBHOOK_UNAVAILABLE','DISPATCH_EXCEPTION','LEASE_EXPIRED','BAD_REFERENCE'):
            code='DISPATCH_EXCEPTION'
        now=time.time()
        with self.s.transaction():
            row=self.repo.leased_row(jid)
            if not row or row['status']!='LEASED':return None
            dead=row['attempts']>=self.MAX_ATTEMPTS
            newstatus='DEAD' if dead else 'PENDING'
            delay=min(240,60*(2**max(0,row['attempts']-1)))
            self.repo.reschedule(jid,newstatus,now+delay,code,now)
            self.s.audit('SYSTEM','DISPATCH_JOB_DEAD' if dead else 'DISPATCH_JOB_RETRY','queue',{'kind':row['job_kind'],'attempts':row['attempts']})
            return {'status':newstatus,'attempts':row['attempts'],'kind':row['job_kind'],'reference_id':row['reference_id']}

    def reap_exhausted_leases(self):
        now=time.time();dead=[]
        with self.s.transaction():
            for row in self.repo.exhausted_leases(now,self.MAX_ATTEMPTS):
                self.repo.mark_exhausted(row['job_id'],now)
                dead.append(row)
                self.s.audit('SYSTEM','DISPATCH_LEASE_EXHAUSTED','queue',{'kind':row['job_kind']})
        return dead

    def recover_accepted(self,min_age=600):
        now=time.time();rearmed=[];dead=[]
        with self.s.transaction():
            for row in self.repo.accepted_without_completion(now-min_age):
                exhausted=row['attempts']>=self.MAX_ATTEMPTS
                self.repo.rearm(row['job_id'],'DEAD' if exhausted else 'PENDING',now)
                (dead if exhausted else rearmed).append((row['job_id'],row['reference_id']))
                self.s.audit('SYSTEM','WEBHOOK_ACK_NOT_COMPLETED','queue',{'exhausted':exhausted})
        return {'rearmed':rearmed,'dead':dead}

    def counts(self):return self.repo.counts()
    def list_jobs(self,limit=40):return self.repo.list_jobs(limit)

class ShiftHandoff:
    def __init__(self,store,coordinator,repository=None):
        self.s=store;self.c=coordinator
        if repository is None:
            from .infrastructure.persistence.handoff_repository import SqlHandoffRepository
            repository=SqlHandoffRepository(store)
        self.repo=repository

    def record(self, patient_ref, task_id, event_code, actor, metadata=None):
        # metadata must contain no PHI, reason text or clinical interpretation.
        allowed={'HANDOFF_OFFERED','HANDOFF_ACCEPTED','HANDOFF_REJECTED',
                 'HANDOFF_EXPIRED','SHIFT_REGISTERED','SHIFT_CANCELLED','TASK_CLAIMED',
                 'TASK_RESOLVED','CASE_DECISION','PATIENT_RECEIPT','TASK_SLA_VISIBLE'}
        if event_code not in allowed:raise ValueError('Unsupported timeline event')
        with self.s.transaction():
            self.repo.record('EVT-'+uuid.uuid4().hex[:16].upper(),patient_ref,task_id,event_code,actor,time.time(),metadata)
            self.s.audit('OPERATIONS',event_code,actor,{'synthetic':True})

    def shift(self,sub,patient_ref,starts_at,ends_at):
        begin=parse_clock(starts_at);end=parse_clock(ends_at);now=time.time()
        if begin>now+14*86400 or end<=now or end-begin>24*3600 or end-begin<900:
            raise ValueError('SHIFT_OUTSIDE_DEMO_LIMITS')
        sid='SHIFT-'+uuid.uuid4().hex[:16].upper()
        with self.s.transaction():
            self.repo.insert_shift(sid,sub,patient_ref,begin,end,now)
            self.record(patient_ref,None,'SHIFT_REGISTERED',sub)
        return {'shift_id':sid,'patient_ref':patient_ref,'starts_at':begin,'ends_at':end,'synthetic_only':True}

    def cancel_shift(self,shift_id,actor):
        with self.s.transaction():
            r=self.repo.shift(shift_id)
            if not r:raise KeyError('SHIFT_NOT_FOUND')
            if r['clinician_sub']!=actor:raise ValueError('SHIFT_OWNER_ONLY')
            if r['cancelled_at'] is not None:raise ValueError('SHIFT_ALREADY_CANCELLED')
            self.repo.cancel_shift(shift_id,time.time())
            self.record(r['patient_ref'],None,'SHIFT_CANCELLED',actor)
        return {'shift_id':shift_id,'cancelled':True,
                'warning':'Cancelling a shift does not automatically transfer any existing tasks.'}

    def roster(self,patient_ref):
        return self.repo.roster(patient_ref,time.time())

    def on_shift(self,sub,patient_ref):
        return self.repo.on_shift(sub,patient_ref,time.time())

    def offer(self,task_id,actor,target,reason):
        with self.s.transaction():
            task=self.c.get_task(task_id)
            if task['assigned_to']!=actor or task['status'] not in ('ACKNOWLEDGED','OVERDUE'):
                raise ValueError('HANDOFF_REQUIRES_CURRENT_OWNER')
            if target==actor:raise ValueError('CANNOT_TRANSFER_TO_SELF')
            if not self.on_shift(target,task['patient_ref']):raise ValueError('TARGET_NOT_ON_SHIFT')
            if self.repo.pending(task_id):raise ValueError('HANDOFF_ALREADY_PENDING')
            now=time.time();hid='HOF-'+uuid.uuid4().hex[:16].upper()
            self.repo.offer(hid,task_id,task['patient_ref'],actor,target,reason,now,now+900)
            self.record(task['patient_ref'],task_id,'HANDOFF_OFFERED',actor)
            return {'handoff_id':hid,'task_id':task_id,'from_sub':actor,'to_sub':target,
                    'status':'OFFERED','expires_at':now+900,'original_owner_retained':True}

    def get_handoff(self,hid):
        row=self.repo.handoff(hid)
        if not row:raise KeyError('HANDOFF_NOT_FOUND')
        return row

    def inbox(self,sub,patient_refs):
        return self.repo.inbox(sub,patient_refs)

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
                if not self.repo.transfer_task(h['task_id'],h['from_sub'],actor,time.time()):
                    raise ValueError('TASK_OWNER_CONFLICT')
            new='ACCEPTED' if action=='accept' else 'REJECTED'
            self.repo.update_handoff(hid,new,time.time())
            self.record(h['patient_ref'],h['task_id'],'HANDOFF_'+new,actor)
            return {'handoff_id':hid,'status':new,'task_id':h['task_id'],
                    'assigned_to':actor if action=='accept' else h['from_sub']}

    def watch(self):
        now=time.time();expired=[]
        with self.s.transaction():
            for r in self.repo.expired(now):
                self.repo.update_handoff(r['handoff_id'],'EXPIRED',now)
                self.record(r['patient_ref'],r['task_id'],'HANDOFF_EXPIRED','handoff-watch')
                expired.append(r['handoff_id'])
        return {'expired_handoff_ids':expired,'count':len(expired),
                'warning':'No actual paging. Original owner retained; manual escalation required.'}

    def timeline(self,patient_ref,limit=80):
        return self.repo.timeline(patient_ref,limit)
