"""Bounded synthetic FHIR use-cases, before reaching FHIR persistence bridge."""
import json

class FHIRInputError(ValueError):pass

class FHIRUseCases:
    def __init__(self,bridge):
        self.bridge=bridge

    def import_bundle(self,payload,actor):
        if len(json.dumps(payload,ensure_ascii=False)) > 256_000:
            raise FHIRInputError('FHIR_PAYLOAD_TOO_LARGE')
        if not isinstance(payload,dict) or set(payload)!={'patient_ref','is_synthetic','bundle'} or payload.get('is_synthetic') is not True:
            raise FHIRInputError('SYNTHETIC_WRAPPER_REQUIRED')
        return self.bridge.import_bundle(payload['patient_ref'],payload['bundle'],actor=actor)

    def export(self,patient_ref,limit):
        return self.bridge.export_observations(patient_ref,limit)

    def sync_synthetic(self):
        return self.bridge.sync_demo()
