"""Manual-run support: export prompts for chat-only models, import the answers.

Some models (e.g. GaMS on povejmo.si) are reachable only through a chat UI.
:func:`export_prompt_kit` turns the logged prompts of an existing run into a
copy-paste kit (a CSV plus one text file per prompt); :func:`import_answers`
reads the filled CSV back into a normal run directory, so ``make eval`` and the
notebooks work unchanged.

The contexts (shown candidates, retrieval, graph evidence) are model
independent, so the imported run copies them from the source run and replaces
only the model outputs. The import is explicitly marked as ``manual`` in the
run manifest - manual runs are less reproducible (UI defaults, copy-paste).
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

from elexai import __version__

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"

_HOWTO = """\
# Manual prompt kit

This folder was generated from run `{source_run}`. It contains the exact
prompts the other variants saw, so the answers can be compared 1:1.

## How to fill it

1. Open `answers.csv` and work through it row by row (the same order as
   `prompts.csv`; one text file per prompt is in `prompts/`).
2. For each row:
   - copy the full prompt into the chat (povejmo.si),
   - copy the model's **complete reply** into the `answer_raw` column,
   - do not edit, shorten or reformat the reply (raw output is the record).
3. You can fill the file in several sessions - only non-empty rows are
   imported.
4. Recommended phase 1: the 30 sense questions for variants A, C and D
   (question ids `q-001`..`q-030`; 90 rows). This answers how GaMS behaves
   without a dictionary (A) and whether it is sensitive to candidate ORDER
   (C vs D). Phase 2: B and oracle; phase 3: relation questions.

## How to import the answers

```
uv run python scripts/import_manual_answers.py \\
    --source-run {source_run} \\
    --csv manual_kit/answers.csv \\
    --model-label "GaMS3-12B-Instruct (manual via povejmo.si)"
make eval RUN=<printed run id>
```

Notes:
- The run manifest records `manual: true` and the model label; treat latency
  (not logged) and reproducibility accordingly.
- If the model does not follow the `SENSE_ID:`/`ODGOVOR:` format exactly,
  paste the reply as-is - the parser records what it can, the raw text is kept.
