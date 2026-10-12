"""Bearer-token verifier: strict demo HS256 OR externally signed OIDC RS256.

OIDC mode trusts only configured issuer/JWKS and audience. It derives role from a
configured groups claim; the token's arbitrary 'role' claim is intentionally ignored.
Patient-to-clinician assignments are checked separately against server-side DB.
"""
from __future__ import annotations
import jwt
from fastapi import HTTPException

class TokenVerifier:
    def __init__(self,settings,jwks_client=None):
        self.settings=settings
        if settings.auth_mode=='oidc':
            self.jwks=jwks_client or jwt.PyJWKClient(settings.oidc_jwks_url,cache_jwk_set=True,
                                                     lifespan=300,timeout=5)
        else: self.jwks=None

    def verify(self,authorization):
        if not authorization or not authorization.startswith('Bearer '):
            raise HTTPException(401,'Bearer token required')
        token=authorization[7:]
        if len(token)>16000:raise HTTPException(401,'Invalid bearer token')
        try:
            if self.settings.auth_mode=='demo':
                claims=jwt.decode(token,self.settings.jwt_secret,algorithms=['HS256'],
                    issuer='hah-course-demo',options={'require':['exp','iss','sub','role']})
                if claims.get('role') not in ('patient','clinician'):raise HTTPException(403,'Invalid role')
                return claims
            header=jwt.get_unverified_header(token)
            if header.get('alg')!='RS256' or not isinstance(header.get('kid'),str):
                raise HTTPException(401,'OIDC signature algorithm not permitted')
            signing_key=self.jwks.get_signing_key_from_jwt(token)
            claims=jwt.decode(token,signing_key.key,algorithms=['RS256'],
                issuer=self.settings.oidc_issuer,audience=self.settings.oidc_audience,
                options={'require':['exp','iat','iss','sub','aud']},leeway=30)
            groups=claims.get('groups',[])
            if not isinstance(groups,list) or not all(isinstance(g,str) for g in groups):
                raise HTTPException(403,'OIDC group claim invalid')
            clinician=self.settings.oidc_clinician_group in groups
            patient=self.settings.oidc_patient_group in groups
            if clinician==patient:raise HTTPException(403,'Exactly one role group is required')
            claims['role']='clinician' if clinician else 'patient'
            if patient:
                from .fhir_bridge import PATIENT_REF
                if not isinstance(claims.get('patient_ref'),str) or not PATIENT_REF.fullmatch(claims['patient_ref']):
                    raise HTTPException(403,'Patient reference must be a valid synthetic ID')
            return claims
        except HTTPException:raise
        except (jwt.PyJWTError,ValueError,KeyError,TypeError):
            raise HTTPException(401,'Invalid or expired bearer token')
