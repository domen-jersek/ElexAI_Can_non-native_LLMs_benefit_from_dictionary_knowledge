"""Pure (no-IO) neighborhood scoring + context rendering for variant D.

`rank_candidates` scores each candidate sense by how well the sentence matches
the sense's neighborhood:

- definition/indicator tokens: weight ``weight_definition`` (default 1)
- synonym words: weight ``weight_synonym`` (default 2)
- typical collocation forms: weight ``weight_collocation`` (default 2)

The target **word form** (and the lemma, and their stems) are excluded from
scoring: they appear in many candidates' collocations and would otherwise act as
evidence for a sense that merely happens to own the surface form (the "boksu"
false positive found by the v2 designed set). Ties break by dictionary sense
order, then by sense id, so the ranking is deterministic.

`build_context` renders the top candidates as context blocks through the SAME
``SenseChunk.block`` code path as variant C, so the only difference between C and
D is the ORDER of candidates (plus the logged scores).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from elexai.eval.metrics import normalize_text
from elexai.retrieval.chunks import SenseChunk
from elexai.text import stem

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
    synset_literals: list[str] = field(default_factory=list)  # words of linked synsets
    hypernym_glosses: list[str] = field(default_factory=list)  # glosses of hypernyms


@dataclass
class RankedSense:
    sense: GraphSense
    score: float
    matched_definition: list[str] = field(default_factory=list)
    matched_synonyms: list[str] = field(default_factory=list)
    matched_collocations: list[str] = field(default_factory=list)
    matched_synset_literals: list[str] = field(default_factory=list)
    matched_hypernym_glosses: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return [t for t in normalize_text(text).split() if t and t not in STOPWORDS]


def _target_forms(target_lemma: str, target_word: str) -> set[str]:
    """All surface/stem forms of the target that must never count as evidence."""
    forms: set[str] = set()
    for text in (target_lemma, target_word):
        for token in _tokens(text):
            forms.add(token)
            forms.add(stem(token))
    return forms


def rank_candidates(
    sentence: str,
    target_lemma: str,
    candidates: list[GraphSense],
    *,
    target_word: str,
    weight_definition: float = 1.0,
    weight_collocation: float = 2.0,
    weight_synonym: float = 2.0,
    weight_synset_literal: float = 2.0,
    weight_hypernym_gloss: float = 1.0,
) -> list[RankedSense]:
    """Rank the lemma's candidate senses by (IDF-weighted) neighborhood match.

    Two correctness rules, both found by the v2 designed set:

    - ``target_word`` is the surface form as it appears in the sentence (e.g.
      ``boksu`` for lemma ``boks``); it, the lemma, and their stems are excluded
      from the sentence tokens. Without this, a sense that merely owns the
      target's surface form in its collocation list collects fake evidence.
    - matches are compared on **stems**, not exact tokens (garažni/garažnem,
      dišavne/dišavnih), and each matched stem is weighted by its **inverse
      document frequency across the candidate senses**: a word that appears in
      many senses' neighbourhoods (vplivalo, potek) carries little signal, a
      word that appears in one (temperature, antigen, garažni) carries a lot.
      Without the IDF weight, stemming alone lets generic words outvote the
      real cue (the v2-034 regression).
    """
    target = normalize_text(target_lemma)
    excluded = _target_forms(target_lemma, target_word)

    def token_map(text: str) -> dict[str, str]:
        """stem -> surface form, dropping stopwords and the target's own forms."""
        return {
            stem(t): t
            for t in _tokens(text)
            if t != target and stem(t) not in excluded
        }

    def matched(left: dict[str, str], right: dict[str, str]) -> list[str]:
        return sorted(left[s] for s in left.keys() & right.keys())

    sentence_tokens = token_map(sentence)
    maps_per_sense = [
        {
            "definition": token_map(f"{sense.indicator} {sense.definition}"),
            "synonym": token_map(" ".join(lemma for _, lemma in sense.synonyms)),
            "collocation": token_map(" ".join(sense.collocations)),
            "synset": token_map(" ".join(sense.synset_literals)),
            "hypernym": token_map(" ".join(sense.hypernym_glosses)),
        }
        for sense in candidates
    ]

    document_frequency: Counter[str] = Counter()
    for maps in maps_per_sense:
        for token in set().union(*maps.values()):
            document_frequency[token] += 1
    total = max(1, len(candidates))
    idf = {
        token: math.log((total + 1) / (df + 1)) + 1.0
        for token, df in document_frequency.items()
    }

    def weighted(tokens: dict[str, str], matches: list[str]) -> float:
        by_surface = {surface: stem(surface) for surface in matches}
        return sum(idf.get(by_surface[surface], 1.0) for surface in matches)

    ranked: list[RankedSense] = []
    for sense, maps in zip(candidates, maps_per_sense, strict=True):
        matched_def = matched(sentence_tokens, maps["definition"])
        matched_syn = matched(sentence_tokens, maps["synonym"])
        matched_coll = matched(sentence_tokens, maps["collocation"])
        matched_synset = matched(sentence_tokens, maps["synset"])
        matched_hypernym = matched(sentence_tokens, maps["hypernym"])
        score = (
            weight_definition * weighted(sentence_tokens, matched_def)
            + weight_synonym * weighted(sentence_tokens, matched_syn)
            + weight_collocation * weighted(sentence_tokens, matched_coll)
            + weight_synset_literal * weighted(sentence_tokens, matched_synset)
            + weight_hypernym_gloss * weighted(sentence_tokens, matched_hypernym)
        )
        ranked.append(
            RankedSense(
                sense=sense,
                score=round(score, 4),
                matched_definition=matched_def,
                matched_synonyms=matched_syn,
                matched_collocations=matched_coll,
                matched_synset_literals=matched_synset,
                matched_hypernym_glosses=matched_hypernym,
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
    target_word: str,
    max_candidates: int = 12,
    synonyms_shown: int = 5,
    collocations_shown: int = 8,
    weight_definition: float = 1.0,
    weight_collocation: float = 2.0,
    weight_synonym: float = 2.0,
    weight_synset_literal: float = 2.0,
    weight_hypernym_gloss: float = 1.0,
) -> tuple[str, list[str], list[dict]]:
    """Return (context text, shown sense ids, score log for all candidates)."""
    ranked = rank_candidates(
        sentence,
        target_lemma,
        candidates,
        target_word=target_word,
        weight_definition=weight_definition,
        weight_collocation=weight_collocation,
        weight_synonym=weight_synonym,
        weight_synset_literal=weight_synset_literal,
        weight_hypernym_gloss=weight_hypernym_gloss,
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
            "matched_synset_literals": r.matched_synset_literals[:5],
            "matched_hypernym_glosses": r.matched_hypernym_glosses[:5],
        }
        for r in ranked
    ]
    return text, shown_ids, scores


