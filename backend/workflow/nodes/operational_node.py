from __future__ import annotations

import json
from typing import Any

from backend.config import Settings
from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.retrieval.hybrid_retriever import HybridRetriever
from backend.workflow.models import (
    OperationalDraftPayload,
    OperationalNodeOutput,
)


class OperationalNode:
    _D_STATE_LABELS: dict[str, str] = {
        "D1_2": "Problem Definition",
        "D3": "Containment Actions",
        "D4": "Root Cause Analysis",
        "D5": "Permanent Corrective Actions",
        "D6": "Implementation & Validation",
        "D7": "Prevention",
        "D8": "Closure & Learnings",
    }

    _NEW_PROBLEM_KEYWORDS = (
        "new problem",
        "just found",
        "just discovered",
        "where do we start",
        "where do i start",
        "what should we do first",
        "what do we do first",
        "never seen this before",
        "how do we start",
        "how do i start",
        "getting started",
        "don't know where to start",
        "not sure where to start",
        "first time",
        "brand new issue",
        "just happened",
        "just occurred",
    )

    @staticmethod
    def _is_new_problem_question(question: str, case_id: str) -> bool:
        """True when no case is loaded and the question signals a new problem."""
        if case_id:
            return False
        q = question.lower()
        if any(kw in q for kw in OperationalNode._NEW_PROBLEM_KEYWORDS):
            return True
        # Short question (≤10 words) containing a problem-domain word
        if len(q.split()) <= 10 and any(
            w in q for w in ("problem", "issue", "fault", "failure")
        ):
            return True
        return False

    _NEW_PROBLEM_SYSTEM_PROMPT = """\
You are a collaborative problem-solving advisor. A team member has just reported
a new problem and is not sure where to begin. There is no open case yet.

Your job is to guide them through the very first steps: understand what happened,
check if it has been seen before, and explain how to open a formal investigation
if needed.

Respond using EXACTLY these five sections in EXACTLY this order. No other
sections are permitted.

[CURRENT STATE]
Acknowledge that the team has just found a new problem (use the specific symptom
or equipment from their question where possible). Then ask the team to describe:
- What exactly happened or was observed?
- When and where did it occur?
- How widespread is it — one unit, multiple units, whole fleet?
- Is there an immediate safety or operational risk right now?

[SIMILAR CASES — CHECK FIRST]
Before opening a formal investigation, it is worth checking whether this problem
has been seen before. Describe the problem in a few words and ask CoSolve:
'Have we had similar incidents involving [component/symptom]?'
Past cases may already have a proven solution — use the specific symptom from
the question when you fill in [component/symptom].

[IF THIS IS A NEW PROBLEM — HOW TO START]
If no similar cases exist, the first step is to document the problem clearly
before any analysis begins. The team will need:
- A clear description of what failed or behaved unexpectedly
- The affected equipment, line, or location
- The team who will investigate
Use the Case Board on the left to open a new case and capture this information.
Once the problem is documented, come back here for guidance on next steps.

[GENERAL ADVICE]
\u26a0\ufe0f General advice on starting a new problem investigation:
The most effective investigations start with a clear, factual description of
what was observed — not what caused it. Avoid jumping to conclusions before
the problem is fully documented. The Case Board guides you through this step
by step.

[WHAT TO EXPLORE NEXT]
Questions to ask your team right now:
\u2022 What exactly did you observe — describe it in one sentence
\u2022 Is this happening on one unit only or across multiple?

Questions to ask CoSolve:
\U0001f50d Similar cases: 'Have we had similar incidents involving [describe symptom]?'
\u2699\ufe0f Once case is open: 'What should we focus on first for this problem?'
\U0001f4ca Strategic view: 'Is this type of failure recurring across our fleet?'
\U0001f4c8 KPI & trends: 'How often do we see this failure type and is it increasing?'

Replace [describe symptom] with the actual symptom mentioned in the question.

RULES:
- Use exactly the five section markers above. No others.
- Reference the specific symptom or equipment from the question where possible.
- Return plain text only. No JSON. No markdown.
- [WHAT TO EXPLORE NEXT] must be the last section. Nothing may appear after it.
"""
    _OPERATIONAL_SYSTEM_PROMPT = """\
You are a senior 8D problem-solving advisor embedded in an active incident case.
Your role is to reason like an experienced quality engineer who has just been handed
a full case file and asked a specific question by the team.

Before answering, you must reason through the case in sequence.
Your internal reasoning follows this mandatory order:

STEP 1 — READ THE CASE HISTORY
Read Problem Definition through the current active step in order. For each completed step,
extract: what was decided, what was found, and what was left unresolved or unclear.
Do not skip D-states. Gaps and weak entries are as important as strong ones.

STEP 2 — CROSS-REFERENCE CLOSED CASES
Review the supporting closed cases provided. Identify if any closed case had a similar
symptom pattern, failure mode, or root cause path. Note specifically: did those cases
reveal anything in their Root Cause through Corrective Actions that the current team has not yet considered?

STEP 3 — ANSWER THE QUESTION IN CONTEXT
Only after Steps 1 and 2, answer the user's question. Your answer must be structured
in exactly this order — do not reorder, do not skip sections:

  [CURRENT STATE]
  Direct recommendations for the active D-state. Be specific to what the team has
  entered so far. Reference actual data from the case, not generic advice.

  [GAPS IN PREVIOUS STATES]
  Identify anything in Problem Definition through the previous step that appears incomplete,
  contradictory, or worth revisiting before proceeding. Frame these as questions
  the team should ask themselves, not criticism.

  [NEXT STATE PREVIEW]
  Concrete hints for what the team should prepare, investigate, or decide as they
  move into the next D-state. Ground these in what you found in Steps 1 and 2.

  [GENERAL ADVICE]
  ⚠️ The following is general 8D methodology guidance not specific to this case:
  <general advice here>

  [WHAT TO EXPLORE NEXT]
  Based on this case and your analysis above, here are ways to go deeper:

  Questions to ask your team right now:
  • "<a specific investigative question the team should discuss internally,
     grounded in a gap or ambiguity found in the D-states above>"
  • "<a second specific investigative question about something the team
     may not have checked yet, referenced directly from the case data>"

  Questions to ask CoSolve:
  🔍 Similar cases: "<a specific question about whether other incidents had the same
     failure pattern, component, or symptom — use actual details from this case>"

  ⚙️ Operational deep-dive: "<a specific question about a gap or ambiguity you found
     in the D-states above that the team should resolve>"

  📊 Strategic view: "<a specific question about systemic risks, recurring patterns,
     or process weaknesses suggested by this case>"

  📈 KPI & trends: "<a specific question about metrics, frequency, or performance
     indicators relevant to this failure type>"

  All questions — both team and CoSolve — must reference something specific found in
  the case data. Do not generate generic questions like "what are the root causes?" —
  every suggestion must cite an actual detail from this case.

CRITICAL RULES:
- Every recommendation in [CURRENT STATE] and [GAPS] must reference something
  actually present in the case data. Do not invent details.
- If a D-state field is empty or missing, say so explicitly — do not fill it in.
- The [GENERAL ADVICE] section must always carry the warning prefix.
- The [WHAT TO EXPLORE NEXT] section must always be present with both subsections:
  "Questions to ask your team right now" (two bullet points) and
  "Questions to ask CoSolve" (four icon-prefixed questions).
- When an active case is loaded (ACTIVE CASE is present in the user prompt), you MUST
  reference the active case ID by name at least once in either [CURRENT STATE] or
  [GAPS IN PREVIOUS STATES] — for example: 'In case TRM-20250310-0001, ...' or
  'Case TRM-20250310-0001 is currently at ...'. This confirms case grounding.
- Return plain text. No JSON. No markdown headers beyond the section labels above.
- SECTION ORDER IS MANDATORY. The five sections must appear in exactly this sequence
  and no other:
  1. [CURRENT STATE]
  2. [GAPS IN PREVIOUS STATES]
  3. [NEXT STATE PREVIEW]
  4. [GENERAL ADVICE]
  5. [WHAT TO EXPLORE NEXT]
  [WHAT TO EXPLORE NEXT] must always be the final section. Nothing may appear after it.
- LENGTH RULE: Be concise. Target 300-400 words maximum. IMPORTANT: all five
  sections are REQUIRED regardless of word count — write one sentence per
  section if necessary; never skip a section to meet the word target.
- RESPONSE CHECKLIST (active case mode) — before finishing, verify ALL FIVE are present:
  ☑ [CURRENT STATE]
  ☑ [GAPS IN PREVIOUS STATES] — REQUIRED even when gaps are minimal
  ☑ [NEXT STATE PREVIEW]
  ☑ [GENERAL ADVICE] — MUST start with the ⚠️ warning prefix
  ☑ [WHAT TO EXPLORE NEXT] — MUST contain both subsections
  If any section is absent, add it before returning your response.
- NEW PROBLEM DETECTION: If no case context is available and the question indicates a
  new problem has just been discovered (keywords: 'new problem', 'just found',
  'just discovered', 'where do we start', 'where do i start',
  'what should we do first', 'what do we do first',
  'never seen this before', 'how do we start', 'how do i start',
  'getting started', "don't know where to start", 'not sure where to start',
  'first time', 'brand new issue', 'just happened', 'just occurred'),
  OR if the question is 10 words or fewer AND no case context is loaded AND
  it contains any of: 'problem', 'issue', 'fault', 'failure',
  then respond with this specific structure instead of the standard five sections.

  When NEW PROBLEM DETECTION is triggered, you MUST use exactly these section
  markers and no others:
  [CURRENT STATE]
  [SIMILAR CASES — CHECK FIRST]
  [IF THIS IS A NEW PROBLEM — HOW TO START]
  [GENERAL ADVICE]
  [WHAT TO EXPLORE NEXT]

  Do NOT use [GAPS TO ADDRESS], [NEXT STEPS PREVIEW], [GAPS IN PREVIOUS STATES]
  or any other section markers. These are reserved for active case analysis only.

  [CURRENT STATE]
  Acknowledge the new problem briefly. Ask the team to describe:
  - What exactly happened or was observed?
  - When and where did it occur?
  - How widespread is it — one unit, multiple units, whole fleet?
  - Is there an immediate safety or operational risk right now?

  [SIMILAR CASES — CHECK FIRST]
  Before opening a formal investigation, it is worth checking whether this problem has
  been seen before. Describe the problem in a few words and ask CoSolve:
  'Have we had similar incidents involving [component/symptom]?'
  Past cases may already have a proven solution.

  [IF THIS IS A NEW PROBLEM — HOW TO START]
  If no similar cases exist, the first step is to document the problem clearly before
  any analysis begins. You will need:
  - A clear description of what failed or behaved unexpectedly
  - The affected equipment, line, or location
  - The team who will investigate
  Use the Case Board on the left to open a new case and capture this information.
  Once the problem is documented, come back here for guidance on next steps.

  [GENERAL ADVICE]
  ⚠️ General advice on starting a new problem investigation:
  The most effective investigations start with a clear, factual description of what
  was observed — not what caused it. Avoid jumping to conclusions before the problem
  is fully documented. The Case Board guides you through this step by step.

  [WHAT TO EXPLORE NEXT]
  Questions to ask your team right now:
  • What exactly did you observe — describe it in one sentence
  • Is this happening on one unit only or across multiple?

  Questions to ask CoSolve:
  🔍 Similar cases: 'Have we had similar incidents involving [describe symptom]?'
  ⚙️ Once case is open: 'What should we focus on first for this problem?'
  📊 Strategic view: 'Is this type of failure recurring across our fleet?'
  📈 KPI & trends: 'How often do we see this failure type and is it increasing?'

  Replace [describe symptom] with the actual symptom mentioned in the question.
"""

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        llm_client: LoggedLanguageModelClient,
        settings: Settings,
    ) -> None:
        self._hybrid_retriever = hybrid_retriever
        self._llm_client = llm_client
        self._settings = settings

    def run(
        self,
        question: str,
        case_id: str,
        case_context: dict[str, Any],
        current_d_state: str | None,
    ) -> OperationalNodeOutput:
        return self.run_with_model_override(
            question=question,
            case_id=case_id,
            case_context=case_context,
            current_d_state=current_d_state,
            model_name=None,
        )

    def run_with_model_override(
        self,
        question: str,
        case_id: str,
        case_context: dict[str, Any],
        current_d_state: str | None,
        model_name: str | None,
    ) -> OperationalNodeOutput:
        # Route new-problem questions (no case loaded) to a dedicated prompt so the
        # LLM is not confused by the "embedded in an active case" framing.
        if OperationalNode._is_new_problem_question(question, case_id):
            response_text = self._llm_client.complete_text(
                system_prompt=OperationalNode._NEW_PROBLEM_SYSTEM_PROMPT,
                user_prompt=f"USER QUESTION: {question}",
                temperature=0.2,
                user_question=question,
                model_name=model_name,
            )
            suggestions = self._extract_suggestions(response_text)
            return OperationalNodeOutput(
                operational_draft=OperationalDraftPayload(
                    current_state="No case loaded",
                    current_state_recommendations=response_text,
                    next_state_preview="",
                    supporting_cases=[],
                    referenced_evidence=[],
                    suggestions=suggestions,
                )
            )

        current_state = current_d_state or "D1_2"
        country = self._extract_country(case_context)
        supporting_cases = self._hybrid_retriever.retrieve_similar_cases(
            query=question,
            current_case_id=case_id,
            country=country,
        )
        referenced_evidence = self._hybrid_retriever.retrieve_evidence_for_case(
            case_id=case_id,
        )

        user_prompt = self._build_structured_prompt(
            case_context=case_context,
            case_id=case_id,
            question=question,
            current_state=current_state,
            supporting_cases=supporting_cases,
            referenced_evidence=referenced_evidence,
        )

        response_text = self._llm_client.complete_text(
            system_prompt=OperationalNode._OPERATIONAL_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            user_question=question,
            model_name=model_name,
        )

        # FIX 1: next_state_preview is suppressed as a separate field.
        # The full response_text already contains [NEXT STATE PREVIEW] inline;
        # rendering it separately caused the section to appear twice in the UI.
        suggestions = self._extract_suggestions(response_text)
        return OperationalNodeOutput(
            operational_draft=OperationalDraftPayload(
                current_state=current_state,
                current_state_recommendations=response_text,
                next_state_preview="",
                supporting_cases=supporting_cases,
                referenced_evidence=referenced_evidence,
                suggestions=suggestions,
            )
        )

    @staticmethod
    def _extract_suggestions(response_text: str) -> list[dict]:
        """Extract [WHAT TO EXPLORE NEXT] items as structured suggestions."""
        suggestions: list[dict] = []
        try:
            marker = "[WHAT TO EXPLORE NEXT]"
            if marker not in response_text:
                return []
            section = response_text.split(marker, 1)[1].strip()

            label_map: dict[str, str] = {
                "\U0001f50d": "Similar cases",
                "\u2699\ufe0f": "Operational deep-dive",
                "\U0001f4ca": "Strategic view",
                "\U0001f4c8": "KPI & trends",
            }

            for line in section.split("\n"):
                line = line.strip()
                if line.startswith("\u2022") or line.startswith("-"):
                    question = line.lstrip("\u2022-").strip().strip('"')
                    if question:
                        suggestions.append(
                            {
                                "label": (
                                    question[:40] + "..."
                                    if len(question) > 40
                                    else question
                                ),
                                "question": question,
                                "type": "team",
                            }
                        )
                for emoji, label in label_map.items():
                    if line.startswith(emoji):
                        parts = line.split(":", 1)
                        if len(parts) > 1:
                            raw = parts[1].strip().strip('"')
                            suggestions.append(
                                {"label": label, "question": raw, "type": "cosolve"}
                            )
        except Exception:
            pass
        return suggestions

    @staticmethod
    def _normalize_d_states(case_context: dict[str, Any]) -> dict[str, Any] | None:
        """Return a d_states-keyed dict (D1_2, D3, …) from either format.

        Supports:
        - Native format: ``case_context["d_states"]`` with key ``D1_2``
        - Legacy/phases format: ``case_context["phases"]`` with key ``D1_D2``
        """
        d_states = case_context.get("d_states")
        if isinstance(d_states, dict) and d_states:
            return d_states
        phases = case_context.get("phases")
        if isinstance(phases, dict) and phases:
            normalized: dict[str, Any] = {}
            for k, v in phases.items():
                norm_key = "D1_2" if k == "D1_D2" else k
                normalized[norm_key] = v
            return normalized
        return None

    def _extract_country(self, case_context: dict[str, Any]) -> str | None:
        direct_country = case_context.get("organization_country")
        if isinstance(direct_country, str) and direct_country.strip():
            return direct_country.strip()
        d_states = self._normalize_d_states(case_context)
        if isinstance(d_states, dict):
            d12 = d_states.get("D1_2")
            if isinstance(d12, dict):
                data = d12.get("data")
                if isinstance(data, dict):
                    country = data.get("country")
                    if isinstance(country, str) and country.strip():
                        return country.strip()
        return None

    @staticmethod
    def _format_d_states(case_context: dict[str, Any]) -> str:
        d_states = OperationalNode._normalize_d_states(case_context)
        if not isinstance(d_states, dict) or not d_states:
            return "No case history available."
        lines: list[str] = []
        for key in ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"]:
            if key not in d_states:
                continue
            label = OperationalNode._D_STATE_LABELS.get(key, key)
            lines.append(f"{label}:")
            entry = d_states[key]
            data: dict[str, Any] = {}
            if isinstance(entry, dict):
                data = entry.get("data") or entry
            if isinstance(data, dict) and data:
                for field, value in data.items():
                    display = (
                        str(value).strip()
                        if value not in (None, "", [], {})
                        else "NOT ENTERED"
                    )
                    lines.append(f"  {field}: {display}")
            else:
                lines.append("  (no data entered)")
        return "\n".join(lines) if lines else "No case history available."

    @staticmethod
    def _extract_section(text: str, start_marker: str, end_marker: str) -> str:
        start_idx = text.find(start_marker)
        if start_idx < 0:
            return ""
        content_start = start_idx + len(start_marker)
        end_idx = text.find(end_marker, content_start)
        if end_idx < 0:
            return text[content_start:].strip()
        return text[content_start:end_idx].strip()

    def _build_structured_prompt(
        self,
        case_context: dict[str, Any],
        case_id: str,
        question: str,
        current_state: str,
        supporting_cases: list[Any],
        referenced_evidence: list[Any],
    ) -> str:
        formatted_d_states = self._format_d_states(case_context)
        formatted_supporting_cases = json.dumps(
            [item.model_dump(mode="json") for item in supporting_cases], indent=2
        )
        formatted_evidence = json.dumps(
            [item.model_dump(mode="json") for item in referenced_evidence], indent=2
        )
        return (
            f"ACTIVE CASE: {case_id}\n"
            f"ACTIVE D-STATE: {current_state}\n"
            f"USER QUESTION: {question}\n"
            "\n--- CASE HISTORY ---\n"
            f"{formatted_d_states}\n"
            "\n--- SUPPORTING CLOSED CASES ---\n"
            f"{formatted_supporting_cases}\n"
            "\n--- REFERENCED EVIDENCE ---\n"
            f"{formatted_evidence}"
        )


__all__ = ["OperationalNode"]
