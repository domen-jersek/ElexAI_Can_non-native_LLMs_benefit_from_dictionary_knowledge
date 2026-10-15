"""Source adapter interface.

A *source adapter* turns one lexicographic dataset (the DDDS PostgreSQL
snapshot, a WordNet XML file, ...) into a stream of normalized sense records.
Consumers (chunker for text RAG, Neo4j graph loader, question builder) are
written against this interface only, so that adding or replacing a dictionary
source never requires touching retrieval or evaluation code.

The interface is intentionally thin for Phase 0; it will grow as the first
real consumers appear (Phases 1-3), but existing adapters must keep working.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SenseRecord:
    """One dictionary sense, normalized across sources.

    Identifiers:
      sense_id   -- primary citation id. For DDDS this is ``jedro_sense.id``
                    (the id that gold answers and citations use in this pilot).
      synset_id  -- WordNet synset id when the source has one (e.g. OSWN
                    ``oswn-00001740-a``), else ``None``.
    """

    sense_id: str
    lemma: str
    pos: str | None = None
    definition: str | None = None
    examples: list[str] = field(default_factory=list)
    synset_id: str | None = None
    source_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(ABC):
    """Read-only access to one lexicographic source."""

    source_id: str = "abstract"

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Return a human-readable summary (counts, fields, license, path)."""

    @abstractmethod
    def iter_senses(self) -> Iterator[SenseRecord]:
        """Yield normalized records. Iteration order must be deterministic."""
