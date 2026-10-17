"""CLI: load the graph for variant D (graph RAG) into Neo4j.

Inputs (all under data/...; missing optional pieces are skipped with a note):

- ``data/processed/ddds/lexical_core.jsonl`` -> Lexeme/Sense nodes, HAS_SENSE,
  COLLOCATES_WITH, sense relations (synonym/antonym/hypernym/hyponym)
- ``data/processed/ddds/oswn_ddds_link_v2.tsv`` -> IN_SYNSET edges
  (produced by scripts/relink_oswn.py; exact-lemma links load by default,
  --include-approx adds approximate-label links above --min-score)
- ``data/raw/.../open_slovene_wordnet.xml`` -> Synset nodes (glosses, literals)
  (OSWN ships no relations - verified; the hierarchy comes from:)
- ``data/raw/oewn/english-wordnet-2023.xml`` -> synset relations, mapped by id
  equality (OSWN ids are OEWN ids with a swapped prefix; verified 99.98%)
- ``data/processed/ddds/collocation_parts.tsv`` -> Phrase -[:HAS_PART]-> Lexeme
  (produced by scripts/export_collocation_parts.py)

Idempotent (MERGE everywhere). Recommended for the first v2 load: wipe the
database first in Neo4j Browser (:  MATCH (n) DETACH DELETE n  ) and re-run
this loader. Connection details come from .env (NEO4J_URI defaults to
bolt://localhost:7687 for Neo4j Desktop).

Usage:
    uv run python scripts/load_graph.py                  # full load
    uv run python scripts/load_graph.py --quick          # 2000 senses only (smoke)
    uv run python scripts/load_graph.py --include-approx  # also approximate links
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from typing import Any

from elexai.config import GraphConfig
from elexai.env import REPO_ROOT, load_env
from elexai.sources.oswn import literals_for, load_oswn

LEXICAL_CORE = REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl"
LINK_TSV = REPO_ROOT / "data" / "processed" / "ddds" / "oswn_ddds_link_v2.tsv"
PARTS_TSV = REPO_ROOT / "data" / "processed" / "ddds" / "collocation_parts.tsv"
OSWN_XML = (
    REPO_ROOT
    / "data"
    / "raw"
    / "open_slovene_wordnet_1.0"
    / "open_slovene_wordnet_1.0"
    / "open_slovene_wordnet.xml"
)
OEWN_XML = REPO_ROOT / "data" / "raw" / "oewn" / "english-wordnet-2023.xml"

CONSTRAINTS = [
    "CREATE CONSTRAINT sense_id_unique IF NOT EXISTS FOR (s:Sense) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT phrase_form_unique IF NOT EXISTS FOR (p:Phrase) REQUIRE p.form IS UNIQUE",
    "CREATE CONSTRAINT synset_id_unique IF NOT EXISTS FOR (y:Synset) REQUIRE y.id IS UNIQUE",
    "CREATE INDEX lexeme_lemma IF NOT EXISTS FOR (l:Lexeme) ON (l.lemma)",
]

SENSES_CYPHER = """
UNWIND $rows AS row
MERGE (l:Lexeme {lemma: row.lemma, pos: row.pos})
MERGE (s:Sense {id: row.sense_id})
SET s.position = row.position,
    s.indicator = row.indicator,
    s.definition = row.definition,
    s.lu_type = row.lu_type,
    s.example_count = row.example_count
MERGE (l)-[:HAS_SENSE]->(s)
"""

PHRASES_CYPHER = "UNWIND $rows AS row MERGE (p:Phrase {form: row.form})"

COLLOCATIONS_CYPHER = """
UNWIND $rows AS row
MATCH (s:Sense {id: row.sense_id})
MATCH (p:Phrase {form: row.form})
MERGE (s)-[:COLLOCATES_WITH]->(p)
"""

REL_CYPHER = """
UNWIND $rows AS row
MATCH (a:Sense {id: row.from_id})
MATCH (b:Sense {id: row.to_id})
MERGE (a)-[:{rtype}]->(b)
"""

SYNSETS_CYPHER = """
UNWIND $rows AS row
MERGE (y:Synset {id: row.synset_id})
SET y.ili = row.ili, y.gloss_en = row.gloss_en, y.gloss_sl = row.gloss_sl,
    y.literals = row.literals
