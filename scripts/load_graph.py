"""CLI: load the lexical core into Neo4j for variant D (graph RAG).

Expects an (empty) database; safe to re-run - everything is MERGE-based and
idempotent. Reads connection details from the repository .env
(``NEO4J_URI`` / ``NEO4J_USER`` / ``NEO4J_PASSWORD``; URI defaults to
``bolt://localhost:7687`` for Neo4j Desktop).

Usage:
    uv run python scripts/load_graph.py            # full load (~5-10 min)
    uv run python scripts/load_graph.py --quick    # first 2000 senses (smoke test)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from elexai.config import GraphConfig
from elexai.env import REPO_ROOT, load_env

LEXICAL_CORE = REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl"

CONSTRAINTS = [
    "CREATE CONSTRAINT sense_id_unique IF NOT EXISTS FOR (s:Sense) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT phrase_form_unique IF NOT EXISTS FOR (p:Phrase) REQUIRE p.form IS UNIQUE",
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

REL_TYPES = {"synonyms": "SYNONYM", "antonyms": "ANTONYM", "hypernyms": "HYPERNYM", "hyponyms": "HYPONYM"}


def _batches(session: Any, cypher: str, rows: list[dict], batch: int, label: str) -> None:
    total = len(rows)
    for i in range(0, total, batch):
        chunk = rows[i : i + batch]

        def _write(tx: Any, chunk: list[dict] = chunk) -> None:
            tx.run(cypher, rows=chunk).consume()

        session.execute_write(_write)
        if (i // batch) % 20 == 0 or i + batch >= total:
            print(f"  {label}: {min(i + batch, total)}/{total}", flush=True)


def _collect(
    quick: bool,
) -> tuple[list[dict], list[dict], list[dict], set[str], list[dict]]:
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
                    "pos": rec.get("pos"),
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
    phrases = [{"form": form} for form in sorted(phrase_set)]
    rel_kept = [r for r in rel_rows if r["from_id"] in loaded_ids and r["to_id"] in loaded_ids]
    return sense_rows, coll_rows, rel_kept, phrase_set, phrases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="load only the first 2000 senses")
    ap.add_argument("--batch", type=int, default=2000)
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
    sense_rows, coll_rows, rel_rows, phrase_set, phrase_rows = _collect(args.quick)
    print(
        f"  senses: {len(sense_rows)}, phrases: {len(phrase_set)}, "
        f"collocation edges: {len(coll_rows)}, relation edges: {len(rel_rows)}"
        + ("  [QUICK MODE]" if args.quick else ""),
        flush=True,
    )

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
        for c in CONSTRAINTS:
            session.run(c).consume()
        _batches(session, SENSES_CYPHER, sense_rows, args.batch, "lexemes+senses")
        _batches(session, PHRASES_CYPHER, phrase_rows, args.batch, "phrases")
        _batches(session, COLLOCATIONS_CYPHER, coll_rows, args.batch, "collocations")
        for rtype in sorted(set(REL_TYPES.values())):
            rows = [r for r in rel_rows if r["rtype"] == rtype]
            if rows:
                _batches(session, REL_CYPHER.replace("{rtype}", rtype), rows, args.batch, f"rel {rtype}")

    print("done; verifying counts:", flush=True)
    checks = [
        ("MATCH (l:Lexeme) RETURN count(l) AS n", "lexemes"),
        ("MATCH (s:Sense) RETURN count(s) AS n", "senses"),
        ("MATCH (p:Phrase) RETURN count(p) AS n", "phrases"),
        ("MATCH ()-[r:COLLOCATES_WITH]->() RETURN count(r) AS n", "collocations"),
        ("MATCH ()-[r:SYNONYM]->() RETURN count(r) AS n", "synonym edges"),
        ("MATCH ()-[r:ANTONYM]->() RETURN count(r) AS n", "antonym edges"),
        ("MATCH ()-[r:HYPERNYM]->() RETURN count(r) AS n", "hypernym edges"),
        ("MATCH ()-[r:HYPONYM]->() RETURN count(r) AS n", "hyponym edges"),
    ]
    with driver.session() as session:
        for query, label in checks:
            record = session.run(query).single()
            print(f"  {label}: {record['n'] if record else 0}")
    driver.close()
    print(f"finished in {(time.time() - started) / 60:.1f} min - re-running is safe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
