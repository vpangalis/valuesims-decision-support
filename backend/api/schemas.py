from pydantic import BaseModel


class CoSolveRequest(BaseModel):
    """What the UI sends. Nothing else crosses inbound."""
    question: str
    case_id: str | None = None
    session_id: str | None = None


class Source(BaseModel):
    case_id: str
    title: str
    relevance: float | None = None


class SuggestedQuestions(BaseModel):
    ask_your_team: list[str] = []
    ask_cosolve: list[str] = []


class CoSolveResponse(BaseModel):
    """What the backend returns. Nothing else crosses outbound."""
    answer: str
    intent: str
    sources: list[Source] = []
    suggested_questions: SuggestedQuestions | None = None
    warning: str | None = None
