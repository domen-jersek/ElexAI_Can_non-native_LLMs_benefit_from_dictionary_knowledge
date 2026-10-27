"""Tests for the manual-run kit (export prompts / import answers)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from elexai.manual import export_prompt_kit, import_answers, latest_run


def _source_row(qid: str, variant: str, **kw) -> dict:
    base = {
        "run_id": "20260101-000000_testrun",
        "variant": variant,
        "question_id": qid,
        "question_type": "sense_disambiguation",
        "lemma": "kos",
        "target_word": "kos",
        "gold_sense_id": "10",
        "prompt": f"PROMPT {qid} {variant}",
        "template_version": "sd-v1",
        "output_raw": "SENSE_ID: 10\nODGOVOR: del celote",
        "parsed_sense_id": "10",
        "parsed_answer": "del celote",
        "latency_ms": 10.0,
        "cache_hit": False,
        "model": "source-model",
        "error": None,
        "context_kind": "structured",
        "shown_sense_ids": ["10", "11"],
        "retrieved": [],
        "timestamp": "t",
    }
    base.update(kw)
    return base


def _write_source_run(tmp_path: Path) -> Path:
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "20260101-000000_testrun"
    run_dir.mkdir(parents=True)
    (run_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "testrun",
                "description": "source",
                "variants": ["A", "C"],
                "questions_path": "questions.jsonl",
                "llm": {"model": "source-model"},
                "structured": {"max_senses": 12},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(json.dumps({"dry_run": False}), encoding="utf-8")
    rows = [
        _source_row("q-001", "A", prompt="PROMPT q-001 A", shown_sense_ids=[]),
        _source_row("q-002", "A", prompt="PROMPT q-002 A", shown_sense_ids=[]),
        _source_row("q-001", "C"),
        _source_row("q-002", "C"),
    ]
    (run_dir / "answers.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    # a dry-run dir must be skipped by latest_run
    dry_dir = runs_dir / "20260102-000000_testrun"
    dry_dir.mkdir()
    (dry_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump({"name": "testrun"}), encoding="utf-8"
    )
    (dry_dir / "manifest.json").write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    return runs_dir


def test_latest_run_skips_dry_runs(tmp_path):
    runs_dir = _write_source_run(tmp_path)
    assert latest_run("testrun", runs_dir) == "20260101-000000_testrun"


def test_export_prompt_kit(tmp_path):
    runs_dir = _write_source_run(tmp_path)
    out_dir = tmp_path / "manual_kit"
    summary = export_prompt_kit(
        "20260101-000000_testrun", out_dir, runs_dir=runs_dir
    )
    assert summary["n_prompts"] == 4
    assert summary["per_variant"] == {"A": 2, "C": 2}
    assert (out_dir / "prompts.csv").exists()
    assert (out_dir / "answers.csv").exists()
    assert (out_dir / "HOWTO.md").exists()
    assert len(list((out_dir / "prompts").glob("*.txt"))) == 4

    filtered = export_prompt_kit(
        "20260101-000000_testrun",
        tmp_path / "manual_kit_c",
        variants=["C"],
        runs_dir=runs_dir,
    )
    assert filtered["n_prompts"] == 2
    with (tmp_path / "manual_kit_c" / "answers.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["variant"] for r in rows] == ["C", "C"]
    assert all(r["answer_raw"] == "" for r in rows)


def test_import_answers(tmp_path):
    runs_dir = _write_source_run(tmp_path)
    kit = tmp_path / "manual_kit"
    export_prompt_kit("20260101-000000_testrun", kit, runs_dir=runs_dir)

    answers_csv = kit / "answers.csv"
    lines = answers_csv.read_text(encoding="utf-8").splitlines()
    with answers_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["question_id", "variant", "answer_raw"])
        writer.writerow(["q-001", "A", "Odgovor: kos je del kruha."])
        writer.writerow(["q-001", "C", "SENSE_ID: 10\nODGOVOR: del celote"])
    assert lines  # keep linters happy about the read

    run_dir = import_answers(
        "20260101-000000_testrun",
        answers_csv,
        model_label="TestGaMS (manual)",
        name="gams",
        runs_dir=runs_dir,
    )
    assert run_dir.name.endswith("_gams_manual")
    records = [
        json.loads(line)
        for line in (run_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    by_variant = {r["variant"]: r for r in records}
    assert by_variant["C"]["parsed_sense_id"] == "10"
    assert by_variant["C"]["model"] == "TestGaMS (manual)"
    assert by_variant["C"]["manual"] is True
    assert by_variant["C"]["cache_hit"] is False
    assert by_variant["C"]["latency_ms"] is None
    assert by_variant["C"]["shown_sense_ids"] == ["10", "11"]  # contexts copied
    assert by_variant["A"]["parsed_sense_id"] is None
    cfg = yaml.safe_load((run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    assert cfg["name"] == "gams"
    assert cfg["llm"]["model"] == "TestGaMS (manual)"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manual"] is True
    assert manifest["n_answers"] == 2
    assert manifest["variants"] == ["A", "C"]


def test_import_answers_errors(tmp_path):
    runs_dir = _write_source_run(tmp_path)
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("question_id,variant,answer_raw\nq-001,C,\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        import_answers("20260101-000000_testrun", empty_csv, model_label="m", runs_dir=runs_dir)

    wrong_csv = tmp_path / "wrong.csv"
    wrong_csv.write_text(
        "question_id,variant,answer_raw\nq-999,C,nekaj\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        import_answers("20260101-000000_testrun", wrong_csv, model_label="m", runs_dir=runs_dir)
