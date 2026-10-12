"""Application permission service using DB-backed assignments (in OIDC mode)."""
from __future__ import annotations
from ..domain.patient_scope import assert_patient_access

class AccessControl:
    def __init__(self, assignments, auth_mode: str):
        self._assignments = assignments
        self._oidc = auth_mode == 'oidc'

    def require(self, claim, patient_ref):
        # In OIDC mode, the server-side assignment must be queried for EACH request.
        assigned = (self._assignments.is_assigned(claim['sub'], patient_ref)
                    if self._oidc and claim.get('role') == 'clinician' else False)
        assert_patient_access(claim, patient_ref, oidc=self._oidc, assigned=assigned)

    def assigned_patients(self, claim):
        return self._assignments.assignments(claim['sub']) if self._oidc else None
