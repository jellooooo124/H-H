"""Build importable, disabled v2.2 audit/DB operational check workflow."""
import json,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def node(name,kind,position,params,version):
    return {'id':str(uuid.uuid5(uuid.NAMESPACE_DNS,'hah-2.2:'+name)),'name':name,
        'type':'n8n-nodes-base.'+kind,'position':position,'typeVersion':version,'parameters':params}
a=node('Hourly Synthetic Datastore Audit','scheduleTrigger',[0,80],
       {'rule':{'interval':[{'field':'hours','hoursInterval':1}]}},1.2)
b=node('Verify DB Connectivity and Audit HMAC Chain','httpRequest',[270,80],{
    'method':'POST','url':'http://api:8000/internal/ops/audit-health',
    'sendHeaders':True,'headerParameters':{'parameters':[{'name':'X-Internal-Key',
                       'value':'={{ $env.HAH_INTERNAL_KEY }}'}]},
    'sendBody':True,'specifyBody':'json','jsonBody':'={{ JSON.stringify({}) }}',
    'options':{'timeout':30000}},4.2)
c=node('Fail Closed on Readiness Errors','if',[540,80],{
    'conditions':{'options':{'caseSensitive':True,'leftValue':'','typeValidation':'strict','version':2},
        'combinator':'and','conditions':[{'id':'cf116983-98ca-4b31-b280-3c0b1a5f6cd2',
        'leftValue':'={{ $json.ok }}','rightValue':True,'operator':{'type':'boolean','operation':'true','singleValue':True}}]},
    'options':{}},2.2)
# Only a straightforward schedule->HTTP call is necessary: HTTP errors already fail the workflow.
doc={'name':'H@H 09 — PostgreSQL and Audit Chain Readiness (Synthetic)',
    'nodes':[a,b],'connections':{a['name']:{'main':[[{'node':b['name'],'type':'main','index':0}]]}},
    'settings':{'executionOrder':'v1','saveExecutionProgress':False,'saveManualExecutions':False,
                'saveDataErrorExecution':'none','saveDataSuccessExecution':'none'},
    'active':False,'pinData':{},'tags':[]}
p=root/'workflows'/'09_database_auth_audit_health.json'
p.write_text(json.dumps(doc,indent=2,ensure_ascii=False)+'\n')
print('Created:',p)
