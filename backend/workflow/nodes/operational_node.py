from __future__ import annotations

import json
from typing import Any

from backend.config import Settings
from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.retrieval.hybrid_retriever import HybridRetriever
from backend.workflow.models import (
    OperationalPayload,
    OperationalNodeOutput,
)
from backend.workflow.nodes.node_parsing_utils import (
    NEW_PROBLEM_KEYWORDS,
    extract_suggestions,
    format_d_states,
    is_new_problem_question,
    normalize_d_states,
)


class OperationalNode:

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
  Stage names must use plain language — "Problem Definition", "Containment Actions",
  "Root Cause Analysis", "Permanent Corrective Actions", "Implementation & Validation",
  "Prevention", "Closure & Learnings". Never use "Stage 1", "Stage 2" or any numbered
  stage labels.
  For each stage mentioned, list the actual case IDs with their country/site brackets
  underneath — same citation format as ROOT CAUSE CATEGORIES in the strategy reports:
    • Stage Name
      • [Country][Site] case_id

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
- LENGTH RULE: Be concise. Target 450-550 words maximum. IMPORTANT: all five
  sections are REQUIRED regardless of word count — write one sentence per
  section if necessary; never skip a section to meet the word target.
- RESPONSE CHECKLIST — verify ALL FIVE are present before returning:
  ☑ [CURRENT STATE]  ☑ [GAPS IN PREVIOUS STATES]  ☑ [NEXT STATE PREVIEW]
  ☑ [GENERAL ADVICE] — must start with ⚠️  ☑ [WHAT TO EXPLORE NEXT]
  If any section is absent, add it before returning your response.
"""

    _CLOSED_CASE_SYSTEM_PROMPT = """\
You are a senior quality advisor reviewing a CLOSED and fully resolved incident case.
This case is closed. The investigation is complete. Do not suggest next steps,
gaps to address, or further actions — the team has already finished.

Your role is to summarise what was investigated, what the root cause was,
what actions were taken, and what the organisation learned.

If knowledge documents are provided in the user prompt under
'--- KNOWLEDGE BASE REFERENCES ---', cite them inline using EXACTLY this format:
Per [exact_filename.pdf]: [your point here].
The filename must be copied character-for-character from the knowledge block line —
including the .pdf extension. Do not shorten, paraphrase, or reformat the filename.
Place citations naturally within [ROOT CAUSE] or [LESSONS LEARNED] where directly
relevant to the failure mechanism or lessons identified. Only cite if the content
is directly relevant to this specific case. Do not fabricate citations if no
documents were provided.

Respond using EXACTLY these five sections in EXACTLY this order.

[RESOLUTION SUMMARY]
Briefly describe what the case was about, what symptom was investigated,
and how the investigation concluded. Reference the case ID and the final resolved state.

[ROOT CAUSE]
State the root cause(s) identified during the investigation. Be specific — use
actual data from the case history. If multiple root causes were found, list them clearly.

[ACTIONS TAKEN]
Describe the corrective and preventive actions that were implemented to resolve
the case. Reference specific steps from the case history where available.

[LESSONS LEARNED]
Summarise what the organisation learned from this case: what process, technical,
or organisational knowledge can be applied to future cases or fleet-wide prevention.

[WHAT TO EXPLORE NEXT]
Suggest related searches or portfolio-level questions the team could explore to build
on the knowledge from this resolved case. These must be similarity searches or
strategic/portfolio questions — never operational next steps for this case.

Questions to ask CoSolve:
🔍 Similar cases: "<a specific question about whether other cases share the same root cause,
   failure mode, or component — grounded in actual details from this resolved case>"
⚙️ Portfolio follow-up: "<a specific question about whether the corrective actions
   from this case have been applied more broadly across similar assets or locations>"
📊 Strategic view: "<a specific question about systemic patterns this case reveals
   when viewed across the wider fleet or portfolio>"
📈 KPI & trends: "<a specific question about whether recurrence metrics show the
   effectiveness of the actions taken in this case>"

