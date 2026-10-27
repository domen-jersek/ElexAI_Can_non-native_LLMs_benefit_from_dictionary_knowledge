"""Notebook-facing analysis helpers for the pilot runs (read-only).

The notebooks under ``notebooks/`` use this module to load run artifacts
(``runs/<run_id>/``) into pandas tables and to draw consistent, classic
scientific figures (light theme, fixed per-variant colours).

Everything here is derived data: nothing writes into ``runs/`` and no LLM
calls are made. Paths resolve relative to the repository root, so notebooks
can be executed from any working directory.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from elexai.questions import load_questions

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
FIGURES_DIR = REPO_ROOT / "notebooks" / "figures"
QUESTIONS_PATH = REPO_ROOT / "data" / "questions" / "questions.jsonl"
SENSES_EXPORT = REPO_ROOT / "data" / "processed" / "ddds" / "senses.jsonl"
LEXICAL_CORE = REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl"

VARIANT_ORDER = ["A", "B", "C", "D", "oracle"]
VARIANT_COLORS = {
    "A": "#7f7f7f",  # grey
    "B": "#1f77b4",  # blue
    "C": "#2ca02c",  # green
    "D": "#ff7f0e",  # orange
    "oracle": "#9467bd",  # purple
}
VARIANT_LABELS = {
    "A": "A - base LLM",
    "B": "B - text RAG",
    "C": "C - dictionary list",
    "D": "D - graph-ranked",
    "oracle": "oracle - ceiling",
}

CITATION_VARIANTS = ["B", "C", "D", "oracle"]


def scientific_style() -> None:
    """Classic light scientific matplotlib style used by all notebooks."""
    matplotlib.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#444444",
            "axes.grid": True,
            "grid.color": "#dddddd",
            "grid.linewidth": 0.6,
            "axes.axisbelow": True,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "legend.frameon": False,
            "font.size": 10,
            "figure.dpi": 110,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        }
    )


def save_figure(fig: plt.Figure, name: str) -> Path:
    """Save a figure to notebooks/figures/<name>.png and return the path."""
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / f"{name}.png"
    fig.savefig(path)
    return path


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# run discovery
# ---------------------------------------------------------------------------


def find_runs(runs_dir: Path = RUNS_DIR) -> pd.DataFrame:
    """All runs that have a resolved config and answers, oldest first."""
    rows: list[dict] = []
    for run_dir in sorted(runs_dir.glob("*")):
        cfg_path = run_dir / "config.resolved.yaml"
        answers_path = run_dir / "answers.jsonl"
        if not (run_dir.is_dir() and cfg_path.exists() and answers_path.exists()):
            continue
        cfg = _read_yaml(cfg_path)
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        metrics_path = run_dir / "metrics.json"
        n_questions = None
        if metrics_path.exists():
            n_questions = json.loads(metrics_path.read_text(encoding="utf-8")).get("n_questions")
        rows.append(
            {
                "run_id": run_dir.name,
                "config": cfg.get("name", "?"),
                "cap": int(cfg.get("structured", {}).get("max_senses", 0)),
                "n_questions": n_questions,
                "variants": ",".join(cfg.get("variants", [])),
                "dry_run": bool(manifest.get("dry_run", False)),
                "started_at": manifest.get("started_at", ""),
            }
        )
    return pd.DataFrame(rows)


def find_run(config: str, runs_dir: Path = RUNS_DIR) -> str:
    """Latest non-dry-run run id for a config name (e.g. "cap3")."""
    df = find_runs(runs_dir)
    df = df[(df["config"] == config) & (~df["dry_run"])]
    if df.empty:
        raise KeyError(f"no (non-dry-run) run found for config {config!r}")
    return str(df["run_id"].iloc[-1])


def find_run_with_questions(config: str, n_questions: int, runs_dir: Path = RUNS_DIR) -> str:
    """Latest non-dry-run run of a config with an exact question count."""
    df = find_runs(runs_dir)
    df = df[
        (df["config"] == config) & (~df["dry_run"]) & (df["n_questions"] == n_questions)
    ]
    if df.empty:
        raise KeyError(f"no run found for config {config!r} with {n_questions} questions")
    return str(df["run_id"].iloc[-1])


# ---------------------------------------------------------------------------
# questions and senses
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def load_questions_table(path: Path = QUESTIONS_PATH) -> pd.DataFrame:
    """The committed question set as a table."""
    questions = load_questions(path)
    return pd.DataFrame(
        [
            {
                "question_id": q.id,
                "question_type": q.question_type,
                "flags": q.flags,
                "is_trick": "trick" in q.flags,
                "lemma": q.lemma,
                "target_word": q.target_word,
                "pos": q.pos,
                "gold_sense_id": q.gold_sense_id,
                "gold_answer": q.gold_answer,
                "relation": q.relation,
                "related_sense_id": q.related_sense_id or None,
                "question": q.question,
                "context_sentence": q.context_sentence,
            }
            for q in questions
        ]
    )


@lru_cache(maxsize=4)
def load_senses_table(path: Path = LEXICAL_CORE) -> pd.DataFrame:
    """Definition-bearing senses (id, lemma, pos, dictionary position, definition)."""
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            rows.append(
                {
                    "sense_id": str(rec["sense_id"]),
                    "lemma": rec["lemma"],
                    "pos": rec.get("pos"),
                    "position": rec.get("position"),
                    "definition": " | ".join(
                        d["text"] for d in rec.get("definitions", []) if d.get("text")
                    ),
                }
            )
    df = pd.DataFrame(rows)
    df["n_senses_lemma"] = df.groupby("lemma")["sense_id"].transform("count")
    return df


@lru_cache(maxsize=4)
def _sense_lemma_map(path: Path = SENSES_EXPORT) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not path.exists():
        return mapping
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                mapping[str(rec["sense_id"])] = rec.get("lemma", "")
    return mapping


# ---------------------------------------------------------------------------
# run answers and metrics
# ---------------------------------------------------------------------------


def load_answers(
    run_id: str,
    runs_dir: Path = RUNS_DIR,
    questions_path: Path = QUESTIONS_PATH,
    senses_path: Path = SENSES_EXPORT,
) -> pd.DataFrame:
    """One tidy row per (variant, question) with citation category and orders.

    Columns include: variant, question_id, question_type, is_trick, lemma,
    gold_sense_id, cited_sense_id, correct, category, gold_rank, gold_present,
    gold_evidence, shown_ids (C order), ranked_ids (D graph order),
    retrieved_ids/scores (B), latency_ms, cache_hit, prompt.
    """
    run_dir = runs_dir / run_id
    raw = [
        json.loads(line)
        for line in (run_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    meta = load_questions_table(questions_path).set_index("question_id")
    senses = _sense_lemma_map(senses_path)

    records: list[dict] = []
    for r in raw:
        qid = r["question_id"]
        m = meta.loc[qid] if qid in meta.index else None
        cited = str(r["parsed_sense_id"]) if r.get("parsed_sense_id") else None
        gold = str(r["gold_sense_id"])
        variant = r["variant"]
        correct: bool | None = None
        category: str | None = None
        if variant in CITATION_VARIANTS:
            correct = cited == gold
            if cited is None:
                category = "none"
            elif cited == gold:
                category = "correct"
            else:
                cited_lemma = senses.get(cited)
                if senses and cited_lemma is None:
                    category = "wrong_unknown_id"
                elif m is not None and cited_lemma and cited_lemma.lower() == str(m["lemma"]).lower():
                    category = "wrong_same_lemma"
                elif senses:
                    category = "wrong_other_lemma"
                else:
                    category = "wrong_unclassified"
        records.append(
            {
                "run_id": run_id,
                "variant": variant,
                "question_id": qid,
                "question_type": m["question_type"] if m is not None else r.get("question_type"),
                "is_trick": bool(m["is_trick"]) if m is not None else False,
                "lemma": r.get("lemma"),
                "gold_sense_id": gold,
                "gold_answer": m["gold_answer"] if m is not None else None,
                "cited_sense_id": cited,
                "correct": correct,
                "category": category,
                "answer": r.get("parsed_answer"),
                "latency_ms": r.get("latency_ms"),
                "cache_hit": bool(r.get("cache_hit")),
                "error": r.get("error"),
                "gold_rank": r.get("gold_rank"),
                "gold_present": r.get("gold_present"),
                "gold_evidence": r.get("gold_evidence"),
                "evidence_sense_ids": r.get("evidence_sense_ids"),
                "shown_ids": r.get("shown_sense_ids"),
                "ranked_ids": [str(s["sense_id"]) for s in (r.get("graph_scores") or [])],
                "ranked_features": [
                    {
                        "sense_id": str(s["sense_id"]),
                        "score": s.get("score"),
                        "matched_definition": s.get("matched_definition"),
                        "matched_collocations": s.get("matched_collocations"),
                        "matched_synonyms": s.get("matched_synonyms"),
                        "matched_synset_literals": s.get("matched_synset_literals"),
                        "matched_hypernym_glosses": s.get("matched_hypernym_glosses"),
                    }
                    for s in (r.get("graph_scores") or [])
                ],
                "retrieved_ids": [str(x["sense_id"]) for x in (r.get("retrieved") or [])],
                "retrieved_scores": [float(x["score"]) for x in (r.get("retrieved") or [])],
                "relation": m["relation"] if m is not None else r.get("relation"),
                "related_sense_id": m["related_sense_id"] if m is not None else None,
                "prompt": r.get("prompt"),
            }
        )
    return pd.DataFrame(records)


def load_metrics(run_id: str, runs_dir: Path = RUNS_DIR) -> dict:
    return json.loads((runs_dir / run_id / "metrics.json").read_text(encoding="utf-8"))


def accuracy_frame(run_ids: list[str], runs_dir: Path = RUNS_DIR) -> pd.DataFrame:
    """Per-run, per-variant headline numbers (one row per variant)."""
    rows: list[dict] = []
    for run_id in run_ids:
        cfg = _read_yaml(runs_dir / run_id / "config.resolved.yaml")
        metrics = load_metrics(run_id, runs_dir)
        for variant, m in metrics["variants"].items():
            excl = m.get("excl_trick") or {}
            rows.append(
                {
                    "run_id": run_id,
                    "config": cfg.get("name", "?"),
                    "model": (cfg.get("llm") or {}).get("model"),
                    "cap": int(cfg.get("structured", {}).get("max_senses", 0)),
                    "variant": variant,
                    "n": m.get("n"),
                    "citation_accuracy": m.get("citation_accuracy"),
                    "citation_accuracy_excl_trick": excl.get("citation_accuracy"),
                    "retrieval_errors": m.get("retrieval_errors"),
                    "composition_errors": m.get("composition_errors"),
                    "excl_retrieval_errors": excl.get("retrieval_errors"),
                    "excl_composition_errors": excl.get("composition_errors"),
                    "coverage_at_k": m.get("coverage_at_k"),
                    "gold_rank_mean": m.get("gold_rank_mean"),
                    "mrr": m.get("mrr"),
                    "error_taxonomy": m.get("error_taxonomy"),
                }
            )
    return pd.DataFrame(rows)


def coverage_frame(
    run_ids: list[str],
    variants: tuple[str, ...] = ("C", "D"),
    scope: str = "all",
    runs_dir: Path = RUNS_DIR,
) -> pd.DataFrame:
    """Long table of coverage@k curves (k = 1..max logged) per run and variant.

    ``scope`` is "all" or "excl_trick" (trick questions removed).
    """
    rows: list[dict] = []
    for run_id in run_ids:
        cfg = _read_yaml(runs_dir / run_id / "config.resolved.yaml")
        metrics = load_metrics(run_id, runs_dir)
        for variant in variants:
            entry = metrics["variants"].get(variant) or {}
            if scope == "excl_trick":
                entry = entry.get("excl_trick") or {}
            cov = entry.get("coverage_at_k") or {}
            for k, value in cov.items():
                rows.append(
                    {
                        "run_id": run_id,
                        "config": cfg.get("name", "?"),
                        "cap": int(cfg.get("structured", {}).get("max_senses", 0)),
                        "variant": variant,
                        "k": int(k),
                        "coverage": value,
                    }
                )
    return pd.DataFrame(rows)


def correctness_matrix(
    df: pd.DataFrame,
    variants: tuple[str, ...] = ("B", "C", "D", "oracle"),
    *,
    exclude_trick: bool = True,
) -> pd.DataFrame:
    """Per-question correctness (citation) aligned across variants."""
    d = df[df["variant"].isin(variants)]
    if exclude_trick:
        d = d[~d["is_trick"]]
    return d.pivot_table(
        index="question_id", columns="variant", values="correct", aggfunc="first"
    ).astype(bool)


def payoff_table(
    run_id: str,
    runs_dir: Path = RUNS_DIR,
    questions_path: Path = QUESTIONS_PATH,
    senses_path: Path = SENSES_EXPORT,
) -> pd.DataFrame:
    """Per-question features behind the "when does the graph pay off?" rule.

    For every non-trick question (use the FULL-context run; the ranking is
    logged for all candidates there):

    - ``c_position``: gold position in variant C's dictionary order;
    - ``d_rank``: gold rank in variant D's graph order;
    - ``score``: the gold sense's graph score (weighted token overlap with its
      neighbourhood);
    - ``signal``: did the sentence match ANY part of the sense's structured
      neighbourhood (collocations, synonyms, synset literals, hypernym glosses,
      definition tokens)?

    Candidate-set size (senses of the lemma) can be joined by the notebook from
    its own senses table.
    """
    df = load_answers(run_id, runs_dir=runs_dir, questions_path=questions_path, senses_path=senses_path)
    c = df[df["variant"] == "C"].set_index("question_id")
    d = df[df["variant"] == "D"].set_index("question_id")

    rows: list[dict] = []
    for qid in c.index:
        if bool(c.loc[qid, "is_trick"]):
            continue
        gold = str(c.loc[qid, "gold_sense_id"])
        shown = [str(x) for x in (c.loc[qid, "shown_ids"] or [])]
        c_position = shown.index(gold) + 1 if gold in shown else None
        d_rank = d.loc[qid, "gold_rank"]
        features = {f["sense_id"]: f for f in (d.loc[qid, "ranked_features"] or [])}
        gold_features = features.get(gold, {})
        matched_collocations = gold_features.get("matched_collocations") or []
        signal = bool(
            matched_collocations
            or gold_features.get("matched_synonyms")
            or gold_features.get("matched_synset_literals")
            or gold_features.get("matched_hypernym_glosses")
            or gold_features.get("matched_definition")
        )
        rows.append(
            {
                "question_id": qid,
                "lemma": c.loc[qid, "lemma"],
                "question_type": c.loc[qid, "question_type"],
                "gold_sense_id": gold,
                "c_position": c_position,
                "d_rank": int(d_rank) if pd.notna(d_rank) else None,
                "score": gold_features.get("score"),
                "signal": signal,
                "matched_collocations": matched_collocations,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# small statistics helpers
# ---------------------------------------------------------------------------


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for b/c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2**n
    return min(1.0, 2 * tail)


def bootstrap_ci(k: int, n: int, *, iters: int = 20000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap CI for a proportion k/n (binomial resampling)."""
    if n == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    draws = rng.binomial(n, k / n, size=iters) / n
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
