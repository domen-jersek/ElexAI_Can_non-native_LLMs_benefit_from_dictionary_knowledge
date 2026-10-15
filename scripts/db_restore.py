"""CLI: bring up Postgres (docker compose) and restore the DDDS snapshot.

Idempotent: if the core tables already exist the restore is skipped
(use ``--force`` to drop schema ``public`` and restore from scratch).

Internal Django/auth/session tables and editor working logs are excluded for
privacy, as is the ~4 GB example-token alignment table (see
EXCLUDED_TABLES below and docs/DECISIONS.md D-002).

Artifacts:
  data/interim/ddds_restore.list          exact TOC list used (audit)
  data/processed/ddds/restore_summary.json summary (counts, timings)

Usage:
    uv run python scripts/db_restore.py              # start + restore (idempotent)
    uv run python scripts/db_restore.py --force      # drop + restore again
    uv run python scripts/db_restore.py --list-only  # just build the TOC list
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from elexai.sources.ddds import ddds_connect

REPO_ROOT = Path(__file__).resolve().parents[1]
DUMP_SUBDIR = "gigabaza-003-068-2026q"  # under data/raw/
DUMP_DIR_LOCAL = REPO_ROOT / "data" / "raw" / DUMP_SUBDIR
DUMP_DIR_CONTAINER = f"/raw/{DUMP_SUBDIR}"
CONTAINER_NAME = "elexai-postgres"
LIST_LOCAL = REPO_ROOT / "data" / "interim" / "ddds_restore.list"
LIST_CONTAINER = "/tmp/ddds_restore.list"
SUMMARY_PATH = REPO_ROOT / "data" / "processed" / "ddds" / "restore_summary.json"

# Tables that are NOT restored. Reason: privacy (internal Django/admin/editor
# data from a production-like dictionary database) or size vs. usefulness for
# this pilot. django_content_type is deliberately KEPT because generic
# relations (object_feature, resourcerelevance) reference it.
EXCLUDED_TABLES = {
    # Django auth / sessions / admin
    "auth_group", "auth_group_permissions", "auth_permission", "auth_user",
    "auth_user_groups", "auth_user_user_permissions",
    "authtoken_token",
    "django_admin_log", "django_cron_cronjoblock", "django_cron_cronjoblog",
    "django_migrations", "django_session",
    "jet_bookmark", "jet_pinnedapplication",
    # editor working metadata / logs
    "metadata_actionlog", "metadata_comment",
    "metadata_lexicalunitlog", "metadata_lexicalunitlogrelation",
    "metadata_lexicalunitreindexrequest", "metadata_mainmenuresourceviewsetting",
    # ~4 GB alignment table, not needed for the pilot
    "jedro_senseexampletoken",
}

COUNT_TABLES = [
    "jedro_lexeme", "jedro_lexicalunit", "jedro_sense", "jedro_definition",
    "jedro_senserelation", "jedro_example", "jedro_sense_example",
]


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, **kw)


def _compose(*args: str, **kw) -> subprocess.CompletedProcess:
    return _run(["docker", "compose", *args], **kw)


def _docker_ok() -> bool:
    r = _run(["docker", "info"], capture_output=True)
    return r.returncode == 0


def ensure_postgres_up(timeout_s: int = 240) -> None:
    if not _docker_ok():
        raise SystemExit(
            "Docker daemon is not available. Start Docker Desktop, then re-run."
        )
    if not DUMP_DIR_LOCAL.exists():
        raise SystemExit(
            f"DDDS dump not found at {DUMP_DIR_LOCAL}. "
            "See scripts/download_data.py for how to obtain it."
        )
    print("starting postgres service ...", flush=True)
    _compose("up", "-d", "postgres", capture_output=True)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = _compose("exec", "-T", "postgres", "pg_isready", capture_output=True)
        if r.returncode == 0:
            print("postgres is ready", flush=True)
            return
        time.sleep(2)
    raise SystemExit("postgres did not become ready in time")


def _is_excluded(tag: str) -> bool:
    return any(tag == t or tag.startswith(t + "_") for t in EXCLUDED_TABLES)


def build_restore_list() -> dict:
    """Fetch the full TOC listing and write a filtered --use-list file."""
    r = _compose(
        "exec", "-T", "postgres", "pg_restore", "-l", DUMP_DIR_CONTAINER,
        capture_output=True,
    )
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit("`pg_restore -l` failed - is the dump complete?")
    kept: list[str] = []
    n_excluded = 0
    for line in r.stdout.splitlines():
        if not line or line.startswith(";"):
            kept.append(line)
            continue
        parts = line.split()
        excluded = False
        if "SCHEMA" in parts and "public" in parts:
            excluded = True  # schema public already exists in the target DB
        elif any(_is_excluded(tok) for tok in parts):
            excluded = True
        if excluded:
            kept.append(";" + line)
            n_excluded += 1
        else:
            kept.append(line)
    LIST_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LIST_LOCAL.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    info = {"toc_lines": len(r.stdout.splitlines()), "excluded_entries": n_excluded}
    print(f"restore list written to {LIST_LOCAL.relative_to(REPO_ROOT)}: {info}", flush=True)
    return info


def core_counts() -> dict | None:
    """Row counts of key tables, or None if not restored yet / DB unreachable."""
    try:
        with ddds_connect(REPO_ROOT) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.jedro_sense')")
            row = cur.fetchone()
            if row is None or row[0] is None:
                return None
            counts = {}
            for t in COUNT_TABLES:
                cur.execute(f"SELECT count(*) FROM {t}")  # noqa: S608 - fixed names
                row = cur.fetchone()
                assert row is not None
                counts[t] = int(row[0])
            return counts
    except psycopg.OperationalError:
        return None


def drop_and_recreate_schema() -> None:
    with ddds_connect(REPO_ROOT) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")


def run_restore() -> int:
    subprocess.run(
        ["docker", "cp", str(LIST_LOCAL), f"{CONTAINER_NAME}:{LIST_CONTAINER}"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    sh_cmd = (
        'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h localhost '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -j 3 --no-owner --no-acl '
        f"--use-list={LIST_CONTAINER} {DUMP_DIR_CONTAINER}"
    )
    print("restoring DDDS snapshot (parallel, this can take 15-45 minutes) ...", flush=True)
    t0 = time.time()
    r = _compose("exec", "-T", "postgres", "sh", "-c", sh_cmd)
    elapsed = time.time() - t0
    print(f"pg_restore finished in {elapsed / 60:.1f} min (exit code {r.returncode})", flush=True)
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="drop schema and restore again")
    ap.add_argument("--list-only", action="store_true", help="only rebuild the TOC list")
    args = ap.parse_args()

    ensure_postgres_up()
    if args.list_only:
        build_restore_list()
        return 0

    existing = core_counts()
    if existing and not args.force:
        print("DDDS tables already restored - nothing to do (use --force to restore again).")
        print(json.dumps(existing, indent=2))
        return 0

    t0 = time.time()
    if existing and args.force:
        print("dropping schema public (--force) ...", flush=True)
        drop_and_recreate_schema()

    info = build_restore_list()
    rc = run_restore()
    counts = core_counts()
    total_min = (time.time() - t0) / 60

    summary = {
        "restored_at": datetime.now(UTC).isoformat(),
        "dump_subdir": DUMP_SUBDIR,
        "restore_list": str(LIST_LOCAL.relative_to(REPO_ROOT)),
        "toc_info": info,
        "pg_restore_exit_code": rc,
        "elapsed_minutes": round(total_min, 1),
        "counts": counts,
        "excluded_tables": sorted(EXCLUDED_TABLES),
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if not counts or counts.get("jedro_sense", 0) == 0:
        print("RESTORE FAILED: core tables are empty - inspect the log above.")
        return 1
    print(f"restore verified: {json.dumps(counts, indent=2)}")
    print(f"summary written to {SUMMARY_PATH.relative_to(REPO_ROOT)}")
    if rc != 0:
        print(
            "NOTE: pg_restore reported warnings/errors (exit code != 0) but the core "
            "tables are populated. Check the log for details."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
