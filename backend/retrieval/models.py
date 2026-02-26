from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CaseSummary(BaseModel):
    case_id: str
    organization_country: Optional[str]
    organization_site: Optional[str]
    opening_date: Optional[datetime]
    closure_date: Optional[datetime]
    problem_description: Optional[str]
    five_whys_text: Optional[str]
    permanent_actions_text: Optional[str]
    ai_summary: Optional[str]
    # KPI-relevant fields — populated from filterable index fields.
    status: Optional[str] = None
    current_stage: Optional[str] = None
    responsible_leader: Optional[str] = None
    department: Optional[str] = None


class KnowledgeSummary(BaseModel):
    doc_id: str
    title: Optional[str]
    source: Optional[str]
    created_at: Optional[datetime]


class EvidenceSummary(BaseModel):
    case_id: str
    filename: str
    content_type: Optional[str]
    created_at: Optional[datetime]


__all__ = ["CaseSummary", "KnowledgeSummary", "EvidenceSummary"]
