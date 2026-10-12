"""Generate n8n 2.x importable workflows using only built-in nodes."""
import json, pathlib, uuid
ROOT=pathlib.Path(__file__).resolve().parents[1]/'workflows'
ROOT.mkdir(exist_ok=True)

def node(name,typ,pars,x,y,version=1):
    return {'id':str(uuid.uuid5(uuid.NAMESPACE_DNS,'hah-full-'+name)),'name':name,
            'type': 'n8n-nodes-base.'+typ,'typeVersion':version,'position':[x,y],'parameters':pars}

def http(name,path,x,y,body=None):
    par={'method':'POST','url':'http://api:8000'+path,'sendHeaders':True,
         'headerParameters':{'parameters':[{'name':'X-Internal-Key','value':'={{ $env.HAH_INTERNAL_KEY }}'}]},
         'sendBody':True,'specifyBody':'json','jsonBody':body or '={{ JSON.stringify({case_id: $json.case_id}) }}',
         'options':{'timeout':120000}}
    return node(name,'httpRequest',par,x,y,4.2)

def connect(conn,a,b,output=0):
    conn.setdefault(a,{'main':[]})
    while len(conn[a]['main'])<=output:conn[a]['main'].append([])
    conn[a]['main'][output].append({'node':b,'type':'main','index':0})

def emit(filename,name,nodes,conn):
    doc={'name':name,'nodes':nodes,'connections':conn,'settings':{'executionOrder':'v1','saveExecutionProgress':False,
         'saveManualExecutions':False,'saveDataErrorExecution':'none','saveDataSuccessExecution':'none'},
         'active':False,'pinData':{},'tags':[]}
    (ROOT/filename).write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

webhook=node('Case ID Webhook (Internal Only)','webhook',{'httpMethod':'POST','path':'hah-case-intake','responseMode':'onReceived','options':{}},0,250,2)
start=http('Start Case State','/internal/start',240,250,'={{ JSON.stringify({case_id: $json.body.case_id}) }}')
plan=http('Planner (Real LLM)','/internal/plan',480,250)
check=node('Finish When All Tools Complete','if',{'conditions':{'options':{'caseSensitive':True,'leftValue':'','typeValidation':'strict','version':2},'combinator':'and','conditions':[{'id':'done-condition','leftValue':'={{ $json.done }}','rightValue':True,'operator':{'type':'boolean','operation':'equals'}}]},'options':{}},720,250,2.2)
run=http('Execute Bounded Agent Tool','/internal/tool',960,420,'={{ JSON.stringify({case_id: $json.case_id, tool: $json.next_tool}) }}')
final=http('Synthesize and Safety Gate','/internal/finalize',960,100)
conn={}
connect(conn,webhook['name'],start['name']);connect(conn,start['name'],plan['name']);connect(conn,plan['name'],check['name']);connect(conn,check['name'],final['name'],0);connect(conn,check['name'],run['name'],1);connect(conn,run['name'],plan['name'])
emit('01_agentic_case_loop.json','H@H 01 — Dynamic Multi-Agent Planner + Tools + Clinical Gate',[webhook,start,plan,check,run,final],conn)

schedule=node('Every 5 Minutes','scheduleTrigger',{'rule':{'interval':[{'field':'minutes','minutesInterval':5}]}},0,100,1.2)
watch=http('Fail-Closed Overdue Escalation','/internal/watchdog',240,100,'={{ JSON.stringify({}) }}')
emit('02_sla_watchdog.json','H@H 02 — Overdue Cases / Human Escalation',[schedule,watch],{'Every 5 Minutes':{'main':[[{'node':watch['name'],'type':'main','index':0}]]}})

manual=node('Manual Index Trigger','manualTrigger',{},0,100)
index=http('Index Approved Guideline Embeddings','/internal/knowledge/reindex',260,100,'={{ JSON.stringify({}) }}')
emit('03_rag_index_refresh.json','H@H 03 — Approved RAG Index Refresh',[manual,index],{'Manual Index Trigger':{'main':[[{'node':index['name'],'type':'main','index':0}]]}})

err=node('Execution Error (No PHI Forwarded)','errorTrigger',{},0,100)
report=http('Redacted Error Log','/internal/error',280,100,'={{ JSON.stringify({ workflow_name: "n8n", error_code: "EXECUTION_FAILED" }) }}')
emit('04_redacted_error_handler.json','H@H 04 — Operational Error (No PHI)',[err,report],{'Execution Error (No PHI Forwarded)':{'main':[[{'node':report['name'],'type':'main','index':0}]]}})
print('Created',len(list(ROOT.glob('*.json'))),'workflows')
