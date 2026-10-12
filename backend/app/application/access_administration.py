"""Synthetic patient-to-clinician assignment use case."""
from ..domain.patient_scope import PATIENT_REF
from ..domain.workflow_rules import WorkflowError

class AccessAdministration:
    def __init__(self,store):self.store=store
    def assign(self,clinician_sub,patient_ref,active):
        if not 1<=len(clinician_sub)<=150 or not PATIENT_REF.fullmatch(patient_ref):
            raise WorkflowError('invalid','Invalid synthetic assignment')
        self.store.set_assignment(clinician_sub,patient_ref,active,'access-admin')
        return {'assignment_updated':True,'active':active,'synthetic_only':True}
