from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

class Vitals(BaseModel):
    model_config = ConfigDict(extra='forbid')
    weight_kg: float | None = Field(default=None, ge=15, le=400)
    weight_prev_kg: float | None = Field(default=None, ge=15, le=400)
    glucose_mg_dl: float | None = Field(default=None, ge=10, le=800)
    heart_rate_bpm: float | None = Field(default=None, ge=20, le=250)
    spo2_pct: float | None = Field(default=None, ge=50, le=100)
    measured_at: str | None = Field(default=None, max_length=36)
    last_sensor_at: str | None = Field(default=None, max_length=36)

class Symptoms(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chest_pain: bool = False
    severe_breathlessness: bool = False
    fainting: bool = False
    confusion: bool = False
    swelling: bool = False
    notes: str = Field(default='', max_length=600)

class Intake(BaseModel):
    model_config = ConfigDict(extra='forbid')
    case_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    patient_ref: str = Field(pattern=r'^DEMO-[A-Za-z0-9_-]{3,45}$')
    is_synthetic: Literal[True]
    consent_for_demo_processing: Literal[True]
    vitals: Vitals
    symptoms: Symptoms
    meal_text: str = Field(default='', max_length=1000)
    meal_image_data_url: str | None = None

    @field_validator('meal_image_data_url')
    @classmethod
    def check_image(cls, value):
        if value is not None:
            if len(value) > 2_500_000 or not value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,')):
                raise ValueError('Image must be a JPEG/PNG data URL <= 2.5 MB; images remain encrypted until inference')
        return value

class Decision(BaseModel):
    case_id: str
    choice: Literal['approve', 'reject', 'escalate']
    comment: str = Field(min_length=8, max_length=500)
    expected_version: int = Field(ge=0)

class AgentResult(BaseModel):
    summary: str = Field(min_length=1, max_length=1200)
    observations: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal['low','medium','high']
    needs_clinician_review: bool = True
    hydration_direction: Literal['none','increase','restrict'] = 'none'
    uncertainties: list[str] = Field(default_factory=list, max_length=8)

class PlannerResponse(BaseModel):
    next_tool: Literal['nutrition','heart_failure','diabetes','guideline_search','finish']
    rationale: str = Field(default='', max_length=240)

class SynthesisResponse(BaseModel):
    clinician_summary: str = Field(min_length=1, max_length=2000)
    patient_draft: str = Field(min_length=1, max_length=800)
    cited_source_ids: list[str] = Field(default_factory=list, max_length=6)
    limitations: list[str] = Field(default_factory=list, max_length=8)

# Care Coordination 2.0 - strictly synthetic patient monitoring contracts.
class ObservationIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: str = Field(pattern=r'^OBS-[A-Za-z0-9_-]{8,56}$')
    patient_ref: str = Field(pattern=r'^DEMO-[A-Za-z0-9_-]{3,45}$')
    is_synthetic: Literal[True]
    code: Literal['weight_kg','glucose_mg_dl','heart_rate_bpm','spo2_pct']
    value: float
    unit: str = Field(max_length=16)
    taken_at: str = Field(max_length=40)

class CheckinIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: str = Field(pattern=r'^CHK-[A-Za-z0-9_-]{8,56}$')
    patient_ref: str = Field(pattern=r'^DEMO-[A-Za-z0-9_-]{3,45}$')
    is_synthetic: Literal[True]
    symptoms: Symptoms
    device_problem: bool = False
    patient_note: str = Field(default='', max_length=500)

class MonitoringPlanIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    patient_ref: str = Field(pattern=r'^DEMO-[A-Za-z0-9_-]{3,45}$')
    observation_code: Literal['weight_kg','glucose_mg_dl','heart_rate_bpm','spo2_pct']
    review_gap_hours: int = Field(ge=2,le=168)
    active: bool = True

class TaskResolveIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outcome: Literal['demo_documented','handoff_documented','unable_to_reach']
    note: str = Field(min_length=12,max_length=500)

class ReceiptIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    case_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    patient_ref: str = Field(pattern=r'^DEMO-[A-Za-z0-9_-]{3,45}$')
