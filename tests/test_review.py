"""Tests for the lexicographer review kit (sheet + table + summary)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

from elexai.review import build_review_kit

QUESTIONS = [
    {
        "id": "q-001", "question": "Kateri pomen besede »kos« je uporabljen?",
        "target_word": "kos", "lemma": "kos", "pos": "noun",
        "context_sentence": "Na krožniku je ostal kos kruha.",
        "gold_sense_id": "10", "gold_answer": "del celote",
        "source_dictionary_version": "DDDS backup v3.68",
    },
    {
        "id": "q-002", "question": "Kateri pomen besede »list« je uporabljen?",
        "target_word": "list", "lemma": "list", "pos": "noun",
        "context_sentence": "Na mizi je ležal list papirja.",
        "gold_sense_id": "20", "gold_answer": "del rastline",
        "source_dictionary_version": "DDDS backup v3.68", "flags": ["trick"],
    },
    {
        "id": "q-003", "question": "Kateri pomen besede »kos« je sopomenka pomena 11?",
        "target_word": "kos", "lemma": "kos", "pos": "noun",
        "question_type": "relation", "relation": "synonym", "related_sense_id": "11",
        "context_sentence": "", "gold_sense_id": "10", "gold_answer": "del celote",
        "source_dictionary_version": "DDDS backup v3.68",
    },
]

SENSES = [
    {"sense_id": "10", "lemma": "kos"},
    {"sense_id": "11", "lemma": "kos"},
    {"sense_id": "20", "lemma": "list"},
    {"sense_id": "21", "lemma": "list"},
    {"sense_id": "22", "lemma": "list"},
    {"sense_id": "23", "lemma": "list"},
]

CORE = [
    {
        "sense_id": "10", "lemma": "kos", "pos": "noun", "position": 1,
        "definitions": [{"type": "general", "text": "del snovi, navadno ločen od večje celote"}],
        "synonyms": [["11", "frtalja"]],
        "dependencies": [["1", "kos kruha"]],
    },
    {
        "sense_id": "11", "lemma": "kos", "pos": "noun", "position": 2,
        "definitions": [{"type": "general", "text": "del snovi ali živila, navadno ločen od večje celote"}],
        "synonyms": [], "dependencies": [],
    },
    {
        "sense_id": "20", "lemma": "list", "pos": "noun", "position": 4,
        "definitions": [{"type": "general", "text": "del rastline"}],
        "synonyms": [], "dependencies": [["2", "list papirja"]],
    },
    {"sense_id": "21", "lemma": "list", "pos": "noun", "position": 1,
     "definitions": [{"type": "general", "text": "dokument"}], "synonyms": [], "dependencies": []},
    {"sense_id": "22", "lemma": "list", "pos": "noun", "position": 2,
     "definitions": [{"type": "general", "text": "riba"}], "synonyms": [], "dependencies": []},
    {"sense_id": "23", "lemma": "list", "pos": "noun", "position": 3,
     "definitions": [{"type": "general", "text": "o seznamu"}], "synonyms": [], "dependencies": []},
]


def _answer(qid: str, variant: str, gold: str, cited: str | None, **kw) -> dict:
    base: dict = {
        "run_id": "run", "variant": variant, "question_id": qid,
        "question_type": "sense_disambiguation", "lemma": qid, "target_word": qid,
        "gold_sense_id": gold,
        "parsed_sense_id": cited, "parsed_answer": "opis",
        "latency_ms": 10.0, "cache_hit": False, "error": None,
        "shown_sense_ids": [], "retrieved": [], "graph_scores": [],
        "evidence_sense_ids": None, "gold_present": True, "gold_rank": 1,
        "prompt": "p", "timestamp": "t",
    }
    base.update(kw)
    return base


def _write_run(tmp_path: Path) -> Path:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20260101-000000_testrun"
    run_dir.mkdir(parents=True)
    (tmp_path / "questions.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in QUESTIONS) + "\n", encoding="utf-8"
    )
    (tmp_path / "senses.jsonl").write_text(
        "\n".join(json.dumps(s) for s in SENSES) + "\n", encoding="utf-8"
    )
    (tmp_path / "core.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in CORE) + "\n", encoding="utf-8"
    )
    (run_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump({"name": "testrun", "questions_path": "questions.jsonl"}), encoding="utf-8"
    )
    rows = [
        _answer("q-001", "A", "10", None, parsed_answer="kos je del kruha", lemma="kos"),
        _answer("q-001", "B", "10", "99", retrieved=[{"sense_id": "99", "score": 0.9}], lemma="kos"),
        _answer("q-001", "C", "10", "11", shown_sense_ids=["10", "11"], lemma="kos"),
        _answer("q-001", "D", "10", "10", lemma="kos",
                graph_scores=[{"sense_id": "10", "score": 0.0, "matched_definition": [],
                               "matched_collocations": []}]),
        _answer("q-001", "oracle", "10", "10", shown_sense_ids=["10", "11"], lemma="kos"),
        _answer("q-002", "A", "20", None, parsed_answer="papir", lemma="list"),
        _answer("q-002", "B", "20", "21", retrieved=[{"sense_id": "21", "score": 0.8}], lemma="list"),
        _answer("q-002", "C", "20", "20", shown_sense_ids=["21", "22", "23", "20"], lemma="list"),
        _answer("q-002", "D", "20", "20", lemma="list",
                graph_scores=[{"sense_id": "20", "score": 0.0, "matched_definition": [],
                               "matched_collocations": []}]),
        _answer("q-002", "oracle", "20", "20", shown_sense_ids=["20"], lemma="list"),
        _answer("q-003", "C", "10", "10", shown_sense_ids=["10", "11"], lemma="kos"),
        _answer("q-003", "D", "10", "10", lemma="kos",
                graph_scores=[{"sense_id": "10", "score": 0.0, "matched_definition": [],
                               "matched_collocations": []}]),
    ]
    (run_dir / "answers.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return runs_dir


def test_build_review_kit(tmp_path):
    runs_dir = _write_run(tmp_path)
    out_dir = tmp_path / "review"
    summary = build_review_kit(
        "20260101-000000_testrun",
        out_dir,
        runs_dir=runs_dir,
        questions_path=tmp_path / "questions.jsonl",
        senses_path=tmp_path / "senses.jsonl",
        lexical_core=tmp_path / "core.jsonl",
    )
    assert summary["n_questions"] == 3
    assert summary["n_relations"] == 1
    assert summary["flagged"]["trick"] == ["q-002"]
    assert summary["flagged"]["brez-namiga (težko)"] == ["q-002"]
    assert summary["flagged"]["podvojen-kandidat"] == ["q-001", "q-003"]
    assert summary["flagged"]["B-brez-zlatega"] == ["q-001", "q-002"]

    sheet = (out_dir / "review_sheet.md").read_text(encoding="utf-8")
    assert "q-001" in sheet and "q-002" in sheet and "q-003" in sheet
    assert "podvojen-kandidat:11" in sheet
    assert "brez-namiga (težko)" in sheet
    assert "Predlagani zlati pomen" in sheet
    assert "**Odnos:** synonym" in sheet
    assert "Izhodiščni pomen" not in sheet.split("## q-002")[0]  # sense question: no such block

    with (out_dir / "review_table.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[1]["id"] == "q-002"
    assert "trick" in rows[1]["zastavice"]
    assert rows[2]["id"] == "q-003"
    assert rows[0]["pregledovalec"] == ""

    summary_md = (out_dir / "review_summary.md").read_text(encoding="utf-8")
    assert "Povzetek za pregled" in summary_md
