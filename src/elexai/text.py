"""Small, shared text helpers (one definition of the crude Slovene stemmer).

The stemmer exists for *matching*, not for display: it makes inflected forms of
the same word meet (boksu/boks, paličicah/paličica, dišavnih/dišavne) while
keeping different words apart (napaka/napadov -> napak/napad). It is deliberately
crude and documented as such; a real lemmatiser would be the research-grade
replacement.
"""

from __future__ import annotations

SUFFIXES = (
    "ostjo", "ega", "emu", "ost", "ijo", "ija", "ami", "ih", "ah", "ov", "ev",
    "om", "em", "im", "am", "jo", "ja", "je", "o", "a", "e", "i", "u",
)


def stem(token: str) -> str:
    """Strip one common Slovene ending, keep the first 5 characters."""
    token = token.lower()
    for suffix in SUFFIXES:
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    return token[:5]
