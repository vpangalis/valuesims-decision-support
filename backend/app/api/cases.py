from fastapi import APIRouter, HTTPException
from app.config import settings
from app.infrastructure.storage.blob_client import AzureBlobClient
from app.infrastructure.storage.case_repository import CaseRepository
from app.domain.case.service import CaseService
from app.config import settings
from pydantic import BaseModel,field_validator
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
