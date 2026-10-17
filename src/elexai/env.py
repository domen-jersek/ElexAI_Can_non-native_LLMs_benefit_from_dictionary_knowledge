"""Environment loading shared by all entry points (runner, loaders, scripts)."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env(root: Path | None = None) -> None:
    """Load the repository-root .env into the process environment (no override)."""
    load_dotenv((root or REPO_ROOT) / ".env", override=False)
