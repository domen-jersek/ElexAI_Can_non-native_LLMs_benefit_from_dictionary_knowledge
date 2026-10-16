"""On-disk LLM response cache.

Keyed by sha256 of (model, params, full prompt). The cache is the source of
truth for published numbers: re-runs and offline analyses read it instead of
calling the API again (see docs/DECISIONS.md D-006 in the pilot brief).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class ResponseCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(*, model: str, params: dict, prompt: str) -> str:
        payload = json.dumps(
            {"model": model, "params": params, "prompt": prompt},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def put(self, key: str, record: dict) -> None:
        record = {**record, "cached_at": datetime.now(UTC).isoformat()}
        (self.root / f"{key}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
        )
