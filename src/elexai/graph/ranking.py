"""Pure (no-IO) neighborhood scoring + context rendering for variant D.

`rank_candidates` scores each candidate sense by how well the sentence matches
the sense's neighborhood:

- definition/indicator tokens: weight ``weight_definition`` (default 1)
- synonym words: weight ``weight_synonym`` (default 2)
- typical collocation forms: weight ``weight_collocation`` (default 2)

The target lemma's own token(s) are excluded from scoring - they appear in every
candidate's collocations and would otherwise cancel out. Ties break by dictionary
sense order, then by sense id, so the ranking is deterministic.

`build_context` renders the top candidates as context blocks through the SAME
``SenseChunk.block`` code path as variant C, so the only difference between C and
D is the ORDER of candidates (plus the logged scores).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from elexai.eval.metrics import normalize_text
from elexai.retrieval.chunks import SenseChunk

# Small heuristic stopword list (Slovene function words); scoring is lexical, so
# these would otherwise create noise matches.
STOPWORDS = frozenset(
    """
    a ali bi bil bila bili bilo biti bo bomo boste da do ga hoče ima in iz je jih ji
    kot ki kjer le me med mi na naj nas ne ni niso o ob od pa po pod pri s saj se si
    ste še ta te ti tisto to tu tudi v va ve vi vse za zdaj že z
    """.split()
)


@dataclass
class GraphSense:
    """One candidate sense with its graph neighborhood (built by the retriever)."""

    sense_id: str
    lemma: str
    pos: str | None
    position: int | None
    indicator: str
    definition: str  # same joined string as lexical_core ("indicator | general")
    example_count: int = 0
    lu_type: str | None = None
    synonyms: list[tuple[str, str]] = field(default_factory=list)  # (id, lemma)
    collocations: list[str] = field(default_factory=list)  # collocation forms


@dataclass
class RankedSense:
    sense: GraphSense
    score: float
    matched_definition: list[str] = field(default_factory=list)
    matched_synonyms: list[str] = field(default_factory=list)
    matched_collocations: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return [t for t in normalize_text(text).split() if t and t not in STOPWORDS]


def rank_candidates(
    sentence: str,
    target_lemma: str,
    candidates: list[GraphSense],
    *,
    weight_definition: float = 1.0,
    weight_collocation: float = 2.0,
    weight_synonym: float = 2.0,
) -> list[RankedSense]:
    target = normalize_text(target_lemma)
    sentence_tokens = {t for t in _tokens(sentence) if t != target}
    ranked: list[RankedSense] = []
    for sense in candidates:
        definition_tokens = {
            t for t in _tokens(f"{sense.indicator} {sense.definition}") if t != target
        }
        synonym_tokens = {
            t for _, lemma in sense.synonyms for t in _tokens(lemma) if t != target
        }
        collocation_tokens = {
            t for t in _tokens(" ".join(sense.collocations)) if t != target
        }
        matched_def = sorted(sentence_tokens & definition_tokens)
        matched_syn = sorted(sentence_tokens & synonym_tokens)
        matched_coll = sorted(sentence_tokens & collocation_tokens)
        score = (
            weight_definition * len(matched_def)
            + weight_synonym * len(matched_syn)
            + weight_collocation * len(matched_coll)
        )
        ranked.append(
            RankedSense(
                sense=sense,
                score=score,
                matched_definition=matched_def,
                matched_synonyms=matched_syn,
                matched_collocations=matched_coll,
            )
        )
    ranked.sort(
        key=lambda r: (
            -r.score,
            r.sense.position if r.sense.position is not None else 10**9,
            int(r.sense.sense_id),
        )
    )
    return ranked


def to_chunk(ranked: RankedSense) -> SenseChunk:
    """Adapt to SenseChunk so rendering is byte-identical to variant C."""
    s = ranked.sense
    return SenseChunk(
        sense_id=s.sense_id,
        lemma=s.lemma,
        pos=s.pos,
        position=s.position,
        definition=s.definition or s.indicator,
        synonyms=tuple(s.synonyms),
        dependencies=tuple(("", form) for form in s.collocations),
        example_count=s.example_count,
    )


def build_context(
    sentence: str,
    target_lemma: str,
    candidates: list[GraphSense],
    *,
    max_candidates: int = 12,
    synonyms_shown: int = 5,
    collocations_shown: int = 8,
    weight_definition: float = 1.0,
    weight_collocation: float = 2.0,
    weight_synonym: float = 2.0,
) -> tuple[str, list[str], list[dict]]:
    """Return (context text, shown sense ids, score log for all candidates)."""
    ranked = rank_candidates(
        sentence,
        target_lemma,
        candidates,
        weight_definition=weight_definition,
        weight_collocation=weight_collocation,
        weight_synonym=weight_synonym,
    )
    shown = ranked[:max_candidates]
    if shown:
        blocks = [
            to_chunk(r).block(
                with_relations=True,
                max_synonyms=synonyms_shown,
                max_dependencies=collocations_shown,
            )
            for r in shown
        ]
        text = "\n\n".join(blocks)
    else:
        text = "(Ni na voljo.)"
    shown_ids = [r.sense.sense_id for r in shown]
    scores = [
        {
            "sense_id": r.sense.sense_id,
            "score": r.score,
            "matched_collocations": r.matched_collocations[:5],
            "matched_definition": r.matched_definition[:5],
            "matched_synonyms": r.matched_synonyms[:5],
        }
        for r in ranked
    ]
    return text, shown_ids, scores
