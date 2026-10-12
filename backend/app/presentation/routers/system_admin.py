"""HTTP-adapter for protected synthetic admin and readiness endpoints."""
from fastapi import APIRouter,Depends
from pydantic import BaseModel
from ...domain.workflow_rules import WorkflowError
from .clinical_cases import translate

class AssignmentIn(BaseModel):
    clinician_sub:str
    patient_ref:str
    active:bool=True

def build_router(service,admin,store,model,settings):
    router=APIRouter(tags=['system administration'])
    @router.post('/admin/assignments')
    def assign(data:AssignmentIn,ok=Depends(admin)):
        try:return service.assign(data.clinician_sub,data.patient_ref,data.active)
        except WorkflowError as exc:
            if exc.kind=='invalid':
                from fastapi import HTTPException
                raise HTTPException(422,exc.message) from exc
            raise translate(exc) from exc
    @router.get('/health')
    def health():
        return {'ok':True,'synthetic_only':True,'llm_configured':model.available(),
                'db_backend':store.backend,'auth_mode':settings.auth_mode}
    return router
