"""Generate timezone-aware synthetic-only inputs for the Care Coordination 2.0 demo.
No network calls or patient data. Uses a fresh UUID on every invocation.
"""
import argparse, json,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',default='examples/v2',help='Output folder')
a=p.parse_args();path=Path(a.output);path.mkdir(parents=True,exist_ok=True)
now=datetime.now(timezone.utc)

def dump(name,body):
    target=path/name
    target.write_text(json.dumps(body,indent=2,ensure_ascii=False)+'\n')
    print(target)

for idx,weight in enumerate([70.2,70.8,71.6],1):
    at=now-timedelta(days=4-idx)
    dump(f'observation_{idx}.json',{
       'event_id':'OBS-'+uuid.uuid4().hex[:12].upper(),
       'patient_ref':'DEMO-P001','is_synthetic':True,'code':'weight_kg',
       'value':weight,'unit':'kg','taken_at':at.isoformat()})

dump('urgent_checkin.json',{'event_id':'CHK-'+uuid.uuid4().hex[:12].upper(),
    'patient_ref':'DEMO-P001','is_synthetic':True,
    'symptoms':{'severe_breathlessness':True,'notes':'Synthetic reported symptom for demo'},
    'device_problem':True,'patient_note':'Synthetic training case only'})

dump('routine_checkin.json',{'event_id':'CHK-'+uuid.uuid4().hex[:12].upper(),
    'patient_ref':'DEMO-P001','is_synthetic':True,'symptoms':{},
    'device_problem':False,'patient_note':'Synthetic routine check-in'})
