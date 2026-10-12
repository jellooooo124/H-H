"""Pure synthetic patient-scope domain policy; no database, HTTP or framework."""
from __future__ import annotations
import re
from collections.abc import Mapping

PATIENT_REF = re.compile(r'^DEMO-[A-Za-z0-9_-]{3,45}$')

class PatientScopeDenied(Exception):
    """A principal may not access a synthetic patient record."""

def validate_patient_ref(patient_ref: str) -> None:
    if not isinstance(patient_ref, str) or PATIENT_REF.fullmatch(patient_ref) is None:
        raise PatientScopeDenied('Invalid synthetic patient scope')

def assert_patient_access(claim: Mapping, patient_ref: str, *, oidc: bool, assigned: bool) -> None:
    validate_patient_ref(patient_ref)
    role = claim.get('role')
    if role == 'patient':
        permitted = claim.get('patient_ref') == patient_ref
    elif role == 'clinician' and oidc:
        # OIDC claims never authorize patient-specific access; the server DB does.
        permitted = assigned
    elif role == 'clinician':
        declared = claim.get('patient_refs')
        permitted = declared is None or (isinstance(declared, list) and patient_ref in declared)
    else:
        permitted = False
    if not permitted:
        raise PatientScopeDenied('Patient scope not assigned')
