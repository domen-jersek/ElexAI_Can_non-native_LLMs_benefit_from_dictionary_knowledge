"""Question dataset schema and validation (sense-disambiguation pilot).

The question set lives in ``data/questions/questions.jsonl`` (one JSON object
per line, committed). Gold answers are validated structurally here and are
supposed to be *verified by a lexicographer* before any reporting without a
caveat (``review_status`` starts as ``draft``).

Field reference (fixed by the task brief):

- ``id``: stable slug, e.g. ``q-001``
- ``question``: question text shown to the model (Slovene)
- ``target_word``: the word occurrence in the context being disambiguated
- ``lemma``: dictionary headword (DDDS lexeme lemma)
- ``pos``: part of speech of the target
- ``question_type``: ``sense_disambiguation`` | ``relation``
- ``relation``: for relation questions: ``synonym`` | ``antonym`` | ``hypernym`` | ``hyponym``
  (the target sense stands in this relation to ``related_sense_id``)
- ``related_sense_id``: for relation questions: the DDDS sense the target sense is related to
- ``context_sentence``: the sentence containing the target word (sense questions only)
- ``gold_sense_id``: DDDS ``jedro_sense.id`` of the intended sense
- ``gold_answer``: short reference answer (sense-definition wording)
- ``source_dictionary_version``: e.g. ``DDDS backup v3.68``
- ``review_status``: ``draft`` | ``verified``
- ``reviewer``: lexicographer name (required once ``verified``)
- ``notes``: free text (ambiguity notes, caveats)
- ``flags``: free-form markers, e.g. ``["trick"]`` for known-problematic items
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    target_word: str = Field(min_length=1)
    lemma: str = Field(min_length=1)
    pos: str = Field(min_length=1)
    question_type: Literal["sense_disambiguation", "relation"] = "sense_disambiguation"
    relation: Literal["synonym", "antonym", "hypernym", "hyponym"] | None = None
    related_sense_id: str = ""
    context_sentence: str = ""
    gold_sense_id: str = Field(min_length=1)
    gold_answer: str = Field(min_length=1)
    source_dictionary_version: str = Field(min_length=1)
    review_status: Literal["draft", "verified"] = "draft"
    reviewer: str = ""
    notes: str = ""
    flags: list[str] = Field(default_factory=list)


def load_questions(path: str | Path) -> list[Question]:
    """Load a JSONL question file; raises ValueError with line context."""
    p = Path(path)
    questions: list[Question] = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            questions.append(Question.model_validate(json.loads(line)))
        except Exception as e:  # noqa: BLE001 - want line context for humans
            raise ValueError(f"{p}:{lineno}: invalid question: {e}") from e
    return questions


def validate_questions(
    questions: list[Question], senses: dict[str, str] | None = None
) -> list[str]:
    """Structural validation. ``senses`` optionally maps sense_id -> lemma
    (from the DDDS export) to cross-check gold ids."""
    problems: list[str] = []
    seen: set[str] = set()
    for q in questions:
        if q.id in seen:
            problems.append(f"{q.id}: duplicate id")
        seen.add(q.id)
        if not q.gold_sense_id.isdigit():
            problems.append(f"{q.id}: gold_sense_id is not a numeric DDDS sense id")
        if q.review_status == "verified" and not q.reviewer.strip():
            problems.append(f"{q.id}: review_status=verified but reviewer is empty")
        if q.question_type == "relation":
            if not q.related_sense_id:
                problems.append(f"{q.id}: relation question without related_sense_id")
            elif not q.related_sense_id.isdigit():
                problems.append(
                    f"{q.id}: related_sense_id is not a numeric DDDS sense id"
                )
            if q.relation is None:
                problems.append(f"{q.id}: relation question without relation type")
            if q.related_sense_id and q.related_sense_id == q.gold_sense_id:
                problems.append(f"{q.id}: related_sense_id equals gold_sense_id")
            if q.target_word.lower() not in q.question.lower():
                problems.append(
                    f"{q.id}: target_word '{q.target_word}' not found in question"
                )
        else:
            if not q.context_sentence.strip():
                problems.append(
                    f"{q.id}: sense_disambiguation question without context_sentence"
                )
            elif q.target_word.lower() not in q.context_sentence.lower():
                problems.append(
                    f"{q.id}: target_word '{q.target_word}' not found in context_sentence"
                )
        if senses is not None:
            if q.gold_sense_id not in senses:
                problems.append(
                    f"{q.id}: gold_sense_id {q.gold_sense_id} not present in DDDS export"
                )
            else:
                ddds_lemma = senses[q.gold_sense_id]
                if ddds_lemma and ddds_lemma.lower() != q.lemma.lower():
                    problems.append(
                        f"{q.id}: lemma mismatch: question has '{q.lemma}', "
                        f"DDDS sense {q.gold_sense_id} belongs to '{ddds_lemma}'"
                    )
            if q.question_type == "relation" and q.related_sense_id:
                if q.related_sense_id not in senses:
                    problems.append(
                        f"{q.id}: related_sense_id {q.related_sense_id} not present in "
                        f"DDDS export"
                    )
    return problems


def load_senses_export(path: str | Path) -> dict[str, str]:
    """Load sense_id -> lemma mapping from data/processed/ddds/senses.jsonl."""
    senses: dict[str, str] = {}
    p = Path(path)
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        senses[str(rec["sense_id"])] = rec.get("lemma", "")
    return senses
