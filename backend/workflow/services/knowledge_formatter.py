from typing import List

from backend.retrieval.models import KnowledgeSummary


class KnowledgeFormatter:

    def build_refs_block(self, knowledge_docs: List[KnowledgeSummary]) -> str:
        """
        Builds the [KNOWLEDGE REFERENCES] block content as pipe-delimited
        KNOWLEDGEREF lines, one per knowledge doc.
        Format: KNOWLEDGEREF|filename|section_title|page|excerpt|score_pct
        """
        items = knowledge_docs
        max_score = max((item.score or 0.0) for item in items) if items else 1.0
        if max_score == 0.0:
            max_score = 1.0
        entries = []
        for item in items:
            filename = item.source or item.doc_id or ""
            section = item.section_title or ""
            page = str(item.page_start) if item.page_start else ""

            # Strip leading section_title if content_text begins with it
            raw = (
                (item.content_text or "").replace("\n", " ").replace("\r", " ").strip()
            )
            if section and raw.startswith(section):
                raw = raw[len(section) :].lstrip(" \n:-")

            # Truncate to first sentence (ends at . ! or ?)
            # Fall back to 150-char word-boundary if no sentence end found
            import re

            sentence_match = re.search(r"[.!?]", raw)
            if sentence_match and sentence_match.end() <= 200:
                truncated = raw[: sentence_match.end()].strip()
            elif len(raw) > 150:
                truncated = raw[:150].rsplit(" ", 1)[0]
            else:
                truncated = raw

            score_pct = ""
            if hasattr(item, "score") and item.score is not None and max_score > 0:
                pct = round((item.score / max_score) * 100 / 5) * 5  # nearest 5%
                score_pct = f"{min(pct, 100)}%"
            entries.append(
                f"KNOWLEDGEREF|{filename}|{section}|{page}|{truncated}|{score_pct}"
            )

        return "\n".join(entries)
