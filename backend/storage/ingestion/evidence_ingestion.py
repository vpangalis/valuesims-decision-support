from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from functools import lru_cache

from langchain_community.vectorstores.azuresearch import AzureSearch

from backend.core.config import settings
from backend.storage.blob_storage import CaseRepository
from backend.knowledge.embeddings import get_embeddings


@lru_cache(maxsize=1)
def _get_evidence_store() -> AzureSearch:
    return AzureSearch(
        azure_search_endpoint=settings.AZURE_SEARCH_ENDPOINT,
        azure_search_key=settings.AZURE_SEARCH_ADMIN_KEY,
        index_name=settings.EVIDENCE_INDEX_NAME,
        embedding_function=get_embeddings(),
        search_type="hybrid",
    )


class EvidenceIngestionService:
    def __init__(
        self,
        repository: CaseRepository,
    ) -> None:
        self.repo = repository
        self._vector_store = _get_evidence_store()
        self._index_name = settings.EVIDENCE_INDEX_NAME
        self._logger = logging.getLogger("evidence_ingestion")

    def upload_evidence(self, case_id, filename, data, content_type):
        self._ensure_case_exists(case_id)
        self.repo.add_evidence(case_id, filename, data, content_type)
        text = self._extract_text(data, content_type, filename)
        doc_id = self._build_doc_id(case_id, filename)

        self._logger.info(f"[EVIDENCE] uploading to index: doc_id={doc_id}")

        try:
            self._vector_store.add_texts(
                texts=[text],
                metadatas=[{
                    "case_id": case_id,
                    "evidence_type": content_type,
                    "source": filename,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }],
                ids=[doc_id],
            )
        except Exception as e:
            self._logger.error(f"[EVIDENCE] index upload failed: {e}")
            raise

        self._logger.info(f"[EVIDENCE] indexed successfully: {doc_id}")

    def list_evidence(self, case_id: str) -> list[dict]:
        self._ensure_case_exists(case_id)
        return self.repo.list_evidence(case_id)

    def get_evidence(self, case_id: str, filename: str) -> tuple[bytes, str]:
        return self.repo.get_evidence(case_id, filename)

    def _ensure_case_exists(self, case_id: str) -> None:
        self.repo.load(case_id)

    def _build_doc_id(self, case_id: str, filename: str) -> str:
        digest = hashlib.sha1(f"{case_id}:{filename}".encode("utf-8")).hexdigest()
        return f"{case_id}__{digest}__{self._index_name}"

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
]
