"""CLI: download publicly fetchable sources from CLARIN.SI (and verify MD5s).

The DDDS snapshot cannot be fetched automatically (Nextcloud share); this
script checks for its presence and points to the distribution page.

Usage:
    uv run python scripts/download_data.py            # fetch what is missing
    uv run python scripts/download_data.py --force    # re-download everything
    uv run python scripts/download_data.py --register # also refresh MANIFEST.json
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

from elexai.manifest import register, summary_line
from elexai.sources.catalog import SOURCES

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW = REPO_ROOT / "data" / "raw"
DOWNLOADS = REPO_ROOT / "data" / "raw" / "_downloads"

_DDDS_HELP = """
The DDDS snapshot is not downloadable by script (Nextcloud share):
  1. Open https://wiki.cjvt.si/books/digital-dictionary-database-of-slovene/page/domain-and-data-model-links
  2. Find 'Database dump v3.68 (07.10.2026)' and follow the share link
     (https://nas.cjvt.si/s/gTQjMiKzD53yxyd)
  3. Extract the directory into data/raw/gigabaza-003-068-2026q/
     (it should contain toc.dat, restore.sql and 102 numbered .dat files)
"""


def _md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 - matches published CLARIN.SI checksums
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}\n        -> {dest}", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    def hook(blocks: int, block_size: int, total: int) -> None:
        if total > 0 and blocks % 200 == 0:
            done = min(blocks * block_size, total)
            print(f"  {done / 1e6:7.1f} / {total / 1e6:.1f} MB", flush=True)

    urllib.request.urlretrieve(url, tmp, reporthook=hook)  # noqa: S310
    tmp.replace(dest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    ap.add_argument("--register", action="store_true", help="refresh MANIFEST.json afterwards")
    args = ap.parse_args()

    missing_hard = []
    for sid, spec in sorted(SOURCES.items()):
        target = RAW / spec.subdir
        populated = target.exists() and any(p.is_file() for p in target.rglob("*"))
        if populated and not args.force:
            print(f"[{sid}] already present in data/raw/{spec.subdir} - skipping")
            continue
        if not spec.download_url or not spec.download_name:
            print(f"[{sid}] cannot be fetched automatically")
            if sid == "ddds_dump":
                print(_DDDS_HELP)
                missing_hard.append(sid if not populated else "")
            continue
        archive = DOWNLOADS / spec.download_name
        if not archive.exists() or args.force:
            download(spec.download_url, archive)
        if spec.md5:
            got = _md5(archive)
            if got != spec.md5:
                print(f"[{sid}] MD5 MISMATCH: expected {spec.md5}, got {got}")
                return 1
            print(f"[{sid}] md5 ok")
        print(f"[{sid}] extracting {archive.name} -> data/raw/{spec.subdir}/")
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)

    missing = [m for m in missing_hard if m]
    if missing:
        print(f"\nNOTE: {', '.join(missing)} must be obtained manually (see above).")

    if args.register:
        manifest = register(REPO_ROOT)
        print(f"manifest refreshed: {summary_line(manifest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
