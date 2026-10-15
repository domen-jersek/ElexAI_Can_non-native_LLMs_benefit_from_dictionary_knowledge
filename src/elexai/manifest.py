"""Data manifest: hashing and verification of raw source files.

``data/MANIFEST.json`` is committed and records, for every source in
``elexai.sources.catalog``: provenance metadata and one entry per raw file
(relative path, size, sha256). Registering re-hashes everything; verifying
fails loudly on any mismatch, missing or unexpected file.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from elexai.sources.catalog import SOURCES, SourceSpec

RAW_DIR_REL = Path("data/raw")
MANIFEST_REL = Path("data/MANIFEST.json")
_CHUNK = 1 << 20


def sha256_file(path: Path) -> tuple[str, int]:
    """Return (hex sha256, size in bytes) for one file."""
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _iter_files(root: Path) -> Iterable[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _source_entry(spec: SourceSpec, repo_root: Path) -> dict:
    root = repo_root / RAW_DIR_REL / spec.subdir
    entry: dict = {
        "title": spec.title,
        "authors": spec.authors,
        "issued": spec.issued,
        "license": spec.license,
        "handle": spec.handle,
        "download_url": spec.download_url,
        "notes": spec.notes,
        "subdir": spec.subdir,
    }
    if not root.exists():
        entry["missing"] = True
        entry["files"] = []
        entry["total_size"] = 0
        return entry
    files = []
    for p in _iter_files(root):
        digest, size = sha256_file(p)
        files.append(
            {"path": p.relative_to(root).as_posix(), "size": size, "sha256": digest}
        )
    entry["missing"] = False
    entry["files"] = files
    entry["total_size"] = sum(f["size"] for f in files)
    return entry


def register(
    repo_root: Path,
    only: list[str] | None = None,
    progress=None,
) -> dict:
    """(Re)hash all sources and write data/MANIFEST.json."""
    manifest_path = repo_root / MANIFEST_REL
    previous: dict = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest: dict = {
        "schema": 1,
        "created": previous.get("created", datetime.now(UTC).isoformat()),
        "updated": datetime.now(UTC).isoformat(),
        "sources": {},
    }
    for sid, spec in sorted(SOURCES.items()):
        if only and sid not in only:
            if sid in previous.get("sources", {}):
                manifest["sources"][sid] = previous["sources"][sid]
            continue
        if progress:
            progress(f"hashing {sid} ...")
        manifest["sources"][sid] = _source_entry(spec, repo_root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def verify(repo_root: Path, only: list[str] | None = None) -> list[str]:
    """Return a list of problems ([] means everything matches the manifest)."""
    manifest_path = repo_root / MANIFEST_REL
    if not manifest_path.exists():
        return [f"manifest not found: {manifest_path} (run scripts/register_data.py first)"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for sid, recorded in sorted(manifest.get("sources", {}).items()):
        if only and sid not in only:
            continue
        spec = SOURCES.get(sid)
        if spec is None:
            problems.append(f"{sid}: present in manifest but not in catalog")
            continue
        root = repo_root / RAW_DIR_REL / spec.subdir
        if recorded.get("missing"):
            continue
        on_disk = {p.relative_to(root).as_posix(): p for p in _iter_files(root)}
        for f in recorded.get("files", []):
            path = root / f["path"]
            if f["path"] not in on_disk:
                problems.append(f"{sid}: missing file {f['path']}")
                continue
            digest, size = sha256_file(path)
            if size != f["size"]:
                problems.append(
                    f"{sid}: size mismatch for {f['path']} "
                    f"(manifest {f['size']}, disk {size})"
                )
            if digest != f["sha256"]:
                problems.append(f"{sid}: sha256 mismatch for {f['path']}")
        recorded_paths = {f["path"] for f in recorded.get("files", [])}
        for extra in sorted(set(on_disk) - recorded_paths):
            problems.append(f"{sid}: unexpected file not in manifest: {extra}")
    return problems


def summary_line(manifest: dict) -> str:
    parts = []
    for sid, e in sorted(manifest.get("sources", {}).items()):
        if e.get("missing"):
            parts.append(f"{sid}=MISSING")
        else:
            parts.append(f"{sid}={len(e.get('files', []))} files/{e.get('total_size', 0) / 1e9:.2f} GB")
    return "; ".join(parts)
