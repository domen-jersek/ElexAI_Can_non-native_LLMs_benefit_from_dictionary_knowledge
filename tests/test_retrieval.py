"""Tests for chunks, structured retrieval and the exact vector index."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from elexai.config import EmbedderConfig
from elexai.retrieval.chunks import SenseChunk, load_chunks
from elexai.retrieval.structured import StructuredRetriever


def make_chunk(sid: str, lemma: str, position: int, definition: str, **kw) -> SenseChunk:
    return SenseChunk(
        sense_id=sid, lemma=lemma, pos="noun", position=position, definition=definition, **kw
    )


def test_block_formatting():
    chunk = make_chunk(
        "1", "kos", 1, "del celote",
        synonyms=(("2", "mali"),), dependencies=(("3", "kos kruha"),),
    )
    plain = chunk.block()
    assert "Sopomenke" not in plain and "Zveze" not in plain
    assert "ID: 1" in plain
    rel = chunk.block(with_relations=True)
    assert "Sopomenke: mali" in rel
    assert "Zveze: kos kruha" in rel


def test_load_chunks_roundtrip(tmp_path):
    record = {
        "sense_id": 42,
        "position": 1,
        "lemma": "kos",
        "pos": "noun",
        "lu_type": "single_lexeme_unit",
        "definitions": [
            {"type": "indicator", "text": "del celote"},
            {"type": "general", "text": "del snovi, navadno locen od vecje celote"},
        ],
        "synonyms": [[7, "frtalja"]],
        "antonyms": [],
        "hypernyms": [],
        "hyponyms": [],
        "dependencies": [[9, "kos kruha"]],
        "example_count": 5,
    }
    path = tmp_path / "core.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    chunks = load_chunks(path)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.sense_id == "42"
    assert c.definition == "del celote | del snovi, navadno locen od vecje celote"
    assert c.synonyms == (("7", "frtalja"),)
    assert c.dependencies == (("9", "kos kruha"),)
    assert c.example_count == 5


def test_structured_retriever_context_and_oracle():
    chunks = [
        make_chunk("10", "kos", 1, "del celote"),
        make_chunk("11", "kos", 2, "ptica"),
        make_chunk("12", "kos", 3, "sposoben"),
        make_chunk("20", "list", 1, "del rastline"),
    ]
    sr = StructuredRetriever(chunks, max_senses=2, oracle_max_candidates=2)

    ctx = sr.context_for("kos")
    assert ctx.shown_sense_ids == ["10", "11"]  # capped, in position order
    assert "ID: 10" in ctx.text

    oracle = sr.oracle_context("kos", gold_sense_id="12")
    assert oracle.gold_present is True
    assert "12" in oracle.shown_sense_ids
    assert len(oracle.shown_sense_ids) <= 2

    missing = sr.oracle_context("kos", gold_sense_id="999")
    assert missing.gold_present is False

    none = sr.context_for("nope")
    assert none.shown_sense_ids == []
    assert "(Ni na voljo.)" in none.text


class FakeEmbedder:
    """Deterministic pseudo-embeddings: same text -> same vector."""

    def encode(self, texts, batch_size, normalize):  # noqa: ANN001
        vectors = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            vec = rng.normal(size=8).astype("float32")
            if normalize:
                vec /= np.linalg.norm(vec)
            vectors.append(vec)
        return np.vstack(vectors)


def test_vector_index_roundtrip(tmp_path):
    pytest.importorskip("faiss")
    from elexai.retrieval.vector import VectorRetriever, build_index

    chunks = [
        make_chunk("1", "kos", 1, "del celote"),
        make_chunk("2", "kos", 2, "ptica pevka"),
        make_chunk("3", "list", 1, "del rastline"),
    ]
    source = tmp_path / "core.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    cfg = EmbedderConfig(name="fake", hf_id="fake", revision="deadbeef0000")
    out = tmp_path / "idx"
    meta = build_index(chunks, FakeEmbedder(), cfg, out, source)
    assert meta["n_chunks"] == 3 and meta["dim"] == 8

    retriever = VectorRetriever.load(out, FakeEmbedder(), cfg)
    results = retriever.search(chunks[1].embed_text(), top_k=2)
    assert results[0][0] == "2"  # exact match ranks first
    assert len(results) == 2
