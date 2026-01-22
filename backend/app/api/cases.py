from fastapi import APIRouter, HTTPException
from app.config import settings
from app.infrastructure.storage.blob_client import AzureBlobClient
from app.infrastructure.storage.case_repository import CaseRepository
from app.domain.case.service import CaseService
from app.config import settings
from pydantic import BaseModel, RootModel, field_validator
from typing import Any, Dict
import re

router = APIRouter(prefix="/cases", tags=["cases"])

CASE_ID_REGEX = r"^INC-\d{8}-\d{4}$"

class CaseCreateRequest(BaseModel):
    case_number: str
    opening_date: str | None = None

    @field_validator("case_number")
    @classmethod
    def validate_case_number(cls, v):
        if not re.match(CASE_ID_REGEX, v):
            raise ValueError("Invalid Case ID format")
        return v


class CasePatchRequest(RootModel[Dict[str, Any]]):
    """Partial update payload for case.json.

    Payload must include only the subtree that changed.
    Lists replace existing lists, dicts merge recursively, scalars overwrite.
    """


blob_client = AzureBlobClient(
    settings.AZURE_STORAGE_CONNECTION_STRING,
    settings.AZURE_STORAGE_CONTAINER
)

case_service = CaseService(CaseRepository(blob_client))


@router.post("/")
def create_case(request: CaseCreateRequest):
    try:
        case = case_service.create_case(
            request.case_number,
            request.opening_date
        )
        return {
            "status": "created",
            "case_number": case["case"]["case_number"]
        }

    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal error")



@router.get("/{case_id}")
def load_case(case_id: str):
    try:
        return case_service.load_case(case_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Case not found")


@router.patch("/{case_id}")
def patch_case(case_id: str, payload: CasePatchRequest):
    """Apply a partial update to case.json using deep merge.

    - Loads existing case.json from Blob
    - Deep merges payload (lists replaced)
    - Updates meta.updated_at and increments meta.version
    - Persists updated case.json back to Blob
    """
    try:
        result = case_service.patch_case(case_id, payload.root)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Case not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal error")
