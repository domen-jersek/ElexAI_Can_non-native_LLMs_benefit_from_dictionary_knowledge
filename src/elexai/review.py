"""Lexicographer review kit: per-question dossier + machine-assisted audit flags.

Generates (Slovene text, for a lexicographer):

- ``review_sheet.md``   - one section per question: context, proposed gold
  sense with definitions/synonyms/collocations, all candidates, the answers of
  every variant, audit flags, and a decision block;
- ``review_table.csv``  - one machine-readable row per question with empty
  reviewer fields (name, confirmed, corrected gold, corrected text, notes);
- ``review_summary.md`` - what to look at first, how to send the review back.

The flags are computed from the run + the dictionary export: ``trick`` items,
near-duplicate candidates (definition overlap), late senses, gold senses with
no lexical cue in the sentence (hard), variant disagreements, and B retrieval
misses. The kit is generated into ``review/`` (gitignored).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from elexai.analysis import (
    LEXICAL_CORE,
    QUESTIONS_PATH,
    RUNS_DIR,
    SENSES_EXPORT,
    load_answers,
    load_questions_table,
)
from elexai.eval.metrics import normalize_text

FLAG_TRICK = "trick"
FLAG_DUP = "podvojen-kandidat"
FLAG_LATE = "pozni-pomen"
FLAG_HARD = "brez-namiga (težko)"
FLAG_DISAGREE = "neskladje-variant"
FLAG_B_MISS = "B-brez-zlatega"


def _load_core_records(path: Path, ids: set[str]) -> dict[str, dict]:
    """Definitions / synonyms / collocations for the senses we need."""
    out: dict[str, dict] = {}
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            sid = str(rec["sense_id"])
            if sid not in ids:
                continue
            out[sid] = {
                "lemma": rec.get("lemma", ""),
                "pos": rec.get("pos", ""),
                "position": rec.get("position"),
                "definition": " | ".join(
                    d["text"] for d in rec.get("definitions", []) if d.get("text")
                ),
                "synonyms": [str(lemma) for _, lemma in rec.get("synonyms", []) or []],
                "collocations": [str(form) for _, form in rec.get("dependencies", []) or []][
                    :8
                ],
            }
    return out


def _tokens(text: str) -> set[str]:
    return {t for t in normalize_text(text or "").split() if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cited(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def _signal_for_gold(d_row) -> bool:
    features = {f["sense_id"]: f for f in (d_row.get("ranked_features") or [])}
    gold_features = features.get(str(d_row["gold_sense_id"]), {})
    return bool(
        gold_features.get("matched_collocations")
        or gold_features.get("matched_synonyms")
        or gold_features.get("matched_synset_literals")
        or gold_features.get("matched_hypernym_glosses")
        or gold_features.get("matched_definition")
    )


def build_review_kit(
    run_id: str,
    out_dir: Path,
    *,
    runs_dir: Path = RUNS_DIR,
    questions_path: Path = QUESTIONS_PATH,
    senses_path: Path = SENSES_EXPORT,
    lexical_core: Path = LEXICAL_CORE,
) -> dict:
    answers = load_answers(
        run_id, runs_dir=runs_dir, questions_path=questions_path, senses_path=senses_path
    )
    questions = load_questions_table(questions_path).set_index("question_id")
    c_rows = answers[answers["variant"] == "C"].set_index("question_id")
    d_rows = answers[answers["variant"] == "D"].set_index("question_id")
    b_rows = answers[answers["variant"] == "B"].set_index("question_id")
    oracle_rows = answers[answers["variant"] == "oracle"].set_index("question_id")

    needed: set[str] = set()
    for qid in c_rows.index:
        needed.add(str(c_rows.loc[qid, "gold_sense_id"]))
        needed.update(str(s) for s in (c_rows.loc[qid, "shown_ids"] or []))
        rel = questions.loc[qid, "related_sense_id"]
        if rel:
            needed.add(str(rel))
    core = _load_core_records(lexical_core, needed)

    out_dir.mkdir(parents=True, exist_ok=True)
    sheet: list[str] = [
        f"# Pregled vprašanj — leksikografski list ({run_id})",
        "",
        "Za vsako vprašanje: kontekst, predlagani zlati pomen, vsi kandidati in "
        "odgovori vseh variant. Zastavice opozarjajo na sumljive primere. "
        "Ocene vpiši v `review_table.csv`.",
        "",
        "---",
        "",
    ]
    table_rows: list[dict] = []
    flagged: dict[str, list[str]] = {k: [] for k in (FLAG_TRICK, FLAG_DUP, FLAG_LATE, FLAG_HARD, FLAG_DISAGREE, FLAG_B_MISS)}
    relations: list[str] = []

    for qid in c_rows.index:
        q_row = questions.loc[qid]
        is_trick = bool(q_row["is_trick"])
        gold = str(c_rows.loc[qid, "gold_sense_id"])
        shown = [str(s) for s in (c_rows.loc[qid, "shown_ids"] or [])]
        c_position = shown.index(gold) + 1 if gold in shown else None
        gold_def = core.get(gold, {}).get("definition", "")

        flags: list[str] = []
        if is_trick:
            flags.append(FLAG_TRICK)
        dupes = [
            sid
            for sid in shown
            if sid != gold
            and _jaccard(_tokens(core.get(sid, {}).get("definition", "")), _tokens(gold_def))
            >= 0.5
        ]
        for sid in dupes:
            flags.append(f"{FLAG_DUP}:{sid}")
        signal = _signal_for_gold(d_rows.loc[qid]) if qid in d_rows.index else False
        if c_position and c_position > 3:
            flags.append(f"{FLAG_LATE}(poz.{c_position})")
            if not signal:
                flags.append(FLAG_HARD)
        cited_ids = {
            cited
            for cited in (
                _cited(c_rows.loc[qid, "cited_sense_id"]),
                _cited(d_rows.loc[qid, "cited_sense_id"]) if qid in d_rows.index else None,
                _cited(oracle_rows.loc[qid, "cited_sense_id"]) if qid in oracle_rows.index else None,
            )
            if cited is not None
        }
        if len(cited_ids) > 1:
            flags.append(FLAG_DISAGREE)
        if qid in b_rows.index:
            retrieved = [str(s) for s in (b_rows.loc[qid, "retrieved_ids"] or [])]
            if gold not in retrieved:
                flags.append(FLAG_B_MISS)
        for flag_prefix, key in (
            (FLAG_TRICK, FLAG_TRICK),
            (FLAG_DUP, FLAG_DUP),
            (FLAG_LATE, FLAG_LATE),
            (FLAG_HARD, FLAG_HARD),
            (FLAG_DISAGREE, FLAG_DISAGREE),
            (FLAG_B_MISS, FLAG_B_MISS),
        ):
            if any(f == flag_prefix or f.startswith(flag_prefix) for f in flags):
                flagged[key].append(qid)

        if q_row["question_type"] == "relation":
            relations.append(qid)

        # --- sheet section ---
        sheet.append(f"## {qid} · {q_row['question_type']} · {q_row['lemma']}")
        sheet.append("")
        if flags:
            sheet.append(f"*Zastavice: {', '.join(flags)}*")
            sheet.append("")
        sheet.append(f"**Vprašanje:** {q_row['question']}")
        sentence = str(q_row["context_sentence"] or "")
        if sentence:
            sheet.append(f"**Stavek:** »{sentence}«")
        sheet.append(f"**Ciljna beseda:** {q_row['target_word']} ({q_row['pos']})")
        rel_id = _cited(q_row["related_sense_id"])
        if rel_id:
            rel_rec = core.get(rel_id, {})
            sheet.append(
                f"**Izhodiščni pomen:** `{rel_id}` — {rel_rec.get('definition', '')[:140]}"
            )
            sheet.append(f"**Odnos:** {q_row['relation']}")
        gold_rec = core.get(gold, {})
        sheet.append("")
        sheet.append(f"**Predlagani zlati pomen — `{gold}`:** {gold_rec.get('definition', '')[:170]}")
        if gold_rec.get("synonyms"):
            sheet.append(f"- sopomenke: {', '.join(gold_rec['synonyms'][:6])}")
        if gold_rec.get("collocations"):
            sheet.append(f"- zveze: {', '.join(gold_rec['collocations'][:8])}")
        sheet.append("")
        sheet.append("**Kandidati (slovarski red, kot jih vidi C):**")
        sheet.append("")
        sheet.append("| ID | definicija | |")
        sheet.append("|---|---|---|")
        for sid in shown:
            mark = "← **zlati**" if sid == gold else ""
            sheet.append(f"| `{sid}` | {core.get(sid, {}).get('definition', '')[:110]} | {mark} |")
        sheet.append("")
        sheet.append(f"**Odgovori sistemov (tek `{run_id}`):**")
        a_match = answers[(answers["variant"] == "A") & (answers["question_id"] == qid)]
        if not a_match.empty:
            ans = str(a_match.iloc[0]["answer"] or "").strip()
            sheet.append(f"- **A** (brez konteksta): {ans[:170] if ans else '—'}")
        for variant, rows in (("B", b_rows), ("C", c_rows), ("D", d_rows), ("oracle", oracle_rows)):
            if qid not in rows.index:
                continue
            row = rows.loc[qid]
            cited = _cited(row["cited_sense_id"])
            mark = "✔" if cited == gold else ("✘" if cited else "—")
            answer_text = str(row["answer"] or "").strip()
            extra = ""
            if variant == "B":
                top = " | ".join(str(s) for s in (row["retrieved_ids"] or [])[:3])
                extra = f" · zadetki: {top}"
            if variant == "D" and q_row["question_type"] == "relation":
                evidence = row["evidence_sense_ids"] or []
                extra = f" · dokaz: {evidence}"
            sheet.append(f"- **{variant}**: `{cited or '—'}` {mark} · {answer_text[:110]}{extra}")
        sheet.append("")
        sheet.append(
            "**Pregled:** [ ] zlati pomen pravilen · [ ] stavek/kontekst ustrezen · "
            "[ ] kandidati popolni?"
        )
        sheet.append("")
        sheet.append("Opombe: ______________________________________________")
        sheet.append("")
        sheet.append("---")
        sheet.append("")

        table_rows.append(
            {
                "id": qid,
                "tip": q_row["question_type"],
                "lema": q_row["lemma"],
                "ciljna_beseda": q_row["target_word"],
                "zlati_id": gold,
                "zlati_pomen": gold_rec.get("definition", "")[:120],
                "zastavice": "; ".join(flags),
                "pregledovalec": "",
                "potrjeno": "",
                "zlati_pravilen": "",
                "popravljen_zlati_id": "",
                "popravljeno_besedilo": "",
                "opombe": "",
            }
        )

    (out_dir / "review_sheet.md").write_text("\n".join(sheet), encoding="utf-8")

    with (out_dir / "review_table.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(table_rows[0].keys()))
        writer.writeheader()
        writer.writerows(table_rows)

    summary_lines = [
        "# Povzetek za pregled",
        "",
        f"- vprašanj: **{len(table_rows)}** (razločevanje pomena: "
        f"{len(table_rows) - len(relations)}, relacije: {len(relations)})",
        f"- označeni `trick`: {', '.join(flagged[FLAG_TRICK]) or '—'}",
        f"- pozni pomeni: {len(flagged[FLAG_LATE])} · brez namiga (težko): "
        f"{', '.join(flagged[FLAG_HARD]) or '—'}",
        f"- podvojeni kandidati: {', '.join(flagged[FLAG_DUP]) or '—'}",
        f"- neskladje med variantami: {', '.join(flagged[FLAG_DISAGREE]) or '—'}",
        f"- B ni našel zlatega pomena: {len(flagged[FLAG_B_MISS])} vprašanj",
        "",
        "## Kako pregledati",
        "",
        "1. Odpri `review_sheet.md` in `review_table.csv` drug ob drugem.",
        "2. Za vsako vprašanje preveri: ali je predlagani zlati pomen res pravi za "
        "stavek/odnos; ali je stavek naraven in nedvoumen; ali manjka kakšen pomen.",
        "3. V `review_table.csv` izpolni: `pregledovalec`, `potrjeno` (da/ne), "
        "`zlati_pravilen` (da/ne), po potrebi `popravljen_zlati_id`, "
        "`popravljeno_besedilo` in `opombe`.",
        "4. Osredotoči se najprej na zastavice (trick, podvojeni kandidati, "
        "brez namiga) - ostalo je večinoma očitno.",
        "",
        "Ko je tabela izpolnjena, jo vrnite; popravke vnesem v "
        "`data/questions/questions.jsonl` (+ `review_status`).",
    ]
    (out_dir / "review_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    return {
        "out_dir": str(out_dir),
        "n_questions": len(table_rows),
        "n_relations": len(relations),
        "flagged": {k: v for k, v in flagged.items() if v},
    }
