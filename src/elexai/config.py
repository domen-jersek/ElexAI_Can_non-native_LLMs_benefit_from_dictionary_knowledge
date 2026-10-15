"""Configuration models for the pipeline steps that follow Phase 0.

Nothing in this repository may assume a specific LLM, embedder or retrieval
depth: every run is fully described by one YAML file under ``configs/``,
validated by these pydantic models (see ``configs/example.yaml``). Model
identifiers, embedding models and ``k`` are always supplied via configuration
so that alternative setups can be run and compared after the fact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Variant = Literal["A", "B", "C", "oracle"]


class LlmConfig(BaseModel):
    """OpenAI-compatible LLM endpoint (OpenRouter, vLLM, Ollama, ...)."""

    provider: str = "openrouter"
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/gpt-6-luna"
    api_key_env: str = "OPENROUTER_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 800
    timeout_s: int = 180
    seed: int | None = None


class EmbedderConfig(BaseModel):
    """Serving-time text embedder for variant B; swappable via config only.

    ``revision`` must be pinned to an exact Hugging Face commit hash before
    any numbers are published.
    """

    name: str = "bge-m3"
    hf_id: str = "BAAI/bge-m3"
    revision: str = "main"  # TODO: pin exact commit hash before real runs
    query_prefix: str = ""
    passage_prefix: str = ""
    batch_size: int = 16
    normalize: bool = True


class RetrievalConfig(BaseModel):
    """Deterministic (exact, non-ANN) retrieval; ``k`` comes from here."""

    k: int = 5
    sweep_k: list[int] = [1, 3, 5, 10]
    metric: Literal["cosine", "l2", "ip"] = "cosine"


class ExperimentConfig(BaseModel):
    """One experiment run: variants, questions, models and retrieval setup."""

    name: str
    description: str = ""
    variants: list[Variant] = ["A", "B", "oracle"]
    questions_path: Path = Path("data/questions/questions.jsonl")
    llm: LlmConfig = Field(default_factory=LlmConfig)
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    runs_dir: Path = Path("runs")
    seed: int = 0


def load_config(path: str | Path) -> ExperimentConfig:
    """Load and validate one experiment YAML file."""
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return ExperimentConfig.model_validate(data)
