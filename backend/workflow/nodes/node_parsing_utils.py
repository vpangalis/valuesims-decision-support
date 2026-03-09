# Shared pure utilities used by multiple node classes.
# Module-level functions are permitted here because these have no single
# natural class home — they are called by two or more unrelated node classes.
# The rule everywhere else in this project: use instance methods, not @staticmethod.

from __future__ import annotations

from typing import Any

NEW_PROBLEM_KEYWORDS = (
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

_D_STATE_LABELS: dict[str, str] = {
    "D1_2": "Problem Definition",
    "D3": "Containment Actions",
    "D4": "Root Cause Analysis",
    "D5": "Permanent Corrective Actions",
    "D6": "Implementation & Validation",
    "D7": "Prevention",
    "D8": "Closure & Learnings",
}


def is_new_problem_question(question: str, case_id: str) -> bool:
    """True when no case is loaded and the question signals a new problem."""
    if case_id:
        return False
    q = question.lower()
    if any(kw in q for kw in NEW_PROBLEM_KEYWORDS):
        return True
    # Short question (≤10 words) containing a problem-domain word
    if len(q.split()) <= 10 and any(
        w in q for w in ("problem", "issue", "fault", "failure")
    ):
        return True
    return False


def extract_suggestions(response_text: str) -> list[dict]:
    """Extract [WHAT TO EXPLORE NEXT] items as structured suggestions.

    Used by OperationalNode and OperationalReflectionNode.
    The label_map here matches the OperationalNode prompt's icon set.
    """
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


def normalize_d_states(case_context: dict[str, Any]) -> dict[str, Any] | None:
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


def format_d_states(case_context: dict[str, Any]) -> str:
    """Format d_states from a case context dict into a readable string."""
    d_states = normalize_d_states(case_context)
    if not isinstance(d_states, dict) or not d_states:
        return "No case history available."
    lines: list[str] = []
    for key in ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"]:
        if key not in d_states:
            continue
        label = _D_STATE_LABELS.get(key, key)
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


def extract_similarity_suggestions(response_text: str) -> list[dict]:
    """Extract [WHAT TO EXPLORE NEXT] items as structured suggestions.

    Used by SimilarityNode and SimilarityReflectionNode.
    The label_map here matches the SimilarityNode prompt's icon set.
    """
    suggestions: list[dict] = []
    try:
        marker = "[WHAT TO EXPLORE NEXT]"
        if marker not in response_text:
            return []
        section = response_text.split(marker, 1)[1].strip()

        label_map: dict[str, str] = {
            "\u2699\ufe0f": "Operational deep-dive",
            "\U0001f4ca": "Strategic view",
            "\U0001f4c8": "KPI & trends",
            "\U0001f50d": "Dig deeper",
        }

        for line in section.split("\n"):
            line = line.strip()
            if line.startswith("\u2022") or line.startswith("-"):
                question_text = line.lstrip("\u2022-").strip().strip('"')
                if question_text:
                    suggestions.append(
                        {
                            "label": (
                                question_text[:40] + "..."
                                if len(question_text) > 40
                                else question_text
                            ),
                            "question": question_text,
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


__all__ = [
    "NEW_PROBLEM_KEYWORDS",
    "is_new_problem_question",
    "extract_suggestions",
    "extract_similarity_suggestions",
    "normalize_d_states",
    "format_d_states",
]
