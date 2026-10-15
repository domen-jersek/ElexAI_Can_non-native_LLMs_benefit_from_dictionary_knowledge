"""CLI: Phase-0 inspection of every source; prints a report, writes JSON.

Covers:
  - Open Slovene WordNet 1.0 (XML)
  - sloWNet 3.1 (DEBVisDic XML)
  - OSWN <-> DDDS linked senses (TSV)
  - DDDS PostgreSQL snapshot (requires scripts/db_restore.py to have run)

The JSON output (data/processed/inspection/phase0_inspection.json) is the
machine-readable basis for the numbers quoted in docs/DATA.md.

Usage:
    uv run python scripts/inspect_data.py             # all sources, prints report
    uv run python scripts/inspect_data.py --no-db     # skip the DDDS database part
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from elexai.sources.ddds import (
    ddds_connect,
    find_join_path,
    fk_edges,
    prepare_analytics,
    query,
    table_columns,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW = REPO_ROOT / "data" / "raw"
OUT_JSON = REPO_ROOT / "data" / "processed" / "inspection" / "phase0_inspection.json"

console = Console()

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_SUBSTITUTIONS = {
    "--hy--": "-", "\u2212": "-", "\u2013": "-", "--am--": "&", "--lt--": "<",
    "--gt--": ">", "--qt--": '"', "--ap--": "'", "_": " ", "--cm--": ",",
    "--ex--": "!", "\u200b": " ", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u201e": '"', "\u2026": "\u2026", "--dt--": "\u2026", "--pc--": "%",
    "--pl--": "(", "--pr--": ")", "--do--": ".", "--ss--": "/", "--cl--": ":",
    "--qu--": "?", "`": "'", "--dg--": "\u00b0",
}


def unescape_oswn_lemma(s: str) -> str:
    for k in sorted(_SUBSTITUTIONS, key=len, reverse=True):
        s = s.replace(k, _SUBSTITUTIONS[k])
    return s


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def top(counter: Counter, n: int = 12) -> list[list]:
    return [[k, v] for k, v in counter.most_common(n)]


def print_table(title: str, rows: list[list], headers: list[str]) -> None:
    t = Table(title=title, show_lines=False)
    for h in headers:
        t.add_column(h)
    for r in rows:
        t.add_row(*[str(x) for x in r])
    console.print(t)


# ---------------------------------------------------------------------------
# OSWN 1.0
# ---------------------------------------------------------------------------

def inspect_oswn(path: Path) -> dict:
    entries: list[dict] = []
    synsets: dict[str, dict] = {}
    for _, elem in ET.iterparse(path, events=("end",)):
        tag = local(elem.tag)
        if tag == "LexicalEntry":
            lemma_el = elem.find("{*}Lemma")
            senses = [
                {"id": s.get("id"), "synset": s.get("synset")}
                for s in elem.findall("{*}Sense")
            ]
            entries.append(
                {
                    "id": elem.get("id"),
                    "written_form": lemma_el.get("writtenForm") if lemma_el is not None else None,
                    "pos": lemma_el.get("partOfSpeech") if lemma_el is not None else None,
                    "n_senses": len(senses),
                    "senses": senses,
                }
            )
            elem.clear()
        elif tag == "Synset":
            defs = {}
            status: Counter[str] = Counter()
            for d in elem.findall("{*}Definition"):
                lang = d.get("language")
                st = d.get("status")
                status[st] += 1
                if lang and lang not in defs:
                    defs[lang] = (d.text or "").strip()
            synsets[elem.get("id")] = {
                "ili": elem.get("ili"),
                "pos": elem.get("partOfSpeech"),
                "members": (elem.get("members") or "").split(),
                "defs": defs,
                "status": dict(status),
            }
            elem.clear()

    n_senses = sum(e["n_senses"] for e in entries)
    poly = sorted((e for e in entries if e["n_senses"] >= 3), key=lambda e: -e["n_senses"])
    samples = []
    for e in poly[:10]:
        lemma = unescape_oswn_lemma(e["written_form"] or "")
        senses = []
        for s in e["senses"][:5]:
            sy = synsets.get(s["synset"], {})
            senses.append(
                {
                    "sense_id": s["id"],
                    "synset_id": s["synset"],
                    "def_sl": sy.get("defs", {}).get("sl"),
                    "def_en": sy.get("defs", {}).get("en"),
                }
            )
        samples.append({"entry_id": e["id"], "lemma": lemma, "pos": e["pos"],
                        "n_senses": e["n_senses"], "senses": senses})

    ids = {e["id"] for e in entries}
    dangling = [s["synset"] for e in entries for s in e["senses"] if s["synset"] not in synsets]
    escaped = sum(1 for e in entries if "--" in (e["written_form"] or ""))
    empty_defs = sum(
        1 for sy in synsets.values() if not (sy["defs"].get("sl") or "").strip()
    )
    def_status: Counter[str] = Counter()
    for sy in synsets.values():
        def_status.update(sy["status"])

    return {
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "lexical_entries": len(entries),
        "senses": n_senses,
        "synsets": len(synsets),
        "synsets_with_ili": sum(1 for sy in synsets.values() if sy.get("ili")),
        "def_languages": top(Counter(lang for sy in synsets.values() for lang in sy["defs"]), 5),
        "definition_statuses": dict(def_status),
        "entries_with_ge3_senses": len(poly),
        "entries_with_ge5_senses": sum(1 for e in entries if e["n_senses"] >= 5),
        "entries_with_escaped_lemma": escaped,
        "empty_sl_definitions": empty_defs,
        "dangling_synset_refs": len(dangling),
        "synset_pos_distribution": top(Counter(sy["pos"] for sy in synsets.values())),
        "samples_polysemous": samples,
        "unique_entry_ids": len(ids),
    }


# ---------------------------------------------------------------------------
# sloWNet 3.1
# ---------------------------------------------------------------------------

def inspect_slownet(path: Path) -> dict:
    n = 0
    pos: Counter[str] = Counter()
    defs: Counter[str] = Counter()
    literals: Counter[str] = Counter()
    literals_auto: Counter[str] = Counter()
    usages: Counter[str] = Counter()
    ilr: Counter[str] = Counter()
    ilr_types: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    sample_sl_defs: list[dict] = []
    most_sl_literals: list[tuple] = []
    for _, elem in ET.iterparse(path, events=("end",)):
        if local(elem.tag) != "SYNSET":
            continue
        n += 1
        sid = (elem.findtext("{*}ID") or "").strip()
        pos[(elem.findtext("{*}POS") or "").strip()] += 1
        for syn in elem.findall("{*}SYNONYM"):
            lang = syn.get("{http://www.w3.org/XML/1998/namespace}lang")
            lits = syn.findall("{*}LITERAL")
            literals[lang] += len(lits)
            for li in lits:
                if li.get("lnote") == "auto":
                    literals_auto[lang] += 1
        for d in elem.findall("{*}DEF"):
            lang = d.get("{http://www.w3.org/XML/1998/namespace}lang")
            defs[lang] += 1
            if lang == "sl" and len(sample_sl_defs) < 5:
                sample_sl_defs.append({"synset": sid, "def": (d.text or "").strip()[:200]})
        for u in elem.findall("{*}USAGE"):
            usages[u.get("{http://www.w3.org/XML/1998/namespace}lang")] += 1
        for i in elem.findall("{*}ILR"):
            ilr_types[i.get("type")] += 1
        for dom in elem.findall("{*}DOMAIN"):
            domains[(dom.text or "").strip()] += 1
        sl_lits = sum(
            len(s.findall("{*}LITERAL"))
            for s in elem.findall("{*}SYNONYM")
            if s.get("{http://www.w3.org/XML/1998/namespace}lang") == "sl"
        )
        if sl_lits:
            most_sl_literals.append((sl_lits, sid))
        elem.clear()

    most_sl_literals.sort(reverse=True)
    return {
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "synsets": n,
        "pos_distribution": top(pos, 6),
        "defs_by_language": dict(defs),
        "literals_by_language": dict(literals),
        "literals_auto_by_language": dict(literals_auto),
        "usages_by_language": dict(usages),
        "ilr_relation_counts": dict(ilr),
        "top_ilr_types": top(ilr_types),
        "top_domains": top(domains),
        "sample_sl_definitions": sample_sl_defs,
        "synsets_with_most_sl_literals": most_sl_literals[:10],
    }


# ---------------------------------------------------------------------------
# OSWN <-> DDDS link TSV
# ---------------------------------------------------------------------------

def inspect_link_tsv(path: Path) -> dict:
    rows = 0
    synsets: set[str] = set()
    senses: Counter = Counter()
    lus: set[str] = set()
    bad = 0
    forms_multiword = 0
    per_synset: Counter[str] = Counter()
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        for row in reader:
            if len(row) != 4:
                bad += 1
                continue
            synset_id, sense_id, lu_id, form = row
            rows += 1
            synsets.add(synset_id)
            senses[sense_id] += 1
            lus.add(lu_id)
            per_synset[synset_id] += 1
            if " " in form:
                forms_multiword += 1
    return {
        "file": path.name,
        "header": header,
        "rows": rows,
        "bad_rows": bad,
        "unique_synsets": len(synsets),
        "unique_senses": len(senses),
        "unique_lexical_units": len(lus),
        "duplicated_sense_ids": sum(1 for v in senses.values() if v > 1),
        "multiword_forms": forms_multiword,
        "top_synsets_by_linked_senses": top(per_synset, 10),
    }


# ---------------------------------------------------------------------------
# DDDS (PostgreSQL)
# ---------------------------------------------------------------------------

def inspect_ddds() -> dict | None:
    try:
        conn = ddds_connect(REPO_ROOT)
        prepare_analytics(conn)
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]DDDS DB not reachable ({e}); skipping DB part[/yellow]")
        return None

    out: dict = {}
    try:
        cols = table_columns(conn)
        out["tables_present"] = sorted(t for t in cols if t.startswith(("jedro_", "metadata_")))

        # --- core counts -------------------------------------------------
        counts = {}
        for t in [
            "jedro_lexeme", "jedro_lexicalunit", "jedro_sense", "jedro_definition",
            "jedro_senserelation", "jedro_example", "jedro_sense_example",
            "jedro_examplesentence", "jedro_lexicalunitpart", "jedro_wordform",
            "jedro_formrepresentation", "jedro_formencoding", "jedro_lexemerelation",
            "jedro_sensepart", "jedro_object_feature",
        ]:
            if t in cols:
                counts[t] = query(conn, f"SELECT count(*) AS n FROM {t}")[0]["n"]  # noqa: S608
        out["core_counts"] = counts

        # --- snapshot version --------------------------------------------
        if "metadata_version" in cols:
            out["metadata_version"] = query(
                conn, "SELECT * FROM metadata_version ORDER BY id DESC LIMIT 5"
            )

        # --- helper SQL fragments ----------------------------------------
        # path jedro_lexicalunit -> jedro_lexeme, discovered from FKs
        path = find_join_path(fk_edges(conn), "jedro_lexicalunit", "jedro_lexeme")
        lemma_join = ""
        lemma_col = "NULL::text"
        if path:
            joins = []
            prev_alias = "lu"
            for i, (tbl, ncol, pcol) in enumerate(path):
                alias = f"p{i}"
                joins.append(f"JOIN {tbl} {alias} ON {alias}.{ncol} = {prev_alias}.{pcol}")
                prev_alias = alias
            lemma_join = " ".join(joins)
            lemma_col = f"{prev_alias}.lemma"
        out["lemma_join_path"] = [list(step) for step in path] if path else None

        # --- lexical unit types ------------------------------------------
        if "jedro_lexicalunittype" in cols:
            out["lu_type_distribution"] = query(
                conn,
                "SELECT lt.name, count(*) AS n FROM jedro_lexicalunit lu "
                "JOIN jedro_lexicalunittype lt ON lt.id = lu.type_id "
                "GROUP BY 1 ORDER BY 2 DESC",
            )

        # --- senses ------------------------------------------------------
        out["sense_position"] = query(
            conn,
            "SELECT count(*) FILTER (WHERE position IS NULL) AS dummy_position_null, "
            "count(*) FILTER (WHERE position IS NOT NULL) AS real_senses, "
            "count(*) AS total FROM jedro_sense",
        )[0]

        # senses per lexical unit (real senses only) + >=3 polysemy counts
        out["senses_per_lu"] = query(
            conn,
            """
            WITH lu_s AS (
              SELECT s.lexical_unit_id AS lu_id,
                     count(*) FILTER (WHERE s.position IS NOT NULL) AS n
              FROM jedro_sense s GROUP BY 1
            )
            SELECT count(*) FILTER (WHERE n >= 2) AS ge2,
                   count(*) FILTER (WHERE n >= 3) AS ge3,
                   count(*) FILTER (WHERE n >= 4) AS ge4,
                   count(*) FILTER (WHERE n >= 10) AS ge10,
                   count(*) AS total_lexical_units
            FROM lu_s
            """,
        )[0]

        if path:
            out["senses_per_lemma"] = query(
                conn,
                f"""
                WITH lu_s AS (
                  SELECT s.lexical_unit_id AS lu_id,
                         count(*) FILTER (WHERE s.position IS NOT NULL) AS n
                  FROM jedro_sense s GROUP BY 1
                )
                SELECT count(DISTINCT {lemma_col}) FILTER (WHERE n >= 3) AS lemmas_ge3,
                       count(DISTINCT {lemma_col}) AS lemmas_total
                FROM lu_s ls
                JOIN jedro_lexicalunit lu ON lu.id = ls.lu_id
                {lemma_join}
                """,
            )[0]

        # --- definitions --------------------------------------------------
        out["definitions"] = query(
            conn,
            """
            SELECT count(*) AS total_definitions,
                   count(DISTINCT sense_id) AS senses_with_definition,
                   count(*) FILTER (WHERE btrim(description) = '') AS empty_definitions
            FROM jedro_definition
            """,
        )[0]
        out["definition_types"] = query(
            conn,
            "SELECT dt.name, count(*) AS n FROM jedro_definition d "
            "JOIN jedro_definitiontype dt ON dt.id = d.type_id GROUP BY 1 ORDER BY 2 DESC",
        )
        out["definitions_per_sense"] = query(
            conn,
            "SELECT avg(n)::numeric(10,2) AS avg_defs, max(n) AS max_defs "
            "FROM (SELECT sense_id, count(*) AS n FROM jedro_definition GROUP BY 1) x",
        )[0]

        # --- relations ----------------------------------------------------
        if "jedro_senserelationtype" in cols:
            out["sense_relation_types"] = query(
                conn,
                "SELECT t.name, count(*) AS n FROM jedro_senserelation r "
                "JOIN jedro_senserelationtype t ON t.id = r.type_id "
                "GROUP BY 1 ORDER BY 2 DESC",
            )

        # --- examples -----------------------------------------------------
        out["examples"] = query(
            conn,
            """
            SELECT count(*) AS sense_example_links,
                   count(DISTINCT sense_id) AS senses_with_example_link,
                   count(DISTINCT example_id) AS distinct_examples
            FROM jedro_sense_example
            """,
        )[0]

        # --- corpora / measures -------------------------------------------
        if "jedro_corpus" in cols:
            out["corpora"] = query(conn, "SELECT id, name, version FROM jedro_corpus ORDER BY id")
        if "jedro_measure" in cols and "jedro_sense_measure" in cols:
            out["sense_measures_by_type"] = query(
                conn,
                "SELECT m.name, count(*) AS n, count(DISTINCT sm.sense_id) AS senses "
                "FROM jedro_sense_measure sm JOIN jedro_measure m ON m.id = sm.measure_id "
                "GROUP BY 1 ORDER BY 2 DESC",
            )

        # --- resources (dictionary views) ---------------------------------
        if {"jedro_resource", "jedro_status", "jedro_resource_status", "jedro_lexicalunit_status"} <= set(cols):
            out["resources"] = query(conn, "SELECT id, name FROM jedro_resource ORDER BY id")
            out["statuses"] = query(conn, "SELECT id, name FROM jedro_status ORDER BY id")
            out["headwords_per_resource_status"] = query(
                conn,
                """
                SELECT r.name AS resource, s.name AS status, count(*) AS headwords
                FROM jedro_lexicalunit_status lus
                JOIN jedro_resource_status rs ON rs.id = lus.resource_status_id
                JOIN jedro_resource r ON r.id = rs.resource_id
                JOIN jedro_status s ON s.id = rs.status_id
                GROUP BY 1, 2 ORDER BY 3 DESC
                """,
            )

        # --- 10 polysemous samples (with definitions) ---------------------
        if path:
            samples = query(
                conn,
                f"""
                WITH lu_s AS (
                  SELECT s.lexical_unit_id AS lu_id,
                         count(*) FILTER (WHERE s.position IS NOT NULL) AS n
                  FROM jedro_sense s GROUP BY 1
                )
                SELECT ls.lu_id, ls.n AS senses, {lemma_col} AS lemma
                FROM lu_s ls
                JOIN jedro_lexicalunit lu ON lu.id = ls.lu_id
                {lemma_join}
                ORDER BY ls.n DESC, ls.lu_id
                LIMIT 10
                """,
            )
            for row in samples:
                row["senses_detail"] = query(
                    conn,
                    """
                    SELECT s.id AS sense_id, s.position,
                           (SELECT string_agg(d.description, ' // ')
                            FROM jedro_definition d WHERE d.sense_id = s.id) AS defs
                    FROM jedro_sense s
                    WHERE s.lexical_unit_id = %s
                    ORDER BY s.position NULLS LAST, s.id
                    LIMIT 6
                    """,
                    (row["lu_id"],),
                )
            out["samples_polysemous"] = samples

        # --- category / POS of lexemes --------------------------------------
        if "jedro_category" in cols and "jedro_lexeme" in cols:
            out["lexeme_categories"] = query(
                conn,
                "SELECT c.name, count(*) AS n FROM jedro_lexeme l "
                "JOIN jedro_category c ON c.id = l.category_id "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 15",
            )
    finally:
        conn.close()
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-db", action="store_true", help="skip the DDDS database inspection")
    args = ap.parse_args()

    results: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": {},
    }

    oswn_path = RAW / "open_slovene_wordnet_1.0" / "open_slovene_wordnet_1.0" / "open_slovene_wordnet.xml"
    if oswn_path.exists():
        console.print(f"[bold]parsing {oswn_path.name} ...[/bold]")
        results["sources"]["oswn"] = inspect_oswn(oswn_path)
        s = results["sources"]["oswn"]
        print_table(
            "OSWN 1.0",
            [
                ["lexical entries", s["lexical_entries"]],
                ["senses", s["senses"]],
                ["synsets", s["synsets"]],
                ["definition languages", s["def_languages"]],
                ["definition statuses", s["definition_statuses"]],
                ["entries with >= 3 senses", s["entries_with_ge3_senses"]],
                ["entries with escaped lemma ('--')", s["entries_with_escaped_lemma"]],
                ["empty Slovene definitions", s["empty_sl_definitions"]],
                ["dangling synset refs", s["dangling_synset_refs"]],
            ],
            ["metric", "value"],
        )

    slownet_path = RAW / "slownet" / "slownet-2015-05-07.xml"
    if slownet_path.exists():
        console.print(f"[bold]parsing {slownet_path.name} ...[/bold]")
        results["sources"]["slownet"] = inspect_slownet(slownet_path)
        s = results["sources"]["slownet"]
        print_table(
            "sloWNet 3.1",
            [
                ["synsets", s["synsets"]],
                ["definitions by language", s["defs_by_language"]],
                ["literals by language", s["literals_by_language"]],
                ["auto literals", s["literals_auto_by_language"]],
                ["usages by language", s["usages_by_language"]],
            ],
            ["metric", "value"],
        )

    link_path = RAW / "oswn_ddds_linked_senses" / "oswn_ddds_linked_senses" / "oswn_ddds_linked_senses.tsv"
    if link_path.exists():
        results["sources"]["oswn_ddds_link"] = inspect_link_tsv(link_path)
        s = results["sources"]["oswn_ddds_link"]
        print_table(
            "OSWN <-> DDDS linked senses",
            [
                ["rows", s["rows"]],
                ["unique synsets", s["unique_synsets"]],
                ["unique DDDS senses", s["unique_senses"]],
                ["unique DDDS lexical units", s["unique_lexical_units"]],
                ["duplicated sense ids", s["duplicated_sense_ids"]],
            ],
            ["metric", "value"],
        )

    if not args.no_db:
        ddds = inspect_ddds()
        if ddds is not None:
            results["sources"]["ddds"] = ddds
            print_table(
                "DDDS snapshot: core counts",
                [[k, v] for k, v in ddds.get("core_counts", {}).items()],
                ["table", "rows"],
            )

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    console.print(f"\n[bold green]report JSON written to[/bold green] {OUT_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
