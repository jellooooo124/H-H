"""Backward-compatible case query routes (HTTP adapter only)."""
from fastapi import APIRouter,Depends,HTTPException

def build_router(queries, clinician, access, allowed_patient_refs):
    router=APIRouter(tags=['case queries'])
    def find(case_id):
        try:return queries.get(case_id)
        except KeyError:raise HTTPException(404,'Case not found')

    @router.get('/v1/cases')
    def list_cases(claim=Depends(clinician)):
        return queries.list(allowed_patient_refs(claim))

    @router.get('/v1/cases/{case_id}')
    def case_details(case_id:str,claim=Depends(clinician)):
        c=find(case_id);access(claim,c['patient_ref'])
        return queries.details(case_id)

    @router.get('/v1/audit/{case_id}')
    def audit(case_id:str,claim=Depends(clinician)):
        access(claim,find(case_id)['patient_ref'])
        return queries.audit(case_id)

    @router.get('/v1/outbox')
    def outbox(claim=Depends(clinician)):
        return queries.outbox(allowed_patient_refs(claim))
    return router
