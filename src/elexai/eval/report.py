"""Markdown report for one evaluated run (plots come in a later phase)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_VARIANT_LABEL = {
    "A": "A - base LLM (no context)",
    "B": "B - text RAG (semantic search over sense chunks)",
    "C": "C - structured data (lemma lookup + synonyms)",
    "D": "D - graph RAG (neighborhood-ranked candidates)",
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
        templates = manifest.get("template_versions") or [manifest.get("template_version")]
        lines.append(
            f"- Git: `{str(manifest.get('git_commit'))[:12]}` ({dirty}); "
            f"templates `{', '.join(str(t) for t in templates)}`; dry_run={manifest.get('dry_run')}"
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

    trick_ids = metrics.get("trick_question_ids") or []
    if trick_ids:
        lines.append(f"Flagged **trick** questions: {', '.join(trick_ids)} (see caveats).")
        lines.append("")
        lines.append("| variant | citation acc. (all) | citation acc. (excl. trick) |")
        lines.append("|---|---|---|")
        for variant, m in metrics["variants"].items():
            lines.append(
                f"| {_VARIANT_LABEL.get(variant, variant)} | {fmt(m.get('citation_accuracy'))} "
                f"| {fmt(m.get('citation_accuracy_excl_trick'))} |"
            )
        lines.append("")

    question_types = metrics.get("question_types") or []
    if len(question_types) > 1:
        lines.append("## By question type")
        lines.append("")
        lines.append(
            "| variant | type | n | citation acc. | retrieval/coverage errors "
            "| composition errors |"
        )
        lines.append("|---|---|---|---|---|---|")
        for variant, m in metrics["variants"].items():
            for qt in question_types:
                t = (m.get("by_question_type") or {}).get(qt)
                if not t:
                    continue
                lines.append(
                    f"| {_VARIANT_LABEL.get(variant, variant)} | {qt} | {t['n']} "
                    f"| {fmt(t.get('citation_accuracy'))} | {t.get('retrieval_errors', 0)} "
                    f"| {t.get('composition_errors', 0)} |"
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
        elif variant == "D":
            rank = metrics["variants"][variant].get("gold_rank_mean")
            notes = f"graph-ranked; mean gold rank = {rank}"
        elif variant == "oracle":
            notes = "gold sense always shown; all errors are composition"
        rel = m.get("relation_evidence")
        if rel and variant in ("D", "oracle"):
            notes += f"; relation gold evidence {rel['gold_evidence']}/{rel['n']}"
        vis = m.get("relation_visible_in_synonyms")
        if vis and variant == "C":
            notes += f"; relation visible in synonyms {vis['visible']}/{vis['n']}"
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
    if "relation" in (metrics.get("question_types") or []):
        lines.append(
            "- Relation questions (`question_type=relation`): gold pairs come from WordNet "
            "synsets / DDDS sense relations (exact links); variants D/oracle show an explicit "
            "graph evidence line for the linked candidate; drafts until verified."
        )
    if trick_ids:
        lines.append(
            f"- Questions {', '.join(trick_ids)} are flagged `trick` (compound-sense intrusion / "
            "near-duplicate senses); the headline numbers above exclude them."
        )
    lines.append(
        "- Plots (latency/error breakdowns, dark theme) are planned for the evaluation "
        "phase; this report is intentionally plain Markdown."
    )
    lines.append("")
    return "\n".join(lines)
