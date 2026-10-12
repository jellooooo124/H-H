"""Thin transport adapter for synthetic case intake and human decisions."""
from fastapi import APIRouter, Depends, HTTPException
from ...schemas import Intake, Decision
from ...domain.workflow_rules import WorkflowError

STATUS={'not_found':404,'conflict':409,'forbidden':403,'unavailable':503}
def translate(exc:WorkflowError):
    return HTTPException(STATUS.get(exc.kind,500),exc.message)

def build_router(service,patient,clinician,access):
    router=APIRouter(tags=['synthetic case workflow'])

    @router.post('/v1/intake',status_code=202)
    async def intake(data:Intake,claim=Depends(patient)):
        access(claim,data.patient_ref)
        try:return await service.intake(data.model_dump())
        except ValueError:raise HTTPException(409,'Case already exists')
        except WorkflowError as exc:raise translate(exc) from exc

    @router.post('/v1/decisions')
    def decision(data:Decision,claim=Depends(clinician)):
        try:
            case=service.get(data.case_id)
            access(claim,case['patient_ref'])
            return service.decide(data,claim['sub'])
        except WorkflowError as exc:raise translate(exc) from exc
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc

    return router
