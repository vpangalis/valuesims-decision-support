from azure.storage.blob import BlobServiceClient


class AzureBlobClient:

    def __init__(self, connection_string: str, container: str):
        self.service = BlobServiceClient.from_connection_string(connection_string)
        self.container = self.service.get_container_client(container)

    def upload_json(self, path: str, data: str):
        self.container.upload_blob(path, data, overwrite=False)

    def download_json(self, path: str) -> str:
        blob = self.container.get_blob_client(path)
        return blob.download_blob().readall()
    
    def exists(self, path: str) -> bool:
        blob = self.container.get_blob_client(path)
        return blob.exists()

