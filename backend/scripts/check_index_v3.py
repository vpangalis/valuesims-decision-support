from azure.search.documents.indexes import SearchIndexClient
from azure.core.credentials import AzureKeyCredential
from app.config import settings

client = SearchIndexClient(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    credential=AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY),
)

index = client.get_index("case_index_v3")
print("✅ Index found:", index.name)
