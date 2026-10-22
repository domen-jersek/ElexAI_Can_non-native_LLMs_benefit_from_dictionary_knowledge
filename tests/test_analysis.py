"""Tests for the notebook analysis helpers (loading + small statistics)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from elexai.analysis import (
    accuracy_frame,
    bootstrap_ci,
    correctness_matrix,
    coverage_frame,
    find_run,
    find_run_with_questions,
    find_runs,
    load_answers,
    mcnemar_exact,
)

QUESTIONS = [
    {
        "id": "s1", "question": "?", "target_word": "kos", "lemma": "kos", "pos": "noun",
        "context_sentence": "kos", "gold_sense_id": "10", "gold_answer": "del celote",
        "source_dictionary_version": "DDDS backup v3.68",
    },
    {
        "id": "s2", "question": "?", "target_word": "list", "lemma": "list", "pos": "noun",
        "context_sentence": "list", "gold_sense_id": "20", "gold_answer": "del rastline",
        "source_dictionary_version": "DDDS backup v3.68",
    },
    {
        "id": "r1", "question": "Kateri pomen besede »mišičnjak«?", "target_word": "mišičnjak",
        "lemma": "mišičnjak", "pos": "noun", "question_type": "relation",
        "relation": "synonym", "related_sense_id": "99", "context_sentence": "",
        "gold_sense_id": "30", "gold_answer": "moški z mišicami",
        "source_dictionary_version": "DDDS backup v3.68", "flags": ["trick"],
    },
]

SENSES = [
    {"sense_id": "10", "lemma": "kos"},
    {"sense_id": "11", "lemma": "kos"},
    {"sense_id": "20", "lemma": "list"},
    {"sense_id": "21", "lemma": "list"},
    {"sense_id": "30", "lemma": "mišičnjak"},
    {"sense_id": "31", "lemma": "mišičnjak"},
    {"sense_id": "99", "lemma": "drug"},
]


def _answer(qid: str, variant: str, gold: str, cited: str | None, **kw) -> dict:
    base: dict = {
        "run_id": "20260101-000000_testrun",
        "variant": variant,
        "question_id": qid,
        "question_type": "sense_disambiguation",
        "lemma": qid,
        "target_word": qid,
        "gold_sense_id": gold,
        "parsed_sense_id": cited,
        "parsed_answer": "odgovor",
        "latency_ms": 10.0,
        "cache_hit": False,
        "error": None,
        "gold_rank": None,
        "gold_present": None,
        "gold_evidence": None,
        "evidence_sense_ids": None,
        "shown_sense_ids": [],
        "graph_scores": [],
        "retrieved": [],
        "prompt": "p",
    }
    base.update(kw)
    return base


def _write_run(tmp_path: Path) -> Path:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20260101-000000_testrun"
    run_dir.mkdir(parents=True)

    (tmp_path / "questions.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in QUESTIONS) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "senses.jsonl").write_text(
        "\n".join(json.dumps(s) for s in SENSES) + "\n", encoding="utf-8"
    )
    (run_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "testrun",
                "variants": ["C", "D"],
                "structured": {"max_senses": 3},
                "questions_path": "questions.jsonl",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(json.dumps({"dry_run": False}), encoding="utf-8")

    rows = [
        _answer("s1", "C", "10", "10", shown_sense_ids=["10", "11"]),
        _answer("s2", "C", "20", "21", shown_sense_ids=["20", "21"]),
        _answer("r1", "C", "30", None),
        _answer("s1", "D", "10", "12", gold_rank=1, graph_scores=[{"sense_id": "10", "score": 1.0}]),
        _answer("s2", "D", "20", "10", gold_rank=2, graph_scores=[{"sense_id": "21", "score": 1.0}, {"sense_id": "20", "score": 0.5}]),
        _answer("r1", "D", "30", "30", gold_rank=1, gold_evidence=True, evidence_sense_ids=["30"]),
    ]
    (run_dir / "answers.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "n_questions": 3,
                "variants": {
                    "C": {
                        "n": 3,
                        "citation_accuracy": 0.333,
                        "coverage_at_k": {"1": 0.333, "2": 0.667},
                        "excl_trick": {"n": 2, "citation_accuracy": 0.5, "coverage_at_k": {"1": 0.5}},
                    },
                    "D": {
                        "n": 3,
                        "citation_accuracy": 0.667,
                        "coverage_at_k": {"1": 0.667},
                        "gold_rank_mean": 1.5,
                        "excl_trick": {"n": 2, "citation_accuracy": 1.0},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return runs_dir


def test_find_runs_and_find_run(tmp_path):
    runs_dir = _write_run(tmp_path)
    df = find_runs(runs_dir)
    assert list(df["run_id"]) == ["20260101-000000_testrun"]
    assert df.iloc[0]["config"] == "testrun"
    assert df.iloc[0]["cap"] == 3
    assert df.iloc[0]["n_questions"] == 3
    assert find_run("testrun", runs_dir) == "20260101-000000_testrun"
    assert find_run_with_questions("testrun", 3, runs_dir) == "20260101-000000_testrun"


def test_load_answers_categories(tmp_path):
    runs_dir = _write_run(tmp_path)
    df = load_answers(
        "20260101-000000_testrun",
        runs_dir=runs_dir,
        questions_path=tmp_path / "questions.jsonl",
        senses_path=tmp_path / "senses.jsonl",
    )
    assert len(df) == 6
    by = {(r["question_id"], r["variant"]): r for _, r in df.iterrows()}
    assert bool(by[("s1", "C")]["correct"]) is True
    assert by[("s1", "C")]["category"] == "correct"
    assert by[("s2", "C")]["category"] == "wrong_same_lemma"
    assert by[("s2", "D")]["category"] == "wrong_other_lemma"
    assert by[("s1", "D")]["category"] == "wrong_unknown_id"
    assert by[("r1", "C")]["category"] == "none"
    assert bool(by[("r1", "D")]["gold_evidence"]) is True
    assert by[("r1", "D")]["related_sense_id"] == "99"
    assert bool(by[("r1", "D")]["is_trick"]) is True
    assert bool(by[("s1", "D")]["is_trick"]) is False
    assert by[("s2", "D")]["ranked_ids"] == ["21", "20"]


def test_accuracy_and_coverage_frames(tmp_path):
    runs_dir = _write_run(tmp_path)
    acc = accuracy_frame(["20260101-000000_testrun"], runs_dir)
    assert set(acc["variant"]) == {"C", "D"}
    c = acc[acc["variant"] == "C"].iloc[0]
    assert c["cap"] == 3
    assert c["citation_accuracy"] == 0.333
    assert c["citation_accuracy_excl_trick"] == 0.5
    assert c["coverage_at_k"] == {"1": 0.333, "2": 0.667}

    cov = coverage_frame(["20260101-000000_testrun"], runs_dir=runs_dir)
    assert set(cov["variant"]) == {"C", "D"}
    assert set(cov[cov["variant"] == "C"]["k"]) == {1, 2}


def test_correctness_matrix_and_stats(tmp_path):
    runs_dir = _write_run(tmp_path)
    df = load_answers(
        "20260101-000000_testrun",
        runs_dir=runs_dir,
        questions_path=tmp_path / "questions.jsonl",
        senses_path=tmp_path / "senses.jsonl",
    )
    matrix = correctness_matrix(df, variants=("C", "D"))
    assert list(matrix.index) == ["s1", "s2"]  # trick question excluded
    assert bool(matrix.loc["s1", "C"]) and bool(matrix.loc["s2", "D"]) is False

    assert mcnemar_exact(3, 0) == 0.25
    assert mcnemar_exact(0, 0) == 1.0

    lo, hi = bootstrap_ci(10, 10)
    assert lo == 1.0 and hi == 1.0
    lo, hi = bootstrap_ci(5, 10)
    assert 0.0 < lo < 0.5 < hi < 1.0
