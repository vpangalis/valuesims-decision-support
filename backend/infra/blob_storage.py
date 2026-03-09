from __future__ import annotations

from azure.storage.blob import BlobServiceClient
from azure.storage.blob import ContentSettings
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
import json


class BlobStorageClient:

    def __init__(self, connection_string: str, container: str):
        if not connection_string:
            raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING not configured")
        self.service = BlobServiceClient.from_connection_string(connection_string)
        self.container = self.service.get_container_client(container)

    def upload_json(self, path: str, data: str, overwrite: bool = False):
        self.container.upload_blob(path, data, overwrite=overwrite)

    def download_json(self, path: str) -> str:
        blob = self.container.get_blob_client(path)
        data: bytes = blob.download_blob().readall()
        return data.decode("utf-8")

    def exists(self, path: str) -> bool:
        blob = self.container.get_blob_client(path)
        return blob.exists()

    def upload_file(
        self, path: str, data: bytes, content_type: str, overwrite: bool = False
    ):
        print(
            f"[BLOB] Uploading to container={self.container.container_name}, "
            f"path={path}, overwrite={overwrite}"
        )

        if not overwrite and self.exists(path):
            raise RuntimeError(f"Blob already exists and overwrite is False: {path}")

        try:
            self.container.upload_blob(
                name=path,
                data=data,
                overwrite=overwrite,
                content_settings=ContentSettings(content_type=content_type),
            )
        except ResourceExistsError as exc:
            raise RuntimeError(
                f"Blob already exists and overwrite is False: {path}"
            ) from exc

    def list_files(self, prefix: str) -> list[dict]:
        blobs = self.container.list_blobs(name_starts_with=prefix)
        result = []
        for blob in blobs:
            if blob.name.endswith("/"):
                continue
            result.append(
                {
                    "name": blob.name,
                    "size": blob.size,
                    "content_type": blob.content_settings.content_type,
                    "last_modified": blob.last_modified.isoformat(),
                }
            )
        return result

    def download_file(self, path: str) -> tuple[bytes, str]:
        try:
            blob = self.container.get_blob_client(path)
            props = blob.get_blob_properties()
            data = blob.download_blob().readall()

            content_type = (
                props.content_settings.content_type or "application/octet-stream"
            )

            return data, content_type
        except ResourceNotFoundError:
            raise FileNotFoundError(f"Blob not found: {path}")

    def delete_file(self, path: str) -> None:
        """Delete a blob. Silently succeeds if the blob does not exist."""
        try:
            self.container.delete_blob(path)
        except ResourceNotFoundError:
            pass  # already gone — treat as success

    def delete_knowledge_blob(self, filename: str) -> None:
        """Delete a file from the knowledge/ prefix by bare filename."""
        self.delete_file(f"knowledge/{filename}")


class CaseRepository:
    def __init__(self, blob_client: BlobStorageClient):
        self.blob = blob_client

    def create(self, case_number: str, case_doc: dict):
        path = f"{case_number}/case.json"
        self.blob.upload_json(path, json.dumps(case_doc, indent=2), overwrite=False)

    def load(self, case_number: str) -> dict:
        path = f"{case_number}/case.json"
        data = self.blob.download_json(path)
        return json.loads(data)

    def save(self, case_number: str, case_doc: dict):
        path = f"{case_number}/case.json"
        self.blob.upload_json(path, json.dumps(case_doc, indent=2), overwrite=True)

    def exists(self, case_number: str) -> bool:
        path = f"{case_number}/case.json"
        return self.blob.exists(path)

    def _case_prefix(self, case_id: str) -> str:
        return f"{case_id}/evidence/"

    def add_evidence(self, case_id: str, filename: str, data: bytes, content_type: str):
        filename = filename.strip()
        path = f"{self._case_prefix(case_id)}{filename}"
        self.blob.upload_file(path, data, content_type, overwrite=True)

    def list_evidence(self, case_id: str) -> list[dict]:
        prefix = self._case_prefix(case_id)
        files = self.blob.list_files(prefix)
        evidence = []
        for f in files:
            evidence.append(
                {
                    "filename": f["name"].replace(prefix, ""),
                    "size_bytes": f["size"],
                    "content_type": f["content_type"],
                    "uploaded_at": f["last_modified"],
                }
            )
        return evidence

    def get_evidence(self, case_id: str, filename: str) -> tuple[bytes, str]:
        path = f"{self._case_prefix(case_id)}{filename}"
        return self.blob.download_file(path)


class CaseReadRepository:
    """Infrastructure repository for reading case JSON documents."""

    CASES_PREFIX = ""
    CASE_JSON_SUFFIX = "/case.json"

    def __init__(self, connection_string: str, container_name: str) -> None:
        self._blob_client = BlobStorageClient(connection_string, container_name)

    def list_case_paths(self) -> list[str]:
        files = self._blob_client.list_files(self.CASES_PREFIX)
        return [f["name"] for f in files if f["name"].endswith(self.CASE_JSON_SUFFIX)]

    def load_case(self, path: str) -> dict:
        raw = self._blob_client.download_json(path)
        return json.loads(raw)


__all__ = ["BlobStorageClient", "CaseRepository", "CaseReadRepository"]
