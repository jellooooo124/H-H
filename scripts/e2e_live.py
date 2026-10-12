"""Run only after n8n is activated AND your real OPENAI_API_KEY is configured.
This consumes API tokens and uses SYNTHETIC inputs only.
"""
import argparse,copy,json,os,pathlib,time,urllib.request,urllib.error
import jwt

p=argparse.ArgumentParser()
p.add_argument('--scenario',choices=['normal','redflag','injection'],default='normal')
p.add_argument('--base',default='http://127.0.0.1:8000')
a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]
secret=os.environ.get('APP_TOKEN_SECRET','')
if len(secret)<32:raise SystemExit('Load .env into shell first: set -a; source .env; set +a')
def token(role):
    obj={'iss':'hah-course-demo','sub':'smoke-'+role,'role':role,'exp':int(time.time())+3600}
    if role=='patient':obj['patient_ref']='DEMO-P001'
    return jwt.encode(obj,secret,algorithm='HS256')
def req(method,path,data,role):
    payload=json.dumps(data).encode() if data is not None else None
    h={'Authorization':'Bearer '+token(role),'Content-Type':'application/json'}
    try:
        with urllib.request.urlopen(urllib.request.Request(a.base+path,data=payload,headers=h,method=method),timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read().decode()}')
record=json.loads((root/'examples'/f'{a.scenario}.json').read_text())
record['case_id']='HHC-LIVE-'+str(int(time.time()))
print('Submitting synthetic record:',record['case_id'])
print(req('POST','/v1/intake',record,'patient'))
for i in range(35):
    time.sleep(3)
    case=req('GET','/v1/cases/'+record['case_id'],None,'clinician')
    print(f"{i*3+3}s - {case['status']} | completed {case['state']['steps']}")
    if case['status'] not in ('RECEIVED','PROCESSING'):
        print('State:',case['status'],'flags=',case['state']['flags'])
        print('RAG sources:',[s['source_id'] for s in case['state']['sources']])
        print('No patient message has been sent.')
        break
else: raise SystemExit('TIMEOUT: Check n8n activation, logs and provider API configuration')
