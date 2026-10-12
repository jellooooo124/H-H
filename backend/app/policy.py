"""Deterministic clinical-risk routing, independent from all LLM instructions.
Rules are TEACHING heuristics only; NOT approved medical thresholds.
"""
import re
from datetime import datetime, timezone

INJECTION_RE=re.compile(r'ignore (?:all |previous |the )?instructions|system prompt|developer message|bypass (?:security|approval)|send (?:without|directly)|override (?:the )?policy',re.I)
DISALLOWED_ADVICE=re.compile(r'\b(?:take|increase|decrease|stop|start)\s+(?:your\s+)?(?:dose|insulin|medication|tablets?|diuretics?)\b',re.I)

def assess(c):
    e=c['payload']; v=e['vitals']; symptoms=e['symptoms']; state=c['state']
    flags=[]; stop=[]
    if any(symptoms.get(k) for k in ('chest_pain','severe_breathlessness','fainting','confusion')):
        flags.append('REPORTED_URGENT_SYMPTOM');stop.append('REPORTED_URGENT_SYMPTOM')
    ts=v.get('last_sensor_at') or v.get('measured_at')
    if not ts:
        flags.append('MISSING_SENSOR_TIMESTAMP')
    else:
        try:
            t=datetime.fromisoformat(ts.replace('Z','+00:00'))
            if t.tzinfo is None: raise ValueError('Timezone missing')
            lag=(datetime.now(timezone.utc)-t).total_seconds()
            if lag>24*3600 or lag < -5*60: flags.append('STALE_OR_FUTURE_SENSOR_DATA')
        except (ValueError,TypeError):flags.append('INVALID_SENSOR_TIMESTAMP')
    if not any(v.get(k) is not None for k in ('weight_kg','glucose_mg_dl','heart_rate_bpm','spo2_pct')):
        flags.append('NO_ACTIVE_VITALS')
    trend=state.get('monitoring_context',{}).get('measurements',{}).get('weight_kg',{})
    if trend.get('delta') is not None and trend['delta']>=2:
        flags.append('DEMO_LONGITUDINAL_WEIGHT_REVIEW')
    w=v.get('weight_kg'); old=v.get('weight_prev_kg')
    if w is not None and old is not None and w-old>=2:
        flags.append('DEMO_WEIGHT_TREND_REVIEW')
        if e.get('meal_text') or state.get('agents',{}).get('nutrition'):
            flags.append('DIET_WEIGHT_CAUSALITY_UNCERTAIN')
    directions={a.get('hydration_direction') for a in state['agents'].values() if a.get('hydration_direction') not in (None,'none')}
    if len(directions)>1:
        flags.append('CONFLICTING_AGENT_HYDRATION'); stop.append('CONFLICTING_AGENT_HYDRATION')
    if any(a.get('hydration_direction') not in (None,'none') for a in state['agents'].values()):
        flags.append('NON_BOUNDED_HYDRATION_SUGGESTION'); stop.append('NON_BOUNDED_HYDRATION_SUGGESTION')
    if INJECTION_RE.search(e.get('meal_text','')+' '+symptoms.get('notes','')):
        flags.append('POTENTIAL_PROMPT_INJECTION'); stop.append('POTENTIAL_PROMPT_INJECTION')
    if any(a.get('confidence')=='low' for a in state['agents'].values()): flags.append('LOW_AGENT_CONFIDENCE')
    if any(a.get('needs_clinician_review') is False for a in state['agents'].values()):
        flags.append('AGENT_REJECTED_HUMAN_REVIEW'); stop.append('AGENT_REJECTED_HUMAN_REVIEW')
    synth=state.get('synthesis')
    if synth:
        known={s['source_id'] for s in state['sources']}
        if not synth.get('cited_source_ids') or not set(synth['cited_source_ids']).issubset(known):
            flags.append('MISSING_OR_INVALID_CITATIONS'); stop.append('MISSING_OR_INVALID_CITATIONS')
        if DISALLOWED_ADVICE.search(synth.get('patient_draft','')):
            flags.append('UNSAFE_PATIENT_DIRECTIVE'); stop.append('UNSAFE_PATIENT_DIRECTIVE')
    priority='urgent' if 'REPORTED_URGENT_SYMPTOM' in flags else ('review' if flags else 'routine')
    return {'flags':sorted(set(flags)),'safe_stop':bool(stop), 'stop_reasons':sorted(set(stop)),'priority':priority}
