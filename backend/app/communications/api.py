"""HTTP adapter. Never exposes n8n internal credentials or unrestricted patient lists."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .domain import WorkflowConflict

class DraftRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key: str = Field(min_length=12,max_length=80,pattern=r'^REQ-[A-Za-z0-9_-]+$')
    patient_ref: str = Field(pattern=r'^DEMO-[A-Za-z0-9_-]{3,45}$')
    template_code: Literal['CHECKIN_REQUEST','DEVICE_HELP','FOLLOWUP_ACK']
    due_hours: int = Field(ge=1,le=168)
    case_id: str | None = Field(default=None,pattern=r'^[A-Za-z0-9_-]{8,64}$')

def build_router(service,clinician,patient,internal,access):
    router=APIRouter(tags=['synthetic communications'])

    def find(mid):
        try:return service.repo.get(mid)
        except KeyError:raise HTTPException(404,'Message not found')

    @router.post('/v5/communications/drafts',status_code=201)
    def draft(data:DraftRequest,claim=Depends(clinician)):
        access(claim,data.patient_ref)
        try:return service.draft(**data.model_dump(),actor=claim['sub'])
        except WorkflowConflict as e:raise HTTPException(409,str(e))
        except KeyError:raise HTTPException(404,'Case not found')

    @router.post('/v5/communications/{message_id}/publish')
    def publish(message_id:str,claim=Depends(clinician)):
        message=find(message_id);access(claim,message['patient_ref'])
        try:return service.publish(message_id,claim['sub'])
        except WorkflowConflict as e:raise HTTPException(409,str(e))

    @router.get('/v5/clinician/communications/{patient_ref}')
    def clinician_messages(patient_ref:str,claim=Depends(clinician)):
        access(claim,patient_ref)
        return {'messages':service.repo.list_patient(patient_ref,include_drafts=True),'synthetic_only':True}

    @router.get('/v5/patient/communications')
    def patient_messages(claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        return {'messages':service.repo.list_patient(claim['patient_ref']),'external_notifications_sent':0}

    @router.post('/v5/patient/communications/{message_id}/acknowledge')
    def ack(message_id:str,claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        try:return service.acknowledge(message_id,claim['patient_ref'])
        except KeyError:raise HTTPException(404,'Message not found')
        except WorkflowConflict as e:raise HTTPException(409,str(e))

    @router.post('/internal/communications/watch')
    def watch(ok=Depends(internal)):
        return service.watch()

    @router.post('/internal/communications/metrics')
    def metrics(ok=Depends(internal)):
        return service.metrics()

    return router
