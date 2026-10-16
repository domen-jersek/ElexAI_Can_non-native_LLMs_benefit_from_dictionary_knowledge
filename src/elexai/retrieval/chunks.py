"""Sense chunks: the retrieval unit shared by variants B, C and oracle.

One chunk per DDDS sense that has at least one definition, built from
``data/processed/ddds/lexical_core.jsonl`` (see scripts/export_lexical_core.py).
Every chunk carries the DDDS sense id that gold answers and citations use, so
all variants speak the same id space and citations are comparable.

- variant B embeds ``embed_text()`` (lemma, pos, definition - no ids);
- the prompt block always includes the id, so the model can cite it;
- variant C additionally shows ``Sopomenke`` (synonyms) and ``Zveze``
  (typical collocations from DDDS dependency relations).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SenseChunk:
    sense_id: str
    lemma: str
    pos: str | None
    position: int | None
    definition: str
    synonyms: tuple[tuple[str, str], ...] = ()
    antonyms: tuple[tuple[str, str], ...] = ()
    hypernyms: tuple[tuple[str, str], ...] = ()
    dependencies: tuple[tuple[str, str], ...] = ()
    example_count: int = 0

    def embed_text(self) -> str:
        pos = f" ({self.pos})" if self.pos else ""
        return f"{self.lemma}{pos}: {self.definition}"

    def block(
        self,
        with_relations: bool = False,
        max_synonyms: int = 5,
        max_dependencies: int = 8,
    ) -> str:
        lines = [
            f"ID: {self.sense_id}",
            f"Beseda: {self.lemma}" + (f" ({self.pos})" if self.pos else ""),
            f"Definicija: {self.definition}",
        ]
        if with_relations:
            if self.synonyms:
                names = ", ".join(lemma for _, lemma in self.synonyms[:max_synonyms])
                lines.append(f"Sopomenke: {names}")
            if self.dependencies:
                forms = ", ".join(form for _, form in self.dependencies[:max_dependencies])
                lines.append(f"Zveze: {forms}")
        return "\n".join(lines)


def _chunk_from_record(rec: dict) -> SenseChunk:
    def pairs(key: str) -> tuple[tuple[str, str], ...]:
        return tuple((str(a), str(b)) for a, b in rec.get(key, []))

    parts = [d["text"] for d in rec.get("definitions", []) if d.get("text")]
    return SenseChunk(
        sense_id=str(rec["sense_id"]),
        lemma=rec["lemma"],
        pos=rec.get("pos"),
        position=rec.get("position"),
        definition=" | ".join(parts),
        synonyms=pairs("synonyms"),
        antonyms=pairs("antonyms"),
        hypernyms=pairs("hypernyms"),
        dependencies=pairs("dependencies"),
        example_count=int(rec.get("example_count") or 0),
    )


def iter_chunks(path: str | Path) -> Iterator[SenseChunk]:
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield _chunk_from_record(json.loads(line))


def load_chunks(path: str | Path) -> list[SenseChunk]:
    """All chunks, ordered deterministically by numeric sense id."""
    chunks = list(iter_chunks(path))
    chunks.sort(key=lambda c: int(c.sense_id))
    return chunks
