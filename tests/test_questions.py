"""Tests for the question schema and validator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from elexai.questions import Question, validate_questions

BASE = {
    "id": "q-001",
    "question": "V katerem pomenu je uporabljena beseda 'miška'?",
    "target_word": "miška",
    "lemma": "miška",
    "pos": "noun",
    "context_sentence": "Računalniška miška je prenehala delovati.",
    "gold_sense_id": "12345",
    "gold_answer": "računalniška naprava",
    "source_dictionary_version": "DDDS backup v3.68",
    "review_status": "draft",
}


def q(**overrides) -> Question:
    return Question.model_validate({**BASE, **overrides})


def test_valid_draft_has_no_problems():
    assert validate_questions([q()]) == []


def test_duplicate_id():
    problems = validate_questions([q(), q()])
    assert any("duplicate id" in p for p in problems)


def test_verified_requires_reviewer():
    problems = validate_questions([q(review_status="verified")])
    assert any("reviewer is empty" in p for p in problems)
    assert validate_questions([q(review_status="verified", reviewer="A. Lex.")]) == []


def test_gold_sense_id_must_be_numeric():
    problems = validate_questions([q(gold_sense_id="oswn-123-n")])
    assert any("not a numeric DDDS sense id" in p for p in problems)


def test_target_word_must_occur_in_context():
    problems = validate_questions([q(context_sentence="Mačka spi na kavču.")])
    assert any("not found in context_sentence" in p for p in problems)


def test_senses_crosscheck():
    qs = [q(gold_sense_id="12345")]
    assert validate_questions(qs, senses={"12345": "miška"}) == []
    problems = validate_questions(qs, senses={"12345": "kruh"})
    assert any("lemma mismatch" in p for p in problems)
    problems = validate_questions(qs, senses={"999": "miška"})
    assert any("not present in DDDS export" in p for p in problems)


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        Question.model_validate({**BASE, "typo_field": 1})


RELATION_BASE = {
    **BASE,
    "id": "r-001",
    "question": "Kateri pomen besede »miška« je sopomenka pomena 999?",
    "question_type": "relation",
    "relation": "synonym",
    "related_sense_id": "999",
    "context_sentence": "",
}


def rq(**overrides) -> Question:
    return Question.model_validate({**RELATION_BASE, **overrides})


def test_valid_relation_question():
    assert validate_questions([rq()]) == []
    assert validate_questions([rq()], senses={"12345": "miška", "999": "miš"}) == []


def test_relation_requires_related_sense_id():
    problems = validate_questions([rq(related_sense_id="")])
    assert any("without related_sense_id" in p for p in problems)


def test_relation_requires_relation_type():
    problems = validate_questions([rq(relation=None)])
    assert any("without relation type" in p for p in problems)


def test_relation_ids_must_differ():
    problems = validate_questions([rq(related_sense_id="12345")])
    assert any("equals gold_sense_id" in p for p in problems)


def test_relation_related_sense_must_be_numeric_and_present():
    problems = validate_questions([rq(related_sense_id="oswn-1-n")])
    assert any("not a numeric DDDS sense id" in p for p in problems)
    problems = validate_questions([rq()], senses={"12345": "miška"})
    assert any("related_sense_id 999 not present" in p for p in problems)


def test_relation_target_word_must_be_in_question():
    problems = validate_questions([rq(question="Kateri pomen je to?")])
    assert any("not found in question" in p for p in problems)


def test_sense_question_requires_context_sentence():
    problems = validate_questions([q(context_sentence="")])
    assert any("without context_sentence" in p for p in problems)
