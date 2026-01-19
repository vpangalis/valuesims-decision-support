import json
from fastapi import APIRouter, HTTPException
from app.blob import container_client
from app.models import CaseModel

router = APIRouter(
    prefix="/cases",
    tags=["cases"]
)


@router.post("/")
def create_case(case: CaseModel):
    case_number = case.case.get("case_number")

    if not case_number:
        raise HTTPException(
            status_code=400,
            detail="case.case_number is required"
        )

    blob_path = f"{case_number}/case.json"

    try:
        container_client.upload_blob(
            name=blob_path,
            data=json.dumps(case.dict(), indent=2),
            overwrite=False
        )
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="Case already exists"
        )

    return {
        "status": "created",
        "case_number": case_number
    }


@router.get("/{case_id}")
def load_case(case_id: str):
    blob_path = f"{case_id}/case.json"

    try:
        blob = container_client.get_blob_client(blob_path)
        data = blob.download_blob().readall()
        return json.loads(data)
    except Exception:
        raise HTTPException(
            status_code=404,
            detail="Case not found"
        )

