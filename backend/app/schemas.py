from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class IncidentType(str, Enum):
    POWER_INFRASTRUCTURE_DAMAGE = "POWER_INFRASTRUCTURE_DAMAGE"
    ROAD_BLOCKAGE = "ROAD_BLOCKAGE"
    BRIDGE_DAMAGE = "BRIDGE_DAMAGE"
    FLOODING = "FLOODING"
    TELECOM_DAMAGE = "TELECOM_DAMAGE"
    BUILDING_DAMAGE = "BUILDING_DAMAGE"
    HEALTH_FACILITY_ISSUE = "HEALTH_FACILITY_ISSUE"
    PEOPLE_STRANDED = "PEOPLE_STRANDED"
    OTHER = "OTHER"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentExtraction(BaseModel):
    """The ONLY shape of AI output allowed into the operational store."""
    incident_type: IncidentType
    objects: List[str] = Field(default_factory=list, max_length=12)
    road_blocked: bool
    estimated_severity: Severity
    visible_flooding: bool
    people_at_risk: bool
    summary_en: str = Field(max_length=280)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool = True


class Intervention(BaseModel):
    type: str
    target: Optional[str] = None
    source: Optional[str] = None
    village: Optional[str] = None
    option: Optional[int] = None
    activate: Optional[bool] = None


class SimRequest(BaseModel):
    scenario: str = "expected"
    interventions: List[Intervention] = Field(default_factory=list)
    forced: dict = Field(default_factory=dict)


class OptimizeRequest(BaseModel):
    scenario: str = "expected"
    resources: dict = Field(default_factory=dict)
    interventions: List[Intervention] = Field(default_factory=list)


class AlertRequest(BaseModel):
    scenario: str = "expected"
    village_id: str
    interventions: List[Intervention] = Field(default_factory=list)


class BriefRequest(BaseModel):
    scenario: str = "expected"
    interventions: List[Intervention] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    decision: str  # approve | reject
    note: Optional[str] = None
