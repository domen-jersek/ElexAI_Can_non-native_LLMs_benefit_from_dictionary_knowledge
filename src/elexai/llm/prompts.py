"""Prompt template for the sense-disambiguation pilot (single version for all variants).

The SAME template is used for variants A, B, C and oracle; the only thing that
differs is the *context block* handed to :func:`render`. Variant A renders the
template with an empty context block ("(Ni na voljo.)"), so the instruction
text is byte-identical across variants (see docs/DECISIONS.md D-014).

The model must answer in a strict shape:

    SENSE_ID: <ddds sense id or none>
    ODGOVOR: <short Slovene description of the chosen sense>
"""

from __future__ import annotations

from elexai.questions import Question

TEMPLATE_VERSION = "sd-v1"

_INSTRUCTIONS = """\
Si jezikoslovec, ki odgovarja na vprašanje o pomenu slovenske besede v danem stavku.

Pravila:
1. Določi, kateri pomen ciljne besede je uporabljen v stavku.
2. Če so spodaj navedeni možni pomeni z identifikatorji (ID), izberi natanko enega izmed njih.
3. V vrstico SENSE_ID vpiši ID izbranega pomena. Če možni pomeni niso navedeni, vpiši none.
4. V vrstico ODGOVOR vpiši kratek opis izbranega pomena (1-2 stavka), v slovenščini.
5. Ne dodajaj nobenega drugega besedila.\
"""


def render(question: Question, context: str | None) -> str:
    """Render the full prompt. ``context`` is the (already formatted) list of
    candidate senses / retrieved chunks; ``None`` or empty means "not available"
    (variant A)."""
    block = context.strip() if context and context.strip() else "(Ni na voljo.)"
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
