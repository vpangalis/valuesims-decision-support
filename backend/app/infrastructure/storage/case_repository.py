from datetime import datetime
import json
from app.infrastructure.storage.blob_client import AzureBlobClient
 

class CaseRepository:
    # existing __init__,create, load stay unchanged
    
    def __init__(self, blob_client: AzureBlobClient):
        self.blob = blob_client

    def create(self, case_number: str, case_doc: dict):
        path = f"{case_number}/case.json"
        self.blob.upload_json(path, json.dumps(case_doc, indent=2))

    def load(self, case_number: str) -> dict:
        path = f"{case_number}/case.json"
        data = self.blob.download_json(path)
        return json.loads(data)

    def save(self, case_number: str, case_doc: dict):
        path = f"{case_number}/case.json"
        self.blob.upload_json(path, json.dumps(case_doc, indent=2))
    
    def exists(self, case_number: str) -> bool:
        path = f"{case_number}/case.json"
        return self.blob.exists(path)
    
    def _case_prefix(self, case_id: str) -> str:
        return f"{case_id}/evidence/"

    def add_evidence(self, case_id: str, filename: str, data: bytes, content_type: str):
        path = f"{self._case_prefix(case_id)}{filename}"
        self.blob.upload_file(path, data, content_type)

    def list_evidence(self, case_id: str) -> list[dict]:
        prefix = self._case_prefix(case_id)
        files = self.blob.list_files(prefix)
        evidence = []
        for f in files:
            evidence.append({
                "filename": f["name"].replace(prefix, ""),
                "size_bytes": f["size"],
                "content_type": f["content_type"],
                "uploaded_at": f["last_modified"]
            })
        return evidence

    def get_evidence(self, case_id: str, filename: str) -> tuple[bytes, str]:
        path = f"{self._case_prefix(case_id)}{filename}"
        return self.blob.download_file(path)