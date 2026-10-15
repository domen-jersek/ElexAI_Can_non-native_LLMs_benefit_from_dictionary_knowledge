# Reproduction guide

From a clean clone to the Phase-0 inspection report. All commands are run from the
repository root. On Windows, use PowerShell; on Linux/macOS, the same commands apply
(GNU make is native there).

## 0. Prerequisites

| Tool | Version used | Notes |
|---|---|---|
| Python | 3.12.8 | pinned via `.python-version`; uv manages it |
| uv | >= 0.13 | https://docs.astral.sh/uv/ (Windows: `winget install astral-sh.uv`) |
| Docker Desktop | 27.x + Compose v2 | must be running for Postgres/Neo4j |
| GNU make | 3.81+ | Windows: `winget install GnuWin32.Make` |
| Disk | ~70 GB free | 25 GB dump + ~40 GB Postgres volume |

## 1. Environment

```bash
cp .env.example .env      # fill in POSTGRES_* / NEO4J_*; add your OPENROUTER_API_KEY (needed from Phase 2)
make setup                # = uv sync  (creates .venv from uv.lock)
make test                 # optional: unit tests
```

## 2. Data

```bash
make data
# = uv run python scripts/download_data.py   (fetches missing CLARIN.SI sources)
# + uv run python scripts/register_data.py --verify   (checks all sha256 against data/MANIFEST.json)
```

The CLARIN.SI sources (sloWNet 3.1, OSWN 1.0, OSWN<->DDDS link list, Sloleks 3.1) are
downloaded automatically with published MD5 checksums.

**DDDS snapshot (manual, once):**

1. Open https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/domain-and-data-model-links
2. Under "Database dump v3.68 (07.10.2026)" follow the share link
   (https://nas.cjvt.si/s/gTQjMiKzD53yxyd) and download the archive.
3. Extract it into `data/raw/gigabaza-003-068-2026q/` - the folder must contain
   `toc.dat`, `restore.sql` and 102 numbered `.dat` files.
4. Verify: `uv run python scripts/register_data.py --verify --only ddds_dump`.
   The manifest pins the exact v3.68 snapshot by sha256; a future CJVT release will
   fail verification - that is intentional. Update `src/elexai/sources/catalog.py`
   and the manifest deliberately if you switch snapshots.

## 3. Database (Postgres staging)

```bash
docker compose up -d postgres     # pinned to postgres:15.19-bookworm
make db                           # = uv run python scripts/db_restore.py (idempotent)
```

- The restore skips internal Django/auth/admin tables and editor logs (privacy) and the
  ~4 GB `jedro_senseexampletoken` table - see `EXCLUDED_TABLES` in
  `scripts/db_restore.py` and D-002 in `docs/DECISIONS.md`.
- The exact TOC list used is saved to `data/interim/ddds_restore.list`.
- Clean redo: `docker compose down -v && make db`.

## 4. Inspection (Phase 0 deliverable)

```bash
uv run python scripts/inspect_data.py
# prints per-source stats and writes data/processed/inspection/phase0_inspection.json
```

## Reference values (verify your run matches)

| Metric | Expected |
|---|---|
| OSWN lexical entries / senses / synsets | 107,699 / 164,903 / 95,262 |
| OSWN entries with >= 3 senses | 10,774 |
| sloWNet synsets | 117,658 (Slovene defs: 3,177) |
| OSWN<->DDDS link rows | 164,889 (unique DDDS senses: 164,889) |
| DDDS dump | backup v3.68, 2026-10-07, 102 data tables, ~25 GB |
| Postgres image | postgres:15.19-bookworm |
| Neo4j image | neo4j:5.26.32-community |

## Troubleshooting

- **`uv` not found in a fresh shell (Windows)**: restart the terminal, or use
  `.venv\Scripts\python.exe` directly.
- **Docker pipe error**: start Docker Desktop and wait until `docker info` succeeds.
- **Port already in use**: change `POSTGRES_PORT` / `NEO4J_*_PORT` in `.env`.
- **pg_restore exits non-zero** but core tables are populated: expected for a few
  harmless statements (e.g. comments on the existing `public` schema); check
  `data/interim/ddds_restore.log` for details.
