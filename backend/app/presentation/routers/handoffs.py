"""Handoff router: HTTP permissions and error mapping, no SQL or clinical logic."""
from fastapi import APIRouter, Depends, HTTPException
from ...operations23 import ShiftIn,HandoffIn

def build_router(use_cases, clinician, access, allowed_patient_refs):
    router=APIRouter(tags=['shift handoff'])

    @router.post('/v3/shifts',status_code=201)
    def register_shift(data:ShiftIn,claim=Depends(clinician)):
        access(claim,data.patient_ref)
        try:return use_cases.shift(claim['sub'],data.patient_ref,data.starts_at,data.ends_at)
        except ValueError as e:raise HTTPException(422,str(e))

    @router.post('/v3/shifts/{shift_id}/cancel')
    def cancel_shift(shift_id:str,claim=Depends(clinician)):
        try:return use_cases.cancel(shift_id,claim['sub'])
        except KeyError:raise HTTPException(404,'Shift not found')
        except ValueError as e:raise HTTPException(409,str(e))

    @router.get('/v3/shifts/{patient_ref}')
    def roster(patient_ref:str,claim=Depends(clinician)):
        access(claim,patient_ref)
        return use_cases.roster(patient_ref)

    @router.post('/v3/tasks/{task_id}/handoff',status_code=201)
    def handoff(task_id:str,data:HandoffIn,claim=Depends(clinician)):
        try:t=use_cases.task(task_id)
        except KeyError:raise HTTPException(404,'Task not found')
        access(claim,t['patient_ref'])
        try:return use_cases.offer(task_id,claim['sub'],data.to_clinician_sub,data.reason)
        except ValueError as e:raise HTTPException(409,str(e))

    @router.get('/v3/handoffs/inbox')
    def inbox(claim=Depends(clinician)):
        return use_cases.inbox(claim['sub'],allowed_patient_refs(claim))

    def hdecide(handoff_id,claim,choice):
        try:h=use_cases.get_handoff(handoff_id)
        except KeyError:raise HTTPException(404,'Handoff not found')
        access(claim,h['patient_ref'])
        try:return use_cases.decide(handoff_id,claim['sub'],choice)
        except ValueError as e:raise HTTPException(409,str(e))

    @router.post('/v3/handoffs/{handoff_id}/accept')
    def accept(handoff_id:str,claim=Depends(clinician)):
        return hdecide(handoff_id,claim,'accept')

    @router.post('/v3/handoffs/{handoff_id}/reject')
    def reject(handoff_id:str,claim=Depends(clinician)):
        return hdecide(handoff_id,claim,'reject')

    @router.get('/v3/patients/{patient_ref}/timeline')
    def timeline(patient_ref:str,claim=Depends(clinician)):
        access(claim,patient_ref)
        return use_cases.timeline(patient_ref)

    @router.get('/v3/ops/dispatch-jobs')
    def dispatch_jobs(claim=Depends(clinician)):
        try:return use_cases.dispatch_status()
        except PermissionError as e:raise HTTPException(403,str(e))

    return router
