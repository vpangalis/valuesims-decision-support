from datetime import datetime


class CaseFactory:

    @staticmethod
    def create_empty(case_number: str, opening_date: str | None = None) -> dict:
        now = datetime.utcnow().isoformat()

        return {
            "case": {
                "case_number": case_number,
                "opening_date": opening_date or now,
                "closure_date": None,
                "status": "open"
            },
            "evidence": [],
            "phases": {
                "D1_D2": {"header": {"completed": False}, "data": {}},
                "D3": {"header": {"completed": False}, "data": {}},
                "D4": {"header": {"completed": False}, "data": {}},
                "D5": {"header": {"completed": False}, "data": {}},
                "D6": {"header": {"completed": False}, "data": {}},
                "D7": {"header": {"completed": False}, "data": {}},
                "D8": {"header": {"completed": False}, "data": {}}
            },
            "ai": {
                "last_run": None,
                "summary": "",
                "identified_root_causes": [],
                "recommended_actions": []
            },
            "meta": {
                "version": 1,
                "created_at": now
            }
        }
