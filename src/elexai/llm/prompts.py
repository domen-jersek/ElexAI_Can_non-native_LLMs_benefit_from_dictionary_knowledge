"""Prompt template for the sense-disambiguation pilot (single version per question type).

The SAME template is used for variants A, B, C and oracle; the only thing that
differs is the *context block* handed to :func:`render`. Variant A renders the
template with an empty context block ("(Ni na voljo.)"), so the instruction
text is byte-identical across variants (see docs/DECISIONS.md D-014).

Two templates exist (one per question type; D-022):

- ``sd-v1``: sense disambiguation in a sentence (the original 30 questions);
- ``rel-v1``: lexical-relation questions ("which sense of the target word is
  the synonym/antonym/hypernym of the given sense").

The model must answer in a strict shape (identical for both types):

    SENSE_ID: <ddds sense id or none>
    ODGOVOR: <short Slovene description of the chosen sense>
"""

from __future__ import annotations

from elexai.questions import Question

TEMPLATE_VERSION = "sd-v1"  # sense-disambiguation template (kept for old runs)
TEMPLATE_VERSION_RELATION = "rel-v1"
_TEMPLATE_VERSIONS = {
    "sense_disambiguation": TEMPLATE_VERSION,
    "relation": TEMPLATE_VERSION_RELATION,
}

_INSTRUCTIONS = """\
Si jezikoslovec, ki odgovarja na vprašanje o pomenu slovenske besede v danem stavku.

Pravila:
1. Določi, kateri pomen ciljne besede je uporabljen v stavku.
2. Če so spodaj navedeni možni pomeni z identifikatorji (ID), izberi natanko enega izmed njih.
3. V vrstico SENSE_ID vpiši ID izbranega pomena. Če možni pomeni niso navedeni, vpiši none.
4. V vrstico ODGOVOR vpiši kratek opis izbranega pomena (1-2 stavka), v slovenščini.
5. Ne dodajaj nobenega drugega besedila.\
"""

_RELATION_INSTRUCTIONS = """\
Si jezikoslovec, ki odgovarja na vprašanje o pomenskem odnosu med pomeni slovenskih besed.

Pravila:
1. V vprašanju je podan pomen izhodiščne besede in pomenski odnos (sopomenka, protipomenka ali nadpomenka).
2. Med spodaj navedenimi možnimi pomeni ciljne besede izberi natanko tistega, ki je v tem odnosu z izhodiščnim pomenom.
3. V vrstico SENSE_ID vpiši ID izbranega pomena. Če možni pomeni niso navedeni, vpiši none.
4. V vrstico ODGOVOR vpiši kratek opis izbranega pomena (1-2 stavka), v slovenščini.
5. Ne dodajaj nobenega drugega besedila.\
"""


def template_version(question: Question) -> str:
    """The template version used for this question (recorded per answer)."""
    return _TEMPLATE_VERSIONS[question.question_type]


def render(question: Question, context: str | None) -> str:
    """Render the full prompt. ``context`` is the (already formatted) list of
    candidate senses / retrieved chunks; ``None`` or empty means "not available"
    (variant A)."""
    block = context.strip() if context and context.strip() else "(Ni na voljo.)"
    if question.question_type == "relation":
        return (
            f"{_RELATION_INSTRUCTIONS}\n\n"
            f"Vprašanje: {question.question}\n"
            f"Ciljna beseda: {question.target_word}\n\n"
            f"Možni pomeni:\n{block}\n\n"
            f"Odgovori natanko v tej obliki:\n"
            f"SENSE_ID: <ID ali none>\n"
            f"ODGOVOR: <opis pomena>"
        )
    return (
        f"{_INSTRUCTIONS}\n\n"
        f"Stavek: {question.context_sentence}\n"
        f"Ciljna beseda: {question.target_word}\n"
        f"Besedna vrsta: {question.pos}\n\n"
        f"Možni pomeni:\n{block}\n\n"
        f"Odgovori natanko v tej obliki:\n"
        f"SENSE_ID: <ID ali none>\n"
        f"ODGOVOR: <opis pomena>"
    )
