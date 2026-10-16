"""Exact (non-ANN) vector retrieval for variant B; the embedder is pluggable.

- embedder comes from the experiment config (`EmbedderConfig`: HF id + pinned
  revision + optional query/passage prefixes), so switching or comparing
  embedders is a config change, never a code change;
- the index is a FAISS `IndexFlatIP` (exact search, no approximation) over
  L2-normalized embeddings (cosine similarity);
- index artifacts live under ``data/processed/index/<slug>/`` with a meta file
  recording embedder id/revision, dimension, chunk count and source hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import numpy as np

from elexai.config import EmbedderConfig
from elexai.retrieval.chunks import SenseChunk


class Embedder(Protocol):
    def encode(self, texts: Sequence[str], batch_size: int, normalize: bool) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Thin wrapper around sentence-transformers (imported lazily)."""

    def __init__(self, cfg: EmbedderConfig):
        from sentence_transformers import SentenceTransformer  # lazy: heavy import

        self.cfg = cfg
        self.model = SentenceTransformer(cfg.hf_id, revision=cfg.revision)

    def encode(self, texts: Sequence[str], batch_size: int, normalize: bool) -> np.ndarray:
        embeddings = self.model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=normalize,
            show_progress_bar=len(texts) > 1000,
        )
        return np.asarray(embeddings, dtype=np.float32)


def get_embedder(cfg: EmbedderConfig) -> Embedder:
    return SentenceTransformerEmbedder(cfg)


def index_slug(cfg: EmbedderConfig) -> str:
    revision = cfg.revision[:12] if cfg.revision else "unknown"
    return f"{cfg.name}@{revision}"


def _sha256_text_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_index(
    chunks: list[SenseChunk],
    embedder: Embedder,
    cfg: EmbedderConfig,
    out_dir: Path,
    source_path: Path,
    limit: int | None = None,
) -> dict:
    """Build and persist the exact search index. Returns the meta dict."""
    import faiss

    if limit is not None:
        chunks = chunks[:limit]
    texts = [cfg.passage_prefix + c.embed_text() for c in chunks]
    embeddings = embedder.encode(texts, cfg.batch_size, cfg.normalize)

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_dir / "index.faiss"))
    (out_dir / "ids.json").write_text(
        json.dumps([c.sense_id for c in chunks], ensure_ascii=False), encoding="utf-8"
    )
    meta = {
        "embedder_name": cfg.name,
        "hf_id": cfg.hf_id,
        "revision": cfg.revision,
        "dim": int(embeddings.shape[1]),
        "n_chunks": len(chunks),
        "normalized": cfg.normalize,
        "passage_prefix": cfg.passage_prefix,
        "query_prefix": cfg.query_prefix,
        "source": str(source_path),
        "source_sha256": _sha256_text_file(source_path),
        "built_at": datetime.now(UTC).isoformat(),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return meta


class VectorRetriever:
    """Exact top-k search over the built index (deterministic)."""

    def __init__(self, index, ids: list[str], embedder: Embedder, cfg: EmbedderConfig):
        self.index = index
        self.ids = ids
        self.embedder = embedder
        self.cfg = cfg

    @classmethod
    def load(cls, index_dir: Path, embedder: Embedder, cfg: EmbedderConfig) -> VectorRetriever:
        import faiss

        index_dir = Path(index_dir)
        index = faiss.read_index(str(index_dir / "index.faiss"))
        ids = json.loads((index_dir / "ids.json").read_text(encoding="utf-8"))
        return cls(index, ids, embedder, cfg)

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        query_vec = self.embedder.encode([self.cfg.query_prefix + query], 1, self.cfg.normalize)
        scores, idx = self.index.search(query_vec, top_k)
        out: list[tuple[str, float]] = []
        for score, i in zip(scores[0], idx[0], strict=True):
            if i >= 0:
                out.append((self.ids[int(i)], float(score)))
        return out
