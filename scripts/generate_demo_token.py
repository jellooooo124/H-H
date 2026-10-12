"""Development-only short-lived JWT issuer. Never expose as a web endpoint."""
import argparse, os, time
import jwt
p=argparse.ArgumentParser()
p.add_argument('role',choices=['patient','clinician'])
p.add_argument('--patient',default='DEMO-P001')
a=p.parse_args()
secret=os.environ.get('APP_TOKEN_SECRET','')
if len(secret)<32:raise SystemExit('Set APP_TOKEN_SECRET from .env')
claims={'iss':'hah-course-demo','sub':'demo-'+a.role,'role':a.role,'exp':int(time.time())+3600}
if a.role=='patient':claims['patient_ref']=a.patient
print(jwt.encode(claims,secret,algorithm='HS256'))
