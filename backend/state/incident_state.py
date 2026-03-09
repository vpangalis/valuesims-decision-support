from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class IncidentStateModel(BaseModel):
    case_id: str
    case_status: str = "open"
    opened_at: str
    closed_at: Optional[str] = None
    d_states: Dict[str, Any] = {}


class IncidentState(BaseModel):
    case_id: str
    case_status: str = "open"
    organization_country: Optional[str] = None
    reasoning_state: Dict[str, Any] = {}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "IncidentState":
        case_id = str(payload.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("case_id is required")
        case_status = str(payload.get("case_status") or "open")
        reasoning_state = payload.get("reasoning_state")
        if not isinstance(reasoning_state, dict):
            d_states = payload.get("d_states")
            reasoning_state = d_states if isinstance(d_states, dict) else {}
        organization_country = cls._extract_country(payload)
        return cls(
            case_id=case_id,
            case_status=case_status,
            organization_country=organization_country,
            reasoning_state=reasoning_state,
        )

    @classmethod
    def _extract_country(cls, payload: dict[str, Any]) -> Optional[str]:
        direct_country = payload.get("organization_country")
        if isinstance(direct_country, str) and direct_country.strip():
            return direct_country.strip()

        d_states = payload.get("d_states")
        if isinstance(d_states, dict):
            d12 = d_states.get("D1_2")
            if isinstance(d12, dict):
                data = d12.get("data")
                if isinstance(data, dict):
                    country = data.get("country")
                    if isinstance(country, str) and country.strip():
                        return country.strip()
                    organization = data.get("organization")
                    if isinstance(organization, dict):
                        org_country = organization.get("country")
                        if isinstance(org_country, str) and org_country.strip():
                            return org_country.strip()

        phases = payload.get("phases")
        if isinstance(phases, dict):
            d1d2 = phases.get("D1_D2")
            if isinstance(d1d2, dict):
                data = d1d2.get("data")
                if isinstance(data, dict):
                    organization = data.get("organization")
                    if isinstance(organization, dict):
                        org_country = organization.get("country")
                        if isinstance(org_country, str) and org_country.strip():
                            return org_country.strip()
        return None


class LegacyCaseHeader(BaseModel):
    case_number: str
    opening_date: str
    closure_date: Optional[str] = None
    status: str = "open"


class LegacyCaseMeta(BaseModel):
    version: int = 1
    created_at: str
    updated_at: Optional[str] = None


class LegacyCaseAI(BaseModel):
    last_run: Optional[str] = None
    summary: str = ""
    identified_root_causes: List[str] = []
    recommended_actions: List[str] = []


class LegacyCaseModel(BaseModel):
    case: LegacyCaseHeader
    phases: Dict[str, Any]
    evidence: List[Dict[str, Any]] = []
    ai: LegacyCaseAI | None = None
    meta: LegacyCaseMeta


class IncidentFactory:
    @classmethod
    def create_empty(cls, case_id: str, opened_at: Optional[str] = None) -> dict:
        opened_at = opened_at or datetime.utcnow().isoformat()
        return {
            "case_id": case_id,
            "case_status": "open",
            "opened_at": opened_at,
            "closed_at": None,
            "d_states": {
                "D1_2": {"status": "not_started", "closure_date": None, "data": {}},
                "D3": {"status": "not_started", "closure_date": None, "data": {}},
                "D4": {"status": "not_started", "closure_date": None, "data": {}},
                "D5": {"status": "not_started", "closure_date": None, "data": {}},
                "D6": {"status": "not_started", "closure_date": None, "data": {}},
                "D7": {"status": "not_started", "closure_date": None, "data": {}},
                "D8": {"status": "not_started", "closure_date": None, "data": {}},
            },
        }


class IncidentStateAdapter:
    @classmethod
    def to_legacy_case_doc(cls, case_doc: dict) -> dict:
        if case_doc.get("case") and case_doc.get("phases"):
            return case_doc

        if "case_id" not in case_doc:
            return case_doc

        case_id = case_doc.get("case_id") or ""
        status = case_doc.get("case_status") or "open"
        opened_at = case_doc.get("opened_at") or datetime.utcnow().isoformat()
        closed_at = case_doc.get("closed_at")
        d_states = case_doc.get("d_states", {})

        phases = {}
        mapping = {
            "D1_2": "D1_D2",
            "D3": "D3",
            "D4": "D4",
            "D5": "D5",
            "D6": "D6",
            "D7": "D7",
            "D8": "D8",
        }

        for d_key, phase_key in mapping.items():
            d_state = d_states.get(d_key, {}) if isinstance(d_states, dict) else {}
            status_value = d_state.get("status") or "not_started"
            data = d_state.get("data") or {}
            closure_date = d_state.get("closure_date")
            if closure_date and "closure_date" not in data:
                data = {**data, "closure_date": closure_date}

            if d_key == "D1_2":
                organization = data.get("organization") or {}
                if "country" in data:
                    organization = {**organization, "country": data.get("country")}
                if "site" in data:
                    organization = {**organization, "site": data.get("site")}
                if "organization_unit" in data:
                    organization = {
                        **organization,
                        "department": data.get("organization_unit"),
                    }
                elif "department" in data:
                    organization = {
                        **organization,
                        "department": data.get("department"),
                    }
                if organization:
                    data = {**data, "organization": organization}

            phases[phase_key] = {
                "header": {"completed": status_value == "completed"},
                "data": data,
            }

        legacy = {
            "case": {
                "case_number": case_id,
                "opening_date": opened_at,
                "closure_date": closed_at,
                "status": status,
            },
            "evidence": (
                case_doc.get("evidence", []) if isinstance(case_doc, dict) else []
            ),
            "phases": phases,
            "ai": {
                "last_run": None,
                "summary": "",
                "identified_root_causes": [],
                "recommended_actions": [],
            },
            "meta": {
                "version": (
                    int((case_doc.get("meta") or {}).get("version", 1))
                    if isinstance(case_doc, dict)
                    else 1
                ),
                "created_at": (
                    (case_doc.get("meta") or {}).get("created_at") or opened_at
                    if isinstance(case_doc, dict)
                    else opened_at
                ),
            },
        }
        return legacy


__all__ = [
    "IncidentState",
    "IncidentStateModel",
    "LegacyCaseModel",
    "IncidentFactory",
    "IncidentStateAdapter",
]
