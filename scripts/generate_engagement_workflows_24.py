"""Generate two inactive, importable standard n8n workflows (synthetic only)."""
from pathlib import Path
import json, uuid
root=Path(__file__).resolve().parents[1]
out=root/'workflows';out.mkdir(exist_ok=True)

def nodeid(s):return str(uuid.uuid5(uuid.NAMESPACE_DNS,'hah-2.4:'+s))
def make(idx,title,path,interval):
    trigger_name='Hourly — '+title
    invoke_name='POST aggregate-only '+title
    nodes=[
      {'id':nodeid(title+'trigger'),'name':trigger_name,'type':'n8n-nodes-base.scheduleTrigger','typeVersion':1.2,'position':[0,160],
       'parameters':{'rule':{'interval':[{'field':'hours','hoursInterval':interval}]}}},
      {'id':nodeid(title+'request'),'name':invoke_name,'type':'n8n-nodes-base.httpRequest','typeVersion':4.2,'position':[300,160],
       'parameters':{'method':'POST','url':'http://api:8000'+path,
                     'sendHeaders':True,'headerParameters':{'parameters':[{'name':'X-Internal-Key','value':'={{ $env.HAH_INTERNAL_KEY }}'}]},
                     'sendBody':True,'specifyBody':'json','jsonBody':'={{ JSON.stringify({}) }}',
                     'options':{'timeout':45000}}}
    ]
    doc={'name':f'H@H {idx} — {title}', 'nodes':nodes,
         'connections':{trigger_name:{'main':[[{'node':invoke_name,'type':'main','index':0}]]}},
         'settings':{'executionOrder':'v1','saveExecutionProgress':False,'saveManualExecutions':False,
                     'saveDataErrorExecution':'none','saveDataSuccessExecution':'none'},
         'active':False,'pinData':{},'tags':[]}
    path=out/f'{idx}_{title.lower().replace(" ","_")}.json'
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    return path
print(make('12','Synthetic Engagement Watch','/internal/engagement/watch',1))
print(make('13','Aggregate Quality Snapshot','/internal/ops/quality-snapshot',1))
