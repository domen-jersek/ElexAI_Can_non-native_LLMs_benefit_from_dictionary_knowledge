"""Tests for data/MANIFEST.json hashing and verification."""

from __future__ import annotations

import hashlib
import json

from elexai import manifest


def test_sha256_file(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"hello world")
    digest, size = manifest.sha256_file(p)
    assert size == 11
    assert digest == hashlib.sha256(b"hello world").hexdigest()


def _fake_repo(tmp_path):
    """Minimal repo layout for the 'oswn' source (catalog subdir)."""
    root = tmp_path / "data" / "raw" / "open_slovene_wordnet_1.0"
    root.mkdir(parents=True)
    (root / "open_slovene_wordnet.xml").write_bytes(b"<xml/>")
    return tmp_path


def test_register_and_verify_ok(tmp_path):
    repo = _fake_repo(tmp_path)
    manifest.register(repo, only=["oswn"])
    problems = manifest.verify(repo, only=["oswn"])
    assert problems == []

    data = json.loads((repo / manifest.MANIFEST_REL).read_text(encoding="utf-8"))
    entry = data["sources"]["oswn"]
    assert entry["files"][0]["path"] == "open_slovene_wordnet.xml"
    assert entry["missing"] is False


def test_verify_detects_tamper_and_extra(tmp_path):
    repo = _fake_repo(tmp_path)
    manifest.register(repo, only=["oswn"])

    # tamper with the file
    (repo / "data" / "raw" / "open_slovene_wordnet_1.0" / "open_slovene_wordnet.xml").write_bytes(
        b"<xml>changed</xml>"
    )
    problems = manifest.verify(repo, only=["oswn"])
    assert any("sha256 mismatch" in p for p in problems)
    assert any("size mismatch" in p for p in problems)

    # add an unexpected file
    (repo / "data" / "raw" / "open_slovene_wordnet_1.0" / "extra.txt").write_text("x")
    problems = manifest.verify(repo, only=["oswn"])
    assert any("unexpected file" in p for p in problems)


def test_verify_detects_missing_file(tmp_path):
    repo = _fake_repo(tmp_path)
    manifest.register(repo, only=["oswn"])
    (repo / "data" / "raw" / "open_slovene_wordnet_1.0" / "open_slovene_wordnet.xml").unlink()
    problems = manifest.verify(repo, only=["oswn"])
    assert any("missing file" in p for p in problems)
