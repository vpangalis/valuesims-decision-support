from __future__ import annotations

import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient


class EvidenceSearchClient:
    def __init__(self, endpoint: str, index_name: str, admin_key: str) -> None:
        self._logger = logging.getLogger("evidence_search_client")
        self._search_client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(admin_key),
        )

    def search_by_case_id(
        self,
        case_id: str,
        top_k: int,
    ) -> list[dict]:
        safe_case_id = case_id.replace("'", "''")
        filter_expression = f"case_id eq '{safe_case_id}'"
        self._logger.info(
            "Running evidence search by case_id",
            extra={"case_id": case_id, "top_k": top_k},
        )
        results = self._search_client.search(
            search_text="*",
            filter=filter_expression,
            top=top_k,
        )
        return [dict(r) for r in results]


__all__ = ["EvidenceSearchClient"]
