"""Experiment runner: generate answers for every variant of one config.

    uv run python -m elexai.runner configs/skeleton.yaml [--dry-run] [--limit N]

For each (question, variant) pair it builds the variant's context (A: none;
B: exact vector search over sense chunks; C: structured lemma lookup with
synonyms; oracle: gold sense + neighbours), renders the single shared prompt
template, calls the LLM (or the deterministic stub in ``--dry-run``) and
appends one JSONL record with the full prompt, retrieved context, raw output,
parsed fields, latency and cache flag to ``runs/<run_id>/answers.jsonl``.

Run directory artifacts: ``config.resolved.yaml``, ``manifest.json``,
``answers.jsonl``, ``logs.txt``. Evaluation is a separate step
(``scripts/evaluate.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from elexai import __version__
from elexai.config import ExperimentConfig, load_config
from elexai.env import load_env
from elexai.graph.retriever import GraphRetriever
from elexai.llm.cache import ResponseCache
from elexai.llm.client import LlmClient, LlmError, StubLlmClient
from elexai.llm.prompts import TEMPLATE_VERSION, render
from elexai.questions import Question, load_questions, load_senses_export, validate_questions
from elexai.retrieval.chunks import SenseChunk, load_chunks
from elexai.retrieval.structured import StructuredRetriever
from elexai.retrieval.vector import VectorRetriever, get_embedder, index_slug

REPO_ROOT = Path(__file__).resolve().parents[3]
LEXICAL_CORE = REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl"
SENSES_EXPORT = REPO_ROOT / "data" / "processed" / "ddds" / "senses.jsonl"

_SENSE_ID_RE = re.compile(r"SENSE_ID:\s*(\d+|none)", re.IGNORECASE)
_ANSWER_RE = re.compile(r"ODGOVOR:\s*(.*)", re.IGNORECASE | re.DOTALL)


def parse_output(text: str) -> tuple[str | None, str]:
    """Extract (cited sense id or None, answer text) from a model output."""
    m = _SENSE_ID_RE.search(text)
    sense_id = m.group(1) if m and m.group(1).lower() != "none" else None
    a = _ANSWER_RE.search(text)
    answer = a.group(1).strip() if a else ""
    return sense_id, answer


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - manifest best effort
        return "unknown"


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _load_env(root: Path) -> None:
    """Load the repository-root .env into the process environment (no override)."""
    load_env(root)


def resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def build_manifest(
    cfg: ExperimentConfig,
    *,
    root: Path,
    variants: list[str],
    limit: int | None,
    dry_run: bool,
    n_chunks: int,
    index_meta: dict | None,
) -> dict:
    uv_lock = root / "uv.lock"
    data_manifest = root / "data" / "MANIFEST.json"
    questions = resolve_path(root, cfg.questions_path)
    return {
        "run_schema": 1,
        "elexai_version": __version__,
        "template_version": TEMPLATE_VERSION,
        "started_at": datetime.now(UTC).isoformat(),
        "dry_run": dry_run,
        "limit": limit,
        "variants": variants,
        "git_commit": _git(["rev-parse", "HEAD"]),
        "git_dirty": bool(_git(["status", "--porcelain"])),
        "uv_lock_sha256": _sha256_file(uv_lock),
        "data_manifest_sha256": _sha256_file(data_manifest),
        "questions_sha256": _sha256_file(questions),
        "lexical_core_sha256": _sha256_file(LEXICAL_CORE),
        "lexical_core_n_chunks": n_chunks,
        "llm": cfg.llm.model_dump(mode="json"),
        "embedder": cfg.embedder.model_dump(mode="json"),
        "embedder_index": index_meta,
        "retrieval": cfg.retrieval.model_dump(mode="json"),
        "structured": cfg.structured.model_dump(mode="json"),
        "seed": cfg.seed,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }


def _context_for_variant(
    variant: str,
    question: Question,
    *,
    cfg: ExperimentConfig,
    structured: StructuredRetriever,
    vector: VectorRetriever | None,
    graph: GraphRetriever | None,
    chunk_by_id: dict[str, SenseChunk],
) -> tuple[str | None, dict]:
    """Return (context text, record fields) for one variant."""
    if variant == "A":
        return None, {"context_kind": "none", "shown_sense_ids": [], "retrieved": []}
    if variant == "B":
        assert vector is not None
        top_k = max([cfg.retrieval.k, *cfg.retrieval.sweep_k])
        results = vector.search(question.context_sentence, top_k)
        shown = [sid for sid, _ in results[: cfg.retrieval.k]]
        text = "\n\n".join(chunk_by_id[sid].block() for sid in shown)
        return text, {
            "context_kind": "text_rag",
            "shown_sense_ids": shown,
            "retrieved": [{"sense_id": sid, "score": score} for sid, score in results],
        }
    if variant == "C":
        sc = structured.context_for(question.lemma)
        gold_present = question.gold_sense_id in sc.shown_sense_ids
        return sc.text, {
            "context_kind": "structured",
            "shown_sense_ids": sc.shown_sense_ids,
            "retrieved": [],
            "gold_present": gold_present,
        }
    if variant == "oracle":
        sc = structured.oracle_context(question.lemma, question.gold_sense_id)
        return sc.text, {
            "context_kind": "oracle",
            "shown_sense_ids": sc.shown_sense_ids,
            "retrieved": [],
            "gold_present": sc.gold_present,
        }
    if variant == "D":
        assert graph is not None
        gc = graph.context_for(question.lemma, question.context_sentence)
        gold_rank = next(
            (i + 1 for i, s in enumerate(gc.scores) if s["sense_id"] == question.gold_sense_id),
            None,
        )
        return gc.text, {
            "context_kind": "graph",
            "shown_sense_ids": gc.shown_sense_ids,
            "retrieved": [],
            "gold_present": question.gold_sense_id in gc.shown_sense_ids,
            "graph_scores": gc.scores,
            "gold_rank": gold_rank,
        }
    raise ValueError(f"unknown variant {variant!r}")


def run_experiment(
    cfg: ExperimentConfig,
    *,
    root: Path = REPO_ROOT,
    limit: int | None = None,
    dry_run: bool = False,
    variants: list[str] | None = None,
    chunks: list[SenseChunk] | None = None,
    vector: VectorRetriever | None = None,
    llm=None,
) -> Path:
    """Run one experiment; returns the run directory."""
    random.seed(cfg.seed)
    _load_env(root)

    questions_path = resolve_path(root, cfg.questions_path)
    questions = load_questions(questions_path)
    senses = load_senses_export(SENSES_EXPORT) if SENSES_EXPORT.exists() else None
    problems = validate_questions(questions, senses)
    if problems:
        raise SystemExit("question validation failed:\n  " + "\n  ".join(problems))

    variants = variants or list(cfg.variants)
    if limit is not None:
        questions = questions[:limit]
    if chunks is None:
        chunks = load_chunks(LEXICAL_CORE)
    chunk_by_id = {c.sense_id: c for c in chunks}
    structured = StructuredRetriever(
        chunks,
        max_senses=cfg.structured.max_senses,
        synonyms_per_sense=cfg.structured.synonyms_per_sense,
        oracle_max_candidates=cfg.structured.oracle_max_candidates,
    )

    index_meta: dict | None = None
    if "B" in variants and vector is None:
        index_dir = resolve_path(root, cfg.index_dir) / index_slug(cfg.embedder)
        if not (index_dir / "index.faiss").exists():
            raise SystemExit(
                f"variant B needs a vector index at {index_dir}.\n"
                f"Build it first with:  uv run python scripts/build_index.py --config <config>"
            )
        embedder = get_embedder(cfg.embedder)
        vector = VectorRetriever.load(index_dir, embedder, cfg.embedder)
        meta_path = index_dir / "meta.json"
        if meta_path.exists():
            index_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    graph_retriever: GraphRetriever | None = None
    if "D" in variants:
        try:
            graph_retriever = GraphRetriever.from_env(cfg.graph)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"variant D needs the Neo4j graph to be running and loaded:\n  {exc}\n"
                f"  1) start the database in Neo4j Desktop\n"
                f"  2) load it once:  uv run python scripts/load_graph.py\n"
                f"  3) check NEO4J_USER/NEO4J_PASSWORD (and optionally NEO4J_URI) in .env"
            ) from exc

    if llm is None:
        if dry_run:
            llm = StubLlmClient(cfg.llm)
        else:
            llm = LlmClient(cfg.llm, ResponseCache(resolve_path(root, cfg.cache_dir)))

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = resolve_path(root, cfg.runs_dir) / f"{stamp}_{cfg.name}"
    run_dir.mkdir(parents=True, exist_ok=False)

    (run_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    manifest = build_manifest(
        cfg,
        root=root,
        variants=variants,
        limit=limit,
        dry_run=dry_run,
        n_chunks=len(chunks),
        index_meta=index_meta,
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    log_lines = [f"run_dir={run_dir}", f"variants={variants}", f"questions={len(questions)}"]
    total_calls = len(variants) * len(questions)
    done = 0
    errors = 0
    cache_hits = 0
    with (run_dir / "answers.jsonl").open("w", encoding="utf-8", newline="\n") as answers:
        for variant in variants:
            for question in questions:
                context, fields = _context_for_variant(
                    variant,
                    question,
                    cfg=cfg,
                    structured=structured,
                    vector=vector,
                    graph=graph_retriever,
                    chunk_by_id=chunk_by_id,
                )
                prompt = render(question, context)
                record: dict = {
                    "run_id": run_dir.name,
                    "variant": variant,
                    "question_id": question.id,
                    "question_type": question.question_type,
                    "lemma": question.lemma,
                    "target_word": question.target_word,
                    "gold_sense_id": question.gold_sense_id,
                    "prompt": prompt,
                    "template_version": TEMPLATE_VERSION,
                    "timestamp": datetime.now(UTC).isoformat(),
                    **fields,
                }
                try:
                    result = llm.complete(prompt)
                    cited, answer = parse_output(result.text)
                    record.update(
                        {
                            "output_raw": result.text,
                            "parsed_sense_id": cited,
                            "parsed_answer": answer,
                            "latency_ms": round(result.latency_ms, 1),
                            "cache_hit": result.cache_hit,
                            "model": result.model,
                            "error": None,
                        }
                    )
                    if result.cache_hit:
                        cache_hits += 1
                except LlmError as exc:
                    errors += 1
                    record.update(
                        {
                            "output_raw": None,
                            "parsed_sense_id": None,
                            "parsed_answer": None,
                            "latency_ms": None,
                            "cache_hit": False,
                            "model": cfg.llm.model,
                            "error": str(exc),
                        }
                    )
                    answers.write(json.dumps(record, ensure_ascii=False) + "\n")
                    answers.flush()
                    log_lines.append(f"ERROR {variant} {question.id}: {exc}")
                    (run_dir / "logs.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
                    raise SystemExit(
                        f"LLM call failed ({exc}).\n"
                        f"Partial results are in {run_dir}; check your API key and re-run."
                    ) from exc
                answers.write(json.dumps(record, ensure_ascii=False) + "\n")
                done += 1
                if done % 10 == 0 or done == total_calls:
                    answers.flush()
                    print(f"  [{done}/{total_calls}] variants={variants}", flush=True)

    if graph_retriever is not None:
        graph_retriever.close()

    log_lines.append(f"done={done} errors={errors} cache_hits={cache_hits}")
    (run_dir / "logs.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"answers written to {run_dir / 'answers.jsonl'}")
    print(f"next: uv run python scripts/evaluate.py --run {run_dir.name}")
    return run_dir


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config", type=Path, help="experiment YAML (e.g. configs/skeleton.yaml)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N questions (dev)")
    ap.add_argument("--dry-run", action="store_true", help="use the deterministic stub LLM")
    ap.add_argument("--variants", nargs="*", default=None, help="override variants (A B C oracle)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    run_dir = run_experiment(
        cfg, limit=args.limit, dry_run=args.dry_run, variants=args.variants
    )
    print(f"run complete: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
