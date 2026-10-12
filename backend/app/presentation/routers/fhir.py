"""Synthetic FHIR v3 HTTP adapter; no EHR access outside test sandbox."""
from fastapi import APIRouter,Depends,Body,HTTPException
from ...application.fhir_use_cases import FHIRInputError
from ...fhir_bridge import FHIRConflict
import json

def build_router(use_cases,clinician,internal,access):
    router=APIRouter(tags=['synthetic FHIR R4'])

    @router.post('/v3/fhir/import')
    def import_bundle(data:dict=Body(...),claim=Depends(clinician)):
        # Check size/synthetic marker and scope before touching external data.
        try:
            if len(json.dumps(data,ensure_ascii=False))>256_000:raise HTTPException(413,'Synthetic FHIR payload too large')
            if set(data)!={'patient_ref','is_synthetic','bundle'} or data.get('is_synthetic') is not True:
                raise HTTPException(422,'Synthetic FHIR wrapper is required')
            access(claim,data['patient_ref'])
            return use_cases.import_bundle(data,claim['sub'])
        except HTTPException:raise
        except FHIRInputError as e:raise HTTPException(422,str(e))
        except FHIRConflict as e:raise HTTPException(409,str(e))
        except (ValueError,TypeError,KeyError) as e:raise HTTPException(422,str(e))

    @router.get('/v3/fhir/Observation')
    def export(patient_ref:str,limit:int=50,claim=Depends(clinician)):
        access(claim,patient_ref)
        try:return use_cases.export(patient_ref,limit)
        except ValueError as e:raise HTTPException(422,str(e))

    @router.post('/internal/fhir/sandbox-sync')
    def sync(ok=Depends(internal)):
        try:return use_cases.sync_synthetic()
        except (FHIRConflict,ValueError) as e:raise HTTPException(409,str(e))
    return router