RULES:
- Use exactly the five section markers above. No others.
- Do NOT suggest next steps, gaps, or further investigation. The case is closed.
- Every section after [RESOLUTION SUMMARY] must reference actual data from the case.
- Return plain text only. No JSON. No markdown.
- [WHAT TO EXPLORE NEXT] must be the last section. Nothing may appear after it.
- LENGTH RULE: Be concise. Target 250-350 words maximum across all five sections.
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
        model_name: str | None = None,
        case_status: str | None = None,
    ) -> OperationalNodeOutput:
        knowledge_docs = self._hybrid_retriever.retrieve_knowledge(
            query=question,
            top_k=4,
        )
        if knowledge_docs:
            knowledge_block = "\n".join(
                f"Per {(item.source or item.doc_id)}: {(item.content_text or '')[:800]}"
                for item in knowledge_docs
            )
        else:
            knowledge_block = "No relevant knowledge documents found for this case."

        # Route new-problem questions (no case loaded) to a dedicated prompt so the
        # LLM is not confused by the "embedded in an active case" framing.
        if is_new_problem_question(question, case_id):
            user_prompt = f"USER QUESTION: {question}"
            user_prompt = (
                user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
            )
            response_text = self._llm_client.complete_text(
                system_prompt=OperationalNode._NEW_PROBLEM_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                user_question=question,
                model_name=model_name,
            )
            if knowledge_docs:
                refs = "\n".join(
                    f"Per {(item.source or item.doc_id)}: referenced in this analysis."
                    for item in knowledge_docs
                )
                knowledge_section = "\n\n[KNOWLEDGE REFERENCES]\n" + refs
                explore_marker = "[WHAT TO EXPLORE NEXT]"
                if explore_marker in response_text:
                    idx = response_text.index(explore_marker)
                    response_text = (
                        response_text[:idx].rstrip()
                        + knowledge_section
                        + "\n\n"
                        + response_text[idx:]
                    )
                else:
                    response_text = response_text + knowledge_section
            suggestions = extract_suggestions(response_text)
            return OperationalNodeOutput(
                operational_draft=OperationalPayload(
                    current_state="No case loaded",
                    current_state_recommendations=response_text,
                    next_state_preview="",
                    supporting_cases=[],
                    referenced_evidence=[],
                    suggestions=suggestions,
                )
            )

        # Closed case path: summarise history without suggesting next steps.
        # Skip the escalation quality gate — historical summaries need no re-check.
        if case_status == "closed" and case_id:
            supporting_cases = self._hybrid_retriever.retrieve_similar_cases(
                query=question,
                current_case_id=case_id,
                country=self._extract_country(case_context),
            )
            referenced_evidence = self._hybrid_retriever.retrieve_evidence_for_case(
                case_id=case_id,
            )
            user_prompt = (
                f"CLOSED CASE: {case_id}\n"
                f"USER QUESTION: {question}\n"
                "\n--- CASE HISTORY ---\n"
                f"{format_d_states(case_context)}\n"
                "\n--- SUPPORTING CLOSED CASES ---\n"
                f"{json.dumps([item.model_dump(mode='json') for item in supporting_cases], indent=2)}\n"
                "\n--- REFERENCED EVIDENCE ---\n"
                f"{json.dumps([item.model_dump(mode='json') for item in referenced_evidence], indent=2)}"
            )
            user_prompt = (
                user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
            )
            response_text = self._llm_client.complete_text(
                system_prompt=OperationalNode._CLOSED_CASE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                user_question=question,
                model_name=model_name,
            )
            if knowledge_docs:
                refs = "\n".join(
                    f"Per {(item.source or item.doc_id)}: referenced in this analysis."
                    for item in knowledge_docs
                )
                knowledge_section = "\n\n[KNOWLEDGE REFERENCES]\n" + refs
                explore_marker = "[WHAT TO EXPLORE NEXT]"
                if explore_marker in response_text:
                    idx = response_text.index(explore_marker)
                    response_text = (
                        response_text[:idx].rstrip()
                        + knowledge_section
                        + "\n\n"
                        + response_text[idx:]
                    )
                else:
                    response_text = response_text + knowledge_section
            suggestions = extract_suggestions(response_text)
            return OperationalNodeOutput(
                operational_draft=OperationalPayload(
                    current_state="closed",
                    current_state_recommendations=response_text,
                    next_state_preview="",
                    supporting_cases=supporting_cases,
                    referenced_evidence=referenced_evidence,
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
        user_prompt = (
            user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
        )

        response_text = self._llm_client.complete_text(
            system_prompt=OperationalNode._OPERATIONAL_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            user_question=question,
            model_name=model_name,
        )
        if knowledge_docs:
            refs = "\n".join(
                f"Per {(item.source or item.doc_id)}: referenced in this analysis."
                for item in knowledge_docs
            )
            knowledge_section = "\n\n[KNOWLEDGE REFERENCES]\n" + refs
            explore_marker = "[WHAT TO EXPLORE NEXT]"
            if explore_marker in response_text:
                idx = response_text.index(explore_marker)
                response_text = (
                    response_text[:idx].rstrip()
                    + knowledge_section
                    + "\n\n"
                    + response_text[idx:]
                )
            else:
                response_text = response_text + knowledge_section

        # FIX 1: next_state_preview is suppressed as a separate field.
        # The full response_text already contains [NEXT STATE PREVIEW] inline;
        # rendering it separately caused the section to appear twice in the UI.
        suggestions = extract_suggestions(response_text)
        return OperationalNodeOutput(
            operational_draft=OperationalPayload(
                current_state=current_state,
                current_state_recommendations=response_text,
                next_state_preview="",
                supporting_cases=supporting_cases,
                referenced_evidence=referenced_evidence,
                suggestions=suggestions,
            )
        )

    def _extract_country(self, case_context: dict[str, Any]) -> str | None:
        direct_country = case_context.get("organization_country")
        if isinstance(direct_country, str) and direct_country.strip():
            return direct_country.strip()
        d_states = normalize_d_states(case_context)
        if isinstance(d_states, dict):
            d12 = d_states.get("D1_2")
            if isinstance(d12, dict):
                data = d12.get("data")
                if isinstance(data, dict):
                    country = data.get("country")
                    if isinstance(country, str) and country.strip():
                        return country.strip()
        return None

    def _build_structured_prompt(
        self,
        case_context: dict[str, Any],
        case_id: str,
        question: str,
        current_state: str,
        supporting_cases: list[Any],
        referenced_evidence: list[Any],
    ) -> str:
        formatted_d_states = format_d_states(case_context)
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
