from app.domain.case.factory import CaseFactory
from app.infrastructure.storage.case_repository import CaseRepository



class CaseService:

    def __init__(self, repository: CaseRepository):
        self.repo = repository

    def create_case(self, case_number: str, opening_date: str | None):
        if self.repo.exists(case_number):
            raise ValueError("Case already exists")

        case_doc = CaseFactory.create_empty(case_number, opening_date)
        self.repo.create(case_number, case_doc)
        return case_doc

    def load_case(self, case_number: str):
        return self.repo.load(case_number)
