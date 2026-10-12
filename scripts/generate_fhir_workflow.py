"""Generate an import-ready n8n JSON. Only identifiers/aggregates cross this boundary."""
import json,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
namespace=uuid.UUID('b2d73cf0-e81c-4275-ab06-30dc8619dce0')
def node(name,typ,version,pos,params):
    return dict(id=str(uuid.uuid5(namespace,name)),name=name,type='n8n-nodes-base.'+typ,
                typeVersion=version,position=pos,parameters=params)
schedule=node('Every 12 Hours - Synthetic FHIR Sync','scheduleTrigger',1.2,[0,180],
  {'rule':{'interval':[{'field':'hours','hoursInterval':12}]}})
request=node('Sync Allowlisted Synthetic FHIR Observations','httpRequest',4.2,[270,180],{
  'method':'POST', 'url':'http://api:8000/internal/fhir/sandbox-sync',
  'sendHeaders':True,'headerParameters':{'parameters':[{'name':'X-Internal-Key','value':'={{ $env.HAH_INTERNAL_KEY }}'}]},
  'sendBody':True,'specifyBody':'json','jsonBody':'={{ JSON.stringify({}) }}',
  'options':{'timeout':45000}})
w={'name':'H@H 08 — Synthetic FHIR R4 Sandbox Sync (No EHR Connected)',
   'nodes':[schedule,request],
   'connections':{schedule['name']:{'main':[[{'node':request['name'],'type':'main','index':0}]]}},
   'settings':{'executionOrder':'v1','saveExecutionProgress':False,'saveManualExecutions':False,
               'saveDataErrorExecution':'none','saveDataSuccessExecution':'none'},
   'active':False,'pinData':{},'tags':[]}
(root/'workflows'/'08_synthetic_fhir_sandbox_sync.json').write_text(json.dumps(w,indent=2,ensure_ascii=False)+'\n')
