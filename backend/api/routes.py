from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.entry.entry_handler import EntryEnvelope, EntryHandler
from backend.utils.text import normalize_action
from backend.infra.blob_storage import BlobStorageClient, CaseRepository
from backend.infra.case_search_client import CaseSearchClient
from backend.infra.knowledge_search_client import KnowledgeSearchClient
from backend.tools.kpi_tool import KPITool
from backend.workflow.nodes.kpi_reflection_node import KPIReflectionNode

logger = logging.getLogger(__name__)


class CaseSearchRequest(BaseModel):
    query: str
    search_type: str = "text"  # 'case_id' | 'site_or_country' | 'text'
    limit: int = 10


class SuggestionsRequest(BaseModel):
    case_id: str
    case_context: dict = {}


class ApiRoutes:
    _CASE_ID_RE = re.compile(r"^[A-Z]{3,4}-\d{8}-\d{4}$", re.IGNORECASE)

    def _sanitize(self, value: str) -> str:
        """Strip characters unsafe for OData filter string literals."""
        return value.replace("'", "").replace('"', "").strip()

    def _normalize_hit(self, hit: dict) -> dict:
        """Project raw Azure Search hit to a stable UI-facing shape."""
        return {
            "case_id": hit.get("case_id") or hit.get("id", ""),
            "problem_description": (hit.get("problem_description") or "")[:200],
            "country": hit.get("organization_country") or hit.get("country") or "",
            "site": hit.get("organization_site") or hit.get("site") or "",
            "case_status": hit.get("case_status") or hit.get("status") or "",
            "opening_date": str(hit.get("opening_date") or ""),
            "closure_date": str(hit.get("closure_date") or ""),
            "summary": hit.get("ai_summary") or "",
        }

    def __init__(
        self,
        entry_handler: EntryHandler,
        case_repository: CaseRepository,
        case_search_client: CaseSearchClient,
        knowledge_search_client: KnowledgeSearchClient,
        blob_client: BlobStorageClient,
        kpi_tool: KPITool,
        kpi_reflection_node: KPIReflectionNode,
    ) -> None:
        self._entry_handler = entry_handler
        self._case_repository = case_repository
        self._case_search_client = case_search_client
        self._knowledge_search_client = knowledge_search_client
        self._blob_client = blob_client
        self._kpi_tool = kpi_tool
        self._kpi_reflection_node = kpi_reflection_node
        self._allowed_case_actions = {
            "CREATE_CASE",
            "UPDATE_CASE",
            "CLOSE_CASE",
            "UPLOAD_EVIDENCE",
            "UPLOAD_KNOWLEDGE",
        }

    def router(self) -> APIRouter:
        router = APIRouter()
        # Existing entry routes
        router.add_api_route("/entry/case", self.handle_case_entry, methods=["POST"])
        router.add_api_route(
            "/entry/reasoning", self.handle_reasoning_entry, methods=["POST"]
        )
        router.add_api_route(
            "/entry/knowledge", self.handle_knowledge_upload, methods=["POST"]
        )
        router.add_api_route(
            "/entry/suggestions", self.handle_suggestions, methods=["POST"]
        )
        if os.getenv("COSOLVE_ENV", "production") == "development":
            router.add_api_route(
                "/entry/reasoning/debug", self.debug_reasoning, methods=["POST"]
            )
        # Case read/search routes
        router.add_api_route("/cases/kpi", self.get_kpi, methods=["GET"])
        router.add_api_route("/cases/kpi/assessment", self.get_kpi_assessment, methods=["GET"])
        router.add_api_route("/cases/search", self.search_cases, methods=["POST"])
        router.add_api_route("/cases/{case_id}", self.get_case, methods=["GET"])
        router.add_api_route(
            "/cases/{case_id}/evidence", self.list_evidence, methods=["GET"]
        )
        router.add_api_route(
            "/cases/{case_id}/evidence/{filename}",
            self.download_evidence,
            methods=["GET"],
        )
        # Knowledge library routes
        router.add_api_route(
            "/knowledge", self.list_knowledge_documents, methods=["GET"]
        )
        router.add_api_route(
            "/knowledge/file/{filename}", self.get_knowledge_file, methods=["GET"]
        )
        router.add_api_route(
            "/knowledge/{filename}", self.delete_knowledge_document, methods=["DELETE"]
        )
        # LLM stats — DEPRECATED: reads from llm_calls.jsonl which is no longer
        # written to (old custom client removed). UI still calls this endpoint.
        router.add_api_route("/llm/stats", self.get_llm_stats, methods=["GET"])
        # Admin flow visualizer
        router.add_api_route("/admin/flow", self.get_flow_graph, methods=["GET"])
        # Debug/diagnostic routes — only registered in development
        if os.getenv("COSOLVE_ENV", "production") == "development":
            router.add_api_route(
                "/cases/debug/index-count", self.debug_index_count, methods=["GET"]
            )
            router.add_api_route(
                "/knowledge/debug/search", self.debug_knowledge_search, methods=["GET"]
            )
            router.add_api_route(
                "/cases/debug/search-by-id/{case_id}",
                self.debug_search_by_id,
                methods=["GET"],
            )
            router.add_api_route(
                "/cases/debug/reindex/{case_id}",
                self.debug_reindex_case,
                methods=["GET"],
            )
        return router

    # ------------------------------------------------------------------ #
    # Suggestions                                                          #
    # ------------------------------------------------------------------ #

    def handle_suggestions(self, request: SuggestionsRequest):
        """Generate 6 AI-suggested questions for the loaded case."""
        try:
            suggestions = self._entry_handler.generate_suggestions(
                request.case_id, request.case_context
            )
            return {"suggestions": suggestions}
        except Exception as exc:
            logger.exception("[SUGGESTIONS] Unexpected error")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ------------------------------------------------------------------ #
    # KPI                                                                  #
    # ------------------------------------------------------------------ #
    def get_kpi(
        self,
        scope: str = "global",
        country: Optional[str] = None,
        case_id: Optional[str] = None,
    ):
        """Return KPI metrics only (no LLM reflection)."""
        try:
            kpi_result = self._kpi_tool.get_kpis(
                scope=scope,  # type: ignore[arg-type]
                country=country if scope == "country" else None,
                case_id=case_id if scope == "case" else None,
            )
        except Exception as exc:
            logger.exception("[KPI] Error computing KPI metrics")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return kpi_result.model_dump(exclude_none=True)

    def get_kpi_assessment(
        self,
        scope: str = "global",
        country: Optional[str] = None,
        case_id: Optional[str] = None,
    ):
        """Return AI narrative (summary + insights) for KPI scope."""
        try:
            kpi_result = self._kpi_tool.get_kpis(
                scope=scope,  # type: ignore[arg-type]
                country=country if scope == "country" else None,
                case_id=case_id if scope == "case" else None,
            )
        except Exception as exc:
            logger.exception("[KPI] Error computing KPI metrics for assessment")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if scope == "country":
            question = f"Provide a performance overview for {country}."
        elif scope == "case":
            question = f"What is the current status of case {case_id}?"
        else:
            question = "Provide a current global fleet performance overview."

        try:
            reflection = self._kpi_reflection_node.run(
                question=question,
                metrics=kpi_result,
            )
            return {
                "summary": reflection.kpi_interpretation.summary,
                "insights": reflection.kpi_interpretation.insights,
            }
        except Exception:
            logger.exception("[KPI] Reflection node failed")
            return {"summary": None, "insights": []}

    # ------------------------------------------------------------------ #
    # Case read / search                                                   #
    # ------------------------------------------------------------------ #
    def search_cases(self, request: CaseSearchRequest):
        """Search cases by case_id (exact filter), location, or free text."""
        query = request.query.strip()
        logger.info(
            "[SEARCH] Received: query=%r  search_type=%r  limit=%d",
            query,
            request.search_type,
            request.limit,
        )
        mode = (
            "case_id"
            if request.search_type == "case_id"
            else (
                "site_or_country"
                if request.search_type == "site_or_country"
                else "text"
            )
        )
        logger.info("[SEARCH_CASES] raw query=%r  mode=%r", query, mode)
        if not query:
            raise HTTPException(status_code=400, detail="query must not be empty")

        try:
            if request.search_type == "case_id":
                safe = self._sanitize(query).upper()
                filter_expr = f"case_id eq '{safe}'"
                logger.info("[SEARCH] Running exact case_id filter: %r", filter_expr)
                hits = self._case_search_client.filtered_search(
                    filter_expression=filter_expr,
                    top_k=1,
                )
            elif request.search_type == "site_or_country":
                safe = self._sanitize(query)
                safe_lower = safe.lower()
                filter_expr = (
                    f"organization_country eq '{safe}' or organization_country eq '{safe_lower}' or "
                    f"organization_site eq '{safe}' or organization_site eq '{safe_lower}' or "
                    f"organization_unit eq '{safe}' or organization_unit eq '{safe_lower}'"
                )
                logger.info("[SEARCH] Running location filter: %r", filter_expr)
                hits = self._case_search_client.filtered_search(
                    filter_expression=filter_expr,
                    top_k=request.limit,
                )
            else:
                logger.info("[SEARCH] Running text search for: %r", query)
                hits = self._case_search_client.text_search(
                    search_text=query,
                    top_k=request.limit,
                )
        except Exception as exc:
            logger.exception("[SEARCH] Uncaught exception during search")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        results = [self._normalize_hit(h) for h in hits]
        logger.info(
            "[SEARCH] Returning %d result(s): %s",
            len(results),
            [r.get("case_id") for r in results],
        )
        return {"results": results, "count": len(results)}

    def get_case(self, case_id: str):
        """Load a single case document from blob storage."""
        if not ApiRoutes._CASE_ID_RE.match(case_id):
            raise HTTPException(status_code=400, detail="Invalid case_id format")
        if not self._case_repository.exists(case_id):
            raise HTTPException(status_code=404, detail="Case not found")
        try:
            return self._case_repository.load(case_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def list_evidence(self, case_id: str):
        """List evidence files associated with a case."""
        if not ApiRoutes._CASE_ID_RE.match(case_id):
            raise HTTPException(status_code=400, detail="Invalid case_id format")
        try:
            files = self._case_repository.list_evidence(case_id)
            return {"evidence": files}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def download_evidence(self, case_id: str, filename: str):
        """Stream a single evidence file."""
        if not ApiRoutes._CASE_ID_RE.match(case_id):
            raise HTTPException(status_code=400, detail="Invalid case_id format")
        try:
            data, content_type = self._case_repository.get_evidence(case_id, filename)
            return Response(
                content=data,
                media_type=content_type or "application/octet-stream",
                headers={
                    "Content-Disposition": f'inline; filename="{filename}"',
                },
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Evidence file not found"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ------------------------------------------------------------------ #
    # Knowledge library                                                    #
    # ------------------------------------------------------------------ #

    def list_knowledge_documents(self):
        """Return deduplicated documents from the knowledge index (one per source file)."""
        try:
            # Fetch metadata only — intentionally excludes content_text (large body field).
            # Requesting content_text × top=1000 produces a multi-MB Azure response that
            # causes a read timeout and makes the browser panel hang indefinitely.
            raw = self._knowledge_search_client._search_client.search(
                search_text="*",
                top=1000,
                select=["doc_id", "title", "source", "created_at"],
            )
            # Group chunks by source filename → one entry per document
            groups: dict[str, dict] = {}
            for r in raw:
                source = r.get("source") or r.get("title") or r.get("doc_id", "")
                if source not in groups:
                    groups[source] = {
                        "doc_id": r.get("doc_id", ""),
                        "title": r.get("title", source),
                        "source": source,
                        "created_at": r.get("created_at", ""),
                        "chunk_count": 1,
                    }
                else:
                    groups[source]["chunk_count"] += 1

            # Determine which sources have no extractable text via a lightweight
            # filter query (returns only doc_ids of no-text chunks — very small).
            no_text_sources: set[str] = set()
            try:
                no_text_raw = self._knowledge_search_client._search_client.search(
                    search_text="*",
                    filter="content_text eq '[No extractable text]'",
                    top=1000,
                    select=["source"],
                )
                for r in no_text_raw:
                    src = r.get("source")
                    if src:
                        no_text_sources.add(src)
            except Exception:
                # Non-fatal: status badge falls back to "indexed" if this query fails
                logger.warning(
                    "[KNOWLEDGE] no-text filter query failed — skipping status check"
                )

            docs = [
                {
                    "doc_id": g["doc_id"],
                    "title": g["title"],
                    "source": g["source"],
                    "created_at": g["created_at"],
                    "chunk_count": g["chunk_count"],
                    "status": (
                        "no_text" if g["source"] in no_text_sources else "indexed"
                    ),
                }
                for g in groups.values()
            ]
            return {"count": len(docs), "documents": docs}
        except Exception as exc:
            logger.exception("[KNOWLEDGE] list_knowledge_documents failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def get_knowledge_file(self, filename: str):
        """Stream a raw knowledge file blob so the browser can open it inline."""
        import io

        blob_path = f"knowledge/{filename}"
        try:
            data, content_type = self._blob_client.download_file(blob_path)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Knowledge file not found"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "pdf":
            content_type = "application/pdf"
        elif ext == "docx":
            content_type = (
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            )
        elif ext == "pptx":
            content_type = (
                "application/vnd.openxmlformats-officedocument"
                ".presentationml.presentation"
            )

        return StreamingResponse(
            io.BytesIO(data),
            media_type=content_type,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    def delete_knowledge_document(self, filename: str):
        """Remove all indexed chunks for a source file and its blob."""
        # 1. Find every chunk in the index whose source == filename.
        safe = filename.replace("'", "''")
        try:
            raw = list(
                self._knowledge_search_client._search_client.search(
                    search_text="*",
                    filter=f"source eq '{safe}'",
                    top=1000,
                    select=["doc_id"],
                )
            )
        except Exception as exc:
            logger.exception("[KNOWLEDGE] delete lookup failed for source=%r", filename)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if not raw:
            raise HTTPException(status_code=404, detail="Knowledge document not found")

        doc_ids = [r["doc_id"] for r in raw if r.get("doc_id")]
        logger.info(
            "[KNOWLEDGE] deleting %d chunk(s) for source=%r", len(doc_ids), filename
        )

        # 2. Delete the blob.
        blob_path = f"knowledge/{filename}"
        try:
            self._blob_client.delete_file(blob_path)
            logger.info("[KNOWLEDGE] deleted blob %r", blob_path)
        except Exception as exc:
            # Log but don't abort — index deletion is still useful even if blob is gone.
            logger.warning("[KNOWLEDGE] blob delete failed for %r: %s", blob_path, exc)

        # 3. Batch-delete all chunks from the search index.
        try:
            self._knowledge_search_client._search_client.delete_documents(
                documents=[{"doc_id": did} for did in doc_ids]
            )
            logger.info(
                "[KNOWLEDGE] deleted %d index chunk(s) for source=%r",
                len(doc_ids),
                filename,
            )
        except Exception as exc:
            logger.exception("[KNOWLEDGE] index delete failed for source=%r", filename)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {
            "status": "deleted",
            "filename": filename,
            "chunks_deleted": len(doc_ids),
        }

    # ------------------------------------------------------------------ #
    # Temporary diagnostic endpoints — remove after debugging            #
    # ------------------------------------------------------------------ #

    def debug_knowledge_search(self, q: str = "test"):
        """Text search against the knowledge index. Temporary diagnostic."""
        try:
            raw = self._knowledge_search_client._search_client.search(
                search_text=q,
                top=3,
                select=["doc_id", "title", "source", "doc_type", "created_at"],
            )
            results = [
                {"title": r.get("title"), "score": r.get("@search.score")} for r in raw
            ]
            return {"count": len(results), "results": results}
        except Exception as exc:
            return {"error": str(exc)}

    def debug_index_count(self):
        """Return up to 5 documents from the case index. Temporary diagnostic."""
        try:
            raw = self._case_search_client._search_client.search(
                search_text="*",
                top=5,
                select=["case_id", "doc_id", "status", "opening_date"],
            )
            hits = [dict(r) for r in raw]
            return {"count": len(hits), "sample": hits}
        except Exception as exc:
            return {"error": str(exc)}

    def debug_search_by_id(self, case_id: str):
        """Test three query strategies for a given case_id. Temporary diagnostic."""
        client = self._case_search_client._search_client
        out: dict = {}

        # Test 1: OData filter on case_id field
        try:
            r1 = list(
                client.search(
                    search_text="*",
                    filter=f"case_id eq '{case_id}'",
                    select=[
                        "case_id",
                        "doc_id",
                        "status",
                        "organization_country",
                        "organization_unit",
                        "team_members",
                    ],
                )
            )
            out["filter_on_case_id"] = [dict(r) for r in r1]
        except Exception as exc:
            out["filter_on_case_id"] = {"error": str(exc)}

        # Test 2: OData filter on doc_id key field
        try:
            r2 = list(
                client.search(
                    search_text="*",
                    filter=f"doc_id eq '{case_id}'",
                    select=[
                        "case_id",
                        "doc_id",
                        "status",
                        "organization_country",
                        "organization_unit",
                        "team_members",
                    ],
                )
            )
            out["filter_on_doc_id"] = [dict(r) for r in r2]
        except Exception as exc:
            out["filter_on_doc_id"] = {"error": str(exc)}

        # Test 3: full-text search targeting team_members specifically
        try:
            r3 = list(
                client.search(
                    search_text=case_id,
                    search_fields=["team_members", "problem_description", "who"],
                    select=["case_id", "team_members", "organization_unit"],
                    top=5,
                )
            )
            out["fulltext_search"] = [dict(r) for r in r3]
        except Exception as exc:
            out["fulltext_search"] = {"error": str(exc)}

        # Test 4: search for a known team member name directly
        try:
            r4 = list(
                client.search(
                    search_text="Peter",
                    search_fields=["team_members"],
                    select=["case_id", "team_members"],
                    top=5,
                )
            )
            out["team_member_search"] = [dict(r) for r in r4]
        except Exception as exc:
            out["team_member_search"] = {"error": str(exc)}

        return out

    def debug_reindex_case(self, case_id: str):
        """Force-index a specific case without changing its data. Temporary diagnostic."""
        if not ApiRoutes._CASE_ID_RE.match(case_id):
            raise HTTPException(status_code=400, detail="Invalid case_id format")
        try:
            return self._entry_handler.reindex_case(case_id)
        except RuntimeError as e:
            return {"status": "rejected_by_azure", "case_id": case_id, "error": str(e)}
        except Exception as e:
            return {
                "status": "error",
                "case_id": case_id,
                "error": str(e),
                "type": type(e).__name__,
            }

    # ------------------------------------------------------------------ #
    # Entry handlers (unchanged)                                          #
    # ------------------------------------------------------------------ #

    def handle_case_entry(self, envelope: EntryEnvelope):
        if (envelope.intent or "").upper() != "CASE_INGESTION":
            raise HTTPException(status_code=400, detail="intent must be CASE_INGESTION")
        action = self._normalize_action(envelope.action or envelope.event)
        if action not in self._allowed_case_actions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported case intent: {action}",
            )
        return self._dispatch_entry_handler(envelope)

    def handle_reasoning_entry(self, envelope: EntryEnvelope):
        if (envelope.intent or "").upper() != "AI_REASONING":
            raise HTTPException(status_code=400, detail="intent must be AI_REASONING")
        return self._dispatch_entry_handler(envelope)

    async def debug_reasoning(self, request: Request):
        body = await request.body()
        return {"received": body.decode()}

    async def handle_knowledge_upload(self, file: UploadFile = File(...)):
        try:
            data = await file.read()
            filename = file.filename or "unknown"
            content_type = file.content_type or "application/octet-stream"
            self._entry_handler.upload_knowledge(filename, data, content_type)
            return {"status": "knowledge uploaded"}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception:
            raise HTTPException(status_code=500, detail="Internal error")

    async def get_llm_stats(self):
        log_path = Path(__file__).resolve().parents[2] / "logs" / "llm_calls.jsonl"
        if not log_path.exists():
            return {"monthly": [], "totals": {"total_tokens": 0, "total_calls": 0, "avg_tokens_per_call": 0}, "models": []}

        now = datetime.now(timezone.utc)
        # Build last 6 month boundaries
        months: list[tuple[int, int]] = []
        y, m = now.year, now.month
        for _ in range(6):
            months.append((y, m))
            m -= 1
            if m < 1:
                m = 12
                y -= 1
        months.reverse()
        valid_months = {f"{yr:04d}-{mo:02d}" for yr, mo in months}

        monthly_agg: dict[tuple[str, str], dict] = {}
        total_tokens = 0
        total_calls = 0
        models_seen: set[str] = set()

        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                model = entry.get("model_name", "unknown")
                ts = entry.get("timestamp", "")
                month_key = ts[:7]  # "YYYY-MM"
                pt = entry.get("prompt_tokens", 0) or 0
                ct = entry.get("completion_tokens", 0) or 0
                tt = entry.get("total_tokens", 0) or 0

                total_tokens += tt
                total_calls += 1
                models_seen.add(model)

                if month_key not in valid_months:
                    continue
                key = (model, month_key)
                if key not in monthly_agg:
                    monthly_agg[key] = {"model_name": model, "month": month_key, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "call_count": 0}
                bucket = monthly_agg[key]
                bucket["prompt_tokens"] += pt
                bucket["completion_tokens"] += ct
                bucket["total_tokens"] += tt
                bucket["call_count"] += 1

        monthly = sorted(monthly_agg.values(), key=lambda r: (r["month"], r["model_name"]))
        avg = round(total_tokens / total_calls) if total_calls else 0

        return {
            "monthly": monthly,
            "totals": {"total_tokens": total_tokens, "total_calls": total_calls, "avg_tokens_per_call": avg},
            "models": sorted(models_seen),
        }

    def get_flow_graph(self, days: int = 30):
        log_path = Path(__file__).parents[2] / "logs" / "node_transitions.jsonl"
        if not log_path.exists():
            return {"nodes": [], "edges": [], "total_traces": 0}

        cutoff = None
        if days > 0:
            cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)

        node_counts: dict[str, int] = {}
        edge_counts: dict[tuple[str, str], int] = {}
        trace_ids: set[str] = set()

        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cutoff:
                    ts_str = entry.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        continue
                    if ts < cutoff:
                        continue

                from_node = entry.get("from_node", "")
                to_node = entry.get("to_node", "")
                trace_id = entry.get("trace_id", "")

                if to_node:
                    node_counts[to_node] = node_counts.get(to_node, 0) + 1
                if from_node:
                    node_counts.setdefault(from_node, 0)
                if from_node and to_node:
                    key = (from_node, to_node)
                    edge_counts[key] = edge_counts.get(key, 0) + 1
                if trace_id:
                    trace_ids.add(trace_id)

        nodes = [{"id": nid, "count": cnt} for nid, cnt in sorted(node_counts.items())]
        edges = [{"from": k[0], "to": k[1], "count": v} for k, v in sorted(edge_counts.items())]
        return {"nodes": nodes, "edges": edges, "total_traces": len(trace_ids)}

    def _dispatch_entry_handler(self, envelope: EntryEnvelope):
        try:
            return self._entry_handler.handle_entry(envelope)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            import traceback

            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(exc))

    def _normalize_action(self, action: str | None) -> str:
        return normalize_action(action)


__all__ = ["ApiRoutes"]
