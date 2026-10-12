"""Bounded agent use cases. Domain state is checked independently from the LLM."""
from __future__ import annotations
from ..domain.workflow_rules import WorkflowError, processing, tool_allowed, MANDATORY_TOOLS
from ..agents import plan_next, run_agent, synthesize

class AgentExecution:
    def __init__(self, clinical_cases, store, coordination, model, rag, policy):
        self.cases, self.store, self.coordination = clinical_cases, store, coordination
        self.model, self.rag, self.policy = model, rag, policy

    def start(self, case_id):
        with self.store.transaction():
            c=self.cases.get(case_id)
            if c['status']!='RECEIVED':raise WorkflowError('conflict','Case already started')
            c['status']='PROCESSING'
            c['state']['monitoring_context']=self.coordination.summary(c['patient_ref'])
            c=self.store.save(c,'WORKFLOW_STARTED','n8n')
        return {'case_id':c['case_id'],'status':c['status']}

    def plan(self, case_id):
        c=self.cases.get(case_id);processing(c)
        try: recommendation=plan_next(self.model,c)
        except Exception:
            self.cases.fail_closed(case_id,'PLANNER_FAILURE')
            raise WorkflowError('unavailable','Planner failed closed')
        if len(c['state']['steps'])>len(MANDATORY_TOOLS):
            self.cases.fail_closed(case_id,'TOOL_LIMIT')
            raise WorkflowError('conflict','Step limit exceeded')
        c['state']['plan'].append({'tool':recommendation['next_tool'],'forced':recommendation['forced']})
        c['state']['planned_next']=recommendation['next_tool']
        try:self.store.save(c,'PLANNER_DECISION','planner',{'tool':recommendation['next_tool'],'forced':recommendation['forced']})
        except ValueError as exc: raise WorkflowError('conflict','Concurrent case modification') from exc
        return {'case_id':case_id,'next_tool':recommendation['next_tool'],'done':recommendation['next_tool']=='finish'}

    def execute_tool(self, case_id, name):
        c=self.cases.get(case_id);processing(c);tool_allowed(c,name)
        try:
            if name=='guideline_search':
                v=c['payload']['vitals']; symptoms=c['payload']['symptoms']
                parts=['home monitoring','heart failure','diabetes','clinician review','educational local protocol']
                if not v.get('last_sensor_at'):parts.extend(['sensor missingness','data quality'])
                if symptoms.get('swelling') or symptoms.get('severe_breathlessness'):parts.append('heart failure symptoms and body weight')
                if v.get('glucose_mg_dl') is not None:parts.append('glucose measurement')
                result=self.rag.retrieve(' '.join(parts))
                if not result:raise RuntimeError('EMPTY_RETRIEVAL')
                c['state']['sources']=result
            else:
                c['state']['agents'][name]=run_agent(self.model,c,name)
                if name=='nutrition':self.store.remove_image(c)
            c['state']['steps'].append(name)
            c['state']['planned_next']=None
            self.store.save(c,'TOOL_COMPLETED',name,{'tool':name})
            return {'case_id':case_id,'completed_tool':name,'steps_completed':len(c['state']['steps'])}
        except Exception:
            self.cases.fail_closed(case_id,f'TOOL_FAILURE_{name}')
            raise WorkflowError('unavailable','Tool failed closed')

    def finalize(self,case_id):
        c=self.cases.get(case_id);processing(c)
        if set(c['state']['steps'])!=MANDATORY_TOOLS:
            raise WorkflowError('conflict','Mandatory evidence is incomplete')
        if c['state'].get('planned_next')!='finish':
            raise WorkflowError('conflict','Planner has not stopped')
        try:
            c['state']['synthesis']=synthesize(self.model,c)
            result=self.policy(c)
            c['state']['flags']=result['flags'];c['state']['priority']=result['priority']
            c['state']['stop_reasons']=result['stop_reasons']
            c['status']='ESCALATION_REQUIRED' if result['safe_stop'] else 'AWAITING_CLINICIAN'
            self.store.remove_image(c)
            with self.store.transaction():
                c=self.store.save(c,'POLICY_FINALIZED','policy',{'safe_stop':result['safe_stop'],
                    'priority':result['priority'],'flag_count':len(result['flags'])})
                self.coordination.new_task('review:'+case_id,case_id,c['patient_ref'],'clinical_review',
                    result['priority'],'SAFE_STOP' if result['safe_stop'] else 'CLINICIAN_REVIEW_REQUIRED',
                    300 if result['priority']=='urgent' else 1800)
        except Exception:
            self.cases.fail_closed(case_id,'SYNTHESIS_OR_POLICY_FAILURE')
            raise WorkflowError('unavailable','Finalization failed closed')
        return {'case_id':case_id,'status':c['status'],'safe_stop':result['safe_stop'],'priority':result['priority']}

    def reindex(self):
        if any(c['status']=='PROCESSING' for c in self.store.list_cases()):
            raise WorkflowError('conflict','Index changes are blocked during active processing')
        try: return self.rag.reindex()
        except Exception:raise WorkflowError('unavailable','Embedding index unavailable')
