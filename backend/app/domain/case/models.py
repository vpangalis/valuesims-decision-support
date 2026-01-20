from pydantic import BaseModel
from typing import Dict, Any, List, Optional


class CaseHeader(BaseModel):
    case_number: str
    opening_date: str
    closure_date: Optional[str] = None
    status: str = "open"


class CaseMeta(BaseModel):
    version: int = 1
    created_at: str
    updated_at: Optional[str] = None


class CaseAI(BaseModel):
    last_run: Optional[str] = None
    summary: str = ""
    identified_root_causes: List[str] = []
    recommended_actions: List[str] = []


class CaseModel(BaseModel):
    case: CaseHeader
    phases: Dict[str, Any]
    evidence: List[Dict[str, Any]] = []
    ai: CaseAI | None = None
    meta: CaseMeta
