from azure.search.documents.indexes import SearchIndexClient
from azure.core.credentials import AzureKeyCredential
import os
import json

client = SearchIndexClient(
    endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
    credential=AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"]),
)

index = client.get_index("case_index_v3")

print(json.dumps(
    [
        {
            "name": f.name,
            "type": str(f.type),
            "searchable": f.searchable,
            "filterable": f.filterable,
            "facetable": f.facetable,
            "sortable": f.sortable,
        }
        for f in index.fields
    ],
    indent=2
))