def build_relation_context(
    sentence: str,
    target_lemma: str,
    candidates: list[GraphSense],
    evidence: dict[str, str],
    *,
    target_word: str,
    max_candidates: int = 12,
    synonyms_shown: int = 5,
    collocations_shown: int = 8,
    gold_sense_id: str | None = None,
    weight_definition: float = 1.0,
    weight_collocation: float = 2.0,
    weight_synonym: float = 2.0,
    weight_synset_literal: float = 2.0,
    weight_hypernym_gloss: float = 1.0,
) -> tuple[str, list[str], list[dict]]:
    """Relation-question context: the same blocks as variant C, plus an explicit
    graph evidence line ("Graf: ...") for every shown candidate that stands in
    the asked relation to the given sense.

    Candidates WITH graph evidence are ranked first (the edge is the retrieval
    signal), then by the lexical score, then by dictionary order. With
    ``gold_sense_id`` set, only the gold sense + nearest siblings of the same
    lemma are shown (oracle semantics); otherwise candidates are ranked like in
    variant D.
    """
    if gold_sense_id is not None:
        ordered = sorted(
            candidates,
            key=lambda s: (
                s.position if s.position is not None else 10**9,
                int(s.sense_id),
            ),
        )
        gold = [s for s in ordered if s.sense_id == gold_sense_id]
        others = [s for s in ordered if s.sense_id != gold_sense_id]
        selected = (gold + others)[:max_candidates]
        selected.sort(
            key=lambda s: (
                s.position if s.position is not None else 10**9,
                int(s.sense_id),
            )
        )
        ranked = [RankedSense(sense=s, score=0.0) for s in selected]
    else:
        ranked = rank_candidates(
            sentence,
            target_lemma,
            candidates,
            target_word=target_word,
            weight_definition=weight_definition,
            weight_collocation=weight_collocation,
            weight_synonym=weight_synonym,
            weight_synset_literal=weight_synset_literal,
            weight_hypernym_gloss=weight_hypernym_gloss,
        )
        # evidence-bearing candidates first; stable sort keeps the lexical
        # score order within both groups
        ranked.sort(key=lambda r: 0 if r.sense.sense_id in evidence else 1)
        ranked = ranked[:max_candidates]

    blocks: list[str] = []
    for r in ranked:
        block = to_chunk(r).block(
            with_relations=True,
            max_synonyms=synonyms_shown,
            max_dependencies=collocations_shown,
        )
        evidence_line = evidence.get(r.sense.sense_id)
        if evidence_line:
            block = f"{block}\n{evidence_line}"
        blocks.append(block)

    text = "\n\n".join(blocks) if blocks else "(Ni na voljo.)"
    shown_ids = [r.sense.sense_id for r in ranked]
    scores = [{"sense_id": r.sense.sense_id, "score": r.score} for r in ranked]
    return text, shown_ids, scores
