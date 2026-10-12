"""Case read models: redaction is a server invariant, independent of the UI."""
from __future__ import annotations

class CaseQueries:
    def __init__(self, case_repo):
        self.repo=case_repo

    def get(self, case_id):
        return self.repo.get(case_id)

    def details(self, case_id):
        case=self.get(case_id)
        case['payload']['meal_image_data_url']=None
        return case

    def list(self, patient_refs=None):
        return self.repo.list_cases(patient_refs)

    def audit(self, case_id):
        return {'events':self.repo.audit_events(case_id), 'chain_valid':self.repo.verify_audit()}

    def outbox(self, patient_refs=None):
        return self.repo.list_outbox(patient_refs)
