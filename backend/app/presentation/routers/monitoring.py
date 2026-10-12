"""Monitoring HTTP routes; domain work is performed by MonitoringUseCases."""
from fastapi import APIRouter,Depends,HTTPException,Body
from ...schemas import ObservationIn,MonitoringPlanIn,CheckinIn,TaskResolveIn,ReceiptIn

def build_router(service,patient,clinician,auth,internal,access,allowed_patient_refs):
    router=APIRouter(tags=['synthetic monitoring'])

    @router.post('/v2/observations',status_code=201)
    def observation(data:ObservationIn,claim=Depends(patient)):
        access(claim,data.patient_ref)
        try:return service.observation(data.patient_ref,data.event_id,data.code,data.value,data.unit,data.taken_at)
        except ValueError as e:raise HTTPException(409 if str(e)=='DUPLICATE_EVENT' else 422,str(e))

    @router.get('/v2/patients/{patient_ref}/trends')
    def trends(patient_ref:str,days:int=7,claim=Depends(auth)):
        access(claim,patient_ref)
        try:return service.trends(patient_ref,days)
        except ValueError as e:raise HTTPException(422,str(e))

    @router.post('/v2/monitoring-plans')
    def monitoring_plan(data:MonitoringPlanIn,claim=Depends(clinician)):
        access(claim,data.patient_ref)
        return service.monitoring_plan(data.patient_ref,data.observation_code,data.review_gap_hours,claim['sub'],data.active)

    @router.post('/v2/checkins',status_code=202)
    async def checkin(data:CheckinIn,claim=Depends(patient)):
        access(claim,data.patient_ref)
        try:return await service.checkin(data.patient_ref,data.event_id,data.model_dump())
        except ValueError as e:raise HTTPException(409,str(e))

    @router.get('/v2/tasks')
    def tasks(claim=Depends(clinician)):
        return service.tasks(allowed_patient_refs(claim))

    def checked_task(task_id,claim):
        try:task=service.get_task(task_id)
        except KeyError:raise HTTPException(404,'Task not found')
        access(claim,task['patient_ref'])

    @router.post('/v2/tasks/{task_id}/claim')
    def task_claim(task_id:str,claim=Depends(clinician)):
        checked_task(task_id,claim)
        try:return service.claim_task(task_id,claim['sub'])
        except KeyError:raise HTTPException(404,'Task not found')
        except ValueError as e:raise HTTPException(409,str(e))

    @router.post('/v2/tasks/{task_id}/resolve')
    def task_resolve(task_id:str,data:TaskResolveIn,claim=Depends(clinician)):
        checked_task(task_id,claim)
        try:return service.resolve_task(task_id,data.outcome,data.note,claim['sub'])
        except KeyError:raise HTTPException(404,'Task not found')
        except ValueError as e:raise HTTPException(409,str(e))

    @router.post('/v2/patient/receipt')
    def receipt(data:ReceiptIn,claim=Depends(patient)):
        access(claim,data.patient_ref)
        try:return service.patient_receipt(data.case_id,data.patient_ref,claim['sub'])
        except KeyError:raise HTTPException(404,'Case not found')
        except ValueError as e:raise HTTPException(409,str(e))

    @router.post('/internal/checkin/triage')
    def checkin_triage(data:dict=Body(...),ok=Depends(internal)):
        if not isinstance(data.get('event_id'),str):raise HTTPException(422,'event_id required')
        try:return service.triage_checkin(data['event_id'])
        except KeyError:raise HTTPException(404,'Check-in not found')

    @router.post('/internal/coordination/watch')
    def coordination_watch(ok=Depends(internal)):
        return service.watch()

    @router.get('/v2/metrics')
    def metrics(claim=Depends(clinician)):
        try:return service.metrics()
        except PermissionError as e:raise HTTPException(403,str(e))

    return router
