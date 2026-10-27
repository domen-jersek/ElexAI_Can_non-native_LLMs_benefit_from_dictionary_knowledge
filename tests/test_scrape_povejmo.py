"""Tests for the povejmo.si scraper helpers (no browser involved)."""

from __future__ import annotations

from pathlib import Path

import pytest

from elexai.scrape_povejmo import (
    clean_reply,
    is_placeholder,
    load_answers,
    looks_like_answer,
    next_unanswered_index,
    save_answers,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "question_id,variant,answer_raw,extra\n"
        + "\n".join(
            f"{r['question_id']},{r['variant']},{r.get('answer_raw', '')},{r.get('extra', '')}"
            for r in rows
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_and_save_roundtrip_preserves_columns(tmp_path):
    csv_path = tmp_path / "answers.csv"
    rows = [
        {"question_id": "q-001", "variant": "A", "answer_raw": "", "extra": "x"},
        {"question_id": "q-001", "variant": "B", "answer_raw": "", "extra": "y"},
    ]
    _write_csv(csv_path, rows)

    loaded, fieldnames = load_answers(csv_path)
    assert fieldnames == ["question_id", "variant", "answer_raw", "extra"]
    assert len(loaded) == 2

    loaded[0]["answer_raw"] = "SENSE_ID: 10\nODGOVOR: del celote"
    save_answers(csv_path, loaded, fieldnames)

    again, _ = load_answers(csv_path)
    assert again[0]["answer_raw"] == "SENSE_ID: 10\nODGOVOR: del celote"
    assert again[0]["extra"] == "x"
    assert again[1]["answer_raw"] == ""


def test_backup_created_once_and_never_overwritten(tmp_path):
    csv_path = tmp_path / "answers.csv"
    _write_csv(csv_path, [{"question_id": "q-001", "variant": "A"}])
    original = csv_path.read_text(encoding="utf-8")

    rows, fieldnames = load_answers(csv_path)
    rows[0]["answer_raw"] = "first"
    save_answers(csv_path, rows, fieldnames)
    backup = csv_path.with_suffix(".csv.bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original

    rows[0]["answer_raw"] = "second"
    save_answers(csv_path, rows, fieldnames)
    assert backup.read_text(encoding="utf-8") == original  # untouched


def test_next_unanswered_index(tmp_path):
    rows = [
        {"question_id": "q-001", "variant": "A", "answer_raw": "done"},
        {"question_id": "q-001", "variant": "B", "answer_raw": "  "},
        {"question_id": "q-001", "variant": "C", "answer_raw": ""},
    ]
    assert next_unanswered_index(rows) == 1
    rows[1]["answer_raw"] = "x"
    assert next_unanswered_index(rows) == 2
    rows[2]["answer_raw"] = "y"
    assert next_unanswered_index(rows) is None


def test_load_rejects_missing_columns(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_answers(bad)


def test_clean_reply():
    assert clean_reply("  a\r\n\r\n\r\nb  ") == "a\n\nb"
    assert clean_reply("") == ""


def test_is_placeholder():
    assert is_placeholder("Razmišljam...")
    assert is_placeholder(" razmisljam …")
    assert is_placeholder("RAZMIŠLJAM")
    assert is_placeholder("Razmišljam . . .")
    assert not is_placeholder("")
    assert not is_placeholder("SENSE_ID: none")
    assert not is_placeholder("Razmišljam o pomenu besede kos.")


def test_looks_like_answer():
    assert looks_like_answer("SENSE_ID: 16283272\nODGOVOR: del celote")
    assert looks_like_answer("SENSE_ID: none ODGOVOR: beseda pomeni kos kruha")
    assert looks_like_answer("ODGOVOR: brez identifikatorja")
    assert not looks_like_answer("Razmišljam...")
    assert not looks_like_answer("")
    assert not looks_like_answer("Beseda kos pomeni del kruha.")
