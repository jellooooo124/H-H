import hmac, time
import jwt
from fastapi import Depends, Header, HTTPException
from .config import Settings

settings=Settings.from_env()

def internal_auth(x_internal_key: str | None = Header(default=None)):
    if not x_internal_key or not hmac.compare_digest(x_internal_key, settings.internal_key):
        raise HTTPException(status_code=401,detail='Unauthorized internal request')
    return True

def principal(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401,detail='Bearer token required')
    try:
        claims=jwt.decode(authorization[7:],settings.jwt_secret,algorithms=['HS256'],options={'require':['exp','iss','sub','role']},issuer='hah-course-demo')
    except jwt.PyJWTError:
        raise HTTPException(status_code=401,detail='Invalid or expired token')
    if claims.get('role') not in ('patient','clinician'):
        raise HTTPException(status_code=403,detail='Invalid role')
    return claims

def clinician(claims=Depends(principal)):
    if claims['role']!='clinician': raise HTTPException(status_code=403,detail='Clinician permission required')
    return claims

def patient(claims=Depends(principal)):
    if claims['role']!='patient': raise HTTPException(status_code=403,detail='Patient permission required')
    return claims
