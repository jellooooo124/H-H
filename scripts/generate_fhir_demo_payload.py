"""Produce a time-fresh synthetic FHIR R4 Observation Bundle for clinician import."""
import json
from datetime import datetime,timezone
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'examples'/'fhir_synthetic_bundle.json'
day=datetime.now(timezone.utc).strftime('%Y%m%d')
taken=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
entries=[]
for suffix,loinc,ucum,value in [('weight','29463-7','kg',70.3),('glucose','2339-0','mg/dL',124.0),('hr','8867-4','/min',82.0),('spo2','59408-5','%',97.0)]:
    entries.append({'resource':{'resourceType':'Observation','id':f'{suffix}-{day}-manual',
     'status':'final','subject':{'reference':'Patient/DEMO-P001'},
     'code':{'coding':[{'system':'http://loinc.org','code':loinc}]},
     'effectiveDateTime':taken,
     'valueQuantity':{'value':value,'system':'http://unitsofmeasure.org','code':ucum}}})
p.write_text(json.dumps({'patient_ref':'DEMO-P001','is_synthetic':True,
                          'bundle':{'resourceType':'Bundle','type':'collection','entry':entries}},indent=2)+'\n')
print(p)
