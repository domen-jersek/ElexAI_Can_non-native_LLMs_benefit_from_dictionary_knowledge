"""LLM-free scoring for sense-disambiguation runs (generation is separate).

Reads ``runs/<run_id>/answers.jsonl`` (+ the questions file referenced by the
resolved config) and computes, per variant:

- citation accuracy (does the cited DDDS sense id match the gold id; variants
  with a candidate list) and ``none``-citation counts;
- answer quality vs the (draft) gold answer text: token F1 + threshold accuracy;
- latency p50/p95 over non-cached successful calls, cache-hit counts;
- variant B: recall@k from the logged retrieval + retrieval-vs-composition
  error split; variant C: candidate-coverage-vs-composition split;
  oracle: composition-only split;
- per-question rows for eyeballing and the report.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import yaml

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").lower()
    text = _PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def token_f1(prediction: str, gold: str) -> float:
    pred = normalize_text(prediction).split()
    ref = normalize_text(gold).split()
    if not pred or not ref:
        return 0.0
    pred_counts, ref_counts = Counter(pred), Counter(ref)
    overlap = sum((pred_counts & ref_counts).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(ref)
    return 2 * precision * recall / (precision + recall)


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile (q in [0, 100]); None for empty input."""
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return float(values[0])
    rank = (q / 100) * (len(values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(values) - 1)
    frac = rank - lo
    return float(values[lo] + (values[hi] - values[lo]) * frac)


def _load_answers(run_dir: Path) -> list[dict]:
    rows = []
    with (run_dir / "answers.jsonl").open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_question_meta(run_dir: Path, repo_root: Path) -> dict[str, dict]:
    """Question metadata (gold answer text, type, flags) from the run's question file."""
    cfg = yaml.safe_load((run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    questions_path = Path(cfg["questions_path"])
    if not questions_path.is_absolute():
        questions_path = repo_root / questions_path
    meta: dict[str, dict] = {}
    for line in questions_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            meta[rec["id"]] = {
                "gold_answer": rec.get("gold_answer", ""),
                "question_type": rec.get("question_type", "sense_disambiguation"),
                "flags": rec.get("flags", []),
            }
    return meta


def _variant_stats(
    rows: list[dict],
    variant: str,
    *,
    gold_answers: dict[str, str],
    sweep_k: list[int],
    k_generation: int,
    threshold: float,
) -> tuple[dict, list[dict]]:
    """Metrics for one variant over the given rows (+ per-question rows)."""
    n = len(rows)
    errors = sum(1 for r in rows if r.get("error"))
    cache_hits = sum(1 for r in rows if r.get("cache_hit"))
    latencies = [
        r["latency_ms"]
        for r in rows
        if r.get("latency_ms") is not None and not r.get("cache_hit") and not r.get("error")
    ]

    citation_total = 0
    citation_correct = 0
    cite_none = 0
    f1s: list[float] = []
    f1_correct = 0
    retrieval_hits_by_k: dict[int, int] = {k: 0 for k in sorted({*sweep_k, k_generation})}
    retrieval_misses = 0
    coverage_misses = 0
    composition_errors = 0
    retrieval_errors = 0
    gold_ranks: list[int] = []
    rel_evidence_n = 0
    rel_evidence_ok = 0
    rel_visible_n = 0
    rel_visible_ok = 0
    per_question: list[dict] = []

    for r in rows:
        gold_id = str(r["gold_sense_id"])
        if r.get("error"):
            per_question.append(
                {
                    "question_id": r["question_id"],
                    "variant": variant,
                    "question_type": r.get("question_type"),
                    "error": r["error"],
                }
            )
            continue

        f1 = token_f1(r.get("parsed_answer") or "", gold_answers.get(r["question_id"], ""))
        f1s.append(f1)
        if f1 >= threshold:
            f1_correct += 1

        cited = r.get("parsed_sense_id")
        is_correct = False
        if variant in ("B", "C", "D", "oracle"):
            citation_total += 1
            if cited is None:
                cite_none += 1
            if cited is not None and str(cited) == gold_id:
                citation_correct += 1
                is_correct = True
        else:
            is_correct = f1 >= threshold

        if variant == "B":
            retrieved = [str(x["sense_id"]) for x in r.get("retrieved", [])]
            any_hit = gold_id in retrieved
            for k in retrieval_hits_by_k:
                if gold_id in retrieved[:k]:
                    retrieval_hits_by_k[k] += 1
            if not any_hit:
                retrieval_misses += 1
                retrieval_errors += 1
            elif not is_correct:
                composition_errors += 1
        elif variant in ("C", "D"):
            if variant == "D" and r.get("gold_rank") is not None:
                gold_ranks.append(int(r["gold_rank"]))
            if not r.get("gold_present", False):
                coverage_misses += 1
                retrieval_errors += 1
            elif not is_correct:
                composition_errors += 1
        elif variant == "oracle":
            if not r.get("gold_present", False):
                coverage_misses += 1
            elif not is_correct:
                composition_errors += 1

        if r.get("question_type") == "relation":
            if variant in ("D", "oracle") and "evidence_sense_ids" in r:
                rel_evidence_n += 1
                if r.get("gold_evidence"):
                    rel_evidence_ok += 1
            if variant == "C" and "related_visible_in_synonyms" in r:
                rel_visible_n += 1
                if r.get("related_visible_in_synonyms"):
                    rel_visible_ok += 1

        per_question.append(
            {
                "question_id": r["question_id"],
                "variant": variant,
                "question_type": r.get("question_type"),
                "cited_sense_id": cited,
                "citation_correct": (str(cited) == gold_id)
                if variant in ("B", "C", "D", "oracle")
                else None,
                "answer_f1": round(f1, 3),
                "answer_correct": f1 >= threshold,
                "latency_ms": r.get("latency_ms"),
                "cache_hit": r.get("cache_hit", False),
            }
        )

    entry: dict = {
        "n": n,
        "errors": errors,
        "cache_hits": cache_hits,
        "answer_f1_mean": round(sum(f1s) / len(f1s), 3) if f1s else None,
        "answer_accuracy_f1": round(f1_correct / len(f1s), 3) if f1s else None,
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
    }
    if variant in ("B", "C", "D", "oracle"):
        entry["citation_accuracy"] = (
            round(citation_correct / citation_total, 3) if citation_total else None
        )
        entry["cite_none"] = cite_none
        entry["retrieval_errors"] = retrieval_errors
        entry["composition_errors"] = composition_errors
    if variant == "B":
        entry["recall_at_k"] = {
            str(k): round(hits / n, 3) if n else None
            for k, hits in sorted(retrieval_hits_by_k.items())
        }
        entry["retrieval_misses"] = retrieval_misses
    if variant in ("C", "D", "oracle"):
        entry["coverage_misses"] = coverage_misses
    if variant == "D" and gold_ranks:
        entry["gold_rank_mean"] = round(sum(gold_ranks) / len(gold_ranks), 2)
        entry["gold_rank_p50"] = percentile([float(x) for x in gold_ranks], 50)
    if rel_evidence_n:
        entry["relation_evidence"] = {"n": rel_evidence_n, "gold_evidence": rel_evidence_ok}
    if rel_visible_n:
        entry["relation_visible_in_synonyms"] = {"n": rel_visible_n, "visible": rel_visible_ok}
    return entry, per_question


def evaluate_run(run_dir: Path, repo_root: Path) -> dict:
    run_dir = Path(run_dir)
    cfg = yaml.safe_load((run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    sweep_k = cfg["retrieval"]["sweep_k"]
    k_generation = cfg["retrieval"]["k"]
    threshold = cfg["eval"]["answer_f1_threshold"]
    meta = _load_question_meta(run_dir, repo_root)
    gold_answers = {qid: m["gold_answer"] for qid, m in meta.items()}

    rows = _load_answers(run_dir)
    variants: dict[str, dict] = {}
    per_question: list[dict] = []
    question_types = sorted({r.get("question_type", "sense_disambiguation") for r in rows})
    trick_ids = sorted(qid for qid, m in meta.items() if "trick" in (m["flags"] or []))
    trick_set = set(trick_ids)
    stats_kwargs = {
        "gold_answers": gold_answers,
        "sweep_k": sweep_k,
        "k_generation": k_generation,
        "threshold": threshold,
    }

    for variant in sorted({r["variant"] for r in rows}):
        vrows = [r for r in rows if r["variant"] == variant]
        entry, per_rows = _variant_stats(vrows, variant, **stats_kwargs)
        per_question.extend(per_rows)
        if len(question_types) > 1:
            entry["by_question_type"] = {
                qt: _variant_stats(
                    [r for r in vrows if r.get("question_type", "sense_disambiguation") == qt],
                    variant,
                    **stats_kwargs,
                )[0]
                for qt in question_types
            }
        if trick_set:
            subset = [r for r in vrows if r["question_id"] not in trick_set]
            if subset:
                sub, _ = _variant_stats(subset, variant, **stats_kwargs)
                if "citation_accuracy" in sub:
                    entry["citation_accuracy_excl_trick"] = sub["citation_accuracy"]
        variants[variant] = entry

    return {
        "run_id": run_dir.name,
        "n_questions": len({r["question_id"] for r in rows}),
        "answer_f1_threshold": threshold,
        "question_types": question_types,
        "trick_question_ids": trick_ids,
        "variants": variants,
        "per_question": per_question,
    }
