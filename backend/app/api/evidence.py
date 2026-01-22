from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response
from typing import List
from app.infrastructure.storage.blob_client import AzureBlobClient
from app.infrastructure.storage.case_repository import CaseRepository
from app.config import settings

router = APIRouter(prefix="/cases", tags=["evidence"])

blob_client = AzureBlobClient(
    settings.AZURE_STORAGE_CONNECTION_STRING,
    settings.AZURE_STORAGE_CONTAINER
)
repo = CaseRepository(blob_client)


@router.post("/{case_id}/evidence", status_code=201)
async def upload_evidence(case_id: str, files: List[UploadFile] = File(...)):
    uploaded = []
    failed = []

    # Ensure case exists
    try:
        repo.load(case_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Case not found")

    for file in files:
        try:
            data = await file.read()
            repo.add_evidence(case_id, file.filename, data, file.content_type)
            uploaded.append({
                "filename": file.filename,
                "content_type": file.content_type,
                "size_bytes": len(data)
            })
        except FileExistsError as e:
            failed.append({"filename": file.filename, "reason": str(e)})
        except Exception as e:
            failed.append({"filename": file.filename, "reason": "Upload failed"})

    if failed and uploaded:
        return Response(
            content={
                "case_id": case_id,
                "uploaded": uploaded,
                "failed": failed
            }.__str__(),
            status_code=207
        )

    if failed and not uploaded:
        raise HTTPException(status_code=409, detail=failed)

    return {
        "case_id": case_id,
        "uploaded": uploaded,
        "failed": []
    }


@router.get("/{case_id}/evidence")
def list_evidence(case_id: str):
    try:
        repo.load(case_id)
        return {
            "case_id": case_id,
            "evidence": repo.list_evidence(case_id)
        }
    except Exception:
        raise HTTPException(status_code=404, detail="Case not found")


@router.get("/{case_id}/evidence/{filename}")
def download_evidence(case_id: str, filename: str):
    try:
        data, content_type = repo.get_evidence(case_id, filename)
        return Response(
            content=data,
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"'
            }
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
