from __future__ import annotations

import json
from pathlib import Path
from .models import TestResult, ensure_dir


class CheckpointStore:
    def __init__(self, output_dir: str | Path):
        self.path = ensure_dir(output_dir) / "checkpoint.json"
        self.state: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {"results": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"results": {}}

    def has_result(self, test_id: str) -> bool:
        return test_id in self.state.get("results", {})

    def save_result(self, result: TestResult) -> None:
        self.state.setdefault("results", {})[result.test_case.id] = result.to_dict()
        self.path.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")

    def saved_ids(self) -> set[str]:
        return set(self.state.get("results", {}))
