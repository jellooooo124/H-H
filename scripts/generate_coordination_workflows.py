"""Generate 2.0 n8n workflows. Only opaque IDs enter the orchestrator."""
import json,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'workflows'

def node(name,type,xy,params,version):
    return {'id':str(uuid.uuid5(uuid.NAMESPACE_DNS,'hah-v2:'+name)),
            'name':name,'type':'n8n-nodes-base.'+type,'typeVersion':version,
            'position':xy,'parameters':params}

def http_node(name,path,body,xy):
    return node(name,'httpRequest',xy,{
       'method':'POST','url':'http://api:8000'+path,'sendHeaders':True,
       'headerParameters':{'parameters':[{'name':'X-Internal-Key','value':'={{ $env.HAH_INTERNAL_KEY }}'}]},
       'sendBody':True,'specifyBody':'json','jsonBody':body,
       'options':{'timeout':45000}},4.2)

def schedule(name,minutes):
    return node(name,'scheduleTrigger',[0,180],{'rule':{'interval':[{'field':'minutes','minutesInterval':minutes}]}},1.2)

def connect(a,b): return {a:{'main':[[{'node':b,'type':'main','index':0}]]}}

def document(name,nodes,connections):
    return {'name':name,'nodes':nodes,'connections':connections,'settings':{
        'executionOrder':'v1','saveExecutionProgress':False,'saveManualExecutions':False,
        'saveDataErrorExecution':'none','saveDataSuccessExecution':'none'},
        'active':False,'pinData':{},'tags':[]}

trigger=node('Synthetic Checkin Event ID','webhook',[0,180],{
    'httpMethod':'POST','path':'hah-checkin-intake','responseMode':'onReceived','options':{}},2)
triage=http_node('Triage Checkin With Deterministic Safety','/internal/checkin/triage',
    '={{ JSON.stringify({event_id: $json.body.event_id}) }}',[250,180])
checkin=document('H@H 05 — Checkin Safety Routing (No PHI)',[trigger,triage],connect(trigger['name'],triage['name']))

sched=schedule('Every 15 Minutes — Safety Reconciliation',15)
watch=http_node('Reconcile Checkins Data Gaps and Task SLAs','/internal/coordination/watch',
     '={{ JSON.stringify({}) }}',[250,180])
reconcile=document('H@H 06 — Closed-Loop Care Reconciler',[sched,watch],connect(sched['name'],watch['name']))

sched2=schedule('Every 3 Minutes — Replay Pending Accepted Events',3)
retry=http_node('Retry Undispatched Cases With Idempotent Start','/internal/retry-pending',
    '={{ JSON.stringify({}) }}',[250,180])
recovery=document('H@H 07 — Durable Intake Recovery',[sched2,retry],connect(sched2['name'],retry['name']))
for fn,obj in [('05_checkin_safety_route.json',checkin),('06_coordination_reconciler.json',reconcile),('07_pending_recovery.json',recovery)]:
    (DEST/fn).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n')
print('Generated 3 importable n8n workflows')
