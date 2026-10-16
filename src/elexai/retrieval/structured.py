"""Structured (dictionary-native) retrieval for variants C and oracle.

Implemented over the ``lexical_core`` export - no Neo4j dependency. The
interface deliberately mirrors "graph retrieval" (entity linking by lemma ->
senses -> one-hop relation expansion), so a Neo4j-backed implementation can be
plugged in later without touching the runner (see docs/DECISIONS.md D-013).

- variant C: all senses of the target lemma (up to ``max_senses``, in the
  dictionary's sense order) with their synonyms and typical collocations
  ("Zveze") - the structured-data view;
- oracle: the gold sense plus nearest sibling senses of the same lemma, so the
  model never has to *find* the right sense, only to *choose/compose* the
  answer - failures under oracle are composition errors by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from elexai.retrieval.chunks import SenseChunk

_MISSING = "(Ni na voljo.)"


@dataclass
class StructuredContext:
    text: str
    shown_sense_ids: list[str]
    gold_present: bool


def _order_key(chunk: SenseChunk) -> tuple:
    pos = chunk.position if chunk.position is not None else 10**9
    return (pos, int(chunk.sense_id))


class StructuredRetriever:
    def __init__(
        self,
        chunks: list[SenseChunk],
        *,
        max_senses: int = 12,
        synonyms_per_sense: int = 5,
        max_dependencies: int = 8,
        oracle_max_candidates: int = 5,
    ):
        self.max_senses = max_senses
        self.synonyms_per_sense = synonyms_per_sense
        self.max_dependencies = max_dependencies
        self.oracle_max_candidates = oracle_max_candidates
        self.by_lemma: dict[str, list[SenseChunk]] = {}
        for chunk in chunks:
            self.by_lemma.setdefault(chunk.lemma, []).append(chunk)
        for senses in self.by_lemma.values():
            senses.sort(key=_order_key)

    def senses_of_lemma(self, lemma: str) -> list[SenseChunk]:
        return self.by_lemma.get(lemma, [])

    def context_for(self, lemma: str) -> StructuredContext:
        """Variant C: exact lemma lookup + relation expansion."""
        senses = self.senses_of_lemma(lemma)[: self.max_senses]
        if not senses:
            return StructuredContext(text=_MISSING, shown_sense_ids=[], gold_present=False)
        blocks = [
            c.block(
                with_relations=True,
                max_synonyms=self.synonyms_per_sense,
                max_dependencies=self.max_dependencies,
            )
            for c in senses
        ]
        return StructuredContext(
            text="\n\n".join(blocks),
            shown_sense_ids=[c.sense_id for c in senses],
            gold_present=False,  # filled by the caller against the gold id
        )

    def oracle_context(self, lemma: str, gold_sense_id: str) -> StructuredContext:
        """Oracle: gold sense + nearest siblings of the same lemma."""
        senses = self.senses_of_lemma(lemma)
        gold = [c for c in senses if c.sense_id == gold_sense_id]
        others = [c for c in senses if c.sense_id != gold_sense_id]
        selected = (gold + others)[: self.oracle_max_candidates]
        selected.sort(key=_order_key)
        if not selected:
            return StructuredContext(text=_MISSING, shown_sense_ids=[], gold_present=False)
        blocks = [c.block(with_relations=False) for c in selected]
        return StructuredContext(
            text="\n\n".join(blocks),
            shown_sense_ids=[c.sense_id for c in selected],
            gold_present=bool(gold),
        )
