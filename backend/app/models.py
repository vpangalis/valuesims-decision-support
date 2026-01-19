from pydantic import BaseModel
from typing import Dict, Any, List, Optional


class CaseModel(BaseModel):
    case: Dict[str, Any]
    phases: Dict[str, Any]
    evidence: List[Dict[str, Any]] = []
    meta: Optional[Dict[str, Any]] = {"version": 1}
