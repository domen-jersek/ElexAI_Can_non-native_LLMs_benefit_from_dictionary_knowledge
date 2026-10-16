"""Markdown report for one evaluated run (plots come in a later phase)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_VARIANT_LABEL = {
    "A": "A - base LLM (no context)",
    "B": "B - text RAG (semantic search over sense chunks)",
    "C": "C - structured data (lemma lookup + synonyms)",
    "oracle": "oracle - gold sense + neighbours (composition check)",
}


def build_report(run_dir: Path, metrics: dict) -> str:
    cfg = yaml.safe_load((run_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    manifest: dict = {}
    mpath = run_dir / "manifest.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    llm = cfg["llm"]
    emb = cfg["embedder"]
    ret = cfg["retrieval"]

    lines: list[str] = []
    lines.append(f"# Run report: `{metrics['run_id']}`")
    lines.append("")
    lines.append(f"- LLM: `{llm['model']}` (temperature {llm['temperature']})")
    lines.append(f"- Embedder: `{emb['hf_id']}` @ `{emb['revision']}`")
    lines.append(
        f"- Retrieval: k={ret['k']} (sweep {ret['sweep_k']}), exact FAISS over sense chunks"
    )
    lines.append(f"- Questions: {metrics['n_questions']} (file: `{cfg['questions_path']}`)")
    if manifest:
        dirty = "dirty" if manifest.get("git_dirty") else "clean"
        lines.append(
            f"- Git: `{str(manifest.get('git_commit'))[:12]}` ({dirty}); "
            f"template `{manifest.get('template_version')}`; dry_run={manifest.get('dry_run')}"
        )
    lines.append("")
    lines.append("## Summary per variant")
    lines.append("")
    lines.append(
        "| variant | n | citation acc. | cite `none` | answer F1 (mean) | answer acc. (F1>=thr) "
        "| latency p50/p95 (ms) | cache hits |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")

    def fmt(value, digits=3):
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    for variant, m in metrics["variants"].items():
        label = _VARIANT_LABEL.get(variant, variant)
        latency = (
            f"{m['latency_p50_ms']:.0f} / {m['latency_p95_ms']:.0f}"
            if m.get("latency_p50_ms") is not None and m.get("latency_p95_ms") is not None
            else "-"
        )
        lines.append(
            f"| {label} | {m['n']} | {fmt(m.get('citation_accuracy'))} | {m.get('cite_none', '-')} "
            f"| {fmt(m.get('answer_f1_mean'))} | {fmt(m.get('answer_accuracy_f1'))} "
            f"| {latency} | {m.get('cache_hits', 0)} |"
        )
    lines.append("")
    lines.append("## Error decomposition")
    lines.append("")
    lines.append(
        "| variant | retrieval/coverage errors | composition errors | notes |"
    )
    lines.append("|---|---|---|---|")
    for variant, m in metrics["variants"].items():
        notes = ""
        if variant == "B":
            recall = ", ".join(f"{k}: {v:.2f}" for k, v in m.get("recall_at_k", {}).items())
            notes = f"recall@k -> {recall}"
        elif variant == "C":
            notes = "coverage = is the gold sense among the shown candidates"
        elif variant == "oracle":
            notes = "gold sense always shown; all errors are composition"
        lines.append(
            f"| {_VARIANT_LABEL.get(variant, variant)} | "
            f"{m.get('retrieval_errors', 0)} | {m.get('composition_errors', 0)} | {notes} |"
        )
    lines.append("")
    lines.append("## Per-question detail")
    lines.append("")
    lines.append("| question | variant | cited | citation correct | answer F1 | cached |")
    lines.append("|---|---|---|---|---|---|")
    for row in metrics["per_question"]:
        if row.get("error"):
            lines.append(f"| {row['question_id']} | {row['variant']} | ERROR | - | - | - |")
            continue
        cc = row.get("citation_correct")
        cc_s = "-" if cc is None else ("yes" if cc else "no")
        lines.append(
            f"| {row['question_id']} | {row['variant']} | {row.get('cited_sense_id') or '-'} "
            f"| {cc_s} | {row.get('answer_f1')} | {'yes' if row.get('cache_hit') else ''} |"
        )
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- Gold answers and contexts are **DRAFT** until a lexicographer verifies them; "
        "treat absolute numbers as indicative, not final."
    )
    lines.append(
        "- The answer-text metric is a simple token-F1 over normalized strings "
        "(no LLM judge); citation accuracy is exact sense-id matching."
    )
    lines.append(
        "- Latencies include network/provider variance; cached calls are excluded from "
        "percentiles (see the cache column)."
    )
    lines.append(
        "- Plots (latency/error breakdowns, dark theme) are planned for the evaluation "
        "phase; this report is intentionally plain Markdown."
    )
    lines.append("")
    return "\n".join(lines)
