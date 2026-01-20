from fastapi import APIRouter, HTTPException
from app.config import settings
from infrastructure.storage.blob_client import AzureBlobClient
from infrastructure.storage.case_repository import CaseRepository
from domain.case.service import CaseService
from pydantic import BaseModel

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseCreateRequest(BaseModel):
    case_number: str
    opening_date: str | None = None


blob_client = AzureBlobClient(
    settings.AZURE_STORAGE_CONNECTION_STRING,
    settings.AZURE_STORAGE_CONTAINER
)

case_service = CaseService(CaseRepository(blob_client))


@router.post("/")
def create_case(request: CaseCreateRequest):
    try:
        case_service.create_case(request.case_number, request.opening_date)
        return {"status": "created", "case_number": request.case_number}
    except Exception:
        raise HTTPException(status_code=409, detail="Case already exists")


@router.get("/{case_id}")
def load_case(case_id: str):
    try:
        return case_service.load_case(case_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Case not found")
