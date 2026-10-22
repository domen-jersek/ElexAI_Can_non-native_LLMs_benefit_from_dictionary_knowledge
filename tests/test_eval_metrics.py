"""Tests for LLM-free scoring (token F1, percentiles, evaluate_run)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from elexai.eval.metrics import evaluate_run, normalize_text, percentile, token_f1


def test_normalize_text():
    assert normalize_text("Del  celote!") == "del celote"
    assert normalize_text("ČLOVEK, žoga.") == "človek žoga"


def test_token_f1():
    assert token_f1("del celote", "del celote") == 1.0
    assert token_f1("", "del celote") == 0.0
    assert token_f1("del celote", "") == 0.0
    partial = token_f1("del snovi", "del celote")
    assert 0.0 < partial < 1.0


def test_percentile():
    assert percentile([], 50) is None
    assert percentile([5.0], 95) == 5.0
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0
    assert percentile([0.0, 10.0], 50) == 5.0


def _write_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "testrun"
    run_dir.mkdir(parents=True)
    questions = [
        {
            "id": "q1", "question": "?", "target_word": "kos", "lemma": "kos", "pos": "noun",
            "context_sentence": "kos", "gold_sense_id": "10", "gold_answer": "del celote",
            "source_dictionary_version": "DDDS backup v3.68",
        },
        {
            "id": "q2", "question": "?", "target_word": "list", "lemma": "list", "pos": "noun",
            "context_sentence": "list", "gold_sense_id": "20", "gold_answer": "del rastline",
            "source_dictionary_version": "DDDS backup v3.68",
        },
    ]
    qpath = tmp_path / "data" / "questions"
    qpath.mkdir(parents=True)
    (qpath / "questions.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in questions) + "\n", encoding="utf-8"
    )
    (run_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump(
            {
                "questions_path": "data/questions/questions.jsonl",
                "retrieval": {"k": 1, "sweep_k": [1, 3]},
                "eval": {"answer_f1_threshold": 0.6},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    def row(qid, variant, **kw):
        base = {
            "run_id": "testrun", "variant": variant, "question_id": qid,
            "question_type": "sense_disambiguation", "lemma": qid, "target_word": qid,
            "gold_sense_id": {"q1": "10", "q2": "20"}[qid],
            "prompt": "p", "template_version": "sd-v1", "timestamp": "t",
            "output_raw": None, "parsed_sense_id": None, "parsed_answer": None,
            "latency_ms": 10.0, "cache_hit": False, "model": "m", "error": None,
            "context_kind": "x", "shown_sense_ids": [], "retrieved": [],
        }
        base.update(kw)
        return base

    rows = [
        # A: no ids; text scores
        row("q1", "A", parsed_answer="del celote"),
        row("q2", "A", parsed_answer="nekaj povsem drugega"),
        # B: q1 retrieved+correct, q2 retrieval miss
        row("q1", "B", parsed_sense_id="10", parsed_answer="del celote",
            retrieved=[{"sense_id": "10", "score": 0.9}]),
        row("q2", "B", parsed_sense_id="99", parsed_answer="napačno",
            retrieved=[{"sense_id": "99", "score": 0.8}]),
        # C: q1 covered+correct, q2 coverage miss
        row("q1", "C", parsed_sense_id="10", parsed_answer="del celote", gold_present=True),
        row("q2", "C", parsed_sense_id=None, parsed_answer="napačno", gold_present=False),
        # oracle: gold present, q2 wrong citation -> composition error
        row("q1", "oracle", parsed_sense_id="10", parsed_answer="del celote", gold_present=True),
        row("q2", "oracle", parsed_sense_id="21", parsed_answer="napačno", gold_present=True),
    ]
    (run_dir / "answers.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return run_dir


def test_evaluate_run(tmp_path):
    run_dir = _write_run(tmp_path)
    metrics = evaluate_run(run_dir, tmp_path)

    assert metrics["n_questions"] == 2
    assert set(metrics["variants"]) == {"A", "B", "C", "oracle"}

    b = metrics["variants"]["B"]
    assert b["citation_accuracy"] == 0.5
    assert b["recall_at_k"]["1"] == 0.5
    assert b["recall_at_k"]["3"] == 0.5
    assert b["retrieval_errors"] == 1
    assert b["composition_errors"] == 0

    c = metrics["variants"]["C"]
    assert c["citation_accuracy"] == 0.5
    assert c["coverage_misses"] == 1

    o = metrics["variants"]["oracle"]
    assert o["citation_accuracy"] == 0.5
    assert o["composition_errors"] == 1

    a = metrics["variants"]["A"]
    assert a["answer_accuracy_f1"] == 0.5
    assert a["latency_p50_ms"] == 10.0


def _write_relation_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "relrun"
    run_dir.mkdir(parents=True)
    questions = [
        {
            "id": "s1", "question": "?", "target_word": "kos", "lemma": "kos", "pos": "noun",
            "context_sentence": "kos", "gold_sense_id": "10", "gold_answer": "del celote",
            "source_dictionary_version": "DDDS backup v3.68",
        },
        {
            "id": "t1", "question": "?", "target_word": "list", "lemma": "list", "pos": "noun",
            "context_sentence": "list", "gold_sense_id": "20", "gold_answer": "del rastline",
            "source_dictionary_version": "DDDS backup v3.68", "flags": ["trick"],
        },
        {
            "id": "r1", "question": "?", "target_word": "mišičnjak", "lemma": "mišičnjak",
            "pos": "noun", "question_type": "relation", "relation": "synonym",
            "related_sense_id": "99", "context_sentence": "", "gold_sense_id": "30",
            "gold_answer": "moški z mišicami",
            "source_dictionary_version": "DDDS backup v3.68",
        },
    ]
    qpath = tmp_path / "data" / "questions"
    qpath.mkdir(parents=True)
    (qpath / "questions.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in questions) + "\n", encoding="utf-8"
    )
    (run_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump(
            {
                "questions_path": "data/questions/questions.jsonl",
                "retrieval": {"k": 1, "sweep_k": [1, 3]},
                "eval": {"answer_f1_threshold": 0.6},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    def row(qid, variant, **kw):
        base = {
            "run_id": "relrun", "variant": variant, "question_id": qid,
            "question_type": "sense_disambiguation", "lemma": qid, "target_word": qid,
            "gold_sense_id": {"s1": "10", "t1": "20", "r1": "30"}[qid],
            "prompt": "p", "template_version": "sd-v1", "timestamp": "t",
            "output_raw": None, "parsed_sense_id": None, "parsed_answer": None,
            "latency_ms": 10.0, "cache_hit": False, "model": "m", "error": None,
            "context_kind": "x", "shown_sense_ids": [], "retrieved": [],
        }
        base.update(kw)
        return base

    rows = [
        row(
            "s1", "C", parsed_sense_id="10", parsed_answer="del celote",
            gold_present=True, shown_sense_ids=["10", "11"],
        ),
        row(
            "t1", "C", parsed_sense_id="99", parsed_answer="napačno",
            gold_present=True, shown_sense_ids=["21", "20"],
        ),
        row(
            "r1", "C", parsed_sense_id="30", parsed_answer="moški z mišicami",
            gold_present=True, shown_sense_ids=["30", "31"],
            related_visible_in_synonyms=True,
            question_type="relation", related_sense_id="99", relation="synonym",
        ),
        row(
            "s1", "B", parsed_sense_id="20", parsed_answer="del rastline", lemma="kos",
            retrieved=[{"sense_id": "20", "score": 0.9}, {"sense_id": "10", "score": 0.5}],
        ),
        row(
            "r1", "D", parsed_sense_id="30", parsed_answer="moški z mišicami",
            gold_present=True, gold_rank=1, evidence_sense_ids=["30"], gold_evidence=True,
            graph_scores=[
                {"sense_id": "30", "score": 1.0},
                {"sense_id": "31", "score": 0.0},
            ],
            question_type="relation", related_sense_id="99", relation="synonym",
        ),
    ]
    (run_dir / "answers.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return run_dir


def test_relation_and_trick_segmentation(tmp_path):
    run_dir = _write_relation_run(tmp_path)
    senses = {
        "10": "kos",
        "11": "kos",
        "20": "list",
        "21": "list",
        "30": "mišičnjak",
        "31": "mišičnjak",
        "99": "drug",
    }
    metrics = evaluate_run(run_dir, tmp_path, senses=senses)

    assert metrics["question_types"] == ["relation", "sense_disambiguation"]
    assert metrics["trick_question_ids"] == ["t1"]

    c = metrics["variants"]["C"]
    assert c["citation_accuracy"] == round(2 / 3, 3)
    assert c["excl_trick"]["citation_accuracy"] == 1.0
    assert c["by_question_type"]["relation"]["citation_accuracy"] == 1.0
    assert c["by_question_type"]["sense_disambiguation"]["citation_accuracy"] == 0.5
    assert c["relation_visible_in_synonyms"] == {"n": 1, "visible": 1}
    assert c["error_taxonomy"] == {"correct": 2, "wrong_other_lemma": 1}
    assert c["coverage_at_k"]["1"] == round(2 / 3, 3)
    assert c["coverage_at_k"]["2"] == 1.0
    assert c["excl_trick"]["coverage_at_k"]["1"] == 1.0

    b = metrics["variants"]["B"]
    assert b["mrr"] == 0.5
    assert b["top1_wrong_lemma_rate"] == 1.0

    d = metrics["variants"]["D"]
    assert d["relation_evidence"] == {"n": 1, "gold_evidence": 1}
    assert d["by_question_type"]["relation"]["gold_rank_mean"] == 1.0
    assert d["coverage_at_k"]["1"] == 1.0
