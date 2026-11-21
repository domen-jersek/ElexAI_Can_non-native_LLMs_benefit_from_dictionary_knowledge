"""Build the v2 *designed* question set from ``data/questions/design_v2.yaml``.

Why a designed set (docs/DECISIONS.md D-030): with a large candidate list C and D
both saturate, so the comparison carries no information. The v2 set is stratified
by the two mechanisms that actually separate the methods:

- **candidate position** (is the gold sense within the cap of 3, or buried?),
- **lexical cue** (does the sentence contain a distinctive word from the gold
  sense's dictionary neighbourhood - collocations, definition, synonyms?).

Those two axes give four cells with *predicted* signatures (S1 all work,
S2 C wins by position, S3 D must win, S4 C and D both fail), plus relation
cells where the explicit link is the only route.

The cell is **derived from the data**, never asserted: the builder measures the
position and the cue hits and refuses to write a question whose measured cell
differs from the spec's ``expect_cell``. Gold answers are taken from the
dictionary; every question stays ``draft`` until a lexicographer verifies it.

    uv run python scripts/build_questions_v2.py            # write + report
    uv run python scripts/build_questions_v2.py --check    # report only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from elexai.env import REPO_ROOT
from elexai.questions import Question, load_questions, validate_questions
from elexai.text import content_stems

CORE = REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl"
V1 = REPO_ROOT / "data" / "questions" / "questions.jsonl"
SPEC = REPO_ROOT / "data" / "questions" / "design_v2.yaml"
OUT = REPO_ROOT / "data" / "questions" / "questions_v2.jsonl"
DICT_VERSION = "DDDS backup v3.68"
CAP = 3
SENSE_QUESTION = "Kateri pomen besede \u00bb{lemma}\u00ab je uporabljen v podanem stavku?"
PHENOMENA = {"figurative", "decoy", "low_polysemy", "multiword"}
RELATION_LABEL = {
    "synonym": "sopomenka",
    "antonym": "protipomenka",
    "hypernym": "nadpomenka",
    "hyponym": "podpomenka",
}

def definition_text(rec: dict) -> str:
    return " | ".join(d.get("text", "") for d in rec.get("definitions", []) if d.get("text"))


def neighbourhood(rec: dict) -> set[str]:
    """Words the graph can match a sentence against (definition + collocations + synonyms)."""
    parts = [definition_text(rec)]
    parts += [text for _sid, text in rec.get("dependencies", [])]
    parts += [text for _sid, text in rec.get("synonyms", [])]
    return content_stems(" ".join(parts))


def classify_sense(
    sentence: str, gold: dict, senses: list[dict], *, target_word: str
) -> tuple[str, list[str], int]:
    """Derive the design cell from measured position and cue hits."""
    exclude = (gold["lemma"].lower()[:4], target_word.lower()[:4])
    sentence_words = content_stems(sentence, exclude_prefixes=exclude)
    gold_nb = neighbourhood(gold)
    other_nb: set[str] = set()
    for other in senses:
        if other["sense_id"] != gold["sense_id"]:
            other_nb |= neighbourhood(other)
    distinctive = sorted((sentence_words & gold_nb) - other_nb)
    position = int(gold["position"])
    shallow = position <= CAP
    cued = bool(distinctive)
    if shallow and cued:
        cell = "S1_shallow_cued"
    elif shallow:
        cell = "S2_shallow_nocue"
    elif cued:
        cell = "S3_buried_cued"
    else:
        cell = "S4_buried_nocue"
    return cell, distinctive, position


def relation_cell(gold: dict, related: dict, relation: str) -> tuple[str, float]:
    a = content_stems(definition_text(gold))
    b = content_stems(definition_text(related))
    jac = len(a & b) / max(1, len(a | b))
    return f"R_{relation}_{'overlap' if jac >= 0.05 else 'disjoint'}", jac


DISPLAYED_COLLOCATIONS = 8  # the context block shows at most this many "Zveze"


def _indicator(rec: dict) -> str:
    definitions = rec.get("definitions", [])
    return definitions[0]["text"].strip() if definitions else ""


def _indicator_is_distinctive(indicator: str, senses: list[dict]) -> bool:
    key = indicator.strip().lower()
    return sum(1 for s in senses if _indicator(s).lower() == key) == 1


def _collocation_candidates(
    rec: dict, lemma: str, pos_of: dict[str, str]
) -> list[tuple[int, str]]:
    """(index, text) of clean multi-word collocations.

    Keeps noun/adjective phrases (``garažni boks``, ``kartonska paličica``) and
    drops phrases built around a generic verb (``natakniti na paličice``), which
    the dictionary's corpus-derived collocation list also contains but which are
    not characteristic of the sense.
    """
    out: list[tuple[int, str]] = []
    for index, (_sid, text) in enumerate(rec.get("dependencies", [])):
        text = text.strip()
        if len(text.split()) < 2:
            continue
        if not content_stems(text, exclude_prefixes=(lemma[:4],)):
            continue
        tokens = [token.lower() for token in text.split()]
        if any(pos_of.get(token) == "verb" for token in tokens):
            continue
        # the dictionary's collocation list also contains corpus clauses
        # ("blagajna se polni", "noži režejo") - keep noun/adjective phrases only
        if "se" in tokens or any(token.endswith("jo") for token in tokens):
            continue
        out.append((index, text))
    return out


def _collocation_is_distinctive(
    collocation: str, gold: dict, senses: list[dict], lemma: str
) -> bool:
    stems = content_stems(collocation, exclude_prefixes=(lemma[:4],))
    if not stems:
        return False
    other: set[str] = set()
    for sense in senses:
        if sense["sense_id"] != gold["sense_id"]:
            other |= neighbourhood(sense)
    return bool(stems - other)


def build_definition_questions(
    spec: dict, by_lemma: dict
) -> tuple[list[Question], list[dict]]:
    """Generate definition -> sense questions from the dictionary indicators.

    Only **distinctive** indicators are used: if two senses of the same word share
    the indicator, the query would have two correct answers and the question would
    be invalid (this is exactly what the first generation showed for *zvezda*).
    One question per lemma keeps the set diverse.
    """
    cfg = spec.get("definitions") or {}
    per_cell = int(cfg.get("per_cell", 3))
    questions: list[Question] = []
    rows: list[dict] = []
    counts: Counter = Counter()
    for lemma in cfg.get("lemmas", []):
        senses = by_lemma.get((lemma.lower(), "noun")) or by_lemma.get((lemma.lower(), "verb"))
        if not senses:
            continue
        for gold in sorted(senses, key=lambda r: r["position"]):
            indicator = _indicator(gold)
            if len(indicator) < 3:
                continue
            if not _indicator_is_distinctive(indicator, senses):
                continue
            shallow = int(gold["position"]) <= CAP
            cell = f"A_{'shallow' if shallow else 'buried'}_distinctive"
            if counts[cell] >= per_cell:
                continue
            qid = f"v3-d{len(questions) + 1:03d}"
            questions.append(
                Question(
                    id=qid,
                    question=(
                        f"Kateri pomen besede \u00bb{lemma}\u00ab ustreza "
                        f"razlagi \u00bb{indicator}\u00ab?"
                    ),
                    target_word=lemma,
                    lemma=gold["lemma"],
                    pos=gold["pos"],
                    task_type="definition",
                    context_sentence=indicator,
                    gold_sense_id=str(gold["sense_id"]),
                    gold_answer=definition_text(gold),
                    source_dictionary_version=DICT_VERSION,
                    notes="Generated from the DDDS indicator; draft until verified.",
                    design_cell=cell,
                )
            )
            counts[cell] += 1
            rows.append(
                {
                    "id": qid,
                    "cell": cell,
                    "lemma": gold["lemma"],
                    "detail": f"p{gold['position']} {indicator}",
                }
            )
            break  # one definition question per lemma
    return questions, rows


def build_collocation_questions(
    spec: dict, by_lemma: dict
) -> tuple[list[Question], list[dict]]:
    """Generate collocation -> sense questions from the dictionary collocations."""
    cfg = spec.get("collocations") or {}
    per_cell = int(cfg.get("per_cell", 3))
    displayed = int(cfg.get("displayed", DISPLAYED_COLLOCATIONS))
    excluded = [text.lower() for text in cfg.get("exclude", [])]
    questions: list[Question] = []
    rows: list[dict] = []
    counts: Counter = Counter()
    pos_of = {lemma: pos for (lemma, pos) in by_lemma}
    for lemma in cfg.get("lemmas", []):
        senses = by_lemma.get((lemma.lower(), "noun")) or by_lemma.get((lemma.lower(), "verb"))
        if not senses:
            continue
        added = False
        for gold in sorted(senses, key=lambda r: r["position"]):
            shallow = int(gold["position"]) <= CAP
            for index, collocation in _collocation_candidates(gold, lemma, pos_of):
                if any(text in collocation.lower() for text in excluded):
                    continue
                if not _collocation_is_distinctive(collocation, gold, senses, lemma):
                    continue
                visible = index < displayed
                cell = (
                    f"B_{'shallow' if shallow else 'buried'}"
                    f"_{'visible' if visible else 'hidden'}"
                )
                if counts[cell] >= per_cell:
                    continue
                qid = f"v3-c{len(questions) + 1:03d}"
                questions.append(
                    Question(
                        id=qid,
                        question=(
                            f"Kateri pomen besede \u00bb{lemma}\u00ab je uporabljen "
                            f"v zvezi \u00bb{collocation}\u00ab?"
                        ),
                        target_word=lemma,
                        lemma=gold["lemma"],
                        pos=gold["pos"],
                        task_type="collocation",
                        context_sentence=collocation,
                        gold_sense_id=str(gold["sense_id"]),
                        gold_answer=definition_text(gold),
                        source_dictionary_version=DICT_VERSION,
                        notes="Generated from the DDDS collocation; draft until verified.",
                        design_cell=cell,
                    )
                )
                counts[cell] += 1
                rows.append(
                    {
                        "id": qid,
                        "cell": cell,
                        "lemma": gold["lemma"],
                        "detail": f"p{gold['position']} {'visible' if visible else 'hidden'} {collocation}",
                    }
                )
                added = True
                break  # one collocation per sense is enough
            if added:
                break  # one collocation question per lemma
    return questions, rows


def build_relation_question(spec: dict, gold: dict, related: dict) -> Question:
    relation = spec["relation"]
    label = RELATION_LABEL[relation]
    lemma = gold["lemma"]
    rel_lemma = related["lemma"]
    rel_def = definition_text(related)
    if relation in ("synonym", "antonym"):
        question = (
            f"Pomen {related['sense_id']} besede \u00bb{rel_lemma}\u00ab (razlaga: {rel_def}) je "
            f"{label} enega od pomenov besede \u00bb{lemma}\u00ab. "
            f"Kateri pomen besede \u00bb{lemma}\u00ab je to?"
        )
    else:
        question = (
            f"En od pomenov besede \u00bb{lemma}\u00ab je {label} pomena {related['sense_id']} "
            f"(\u00bb{rel_lemma}\u00ab, razlaga: {rel_def}). Kateri pomen besede \u00bb{lemma}\u00ab je to?"
        )
    return Question(
        id=spec["id"],
        question=question,
        target_word=lemma,
        lemma=lemma,
        pos=gold["pos"],
        question_type="relation",
        relation=relation,
        related_sense_id=str(related["sense_id"]),
        gold_sense_id=str(gold["sense_id"]),
        gold_answer=definition_text(gold),
        source_dictionary_version=DICT_VERSION,
        notes=f"Designed v2 question (cell derived by build_questions_v2.py). Related sense: {rel_lemma}.",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report only, do not write")
    ap.add_argument("--spec", type=Path, default=SPEC)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    core: dict[int, dict] = {}
    by_lemma: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in CORE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        core[int(rec["sense_id"])] = rec
        by_lemma[(rec["lemma"].lower(), rec["pos"])].append(rec)

    spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    v1 = {q.id: q for q in load_questions(V1)}
    records: list[Question] = []
    errors: list[str] = []
    report: list[dict] = []

    # ---- reuse existing questions, derive their cell -----------------------
    for entry in spec.get("reuse", []):
        qid = entry["id"]
        if qid not in v1:
            errors.append(f"{qid}: not found in {V1.name}")
            continue
        q = v1[qid].model_copy(deep=True)
        gold = core.get(int(q.gold_sense_id))
        if gold is None:
            errors.append(f"{qid}: gold sense {q.gold_sense_id} not in the dictionary export")
            continue
        if q.question_type == "relation":
            related = core.get(int(q.related_sense_id))
            if related is None:
                errors.append(f"{qid}: related sense {q.related_sense_id} not in the export")
                continue
            cell, jac = relation_cell(gold, related, q.relation or "")
            report.append({"id": qid, "cell": cell, "lemma": q.lemma, "detail": f"jac={jac:.3f}"})
        else:
            senses = by_lemma[(gold["lemma"].lower(), gold["pos"])]
            cell, cues, position = classify_sense(
                q.context_sentence, gold, senses, target_word=q.target_word
            )
            report.append(
                {"id": qid, "cell": cell, "lemma": q.lemma, "detail": f"p{position} cues={cues}"}
            )
        q.design_cell = cell
        q.phenomena = list(entry.get("phenomena", []))
        records.append(q)

    # ---- new sense questions ----------------------------------------------
    for entry in spec.get("new", []):
        gold = core.get(int(entry["gold_sense_id"]))
        if gold is None:
            errors.append(f"{entry['id']}: gold sense {entry['gold_sense_id']} not in the export")
            continue
        if gold["lemma"].lower() != entry["lemma"].lower():
            errors.append(
                f"{entry['id']}: lemma {entry['lemma']!r} != dictionary lemma {gold['lemma']!r}"
            )
            continue
        senses = by_lemma[(gold["lemma"].lower(), gold["pos"])]
        cell, cues, position = classify_sense(
            entry["context_sentence"], gold, senses, target_word=entry["target_word"]
        )
        expected = entry.get("expect_cell")
        if expected and expected != cell:
            errors.append(
                f"{entry['id']}: expected {expected}, measured {cell} "
                f"(p{position}, cues={cues})"
            )
            continue
        phenomena = list(entry.get("phenomena", []))
        unknown = set(phenomena) - PHENOMENA
        if unknown:
            errors.append(f"{entry['id']}: unknown phenomena {sorted(unknown)}")
            continue
        if "low_polysemy" in phenomena and len(senses) > 3:
            errors.append(f"{entry['id']}: low_polysemy but the lemma has {len(senses)} senses")
            continue
        q = Question(
            id=entry["id"],
            question=SENSE_QUESTION.format(lemma=gold["lemma"]),
            target_word=entry["target_word"],
            lemma=gold["lemma"],
            pos=gold["pos"],
            question_type="sense_disambiguation",
            context_sentence=entry["context_sentence"],
            gold_sense_id=str(gold["sense_id"]),
            gold_answer=definition_text(gold),
            source_dictionary_version=DICT_VERSION,
            notes="Designed v2 question (cell derived by build_questions_v2.py).",
            design_cell=cell,
            phenomena=phenomena,
        )
        records.append(q)
        report.append(
            {
                "id": entry["id"],
                "cell": cell,
                "lemma": gold["lemma"],
                "detail": f"p{position}/{len(senses)} cues={cues}",
            }
        )

    # ---- new relation questions -------------------------------------------
    for entry in spec.get("relations", []):
        gold = core.get(int(entry["gold_sense_id"]))
        related = core.get(int(entry["related_sense_id"]))
        if gold is None or related is None:
            errors.append(f"{entry['id']}: gold/related sense missing from the export")
            continue
        if gold["lemma"].lower() != entry["lemma"].lower():
            errors.append(f"{entry['id']}: lemma mismatch with the dictionary")
            continue
        relation = entry["relation"]
        linked = {sid for sid, _label in gold.get(relation + "s", [])}
        reverse = {sid for sid, _label in related.get(relation + "s", [])}
        if int(entry["related_sense_id"]) not in linked and int(entry["gold_sense_id"]) not in reverse:
            errors.append(
                f"{entry['id']}: no {relation} edge between {gold['sense_id']} and "
                f"{related['sense_id']} in the dictionary export"
            )
            continue
        cell, jac = relation_cell(gold, related, relation)
        expected = entry.get("expect_cell")
        if expected and expected != cell:
            errors.append(f"{entry['id']}: expected {expected}, measured {cell} (jac={jac:.3f})")
            continue
        q = build_relation_question(entry, gold, related)
        q.design_cell = cell
        records.append(q)
        report.append(
            {"id": entry["id"], "cell": cell, "lemma": gold["lemma"], "detail": f"jac={jac:.3f}"}
        )

    if errors:
        print("DESIGN VIOLATIONS:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # ---- generated definition / collocation questions (v3) -----------------
    definition_questions, definition_rows = build_definition_questions(spec, by_lemma)
    records.extend(definition_questions)
    report.extend(definition_rows)

    collocation_questions, collocation_rows = build_collocation_questions(spec, by_lemma)
    records.extend(collocation_questions)
    report.extend(collocation_rows)

    problems = validate_questions(records, {str(k): v["lemma"] for k, v in core.items()})
    if problems:
        print("VALIDATION PROBLEMS:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    records.sort(key=lambda q: (q.design_cell, q.id))
    counts = Counter(q.design_cell for q in records)
    print(f"questions: {len(records)}")
    print(f"{'cell':24s} {'n':>3s}")
    for cell, n in sorted(counts.items()):
        print(f"{cell:24s} {n:3d}")
    print()
    print(f"{'id':8s} {'lemma':12s} {'cell':22s} detail")
    for row in report:
        print(f"{row['id']:8s} {row['lemma']:12s} {row['cell']:22s} {row['detail']}")

    if not args.check:
        args.out.write_text(
            "\n".join(json.dumps(q.model_dump(), ensure_ascii=False) for q in records) + "\n",
            encoding="utf-8",
        )
        print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

