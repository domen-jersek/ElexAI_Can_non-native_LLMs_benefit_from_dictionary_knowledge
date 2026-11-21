"""Small, shared text helpers: one definition of the crude Slovene stemmer and
of the content-word extraction used for cue detection.

The stemmer exists for *matching*, not for display: it makes inflected forms of
the same word meet (boksu/boks, paličicah/paličica, dišavnih/dišavne) while
keeping different words apart (napaka/napadov -> napak/napad). It is deliberately
crude and documented as such; a real lemmatiser would be the research-grade
replacement.
"""

from __future__ import annotations

import re

SUFFIXES = (
    "ostjo", "ega", "emu", "ost", "ijo", "ija", "ami", "ih", "ah", "ov", "ev",
    "om", "em", "im", "am", "jo", "ja", "je", "o", "a", "e", "i", "u",
)

WORD = re.compile(
    r"[a-z\u010d\u0161\u017e\u0107\u0111\u00e1\u00e9\u00ed\u00f3\u00fa]+", re.IGNORECASE
)

STOPWORDS = frozenset(
    """in v na za se je ki da s z k o ob po do od iz pri ter ali pa tudi ne ni naj
    bolj zelo kot med brez ga mu ji jih nje njega svoj svoja svoje biti sem
    si smo ste so bil bila bilo bili torej zato ker ce cez proti kdo kaj
    kateri katera katero ta to tega temu tem temvec ampak""".split()
)


def stem(token: str) -> str:
    """Strip one common Slovene ending, keep the first 5 characters."""
    token = token.lower()
    for suffix in SUFFIXES:
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    return token[:5]


def content_stems(text: str, *, exclude_prefixes: tuple[str, ...] = ()) -> set[str]:
    """Content-word stems; stopwords and the target word's forms removed."""
    out: set[str] = set()
    for token in (w.lower() for w in WORD.findall(text or "")):
        if len(token) < 3 or token in STOPWORDS:
            continue
        if any(token.startswith(prefix) for prefix in exclude_prefixes if prefix):
            continue
        out.add(stem(token))
    return out
