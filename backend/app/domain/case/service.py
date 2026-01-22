from datetime import datetime
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

    def patch_case(self, case_number: str, patch: dict):
        if not self.repo.exists(case_number):
            raise FileNotFoundError("Case not found")

        case_doc = self.repo.load(case_number)

        self._validate_patch(case_doc, patch)

        updated = self._deep_merge(case_doc, patch)
        updated_meta = updated.get("meta", {})
        updated_meta["updated_at"] = self._now_iso()
        updated_meta["version"] = int(updated_meta.get("version", 0)) + 1
        updated["meta"] = updated_meta

        self.repo.save(case_number, updated)

        return {
            "meta": {
                "version": updated_meta.get("version"),
                "updated_at": updated_meta.get("updated_at")
            }
        }

    def _now_iso(self) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _validate_patch(self, existing: dict, patch: dict, path: str = ""):
        if not isinstance(patch, dict):
            raise ValueError("PATCH payload must be a JSON object")

        for key, value in patch.items():
            if key not in existing:
                if not self._is_allowed_new_key(path, key):
                    raise ValueError(f"Invalid path: {self._join_path(path, key)}")
                if value is None:
                    continue
                if isinstance(value, dict):
                    self._validate_patch({}, value, self._join_path(path, key))
                continue

            current = existing[key]

            if value is None:
                continue

            if isinstance(current, dict):
                if not isinstance(value, dict):
                    raise ValueError(f"Invalid type at {self._join_path(path, key)}")
                self._validate_patch(current, value, self._join_path(path, key))
                continue

            if isinstance(current, list):
                if not isinstance(value, list):
                    raise ValueError(f"Invalid type at {self._join_path(path, key)}")
                continue

            if isinstance(value, (dict, list)):
                raise ValueError(f"Invalid type at {self._join_path(path, key)}")

    def _join_path(self, base: str, key: str) -> str:
        return f"{base}.{key}" if base else key

    def _is_allowed_new_key(self, path: str, key: str) -> bool:
        if path.endswith(".header"):
            return True
        if ".data" in path:
            return True
        if path == "meta":
            return True
        return False

    def _deep_merge(self, target: dict, patch: dict):
        for key, value in patch.items():
            if value is None:
                target[key] = None
                continue

            if isinstance(value, dict) and isinstance(target.get(key), dict):
                target[key] = self._deep_merge(target.get(key, {}), value)
                continue

            if isinstance(value, list):
                target[key] = value
                continue

            target[key] = value

        return target