"""

SYNSET_REL_CYPHER = """
UNWIND $rows AS row
MATCH (a:Synset {id: row.a})
MATCH (b:Synset {id: row.b})
MERGE (a)-[:{rtype}]->(b)
"""

IN_SYNSET_CYPHER = """
UNWIND $rows AS row
MATCH (s:Sense {id: row.sense_id})
MATCH (y:Synset {id: row.synset_id})
MERGE (s)-[r:IN_SYNSET]->(y)
SET r.score = row.score, r.method = row.method
"""

HAS_PART_CYPHER = """
UNWIND $rows AS row
MATCH (p:Phrase {form: row.form})
MERGE (l:Lexeme {lemma: row.part_lemma, pos: row.part_pos})
MERGE (p)-[:HAS_PART]->(l)
"""

REL_TYPES = {
    "synonyms": "SYNONYM",
    "antonyms": "ANTONYM",
    "hypernyms": "HYPERNYM",
    "hyponyms": "HYPONYM",
}


def _batches(session: Any, cypher: str, rows: list[dict], batch: int, label: str) -> None:
    total = len(rows)
    for i in range(0, total, batch):
        chunk = rows[i : i + batch]

        def _write(tx: Any, chunk: list[dict] = chunk) -> None:
            tx.run(cypher, rows=chunk).consume()

        session.execute_write(_write)
        if (i // batch) % 20 == 0 or i + batch >= total:
            print(f"  {label}: {min(i + batch, total)}/{total}", flush=True)


def _rel_type(rel: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", rel).upper()


def _collect_core(
    quick: bool,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    sense_rows: list[dict] = []
    coll_rows: list[dict] = []
    rel_rows: list[dict] = []
    phrase_set: set[str] = set()
    loaded_ids: set[int] = set()
    with LEXICAL_CORE.open(encoding="utf-8") as f:
        for line in f:
            if quick and len(loaded_ids) >= 2000:
                break
            rec = json.loads(line)
            sid = int(rec["sense_id"])
            loaded_ids.add(sid)
            indicator = next(
                (d["text"] for d in rec["definitions"] if d.get("type") == "indicator"), ""
            )
            sense_rows.append(
                {
                    "sense_id": sid,
                    "lemma": rec["lemma"],
                    "pos": rec.get("pos") or "",
                    "position": rec.get("position"),
                    "indicator": indicator,
                    "definition": " | ".join(d["text"] for d in rec["definitions"]),
                    "lu_type": rec.get("lu_type"),
                    "example_count": int(rec.get("example_count") or 0),
                }
            )
            for dep in rec.get("dependencies") or []:
                form = dep[1]
                if form:
                    coll_rows.append({"sense_id": sid, "form": form})
                    phrase_set.add(form)
            for key, rtype in REL_TYPES.items():
                for other in rec.get(key) or []:
                    rel_rows.append({"from_id": sid, "to_id": int(other[0]), "rtype": rtype})
    sense_rows.sort(key=lambda r: r["sense_id"])
    phrase_rows = [{"form": form} for form in sorted(phrase_set)]
    rel_rows = [r for r in rel_rows if r["from_id"] in loaded_ids and r["to_id"] in loaded_ids]
    return sense_rows, coll_rows, rel_rows, phrase_rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="2000 senses, skip synsets/parts")
    ap.add_argument("--batch", type=int, default=2000)
    ap.add_argument(
        "--include-approx",
        action="store_true",
        help="also load approximate-label links (default: exact-lemma links only)",
    )
    ap.add_argument(
        "--min-score",
        type=float,
        default=1.0,
        help="min description score for approximate links when --include-approx is used",
    )
    args = ap.parse_args()

    if not LEXICAL_CORE.exists():
        print(f"lexical core not found: {LEXICAL_CORE}\nrun: uv run python scripts/export_lexical_core.py")
        return 1

    load_env()
    cfg = GraphConfig()
    import os

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("the 'neo4j' package is not installed (uv sync)")
        return 1

    uri = os.environ.get(cfg.uri_env) or cfg.default_uri
    user = os.environ.get(cfg.user_env, "neo4j")
    password = os.environ.get(cfg.password_env, "")
    if not password:
        print(f"environment variable {cfg.password_env!r} is not set (add it to .env)")
        return 1

    print(f"parsing {LEXICAL_CORE.name} ...", flush=True)
    sense_rows, coll_rows, rel_rows, phrase_rows = _collect_core(args.quick)
    print(
        f"  senses: {len(sense_rows)}, phrases: {len(phrase_rows)}, "
        f"collocation edges: {len(coll_rows)}, sense relations: {len(rel_rows)}"
        + ("  [QUICK MODE]" if args.quick else ""),
        flush=True,
    )

    synset_rows: list[dict] = []
    synset_rel_rows: dict[str, list[dict]] = defaultdict(list)
    link_rows: list[dict] = []
    part_rows: list[dict] = []
    skipped_low_score = 0
    skipped_approx = 0

    if args.quick:
        print("QUICK MODE: skipping synsets, re-link edges and phrase components", flush=True)
    else:
        if OSWN_XML.exists():
            print("parsing OSWN synsets ...", flush=True)
            entries, synsets = load_oswn(OSWN_XML)
            entries_by_id = {e.entry_id: e for e in entries}
            for syn in synsets.values():
                synset_rows.append(
                    {
                        "synset_id": syn.synset_id,
                        "ili": syn.ili or "",
                        "gloss_en": syn.gloss_en,
                        "gloss_sl": syn.gloss_sl,
                        "literals": literals_for(syn, entries_by_id),
                    }
                )
            print(f"  synsets: {len(synset_rows)}", flush=True)
        else:
            print(f"OSWN XML not found ({OSWN_XML}) - synset layer skipped", flush=True)

        if OEWN_XML.exists():
            print("parsing OEWN relations (ids match OSWN by prefix swap) ...", flush=True)
            _, oewn_synsets = load_oswn(OEWN_XML)
            for syn in oewn_synsets.values():
                if not syn.synset_id.startswith("oewn-"):
                    continue
                sid = "oswn-" + syn.synset_id[len("oewn-") :]
                for rel_type, target in syn.relations:
                    if target.startswith("oewn-"):
                        target_oswn = "oswn-" + target[len("oewn-") :]
                        synset_rel_rows[_rel_type(rel_type)].append({"a": sid, "b": target_oswn})
            print(
                f"  synset relation edges (before endpoint matching): "
                f"{sum(len(v) for v in synset_rel_rows.values())}",
                flush=True,
            )
        else:
            print(f"OEWN XML not found ({OEWN_XML}) - hierarchy edges skipped", flush=True)

        if LINK_TSV.exists():
            print(f"reading {LINK_TSV.name} ...", flush=True)
            with LINK_TSV.open(encoding="utf-8") as f:
                next(f)
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) != 6:
                        continue
                    score = float(parts[4])
                    method = parts[5]
                    if method != "exact":
                        if not args.include_approx:
                            skipped_approx += 1
                            continue
                        if score < args.min_score:
                            skipped_low_score += 1
                            continue
                    link_rows.append(
                        {
                            "sense_id": int(parts[0]),
                            "synset_id": parts[3],
                            "score": score,
                            "method": method,
                        }
                    )
            print(
                f"  IN_SYNSET edges: {len(link_rows)} "
                f"(approximate skipped: {skipped_approx}; below min-score: {skipped_low_score})",
                flush=True,
            )
        else:
            print(f"link table not found ({LINK_TSV.name}) - run scripts/relink_oswn.py first", flush=True)
            print("  synset layer will be loaded, but senses stay disconnected from it", flush=True)

        if PARTS_TSV.exists():
            print(f"reading {PARTS_TSV.name} ...", flush=True)
            with PARTS_TSV.open(encoding="utf-8") as f:
                next(f)
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) == 3 and parts[0]:
                        part_rows.append({"form": parts[0], "part_lemma": parts[1], "part_pos": parts[2]})
            print(f"  HAS_PART rows: {len(part_rows)}", flush=True)
        else:
            print(f"parts file not found ({PARTS_TSV.name}) - run scripts/export_collocation_parts.py", flush=True)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        print(f"cannot connect to Neo4j at {uri}: {exc}")
        print("is the database running in Neo4j Desktop?")
        return 1

    started = time.time()
    print(f"connected to {uri}; loading (idempotent, safe to re-run) ...", flush=True)
    with driver.session() as session:
        for constraint in CONSTRAINTS:
            session.run(constraint).consume()
        _batches(session, SENSES_CYPHER, sense_rows, args.batch, "lexemes+senses")
        _batches(session, PHRASES_CYPHER, phrase_rows, args.batch, "phrases")
        _batches(session, COLLOCATIONS_CYPHER, coll_rows, args.batch, "collocations")
        for rtype in sorted(set(REL_TYPES.values())):
            rows = [r for r in rel_rows if r["rtype"] == rtype]
            if rows:
                _batches(session, REL_CYPHER.replace("{rtype}", rtype), rows, args.batch, f"rel {rtype}")
        if synset_rows:
            _batches(session, SYNSETS_CYPHER, synset_rows, args.batch, "synsets")
            for rtype in sorted(synset_rel_rows):
                _batches(
                    session,
                    SYNSET_REL_CYPHER.replace("{rtype}", rtype),
                    synset_rel_rows[rtype],
                    args.batch,
                    f"synset rel {rtype}",
                )
        if link_rows:
            _batches(session, IN_SYNSET_CYPHER, link_rows, args.batch, "IN_SYNSET")
        if part_rows:
            _batches(session, HAS_PART_CYPHER, part_rows, args.batch, "HAS_PART")

    print("done; verifying counts:", flush=True)
    checks = [
        ("MATCH (l:Lexeme) RETURN count(l) AS n", "lexemes"),
        ("MATCH (s:Sense) RETURN count(s) AS n", "senses"),
        ("MATCH (p:Phrase) RETURN count(p) AS n", "phrases"),
        ("MATCH (y:Synset) RETURN count(y) AS n", "synsets"),
        ("MATCH ()-[r:COLLOCATES_WITH]->() RETURN count(r) AS n", "COLLOCATES_WITH"),
        ("MATCH ()-[r:HAS_PART]->() RETURN count(r) AS n", "HAS_PART"),
        ("MATCH ()-[r:IN_SYNSET]->() RETURN count(r) AS n", "IN_SYNSET"),
        ("MATCH (:Sense)-[r:SYNONYM]->(:Sense) RETURN count(r) AS n", "SYNONYM (sense)"),
        ("MATCH (:Sense)-[r:ANTONYM]->(:Sense) RETURN count(r) AS n", "ANTONYM (sense)"),
        ("MATCH (:Sense)-[r:HYPERNYM]->(:Sense) RETURN count(r) AS n", "HYPERNYM (sense)"),
        ("MATCH (:Sense)-[r:HYPONYM]->(:Sense) RETURN count(r) AS n", "HYPONYM (sense)"),
    ]
    with driver.session() as session:
        for query, label in checks:
            record = session.run(query).single()
            print(f"  {label}: {record['n'] if record else 0}")
        print("  synset-level relation counts (top 12):")
        for record in session.run(
            "MATCH (:Synset)-[r]->(:Synset) RETURN type(r) AS t, count(r) AS n "
            "ORDER BY n DESC LIMIT 12"
        ):
            print(f"    {record['t']}: {record['n']}")
    driver.close()
    print(f"finished in {(time.time() - started) / 60:.1f} min - re-running is safe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
