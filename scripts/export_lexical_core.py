"""CLI: export the lexical core of DDDS for the pilot (senses + definitions +
one-hop relations), one JSONL record per real sense with >= 1 definition.

Output (default ``data/processed/ddds/lexical_core.jsonl``) is the single
working artifact for variants B (embeddings), C and oracle (structured lookup)
and for question building. Records:

    {sense_id, position, lemma, pos, lu_type,
     definitions: [{type, text}],
     synonyms|antonyms|hypernyms|hyponyms: [[sense_id, text], ...],
     dependencies: [[sense_id, form], ...],   # typical collocations (capped)
     example_count}

``dependencies`` are DDDS sense relations of type ``dependency`` (an
independent sense -> senses of dependent units such as "kos kruha"); they act
as per-sense collocation signals for variant C.

Usage:
    uv run python scripts/export_lexical_core.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from elexai.sources.ddds import (
    ddds_connect,
    find_join_path,
    fk_edges,
    prepare_analytics,
    query,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl"

REL_TYPES = ("synonym", "antonym", "hypernym", "hyponym", "dependency")
DEPENDENCY_CAP = 24  # per sense, deterministic (ordered by target sense id)


def _join_fragment(conn, start_table: str, alias_prefix: str = "p") -> tuple[str, str]:
    """JOIN fragment from a lexical unit to its first-part lexeme + alias."""
    path = find_join_path(fk_edges(conn), start_table, "jedro_lexeme")
    if not path:
        raise SystemExit(f"could not discover FK path {start_table} -> jedro_lexeme")
    joins: list[str] = []
    prev = "lu"
    for i, (tbl, ncol, pcol) in enumerate(path):
        alias = f"{alias_prefix}{i}"
        joins.append(f"JOIN {tbl} {alias} ON {alias}.{ncol} = {prev}.{pcol}")
        prev = alias
    return " ".join(joins), prev


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    conn = ddds_connect(REPO_ROOT)
    prepare_analytics(conn)

    lemma_join, lexeme_alias = _join_fragment(conn, "jedro_lexicalunit", "p")
    rel_join, rel_alias = _join_fragment(conn, "jedro_lexicalunit", "q")

    print("fetching senses ...", flush=True)
    senses = query(
        conn,
        f"""
        SELECT DISTINCT ON (s.id)
               s.id AS sense_id, s.position, {lexeme_alias}.lemma AS lemma,
               c.name AS pos, lt.name AS lu_type
        FROM jedro_sense s
        JOIN jedro_lexicalunit lu ON lu.id = s.lexical_unit_id
        {lemma_join}
        LEFT JOIN jedro_category c ON c.id = {lexeme_alias}.category_id
        LEFT JOIN jedro_lexicalunittype lt ON lt.id = lu.type_id
        WHERE s.position IS NOT NULL
          AND EXISTS (SELECT 1 FROM jedro_definition d WHERE d.sense_id = s.id)
        ORDER BY s.id, p0.id
        """,
    )
    sense_ids = {int(r["sense_id"]) for r in senses}
    print(f"  {len(senses)} senses with >= 1 definition", flush=True)

    print("fetching definitions ...", flush=True)
    definitions: dict[int, list[dict]] = defaultdict(list)
    for row in query(
        conn,
        """
        SELECT d.sense_id, dt.name AS dtype, d.description
        FROM jedro_definition d
        JOIN jedro_definitiontype dt ON dt.id = d.type_id
        JOIN jedro_sense s ON s.id = d.sense_id
        WHERE s.position IS NOT NULL
        ORDER BY d.sense_id,
                 CASE dt.name WHEN 'indicator' THEN 0 WHEN 'general' THEN 1 ELSE 2 END,
                 d.id
        """,
    ):
        sid = int(row["sense_id"])
        if sid in sense_ids:
            definitions[sid].append({"type": row["dtype"], "text": row["description"]})
    print(f"  {sum(len(v) for v in definitions.values())} definitions", flush=True)

    print("fetching sense relations ...", flush=True)
    relations: dict[int, dict[str, list[list]]] = defaultdict(
        lambda: {t: [] for t in REL_TYPES}
    )
    for row in query(
        conn,
        f"""
        SELECT DISTINCT r.from_sense_id, t.name AS rtype, r.to_sense_id,
               COALESCE(NULLIF(lu.form, ''), {rel_alias}.lemma) AS to_text
        FROM jedro_senserelation r
        JOIN jedro_senserelationtype t ON t.id = r.type_id
        JOIN jedro_sense s2 ON s2.id = r.to_sense_id
        JOIN jedro_lexicalunit lu ON lu.id = s2.lexical_unit_id
        {rel_join}
        WHERE t.name = ANY(%s)
          AND r.from_sense_id IN (
              SELECT id FROM jedro_sense WHERE position IS NOT NULL
          )
        ORDER BY r.from_sense_id, r.to_sense_id
        """,
        (list(REL_TYPES),),
    ):
        frm = int(row["from_sense_id"])
        if frm not in sense_ids:
            continue
        bucket = relations[frm][row["rtype"]]
        if row["rtype"] == "dependency" and len(bucket) >= DEPENDENCY_CAP:
            continue
        bucket.append([int(row["to_sense_id"]), row["to_text"]])
    n_rel = sum(len(v) for rels in relations.values() for v in rels.values())
    print(f"  {n_rel} relation rows kept", flush=True)

    print("fetching example counts ...", flush=True)
    example_counts: dict[int, int] = {}
    for row in query(
        conn,
        """
        SELECT e.sense_id, count(*) AS n
        FROM jedro_sense_example e
        JOIN jedro_sense s ON s.id = e.sense_id
        WHERE s.position IS NOT NULL
        GROUP BY e.sense_id
        """,
    ):
        example_counts[int(row["sense_id"])] = int(row["n"])
    print(f"  example links for {len(example_counts)} senses", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_written = 0
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for record in sorted(senses, key=lambda r: int(r["sense_id"])):
            sid = int(record["sense_id"])
            rels = relations.get(sid, {})
            row = {
                "sense_id": sid,
                "position": record["position"],
                "lemma": record["lemma"],
                "pos": record["pos"],
                "lu_type": record["lu_type"],
                "definitions": definitions.get(sid, []),
                "synonyms": rels.get("synonym", []),
                "antonyms": rels.get("antonym", []),
                "hypernyms": rels.get("hypernym", []),
                "hyponyms": rels.get("hyponym", []),
                "dependencies": rels.get("dependency", []),
                "example_count": example_counts.get(sid, 0),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_written += 1
    conn.close()
    print(f"wrote {n_written} records to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
