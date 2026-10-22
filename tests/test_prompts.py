"""Tests for the shared prompt template."""

from __future__ import annotations

from elexai.llm.prompts import TEMPLATE_VERSION, render, template_version
from elexai.questions import Question

QUESTION = Question(
    id="q-x",
    question="Kateri pomen?",
    target_word="kos",
    lemma="kos",
    pos="noun",
    context_sentence="Na krožniku je ostal kos kruha.",
    gold_sense_id="123",
    gold_answer="del celote",
    source_dictionary_version="DDDS backup v3.68",
)

RELATION_QUESTION = Question(
    id="r-x",
    question="Kateri pomen besede »miška« je sopomenka pomena 999?",
    target_word="miška",
    lemma="miška",
    pos="noun",
    question_type="relation",
    relation="synonym",
    related_sense_id="999",
    gold_sense_id="123",
    gold_answer="računalniška naprava",
    source_dictionary_version="DDDS backup v3.68",
)


def test_render_contains_question_and_shape():
    text = render(QUESTION, None)
    assert "kos" in text
    assert "Na krožniku je ostal kos kruha." in text
    assert "SENSE_ID:" in text and "ODGOVOR:" in text
    assert "(Ni na voljo.)" in text


def test_same_template_except_context():
    no_ctx = render(QUESTION, None)
    with_ctx = render(QUESTION, "ID: 123\nBeseda: kos\nDefinicija: del celote")
    # the instruction part must be byte-identical (only the context block differs)
    head_no = no_ctx.split("Možni pomeni:")[0]
    head_ctx = with_ctx.split("Možni pomeni:")[0]
    assert head_no == head_ctx
    assert "ID: 123" in with_ctx


def test_template_version_is_pinned():
    assert TEMPLATE_VERSION == "sd-v1"


def test_relation_render_contains_question_and_shape():
    text = render(RELATION_QUESTION, "ID: 123\nBeseda: miška\nDefinicija: naprava")
    assert "Kateri pomen besede »miška« je sopomenka pomena 999?" in text
    assert "Ciljna beseda: miška" in text
    assert "SENSE_ID:" in text and "ODGOVOR:" in text
    assert "ID: 123" in text
    assert "Stavek:" not in text


def test_template_versions_per_type():
    assert template_version(QUESTION) == "sd-v1"
    assert template_version(RELATION_QUESTION) == "rel-v1"
