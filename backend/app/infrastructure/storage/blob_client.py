from azure.storage.blob import BlobServiceClient
from azure.storage.blob import ContentSettings
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError


class AzureBlobClient:

    def __init__(self, connection_string: str, container: str):
        self.service = BlobServiceClient.from_connection_string(connection_string)
        self.container = self.service.get_container_client(container)

    def upload_json(self, path: str, data: str, overwrite: bool = False):
        self.container.upload_blob(path, data, overwrite=overwrite)

    def download_json(self, path: str) -> str:
        blob = self.container.get_blob_client(path)
        return blob.download_blob().readall()
    
    def exists(self, path: str) -> bool:
        blob = self.container.get_blob_client(path)
        return blob.exists()
    
    def upload_file(self, path: str, data: bytes, content_type: str):
        try:
            self.container.upload_blob(
                name=path,
                data=data,
                overwrite=False,
                content_settings=ContentSettings(content_type=content_type)
            )
        except ResourceExistsError:
            raise FileExistsError(f"Blob already exists: {path}")

    def list_files(self, prefix: str) -> list[dict]:
        blobs = self.container.list_blobs(name_starts_with=prefix)
        result = []
        for blob in blobs:
            if blob.name.endswith("/"):
                continue
            result.append({
                "name": blob.name,
                "size": blob.size,
                "content_type": blob.content_settings.content_type,
                "last_modified": blob.last_modified.isoformat()
            })
        return result

    def download_file(self, path: str) -> tuple[bytes, str]:
        try:
            blob = self.container.get_blob_client(path)
            props = blob.get_blob_properties()
            data = blob.download_blob().readall()
            return data, props.content_settings.content_type
        except ResourceNotFoundError:
            raise FileNotFoundError(f"Blob not found: {path}")
    

