#!/usr/bin/env python3
"""Offline synthetic rule-based regression only. NEVER label results clinical sensitivity."""
import sys,json,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.policy import assess

def evaluate(dataset):
    results=[]
    for row in dataset['cases']:
        c={'payload':{'vitals':row['vitals'],'symptoms':row['symptoms'],'meal_text':row['meal_text']},
           'state':{'agents':row.get('agents',{}),'monitoring_context':{},
                    'sources':[{'source_id':'DOC-1'}],'synthesis':row.get('synthesis')}}
        actual=assess(c)
        expected_stop=row['expected_safe_stop'];expected_urgent=row['expected_urgent']
        results.append({'id':row['id'],'expected_safe_stop':expected_stop,
                        'actual_safe_stop':actual['safe_stop'],'expected_urgent':expected_urgent,
                        'actual_urgent':actual['priority']=='urgent','flags':actual['flags'],
                        'matches_expected':expected_stop==actual['safe_stop'] and expected_urgent==(actual['priority']=='urgent')})
    summary={'dataset':dataset['dataset'],'scenario_count':len(results),
             'passed':sum(x['matches_expected'] for x in results),
             'failed':sum(not x['matches_expected'] for x in results),
             'scope':'deterministic regression on researcher-written synthetic fixtures; NOT clinical validation',
             'limitations':['No real patient cohort','No blinded expert review','Not sensitivity or specificity','No prospective testing']}
    return {'summary':summary,'cases':results}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default=str(ROOT/'docs'/'SYNTHETIC_POLICY_EVALUATION.json'))
    args=p.parse_args()
    dataset=json.loads((ROOT/'examples'/'policy_ground_truth_synthetic.json').read_text())
    report=evaluate(dataset)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(f"Synthetic scenario checks: {report['summary']['passed']}/{report['summary']['scenario_count']}")
    sys.exit(0 if report['summary']['failed']==0 else 1)
