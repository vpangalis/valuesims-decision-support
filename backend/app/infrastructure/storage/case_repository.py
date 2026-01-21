import json
from app.infrastructure.storage.blob_client import AzureBlobClient
 


class CaseRepository:

    def __init__(self, blob_client: AzureBlobClient):
        self.blob = blob_client

    def create(self, case_number: str, case_doc: dict):
        path = f"{case_number}/case.json"
        self.blob.upload_json(path, json.dumps(case_doc, indent=2))

    def load(self, case_number: str) -> dict:
        path = f"{case_number}/case.json"
        data = self.blob.download_json(path)
        return json.loads(data)
    
    def exists(self, case_number: str) -> bool:
        path = f"{case_number}/case.json"
        return self.blob.exists(path)