"""


def _read_answers(run_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (run_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_answers(csv_path: Path) -> dict:
    """Check a (partially) filled answers CSV before importing it.

    Looks for rows that would silently score as wrong: no ``ODGOVOR:`` text,
    missing ``SENSE_ID:`` on variants that must cite one, suspicious lengths and
    identical answer texts in several rows. The raw text is never changed.
    """
    from elexai.runner.run import parse_output

    with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    per_variant: Counter = Counter()
    problems: list[dict] = []
    seen_texts: dict[str, list[str]] = {}
    for row in rows:
        raw = (row.get("answer_raw") or "").strip()
        if not raw:
            continue
        key = f"{row.get('question_id')} {row.get('variant')}"
        variant = row.get("variant", "?")
        per_variant[variant] += 1
        sense_id, answer = parse_output(raw)
        if not answer:
            problems.append({"row": key, "problem": "no 'ODGOVOR:' text parsed"})
        elif len(answer) < 15:
            problems.append({"row": key, "problem": f"answer text suspiciously short ({len(answer)} chars)"})
        if len(raw) > 2000:
            problems.append({"row": key, "problem": f"raw answer suspiciously long ({len(raw)} chars)"})
        if variant in ("B", "C", "D", "oracle") and sense_id is None:
            problems.append({"row": key, "problem": "no SENSE_ID parsed (expected for this variant)"})
        if answer:
            seen_texts.setdefault(answer[:200], []).append(key)
    for keys in seen_texts.values():
        if len(keys) > 1:
            problems.append({"row": ", ".join(keys), "problem": "identical answer text in several rows"})

    return {
        "csv": str(csv_path),
        "n_rows": len(rows),
        "n_filled": sum(per_variant.values()),
        "per_variant": dict(sorted(per_variant.items())),
        "n_problems": len(problems),
        "problems": problems,
    }


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def latest_run(config: str, runs_dir: Path = RUNS_DIR) -> str:
    """Latest non-dry-run run id for a config name (e.g. "skeleton")."""
    candidates: list[str] = []
    for run_dir in sorted(runs_dir.glob("*")):
        cfg_path = run_dir / "config.resolved.yaml"
        if not cfg_path.exists():
            continue
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        if cfg.get("name") != config:
            continue
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("dry_run"):
                continue
        candidates.append(run_dir.name)
    if not candidates:
        raise SystemExit(f"no (non-dry-run) run found for config {config!r}")
    return candidates[-1]


def export_prompt_kit(
    source_run: str,
    out_dir: Path,
    *,
    variants: list[str] | None = None,
    question_types: list[str] | None = None,
    runs_dir: Path = RUNS_DIR,
) -> dict:
    """Write prompts.csv / answers.csv / prompts/*.txt for manual answering."""
    run_dir = runs_dir / source_run
    rows = _read_answers(run_dir)
    selected = [
        r
        for r in rows
        if (variants is None or r["variant"] in variants)
        and (question_types is None or r.get("question_type") in question_types)
    ]
    if not selected:
        raise SystemExit("no prompts selected - check --variants / --question-types")

    out_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)

    with (out_dir / "prompts.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["question_id", "variant", "lemma", "prompt"])
        for r in selected:
            writer.writerow([r["question_id"], r["variant"], r.get("lemma", ""), r["prompt"]])

    with (out_dir / "answers.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["question_id", "variant", "answer_raw"])
        for r in selected:
            writer.writerow([r["question_id"], r["variant"], ""])

    for r in selected:
        (prompts_dir / f"{r['question_id']}__{r['variant']}.txt").write_text(
            r["prompt"], encoding="utf-8"
        )

    (out_dir / "HOWTO.md").write_text(_HOWTO.format(source_run=source_run), encoding="utf-8")

    counts = Counter(r["variant"] for r in selected)
    counts_by_type = Counter(r.get("question_type", "?") for r in selected)
    return {
        "n_prompts": len(selected),
        "per_variant": dict(sorted(counts.items())),
        "per_question_type": dict(sorted(counts_by_type.items())),
        "out_dir": str(out_dir),
    }


def import_answers(
    source_run: str,
    csv_path: Path,
    *,
    model_label: str,
    name: str = "gams",
    runs_dir: Path = RUNS_DIR,
) -> Path:
    """Turn a filled answers.csv into a normal run directory (manual run)."""
    from elexai.runner.run import parse_output

    src_dir = runs_dir / source_run
    src_rows = {(r["question_id"], r["variant"]): r for r in _read_answers(src_dir)}

    filled: list[tuple[tuple[str, str], str]] = []
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = (row.get("answer_raw") or "").strip()
            if not raw:
                continue
            key = (row["question_id"], row["variant"])
            if key not in src_rows:
                raise SystemExit(
                    f"answers.csv row {key} is not present in source run {source_run!r}"
                )
            filled.append((key, raw))
    if not filled:
        raise SystemExit("no filled answers found in the CSV (answer_raw is empty everywhere)")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}_{name}_manual"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    with (run_dir / "answers.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for (qid, variant), raw in filled:
            record = dict(src_rows[(qid, variant)])
            cited, answer = parse_output(raw)
            record.update(
                {
                    "run_id": run_id,
                    "output_raw": raw,
                    "parsed_sense_id": cited,
                    "parsed_answer": answer,
                    "latency_ms": None,
                    "cache_hit": False,
                    "model": model_label,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "manual": True,
                }
            )
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    cfg = yaml.safe_load((src_dir / "config.resolved.yaml").read_text(encoding="utf-8"))
    cfg["name"] = name
    cfg["description"] = (
        (cfg.get("description") or "").strip()
        + f" [MANUAL RUN: {model_label}; contexts copied from {source_run}]"
    )
    cfg["llm"]["model"] = model_label
    (run_dir / "config.resolved.yaml").write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    manifest = {
        "run_schema": 1,
        "elexai_version": __version__,
        "manual": True,
        "source_run": source_run,
        "model_label": model_label,
        "started_at": datetime.now(UTC).isoformat(),
        "n_answers": len(filled),
        "variants": sorted({key[1] for key, _raw in filled}),
        "questions_sha256": _sha256(REPO_ROOT / "data" / "questions" / "questions.jsonl"),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (run_dir / "logs.txt").write_text(
        f"manual import\nsource run: {source_run}\nmodel: {model_label}\n"
        f"answers: {len(filled)}\n",
        encoding="utf-8",
    )
    return run_dir
