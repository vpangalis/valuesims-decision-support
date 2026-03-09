from __future__ import annotations

import re
from typing import List

from backend.retrieval.models import KnowledgeSummary


def build_refs_block(knowledge_docs: List[KnowledgeSummary]) -> str:
    """Build the [KNOWLEDGE REFERENCES] block as pipe-delimited KNOWLEDGEREF lines.

    Format: KNOWLEDGEREF|filename|section_title|page|excerpt|score_pct
    Score is expressed as an absolute percentage of 1.0 (e.g. 0.73 → 75%).
    """
    entries = []
    for item in knowledge_docs:
        filename = item.source or item.doc_id or ""
        section = item.section_title or ""
        page = str(item.page_start) if item.page_start else ""

        raw = (item.content_text or "").replace("\n", " ").replace("\r", " ").strip()
        if section and raw.startswith(section):
            raw = raw[len(section):].lstrip(" \n:-")

        sentence_match = re.search(r"[.!?]", raw)
        if sentence_match and sentence_match.end() <= 200:
            truncated = raw[:sentence_match.end()].strip()
        elif len(raw) > 150:
            truncated = raw[:150].rsplit(" ", 1)[0]
        else:
            truncated = raw

        score_pct = ""
        if hasattr(item, "score") and item.score is not None:
            pct = round(item.score * 100 / 5) * 5
            score_pct = f"{min(pct, 100)}%"

        entries.append(
            f"KNOWLEDGEREF|{filename}|{section}|{page}|{truncated}|{score_pct}"
        )
    return "\n".join(entries)
