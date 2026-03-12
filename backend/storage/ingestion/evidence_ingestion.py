from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient

from backend.storage.blob_storage import CaseRepository
from backend.knowledge.embeddings import generate_embedding


class EvidenceSearchIndex:
    def __init__(self, endpoint: str, index_name: str, admin_key: str) -> None:
        self._endpoint = endpoint
        self._index_name = index_name
        self._credential = AzureKeyCredential(admin_key)
        self._search_client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=self._credential,
        )
        self._index_client = SearchIndexClient(
            endpoint=endpoint,
            credential=self._credential,
        )

    @property
    def index_name(self) -> str:
        return self._index_name

    def get_doc_id_suffix(self) -> str:
        return f"__{self._index_name}"

    def upload_documents(self, documents: list[dict[str, Any]]) -> list:
        if not isinstance(documents, list):
            raise TypeError(
                f"upload_documents expects list[dict], got {type(documents).__name__}"
            )
        return self._search_client.upload_documents(documents=documents)


class EvidenceIngestionService:
    def __init__(
        self,
        repository: CaseRepository,
        search_index: EvidenceSearchIndex,
    ) -> None:
        self.repo = repository
        self._search_index = search_index
        self._logger = logging.getLogger("evidence_ingestion")

    def upload_evidence(self, case_id, filename, data, content_type):
        self._ensure_case_exists(case_id)
        self.repo.add_evidence(case_id, filename, data, content_type)
        text = self._extract_text(data, content_type, filename)
        try:
            embedding = generate_embedding(text)
        except Exception as e:
            self._logger.warning(f"[EVIDENCE] embedding skipped (non-fatal): {e}")
            embedding = None
        doc_id = self._build_doc_id(case_id, filename)

        document: dict[str, Any] = {
            "doc_id": doc_id,
            "case_id": case_id,
            "evidence_type": content_type,
            "content_text": text,
            "source": filename,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # Only include the vector field when a valid embedding is available.
        # Passing [] (empty collection) to an Azure Search vector field causes a
        # 400/rejected-document error, so we omit the field entirely when the
        # embedding call was skipped.
        if embedding is not None:
            document["embedding"] = embedding

        self._logger.info(
            f"[EVIDENCE] uploading to index: doc_id={doc_id}"
            f" embedding_present={embedding is not None}"
        )

        try:
            results = self._search_index.upload_documents([document])
        except Exception as e:
            self._logger.exception(
                "Evidence index upload exception",
                extra={
                    "case_id": case_id,
                    "filename": filename,
                    "error_type": type(e).__name__,
                    "error_str": str(e),
                    "error_repr": repr(e),
                },
            )
            raise

        for r in results or []:
            if not r.succeeded:
                self._logger.error(
                    f"[EVIDENCE] index rejected document {r.key}: {r.error_message}"
                )
                raise RuntimeError(
                    f"Evidence indexing failed for case_id={case_id}, "
                    f"filename={filename}: {r.error_message}"
                )
            else:
                self._logger.info(f"[EVIDENCE] indexed successfully: {r.key}")

    def list_evidence(self, case_id: str) -> list[dict]:
        self._ensure_case_exists(case_id)
        return self.repo.list_evidence(case_id)

    def get_evidence(self, case_id: str, filename: str) -> tuple[bytes, str]:
        return self.repo.get_evidence(case_id, filename)

    def _ensure_case_exists(self, case_id: str) -> None:
        self.repo.load(case_id)

    def _build_doc_id(self, case_id: str, filename: str) -> str:
        digest = hashlib.sha1(f"{case_id}:{filename}".encode("utf-8")).hexdigest()
        return f"{case_id}__{digest}{self._search_index.get_doc_id_suffix()}"

    def _extract_text(self, data: bytes, content_type: str, filename: str = "") -> str:
        if not data:
            return ""

        fname = (filename or "").lower()
        self._logger.info(f"[EVIDENCE] extracting text from {filename}")

        content_text: str

        if fname.endswith(".docx"):
            try:
                import io
                from docx import Document  # python-docx

                doc = Document(io.BytesIO(data))
                content_text = "\n".join(
                    p.text for p in doc.paragraphs if p.text.strip()
                )
            except Exception as e:
                self._logger.warning(
                    f"[EVIDENCE] {filename} extraction failed"
                    f" ({type(e).__name__}: {e}), falling back to raw decode"
                )
                content_text = data.decode("utf-8", errors="ignore")

        elif fname.endswith(".pdf"):
            try:
                import io
                import pypdf

                reader = pypdf.PdfReader(io.BytesIO(data))
                content_text = "\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
            except Exception as e:
                self._logger.warning(
                    f"[EVIDENCE] {filename} extraction failed"
                    f" ({type(e).__name__}: {e}), falling back to raw decode"
                )
                content_text = data.decode("utf-8", errors="ignore")

        else:
            # Plain text, JSON, XML, and everything else
            content_text = data.decode("utf-8", errors="ignore")

        self._logger.info(
            f"[EVIDENCE] extracted {len(content_text)} chars from {filename}"
        )
        return content_text


__all__ = [
    "EvidenceIngestionService",
    "EvidenceSearchIndex",
]
