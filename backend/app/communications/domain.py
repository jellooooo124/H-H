"""Pure domain rules for synthetic, in-app communication.

No diagnosis, medication, hydration instruction, or automated patient messaging.
"""
from enum import Enum

class Template(str, Enum):
    CHECKIN_REQUEST = 'CHECKIN_REQUEST'
    DEVICE_HELP = 'DEVICE_HELP'
    FOLLOWUP_ACK = 'FOLLOWUP_ACK'

TEMPLATES = {
    Template.CHECKIN_REQUEST: 'This is a synthetic study reminder. Please record your planned check-in in the demo portal. This is not an emergency service.',
    Template.DEVICE_HELP: 'This is a synthetic study message. If your demo sensor is not working, please describe the issue in the demo portal.',
    Template.FOLLOWUP_ACK: 'This is a synthetic study message. Your demo care-team task is being reviewed. No clinical service or response is guaranteed.',
}

class Status(str, Enum):
    DRAFT = 'DRAFT'
    PUBLISHED_IN_APP = 'PUBLISHED_IN_APP'
    ACKNOWLEDGED = 'ACKNOWLEDGED'
    OVERDUE = 'OVERDUE'

class WorkflowConflict(ValueError):
    """Safe state transition violation (HTTP 409 at presentation boundary)."""

def can_publish_for_case(status: str | None) -> bool:
    """Never publish operational communication from unresolved model reviews."""
    return status is None or status == 'APPROVED_SIMULATED'
