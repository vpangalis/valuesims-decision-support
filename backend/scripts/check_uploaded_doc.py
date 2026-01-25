from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from app.config import settings

client = SearchClient(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name="case_index_v3",
    credential=AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY),
)

doc_id = "INC-20260122-0001__case_index_v3"

doc = client.get_document(doc_id)
print("FOUND:", doc["doc_id"])
