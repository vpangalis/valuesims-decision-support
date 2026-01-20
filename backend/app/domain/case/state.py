class CaseState:
    """
    Canonical mutable state for agents.
    LangGraph-ready but workflow-agnostic.
    """

    def __init__(self, case_data: dict):
        self.data = case_data

    @property
    def phases(self):
        return self.data.get("phases", {})

    @property
    def ai(self):
        return self.data.get("ai", {})

    def update_ai_summary(self, summary: str):
        self.data["ai"]["summary"] = summary

    def mark_phase_completed(self, phase: str):
        self.data["phases"][phase]["header"]["completed"] = True
