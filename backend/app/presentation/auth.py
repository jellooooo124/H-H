"""HTTP authentication dependencies; policy and database access are separate."""
import hmac
from fastapi import Depends, Header, HTTPException
from ..domain.patient_scope import PatientScopeDenied

class HttpAccess:
    def __init__(self,settings,verifier,access_control):
        self.settings=settings
        self.verifier=verifier
        self.access_control=access_control
        # No lazy auth defaults: all dependencies are named functions for FastAPI.

    def internal(self,x_internal_key: str | None=Header(default=None)):
        if not x_internal_key or not hmac.compare_digest(x_internal_key,self.settings.internal_key):
            raise HTTPException(401,'Internal authorization required')
        return True

    def auth(self,authorization: str | None=Header(default=None)):
        return self.verifier.verify(authorization)

    def require_patient(self,claim,patient_ref):
        try: self.access_control.require(claim,patient_ref)
        except PatientScopeDenied as exc: raise HTTPException(403,str(exc)) from exc
        return True

    def allowed_patient_refs(self,claim):
        return self.access_control.assigned_patients(claim)


def make_dependencies(settings,verifier,access_control):
    http=HttpAccess(settings,verifier,access_control)
    def clinician(claim=Depends(http.auth)):
        if claim['role']!='clinician': raise HTTPException(403,'Clinician only')
        return claim
    def patient(claim=Depends(http.auth)):
        if claim['role']!='patient': raise HTTPException(403,'Patient only')
        return claim
    def admin(x_admin_key: str | None=Header(default=None)):
        if settings.auth_mode!='oidc' or not x_admin_key or not hmac.compare_digest(x_admin_key,settings.admin_key):
            raise HTTPException(403,'Access administrator permission required')
        return True
    return http, clinician, patient, admin
