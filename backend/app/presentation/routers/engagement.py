"""Patient/clinician engagement HTTP adapter (all routes preserve old URLs)."""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field

class PatientPreferenceIn(BaseModel):
    reminder_opt_in:bool=False
    reminder_hour_utc:int=Field(ge=0,le=23)
    minimum_gap_hours:int=Field(ge=24,le=168)

def build_router(use_cases,clinician,patient,internal,access,allowed_patient_refs):
    router=APIRouter(tags=['patient engagement'])

    @router.get('/v4/patient/dashboard')
    def dashboard(days:int=7,claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        try:return use_cases.dashboard(claim['patient_ref'],days)
        except ValueError as exc:raise HTTPException(422,str(exc))

    @router.get('/v4/patient/preferences')
    def preferences(claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        return use_cases.preferences(claim['patient_ref'])

    @router.put('/v4/patient/preferences')
    def set_preferences(data:PatientPreferenceIn,claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        return use_cases.set_preferences(claim['patient_ref'],data.reminder_opt_in,data.reminder_hour_utc,data.minimum_gap_hours)

    @router.get('/v4/patient/prompts')
    def prompts(claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        return use_cases.prompts(claim['patient_ref'])

    @router.post('/v4/patient/prompts/{prompt_id}/seen')
    def seen(prompt_id:str,claim=Depends(patient)):
        access(claim,claim['patient_ref'])
        try:return use_cases.mark_seen(claim['patient_ref'],prompt_id)
        except KeyError:raise HTTPException(404,'Prompt not found')
        except ValueError:raise HTTPException(409,'Prompt no longer active')

    @router.get('/v4/clinician/alert-groups')
    def alert_groups(claim=Depends(clinician)):
        return use_cases.alert_groups(allowed_patient_refs(claim))

    @router.get('/v4/clinician/evaluation/{patient_ref}')
    def evaluation(patient_ref:str,days:int=7,claim=Depends(clinician)):
        access(claim,patient_ref)
        try:return use_cases.evaluation(patient_ref,days)
        except ValueError as exc:raise HTTPException(422,str(exc))

    @router.post('/internal/engagement/watch')
    def watch(ok=Depends(internal)):
        return use_cases.reminder_watch()

    @router.post('/internal/ops/quality-snapshot')
    def snapshot(ok=Depends(internal)):
        return use_cases.snapshot()
    return router
