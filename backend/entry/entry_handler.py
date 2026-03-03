from __future__ import annotations

import base64
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Literal

from pydantic import BaseModel

from backend.ingestion.case_ingestion import CaseEntryService, CaseIngestionService
from backend.ingestion.evidence_ingestion import EvidenceIngestionService
from backend.ingestion.knowledge_ingestion import KnowledgeIngestionService
from backend.workflow.unified_incident_graph import (
    IncidentGraphState,
    UnifiedIncidentGraph,
)


class SuggestionItem(BaseModel):
    label: str
    question: str


class SuggestionsLLMResponse(BaseModel):
    suggestions: list[SuggestionItem] = []


_logger = logging.getLogger(__name__)


class EntryEnvelope(BaseModel):
    intent: Literal["CASE_INGESTION", "AI_REASONING"]
    action: Optional[str] = None
    payload: dict[str, Any] = {}
    case_id: Optional[str] = None
    event: Optional[str] = None


class EntryResponseEnvelope(BaseModel):
    intent: str
    status: str
    data: dict[str, Any] = {}
    errors: list[str] = []


class EntryHandler:
    _STATS_TRIGGER = "show me llm performance stats"
    _LLM_LOG_PATH = Path("logs/llm_calls.jsonl")
    _MODEL_COSTS: dict[str, dict[str, float]] = {
        "intent-model": {"prompt": 0.00015, "completion": 0.0006},
        "operational-model": {"prompt": 0.0025, "completion": 0.010},
        "operational-premium": {"prompt": 0.0025, "completion": 0.010},
    }

    def __init__(
        self,
        case_entry: CaseEntryService,
        evidence_ingestion: EvidenceIngestionService,
        case_ingestion: CaseIngestionService,
        knowledge_ingestion: KnowledgeIngestionService,
        unified_graph: UnifiedIncidentGraph,
        llm_client: Any | None = None,
    ) -> None:
        self._case_entry = case_entry
        self._evidence_ingestion = evidence_ingestion
        self._case_ingestion = case_ingestion
        self._knowledge_ingestion = knowledge_ingestion
        self._unified_graph = unified_graph
        self._llm_client = llm_client

    def handle_entry(self, envelope: EntryEnvelope) -> EntryResponseEnvelope:
        intent = (envelope.intent or "").upper()
        if intent == "CASE_INGESTION":
            return self._handle_case_ingestion(envelope)
        if intent == "AI_REASONING":
            return self._handle_ai_reasoning(envelope)
        raise ValueError(f"Unsupported intent: {envelope.intent}")

    def _handle_case_ingestion(self, envelope: EntryEnvelope) -> EntryResponseEnvelope:
        _logger.debug("[DEBUG] Received action: %s", envelope.action)
        _logger.debug("[DEBUG] Received event: %s", envelope.event)
        action = self._normalize_action(envelope.action or envelope.event)
        _logger.debug("[DEBUG] Normalized action: %s", action)

        if action == "CREATE_CASE":
            _logger.debug("[DEBUG] Branch taken: CREATE_CASE")
            data = self._create_case(envelope)
        elif action == "UPDATE_CASE":
            _logger.debug("[DEBUG] Branch taken: UPDATE_CASE")
            data = self._update_case(envelope)
        elif action == "CLOSE_CASE":
            _logger.debug("[DEBUG] Branch taken: CLOSE_CASE")
            data = self._close_case(envelope)
        elif action == "UPLOAD_EVIDENCE":
            _logger.debug("[DEBUG] Branch taken: UPLOAD_EVIDENCE")
            data = self._upload_evidence(envelope)
        elif action == "UPLOAD_KNOWLEDGE":
            _logger.debug("[DEBUG] Branch taken: UPLOAD_KNOWLEDGE")
            data = self._upload_knowledge(envelope)
        else:
            _logger.debug("[DEBUG] Unsupported action after normalization: %s", action)
            raise ValueError(f"Unsupported case intent: {action}")
        return EntryResponseEnvelope(
            intent=envelope.intent,
            status="accepted",
            data=data,
        )

    def _compute_llm_stats(self) -> dict | str:
        """Read llm_calls.jsonl and compute 6 performance metrics.

        Returns a structured dict for the UI, or a str if no data is available.
        """
        if not self._LLM_LOG_PATH.exists():
            return "No LLM call data found. Ask a few questions first."

        records: list[dict] = []
        with self._LLM_LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    pass

        if not records:
            return "Log file exists but contains no records."

        # ── Per-node aggregations ────────────────────────────────────
        node_times: dict[str, list[float]] = defaultdict(list)
        node_prompt: dict[str, list[int]] = defaultdict(list)
        node_completion: dict[str, list[int]] = defaultdict(list)
        node_total: dict[str, list[int]] = defaultdict(list)
        node_calls: dict[str, int] = defaultdict(int)
        total_cost = 0.0

        for r in records:
            node = r.get("node_name", "unknown")
            node_calls[node] += 1
            rt = r.get("response_time_ms")
            if rt is not None:
                node_times[node].append(float(rt))
            pt = r.get("prompt_tokens")
            ct = r.get("completion_tokens")
            tt = r.get("total_tokens")
            if pt is not None:
                node_prompt[node].append(int(pt))
            if ct is not None:
                node_completion[node].append(int(ct))
            if tt is not None:
                node_total[node].append(int(tt))

            # cost estimate
            model = (r.get("model_name") or "").lower()
            rates = None
            for key, val in self._MODEL_COSTS.items():
                if key in model:
                    rates = val
                    break
            if rates and pt is not None and ct is not None:
                total_cost += (pt * rates["prompt"] + ct * rates["completion"]) / 1000

        hour_counts: Counter = Counter()
        for r in records:
            ts = r.get("timestamp", "")
            if ts:
                try:
                    hour_counts[ts[:13]] += 1  # "2026-03-03T14"
                except Exception:
                    pass
        time_series = [{"hour": h, "calls": c} for h, c in sorted(hour_counts.items())]

        # ── Regeneration rate ────────────────────────────────────────
        reflection_calls = sum(v for k, v in node_calls.items() if "reflection" in k)
        total_calls = len(records)
        regen_rate = (reflection_calls / total_calls * 100) if total_calls else 0

        # ── Slow calls top 5 ────────────────────────────────────────
        timed = [
            (
                r.get("response_time_ms", 0),
                r.get("node_name", "?"),
                r.get("user_question", "")[:60],
            )
            for r in records
            if r.get("response_time_ms") is not None
        ]
        timed.sort(reverse=True)
        top5 = timed[:5]

        # ── Date range ───────────────────────────────────────────────
        timestamps = [r.get("timestamp", "") for r in records if r.get("timestamp")]
        date_range = (
            f"{min(timestamps)[:10]} → {max(timestamps)[:10]}"
            if timestamps
            else "unknown"
        )

        # ── Build structured output ──────────────────────────────
        node_names = sorted(node_calls.keys())

        response_time_data = {
            node: {
                "avg": round(sum(node_times[node]) / len(node_times[node])),
                "min": round(min(node_times[node])),
                "max": round(max(node_times[node])),
            }
            for node in node_names
            if node in node_times
        }

        token_data = {
            node: {
                "prompt": (
                    round(sum(node_prompt[node]) / len(node_prompt[node]))
                    if node_prompt.get(node)
                    else 0
                ),
                "completion": (
                    round(sum(node_completion[node]) / len(node_completion[node]))
                    if node_completion.get(node)
                    else 0
                ),
                "total": (
                    round(sum(node_total[node]) / len(node_total[node]))
                    if node_total.get(node)
                    else 0
                ),
            }
            for node in node_names
            if node_prompt.get(node)
        }

        slow_calls = [
            {
                "ms": round(ms),
                "node": node,
                "question": (q + "...") if len(q) == 60 else q,
            }
            for ms, node, q in top5
        ]

        return {
            "total_calls": total_calls,
            "date_range": date_range,
            "call_volume": {node: node_calls[node] for node in node_names},
            "response_time": response_time_data,
            "token_counts": token_data,
            "cost": {
                "total": round(total_cost, 4),
                "per_call": round(total_cost / total_calls, 5) if total_calls else 0,
                "disclaimer": "Rates as of Feb 2026 — may vary by contract",
            },
            "regeneration": {
                "reflection_calls": reflection_calls,
                "total_calls": total_calls,
                "rate_pct": round(regen_rate, 1),
            },
            "slow_calls": slow_calls,
            "time_series": time_series,
        }

    def _handle_ai_reasoning(self, envelope: EntryEnvelope) -> EntryResponseEnvelope:
        _logger.debug("[DEBUG AI ENTRY] raw envelope=%r", envelope.model_dump())
        payload = envelope.payload or {}
        question = str(payload.get("question") or "").strip()
        case_id = payload.get("case_id") or envelope.case_id

        if not question:
            response = {"status": "usage", "message": "Provide a non-empty question."}
            return EntryResponseEnvelope(
                intent=envelope.intent,
                status="accepted",
                data=response,
            )

        if question.lower().strip() == self._STATS_TRIGGER:
            stats_data = self._compute_llm_stats()
            if isinstance(stats_data, dict):
                return EntryResponseEnvelope(
                    intent=envelope.intent,
                    status="accepted",
                    data={
                        "status": "stats",
                        "stats_data": stats_data,
                        "suggestions": [],
                    },
                )
            # fallback if stats_data is a string (no records)
            return EntryResponseEnvelope(
                intent=envelope.intent,
                status="accepted",
                data={
                    "status": "stats",
                    "answer": stats_data,
                    "suggestions": [],
                },
            )

        initial_state: IncidentGraphState = {
            "case_id": str(case_id) if case_id else None,
            "question": question,
        }

        try:
            graph_result = self._unified_graph.invoke(initial_state)
        except Exception as e:
            _logger.error("[ENTRY_DEBUG] exception in graph: %s", str(e), exc_info=True)
            return self._clarifying_response(envelope)

        if graph_result.get("classification_low_confidence", False):
            _logger.info(
                "[ENTRY] low-confidence classification — returning clarifying response"
            )
            return self._clarifying_response(envelope)

        if not graph_result.get("question_ready", True):
            _logger.info("[ENTRY] question not ready — returning clarifying question")
            cq = str(graph_result.get("clarifying_question") or "")
            return self._clarifying_question_response(envelope, cq)

        response = graph_result.get("final_response") or {}
        return EntryResponseEnvelope(
            intent=envelope.intent,
            status="accepted",
            data=response,
        )

    _CLARIFYING_TEXT = (
        "I'm not sure what you're looking for with that question. "
        "Here are some things I can help you with \u2014 you could ask about a specific case "
        "you have loaded, look for similar past cases, explore recurring patterns across the "
        "organisation, or check performance metrics. "
        "Try rephrasing or pick one of the suggestions below."
    )

    _CLARIFYING_SUGGESTIONS = [
        {
            "label": "Overall performance",
            "question": "How is our overall performance this year?",
            "type": "cosolve",
        },
        {
            "label": "Recurring problems",
            "question": "Which areas have the most recurring problems?",
            "type": "cosolve",
        },
        {
            "label": "Organisational attention",
            "question": "Which areas need organisational attention?",
            "type": "cosolve",
        },
        {
            "label": "I\u2019ll load a case and ask again",
            "question": "I\u2019ll load a case and ask again",
            "type": "load_case",
        },
    ]

    def _clarifying_response(self, envelope: EntryEnvelope) -> EntryResponseEnvelope:
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "classification": {
                "intent": "SIMILARITY_SEARCH",
                "scope": "GLOBAL",
                "confidence": 0.3,
            },
            "result": {
                "summary": self._CLARIFYING_TEXT,
                "supporting_cases": [],
                "suggestions": list(self._CLARIFYING_SUGGESTIONS),
            },
        }
        return EntryResponseEnvelope(
            intent=envelope.intent,
            status="accepted",
            data=data,
        )

    def _clarifying_question_response(
        self, envelope: EntryEnvelope, clarifying_question: str
    ) -> EntryResponseEnvelope:
        summary = clarifying_question if clarifying_question else self._CLARIFYING_TEXT
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "classification": {
                "intent": "SIMILARITY_SEARCH",
                "scope": "GLOBAL",
                "confidence": 0.3,
            },
            "result": {
                "summary": summary,
                "supporting_cases": [],
                "suggestions": list(self._CLARIFYING_SUGGESTIONS),
            },
        }
        return EntryResponseEnvelope(
            intent=envelope.intent,
            status="ok",
            data=data,
        )

    def _create_case(self, envelope: EntryEnvelope) -> dict[str, Any]:
        payload = envelope.payload or {}
        _logger.debug(
            "[DEBUG AI] payload keys: %s, question: %r",
            list(payload.keys()),
            payload.get("question"),
        )

        case_id = payload.get("case_id") or envelope.case_id
        opened_at = payload.get("opened_at")
        if not case_id:
            raise ValueError("case_id is required")
        doc = self._case_entry.create_case(case_id, opened_at)
        _logger.info("[CREATE_CASE] blob save complete for %s, starting index", case_id)
        try:
            self._case_ingestion.index_open_case(str(case_id))
            _logger.info("[CREATE_CASE] index complete for %s", case_id)
        except Exception as exc:
            _logger.exception("[CREATE_CASE] index FAILED for %s: %s", case_id, exc)
        return {"status": "created", "case_id": doc.get("case_id")}

    def _update_case(self, envelope: EntryEnvelope) -> dict[str, Any]:
        payload = envelope.payload or {}
        # Bulk-import mode: UI sends a 'cases' array with no top-level case_id.
        cases = payload.get("cases")
        if isinstance(cases, list) and cases:
            return self._import_bulk_cases(cases)

        case_id = envelope.case_id or payload.get("case_id")
        if not case_id:
            raise ValueError("case_id is required")
        result = self._case_entry.patch_case(case_id, payload)
        _logger.info("[UPDATE_CASE] patch complete for %s, starting re-index", case_id)
        try:
            self._case_ingestion.index_open_case(str(case_id))
            _logger.info("[UPDATE_CASE] re-index complete for %s", case_id)
        except Exception as exc:
            _logger.exception("[UPDATE_CASE] re-index FAILED for %s: %s", case_id, exc)
        return {"status": "updated", **result}

    def _import_bulk_cases(self, cases: list[dict[str, Any]]) -> dict[str, Any]:
        """Import a batch of closed case documents sent as a JSON array."""
        imported: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for item in cases:
            case_id = str(item.get("case_id") or "").strip()
            case_doc = item.get("case_doc") or {}
            if not case_id:
                failed.append({"case_id": None, "error": "missing case_id in item"})
                continue
            try:
                if not isinstance(case_doc, dict):
                    case_doc = {}
                case_doc.setdefault("case_id", case_id)
                self._case_entry.save_case_document(case_id, case_doc)
                self._case_ingestion.ingest_closed_case(case_id)
                imported.append({"case_id": case_id, "status": "imported"})
            except Exception as exc:
                _logger.exception("[BULK_IMPORT] failed for %s: %s", case_id, exc)
                failed.append({"case_id": case_id, "error": str(exc)})
        return {
            "status": "bulk_imported",
            "imported": len(imported),
            "failed": len(failed),
            "results": imported + failed,
        }

    def reindex_case(self, case_id: str) -> dict[str, Any]:
        """Force-index a single case by case_id (used by diagnostic endpoint)."""
        _logger.info("[REINDEX] force-reindex requested for %s", case_id)
        try:
            self._case_ingestion.index_open_case(case_id)
            return {"status": "indexed", "case_id": case_id}
        except Exception as exc:
            _logger.exception("[REINDEX] failed for %s: %s", case_id, exc)
            return {"status": "error", "case_id": case_id, "error": str(exc)}

    def _close_case(self, envelope: EntryEnvelope) -> dict[str, Any]:
        case_id = envelope.case_id or (envelope.payload or {}).get("case_id")
        if not case_id:
            raise ValueError("case_id is required")
        payload = envelope.payload or {}
        if isinstance(payload, dict) and "case_id" not in payload:
            payload = {**payload, "case_id": case_id}
        existing = self._case_entry.get_case(case_id)
        merged = self._case_entry.merge_case_document(existing, payload)
        self._case_entry.save_case_document(case_id, merged)
        self._case_ingestion.ingest_closed_case(case_id)
        return {"status": "closed", "case_id": case_id}

    def _upload_evidence(self, envelope: EntryEnvelope) -> dict[str, Any]:
        case_id = envelope.case_id or (envelope.payload or {}).get("case_id")
        if not case_id:
            raise ValueError("case_id is required")
        files = (envelope.payload or {}).get("files", [])
        uploaded = []
        for item in files:
            filename = item.get("filename") or "unknown"
            content_type = item.get("content_type") or "application/octet-stream"
            data_base64 = item.get("data_base64") or ""
            raw = self._decode_base64(data_base64)
            self._evidence_ingestion.upload_evidence(
                case_id, filename, raw, content_type
            )
            uploaded.append(
                {
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(raw),
                }
            )
        return {"case_id": case_id, "uploaded": uploaded}

    def _upload_knowledge(self, envelope: EntryEnvelope) -> dict[str, Any]:
        documents = (envelope.payload or {}).get("documents", [])
        uploaded = []
        for item in documents:
            filename = item.get("filename") or "unknown"
            content_type = item.get("content_type") or "application/octet-stream"
            data_base64 = item.get("data_base64") or ""
            raw = self._decode_base64(data_base64)
            try:
                self._knowledge_ingestion.upload_document(filename, raw, content_type)
            except Exception as e:
                _logger.error(
                    "[KNOWLEDGE] upload failed for %r: %s: %s",
                    filename,
                    type(e).__name__,
                    e,
                )
                raise
            uploaded.append(
                {
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(raw),
                }
            )
        return {"status": "uploaded", "documents": uploaded}

    def upload_knowledge(self, filename: str, data: bytes, content_type: str) -> None:
        try:
            self._knowledge_ingestion.upload_document(filename, data, content_type)
        except Exception as e:
            _logger.error(
                "[KNOWLEDGE] upload failed for %r: %s: %s",
                filename,
                type(e).__name__,
                e,
            )
            raise

    def reindex_case(self, case_id: str) -> dict[str, str]:
        """Force-index (or re-index) a case regardless of its status.
        Useful for backfilling cases created before index-on-create was added.
        """
        try:
            self._case_ingestion.index_open_case(case_id)
            return {"status": "indexed", "case_id": case_id}
        except RuntimeError as exc:
            _logger.error(
                "[REINDEX] Azure Search rejected document for %s: %s", case_id, exc
            )
            return {
                "status": "rejected_by_azure",
                "case_id": case_id,
                "error": str(exc),
            }
        except Exception as exc:
            _logger.exception("[REINDEX] unexpected error for %s: %s", case_id, exc)
            return {
                "status": "error",
                "case_id": case_id,
                "error": str(exc),
                "type": type(exc).__name__,
            }

    def _normalize_action(self, action: Optional[str]) -> str:
        value = (action or "").strip().upper()
        value = value.replace("-", "_").replace(" ", "_")
        return value

    def _decode_base64(self, data_base64: str) -> bytes:
        if not data_base64:
            return b""
        return base64.b64decode(data_base64)

    # ------------------------------------------------------------------ #
    # Suggestions — lightweight single-call endpoint                       #
    # ------------------------------------------------------------------ #

    _SUGGESTIONS_SYSTEM = (
        "You are generating suggested questions for a problem-solving "
        "assistant UI. Given a case summary, generate exactly 6 suggested "
        "questions a user might want to ask.\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        '  "suggestions": [\n'
        '    { "label": "short 2-4 word label", "question": "full question text" },\n'
        "    ...6 items...\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- 2 suggestions must be operational (current state / gaps / next steps)\n"
        "- 2 suggestions must be similarity-focused (find similar cases)\n"
        "- 1 suggestion must be strategic (systemic risks or patterns)\n"
        "- 1 suggestion must be KPI-focused (trends or metrics)\n"
        "- Every question must reference the actual problem, component, "
        "or system from the case — no generic questions\n"
        "- Labels must be short: 'Root cause gaps', 'Similar faults', "
        "'Fleet trends', etc.\n"
        "- Questions must be natural language, as a user would type them\n"
        "- NEVER use D-step codes (D1, D2, D3, D4, D5, D6, D7, D8) in labels "
        "or question text — use plain language only. "
        "Instead of 'Next steps for D8' use 'What should we do to close this case?'; "
        "instead of 'D4 root cause' use 'What is the root cause?'; "
        "instead of 'D3 containment' use 'What containment actions are in place?'"
    )

    _FALLBACK_SUGGESTIONS: list[dict[str, str]] = [
        {
            "label": "Current gaps",
            "question": "What are the current gaps in our investigation?",
        },
        {"label": "Next steps", "question": "What should the team focus on next?"},
        {
            "label": "Similar faults",
            "question": "Are there similar cases in the closed case knowledge base?",
        },
        {
            "label": "Past incidents",
            "question": "Have we seen this type of failure before?",
        },
        {
            "label": "Systemic risks",
            "question": "Are there systemic risks highlighted by recurring incidents?",
        },
        {
            "label": "KPI trends",
            "question": "How are we trending on key reliability metrics?",
        },
    ]

    _D_STATE_FRIENDLY: dict[str, str] = {
        "D1_2": "Problem Definition",
        "D3": "Containment Actions",
        "D4": "Root Cause Analysis",
        "D5": "Permanent Corrective Actions",
        "D6": "Implementation & Validation",
        "D7": "Prevention",
        "D8": "Closure & Learnings",
    }

    # Regex that matches any D-step token that may slip through from the LLM.
    _DSTEP_RE = re.compile(r"\bD[1-8]\b", re.IGNORECASE)

    def generate_suggestions(
        self, case_id: str, case_context: dict[str, Any]
    ) -> list[dict[str, str]]:
        """Generate 6 AI-suggested questions for the given case context."""
        if self._llm_client is None:
            return list(self._FALLBACK_SUGGESTIONS)

        try:
            problem_description = self._extract_problem_description(case_context)
            raw_d_state = self._extract_current_d_state(case_context) or "D1_2"
            # Use plain-language step name so the LLM never sees D-step codes
            current_step_label = self._D_STATE_FRIENDLY.get(
                raw_d_state, "Problem Definition"
            )
            status = str(case_context.get("case_status") or "open")

            user_prompt = (
                f"Case ID: {case_id}\n"
                f"Problem: {problem_description}\n"
                f"Current investigation step: {current_step_label}\n"
                f"Status: {status}"
            )

            result: SuggestionsLLMResponse = self._llm_client.complete_json(
                system_prompt=self._SUGGESTIONS_SYSTEM,
                user_prompt=user_prompt,
                response_model=SuggestionsLLMResponse,
                temperature=0.4,
            )
            suggestions = [
                {
                    "label": self._DSTEP_RE.sub("", s.label).strip(" -:"),
                    "question": self._DSTEP_RE.sub("", s.question).strip(),
                }
                for s in result.suggestions
            ]
            if len(suggestions) == 0:
                return list(self._FALLBACK_SUGGESTIONS)
            return suggestions
        except Exception as exc:
            _logger.warning(
                "[SUGGESTIONS] LLM call failed, returning fallback: %s", exc
            )
            return list(self._FALLBACK_SUGGESTIONS)

    def _extract_problem_description(self, case_context: dict[str, Any]) -> str:
        # Try d_states.D1_2 (native format)
        d_states = case_context.get("d_states")
        if isinstance(d_states, dict):
            block = d_states.get("D1_2")
            if isinstance(block, dict):
                data = block.get("data") or {}
                desc = (
                    data.get("problem_description")
                    or data.get("description")
                    or block.get("problem_description")
                )
                if desc:
                    return str(desc)[:500]
        # Try phases.D1_D2 (legacy format)
        phases = case_context.get("phases")
        if isinstance(phases, dict):
            block = phases.get("D1_D2") or phases.get("D1_2")
            if isinstance(block, dict):
                data = block.get("data") or {}
                desc = (
                    data.get("problem_description")
                    or data.get("description")
                    or block.get("problem_description")
                )
                if desc:
                    return str(desc)[:500]
        # Fallback: top-level field
        return str(case_context.get("problem_description") or "(no description)")[:500]

    def _extract_current_d_state(self, case_context: dict[str, Any]) -> str | None:
        reasoning_state = case_context.get("reasoning_state")
        if not isinstance(reasoning_state, dict):
            reasoning_state = case_context.get("d_states")
        if not isinstance(reasoning_state, dict):
            phases = case_context.get("phases")
            if isinstance(phases, dict) and phases:
                reasoning_state = {
                    ("D1_2" if k == "D1_D2" else k): v for k, v in phases.items()
                }
        if not isinstance(reasoning_state, dict):
            return None
        progression = ["D8", "D7", "D6", "D5", "D4", "D3", "D1_2"]
        for key in progression:
            block = reasoning_state.get(key)
            if not isinstance(block, dict):
                continue
            header = block.get("header")
            if isinstance(header, dict) and header.get("completed"):
                return key
            status = str(block.get("status") or "").lower()
            has_data = isinstance(block.get("data"), dict) and bool(block.get("data"))
            if status in {"in_progress", "completed"} or has_data:
                return key
        return "D1_2"


__all__ = ["EntryEnvelope", "EntryHandler", "EntryResponseEnvelope"]
