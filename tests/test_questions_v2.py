"""Tests for the designed v2 question set (builder + committed artifact)."""

from __future__ import annotations

import json
import sys

import pytest

from elexai.env import REPO_ROOT
from elexai.questions import load_questions, validate_questions
from elexai.text import content_stems, stem

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import build_questions_v2 as builder  # noqa: E402

DESIGNED = REPO_ROOT / "data" / "questions" / "questions_v2.jsonl"


def test_stemmer_meets_inflections_but_keeps_words_apart():
    assert stem("brisom") == stem("bris")
    assert stem("dišavnih") == stem("dišavne")
    assert stem("garažnem") == stem("garažni")
    assert stem("napaka") != stem("napadov")


def test_content_words_drops_stopwords_and_target_forms():
    words = content_stems(
        "S paličicami je nabadal koščke piščanca.", exclude_prefixes=("pali",)
    )
    assert "nabad" in words
    assert "pali" not in words
    assert "je" not in words  # stopword


def _sense(sid: int, position: int, definition: str, deps: list[str] | None = None) -> dict:
    return {
        "sense_id": sid,
        "lemma": "test",
        "pos": "noun",
        "position": position,
        "definitions": [{"type": "indicator", "text": definition}],
        "dependencies": [[9000 + i, text] for i, text in enumerate(deps or [])],
        "synonyms": [],
    }


def test_classify_sense_cells():
    gold_shallow = _sense(1, 1, "kruh", ["test kruh"])
    gold_buried = _sense(2, 5, "moka", ["test moka"])
    other = [_sense(3, 2, "ptica", ["test ptica"])]
    senses = [gold_shallow, gold_buried, *other]

    cell, cues, position = builder.classify_sense(
        "Kruh je na mizi.", gold_shallow, senses, target_word="test"
    )
    assert cell == "S1_shallow_cued"
    assert "kruh" in cues and position == 1

    cell, cues, position = builder.classify_sense(
        "Moka je na mizi.", gold_buried, senses, target_word="test"
    )
    assert cell == "S3_buried_cued"
    assert "moka" in cues and position == 5

    cell, cues, _position = builder.classify_sense(
        "Nekaj je na mizi.", gold_buried, senses, target_word="test"
    )
    assert cell == "S4_buried_nocue"
    assert cues == []


def test_relation_cell():
    a = _sense(1, 1, "kruh")
    b = _sense(2, 1, "ptica")
    c = _sense(3, 1, "kruh in moka")
    assert builder.relation_cell(a, b, "synonym")[0] == "R_synonym_disjoint"
    assert builder.relation_cell(a, c, "synonym")[0] == "R_synonym_overlap"


@pytest.mark.skipif(not DESIGNED.exists(), reason="questions_v2.jsonl not built")
def test_committed_design_is_valid_and_stratified():
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
    assert len(questions) >= 45
    assert all(q.design_cell for q in questions), "every question must carry its cell"
    cells = [q.design_cell for q in questions]
    assert cells.count("S3_buried_cued") >= 10  # the payoff cell must be well populated
    assert cells.count("S4_buried_nocue") >= 3  # and so must its boundary
    assert any(c.startswith("R_") and c.endswith("_disjoint") for c in cells)
