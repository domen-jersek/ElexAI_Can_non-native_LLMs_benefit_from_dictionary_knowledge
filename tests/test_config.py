"""Tests for experiment config loading (nothing may be hardcoded)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from elexai.config import ExperimentConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_example_config_loads():
    cfg = load_config(REPO_ROOT / "configs" / "example.yaml")
    assert cfg.name == "example-a-b-oracle"
    assert "A" in cfg.variants and "B" in cfg.variants and "oracle" in cfg.variants
    assert cfg.llm.model  # model id comes from config, never from code
    assert cfg.embedder.hf_id
    assert cfg.retrieval.k >= 1
    assert 1 in cfg.retrieval.sweep_k


def test_defaults_are_sane():
    cfg = ExperimentConfig(name="x")
    assert cfg.llm.temperature == 0.0
    assert cfg.retrieval.sweep_k == [1, 3, 5, 10]
    assert set(cfg.variants) == {"A", "B", "C", "oracle"}


def test_unknown_variant_rejected():
    with pytest.raises(ValidationError):
        ExperimentConfig(name="x", variants=["A", "Z"])


def test_missing_name_rejected():
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate({})


def test_graph_variant_allowed():
    cfg = ExperimentConfig(name="x", variants=["D"])
    assert cfg.variants == ["D"]
    assert cfg.graph.max_candidates == 12


def test_local_model_configs_load():
    """The llama.cpp configs (Lex + its Instruct control) must stay valid."""
    for name, model in [
        ("gams_lex.yaml", "gams3-12b-instruct-lex-q4_k_m"),
        ("gams_instruct_q4.yaml", "gams3-12b-instruct-q4_k_m"),
    ]:
        cfg = load_config(REPO_ROOT / "configs" / name)
        assert cfg.llm.base_url == "http://127.0.0.1:8080/v1"
        assert cfg.llm.model == model
        assert cfg.llm.api_key_env == "LOCAL_LLM_KEY"
        assert cfg.llm.temperature == 0.0
        assert cfg.llm.timeout_s >= 600  # CPU inference is slow
        assert set(cfg.variants) == {"A", "B", "C", "D", "oracle"}
