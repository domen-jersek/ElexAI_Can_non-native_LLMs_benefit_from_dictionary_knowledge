"""Part A: full OSWN <-> DDDS sense re-link with LinkingTK.

The project's standard uv environment deliberately does NOT include linkingtk;
run this script with an environment that has it (e.g. the spike venv), or:

    pip install "git+https://github.com/jmccrae/linkingtk"

Method: StringSimilarityLinker(description vs description, word_overlap).
Pass 1 blocks on the EXACT lemma (high precision; links get method="exact");
pass 2 falls back to approximate label-overlap blocking
(LabelOverlap(max_matches=5)) only for senses still unmatched
(method="approx", min-score filtered downstream). Every DDDS sense gets at
most one (best-scoring) link per pass.

Inputs:
    data/processed/ddds/lexical_core.jsonl         (DDDS senses + definitions)
    data/raw/.../open_slovene_wordnet.xml          (OSWN senses/synsets/glosses)
Outputs:
    data/processed/ddds/oswn_ddds_link_v2.tsv      (ddds_sense_id, lemma,
                                                    oswn_sense_id, oswn_synset_id, score)
    data/processed/ddds/oswn_ddds_link_v2.stats.json
    data/processed/ddds/oswn_ddds_link_v2.sample.tsv  (for manual eyeballing)
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

from elexai.sources.oswn import load_oswn

REPO_ROOT = Path(__file__).resolve().parents[1]

LEXICAL_CORE = REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl"
OSWN_XML = (
    REPO_ROOT
    / "data"
    / "raw"
    / "open_slovene_wordnet_1.0"
    / "open_slovene_wordnet_1.0"
    / "open_slovene_wordnet.xml"
)
OUT_TSV = REPO_ROOT / "data" / "processed" / "ddds" / "oswn_ddds_link_v2.tsv"
OUT_STATS = REPO_ROOT / "data" / "processed" / "ddds" / "oswn_ddds_link_v2.stats.json"
OUT_SAMPLE = REPO_ROOT / "data" / "processed" / "ddds" / "oswn_ddds_link_v2.sample.tsv"

SAMPLE_WORDS = {"kos", "most", "mesec", "zvezda", "srce", "vlak", "jabolko", "pero"}
N_RANDOM_SAMPLE = 30


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    try:
        from linkingtk.algorithms.string_similarity import StringSimilarityLinker  # type: ignore[import-not-found]
        from linkingtk.blocking import ExactMatch, LabelOverlap  # type: ignore[import-not-found]
        from linkingtk.core import Entity  # type: ignore[import-not-found]
    except ImportError:
        print(
            "linkingtk is not installed in this environment.\n"
            "Run with a python that has it, e.g. the spike venv:\n"
            r"  C:\Users\ailab\AppData\Local\Temp\opencode\ltk-spike\.venv\Scripts\python.exe scripts\relink_oswn.py"
        )
        return 1

    started = time.time()
    print("loading DDDS senses ...", flush=True)
    ddds_entities = []
    id_lemma: dict[str, str] = {}
    with LEXICAL_CORE.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            description = " | ".join(d["text"] for d in rec["definitions"])
            sid = str(rec["sense_id"])
            id_lemma[sid] = rec["lemma"]
            ddds_entities.append(Entity(id=sid, labels=[rec["lemma"]], description=description))
    print(f"  {len(ddds_entities)} DDDS senses", flush=True)

    print("loading OSWN ...", flush=True)
    entries, synsets = load_oswn(OSWN_XML)
    sense_to_synset: dict[str, str] = {}
    oswn_entities = []
    for entry in entries:
        for sense in entry.senses:
            if not sense.synset_id:
                continue
            synset = synsets.get(sense.synset_id)
            gloss = ""
            if synset is not None:
                gloss = synset.gloss_sl or synset.gloss_en
            oswn_entities.append(
                Entity(id=sense.sense_id, labels=[entry.written_form], description=gloss)
            )
            sense_to_synset[sense.sense_id] = sense.synset_id
    print(f"  {len(oswn_entities)} OSWN senses in {len(synsets)} synsets", flush=True)

    linker = StringSimilarityLinker(
        source_field="description", target_field="description", metric="word_overlap"
    )
    print("linking: pass 1 = exact label match ...", flush=True)
    exact = linker.link(ddds_entities, oswn_entities, blocking=ExactMatch())
    matched_ids = {r.source_id for r in exact}
    remaining = [e for e in ddds_entities if e.id not in matched_ids]
    print(f"  pass 1: {len(exact)} links ({len(remaining)} senses left for pass 2)", flush=True)

    print("linking: pass 2 = approximate label overlap (unmatched only) ...", flush=True)
    approx = (
        linker.link(remaining, oswn_entities, blocking=LabelOverlap(max_matches=5))
        if remaining
        else []
    )
    print(
        f"  pass 2: {len(approx)} links; both passes done in {time.time() - started:.0f}s",
        flush=True,
    )

    tagged = [(r, "exact") for r in exact] + [(r, "approx") for r in approx]
    rows = [
        (
            result.source_id,
            id_lemma.get(result.source_id, ""),
            result.target_id,
            sense_to_synset.get(result.target_id, ""),
            float(result.score),
            method,
        )
        for result, method in tagged
    ]
    rows.sort(key=lambda r: int(r[0]))

    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_TSV.open("w", encoding="utf-8", newline="\n") as f:
        f.write("ddds_sense_id\tddds_lemma\toswn_sense_id\toswn_synset_id\tscore\tmethod\n")
        for row in rows:
            f.write("{}\t{}\t{}\t{}\t{:.2f}\t{}\n".format(*row))

    matched = len({r[0] for r in rows})
    buckets: Counter[str] = Counter()
    for _, _, _, _, score, _ in rows:
        buckets["0" if score == 0 else "1" if score == 1 else "2" if score == 2 else "3+"] += 1

    stats = {
        "method": "linkingtk StringSimilarityLinker(word_overlap) + LabelOverlap(max_matches=5)",
        "ddds_senses": len(ddds_entities),
        "oswn_senses": len(oswn_entities),
        "oswn_synsets": len(synsets),
        "links": len(rows),
        "links_exact": len(exact),
        "links_approx": len(approx),
        "ddds_senses_with_exact_link": len(matched_ids),
        "ddds_senses_matched": matched,
        "ddds_senses_unmatched": len(ddds_entities) - matched,
        "score_buckets": dict(buckets),
        "distinct_synsets_linked": len({r[3] for r in rows}),
        "lexical_core_sha256": _sha256(LEXICAL_CORE),
        "oswn_xml_sha256": _sha256(OSWN_XML),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    OUT_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    rng = random.Random(0)
    sample = [r for r in rows if r[1] in SAMPLE_WORDS]
    rest = [r for r in rows if r[1] not in SAMPLE_WORDS]
    sample += rng.sample(rest, min(N_RANDOM_SAMPLE, len(rest)))
    with OUT_SAMPLE.open("w", encoding="utf-8", newline="\n") as f:
        f.write("ddds_sense_id\tddds_lemma\toswn_sense_id\toswn_synset_id\tscore\tmethod\n")
        for row in sample:
            f.write("{}\t{}\t{}\t{}\t{:.2f}\t{}\n".format(*row))

    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"written: {OUT_TSV.name}, {OUT_STATS.name}, {OUT_SAMPLE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
