"""Tests for the generated v3 question set (definition / collocation queries)."""

from __future__ import annotations

import json

import pytest

from elexai.env import REPO_ROOT
from elexai.questions import load_questions, validate_questions

DESIGNED = REPO_ROOT / "data" / "questions" / "questions_v3.jsonl"


@pytest.mark.skipif(not DESIGNED.exists(), reason="questions_v3.jsonl not built")
def test_committed_v3_is_valid_and_typed():
    questions = load_questions(DESIGNED)
    senses = {
        str(rec["sense_id"]): rec["lemma"]
        for rec in (
            json.loads(line)
            for line in (REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    }
    assert validate_questions(questions, senses) == []
    assert {q.task_type for q in questions} == {"definition", "collocation"}
    assert all(q.design_cell.startswith(("A_", "B_")) for q in questions)
    assert sum(q.task_type == "definition" for q in questions) >= 10
    assert sum(q.task_type == "collocation" for q in questions) >= 8
    for q in questions:
        assert q.context_sentence.strip()
        assert q.gold_answer.strip()


@pytest.mark.skipif(not DESIGNED.exists(), reason="questions_v3.jsonl not built")
def test_definition_questions_are_not_ambiguous():
    """A definition query must have exactly one matching sense of the lemma."""
    questions = load_questions(DESIGNED)
    by_lemma: dict[str, list[str]] = {}
    for q in questions:
        if q.task_type == "definition":
            by_lemma.setdefault(q.lemma, []).append(q.context_sentence.strip().lower())
    for lemma, indicators in by_lemma.items():
        assert len(indicators) == len(set(indicators)), f"{lemma}: duplicate indicator query"
