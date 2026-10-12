"""Pure clinical-case workflow invariants; synthetic-research rules, not medical advice."""
from __future__ import annotations

MANDATORY_TOOLS = frozenset(('nutrition', 'heart_failure', 'diabetes', 'guideline_search'))
URGENT_SYMPTOMS = frozenset(('chest_pain', 'severe_breathlessness', 'fainting', 'confusion'))

class WorkflowError(Exception):
    """Business-level failure mapped to HTTP only in presentation."""
    def __init__(self, kind: str, message: str):
        self.kind, self.message = kind, message
        super().__init__(message)


def urgent_reported(symptoms: dict) -> bool:
    return any(bool(symptoms.get(key)) for key in URGENT_SYMPTOMS)


def processing(case: dict) -> None:
    if case['status'] != 'PROCESSING':
        raise WorkflowError('conflict', 'Case is not processing')


def reviewable(case: dict, choice: str) -> None:
    if case['status'] not in ('AWAITING_CLINICIAN', 'ESCALATION_REQUIRED', 'TECHNICAL_REVIEW'):
        raise WorkflowError('conflict', 'Case not reviewable')
    if choice == 'approve' and case['status'] != 'AWAITING_CLINICIAN':
        raise WorkflowError('conflict', 'Safe-stop: only escalate/reject')


def approval_evidence(case: dict, policy_result: dict) -> None:
    if policy_result['safe_stop'] or not case['state']['synthesis']:
        raise WorkflowError('conflict', 'Policy blocks approval')
    if not MANDATORY_TOOLS.issubset(case['state']['steps']):
        raise WorkflowError('conflict', 'Missing mandatory tool evidence')


def tool_allowed(case: dict, tool: str) -> None:
    if tool not in MANDATORY_TOOLS or tool != case['state'].get('planned_next'):
        raise WorkflowError('forbidden', 'Tool is not authorized by latest plan')
    if tool in case['state']['steps']:
        raise WorkflowError('conflict', 'Duplicate tool execution prevented')
