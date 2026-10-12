"""Generate n8n-native, synthetic-only workflow JSON (no credentials embedded)."""
import json, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build(number,label,endpoint,field,interval):
    a=f'Every {interval} {field} — {label}'
    b=f'POST synthetic-only {label}'
    trig={'id':str(uuid.uuid5(uuid.NAMESPACE_DNS,str(number)+'-schedule')),'name':a,
      'type':'n8n-nodes-base.scheduleTrigger','typeVersion':1.2,'position':[0,200],
      'parameters':{'rule':{'interval':[{'field':field,field+'Interval':interval}]}}}
    req={'id':str(uuid.uuid5(uuid.NAMESPACE_DNS,str(number)+'-http')),'name':b,
      'type':'n8n-nodes-base.httpRequest','typeVersion':4.2,'position':[320,200],
      'parameters':{'method':'POST','url':'http://api:8000/internal/'+endpoint,
      'sendHeaders':True,'headerParameters':{'parameters':[{'name':'X-Internal-Key','value':'={{ $env.HAH_INTERNAL_KEY }}'}]},
      'sendBody':True,'specifyBody':'json','jsonBody':'={{ JSON.stringify({}) }}','options':{'timeout':45000}}}
    return {'name':f'H@H {number:02d} — {label}','nodes':[trig,req],
      'connections':{a:{'main':[[{'node':b,'type':'main','index':0}]]}},
      'settings':{'executionOrder':'v1','saveExecutionProgress':False,'saveManualExecutions':False,
       'saveDataErrorExecution':'none','saveDataSuccessExecution':'none'},
      'active':False,'pinData':{},'tags':[]}
for num,title,url,field,interval in [
    (14,'Synthetic Message Follow-up Watch','communications/watch','minutes',15),
    (15,'Synthetic Communications Quality Metrics','communications/metrics','hours',1)]:
    (ROOT/'workflows'/(f"{num:02d}_{url.split('/')[-1]}.json")).write_text(json.dumps(build(num,title,url,field,interval),indent=2,ensure_ascii=False)+'\n')
