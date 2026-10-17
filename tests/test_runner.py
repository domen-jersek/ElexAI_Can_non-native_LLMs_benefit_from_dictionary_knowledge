"""End-to-end dry-run test of the runner + evaluation on tiny fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path

from elexai.config import EmbedderConfig, ExperimentConfig, LlmConfig
from elexai.eval.metrics import evaluate_run
from elexai.retrieval.chunks import SenseChunk
from elexai.runner import run as runner_mod

CHUNKS = [
    SenseChunk(sense_id="10", lemma="kos", pos="noun", position=1, definition="del celote"),
    SenseChunk(sense_id="11", lemma="kos", pos="noun", position=2, definition="ptica"),
    SenseChunk(sense_id="20", lemma="list", pos="noun", position=1, definition="del rastline"),
]


class FakeVector:
    def search(self, query: str, top_k: int):
        return [("10", 0.9), ("11", 0.8), ("20", 0.7)][:top_k]


def _question(qid: str, lemma: str, gold: str, answer: str) -> dict:
    return {
        "id": qid,
        "question": f"Kateri pomen besede »{lemma}«?",
        "target_word": lemma,
        "lemma": lemma,
        "pos": "noun",
        "context_sentence": f"Primer rabe za {lemma}.",
        "gold_sense_id": gold,
        "gold_answer": answer,
        "source_dictionary_version": "DDDS backup v3.68",
        "review_status": "draft",
        "reviewer": "",
        "notes": "",
    }


def test_runner_dry_run_end_to_end(tmp_path, monkeypatch):
    # no senses cross-check available in the fixture root
    monkeypatch.setattr(runner_mod, "SENSES_EXPORT", tmp_path / "no_senses.jsonl")
    monkeypatch.setattr(runner_mod, "LEXICAL_CORE", tmp_path / "no_core.jsonl")

    qdir = tmp_path / "data" / "questions"
    qdir.mkdir(parents=True)
    questions = [
        _question("q1", "kos", "10", "del celote"),
        _question("q2", "list", "20", "del rastline"),
    ]
    (qdir / "questions.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in questions) + "\n",
        encoding="utf-8",
    )

    cfg = ExperimentConfig(
        name="test-run",
        questions_path=Path("data/questions/questions.jsonl"),
        llm=LlmConfig(),
        embedder=EmbedderConfig(name="fake", hf_id="fake", revision="x"),
        runs_dir=Path("runs"),
    )
    run_dir = runner_mod.run_experiment(
        cfg,
        root=tmp_path,
        dry_run=True,
        variants=["A", "B", "C", "oracle"],
        chunks=CHUNKS,
        vector=FakeVector(),
    )

    assert (run_dir / "answers.jsonl").exists()
    rows = [
        json.loads(line)
        for line in (run_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 8  # 4 variants x 2 questions
    assert {r["variant"] for r in rows} == {"A", "B", "C", "oracle"}
    assert all(r["error"] is None for r in rows)
    assert all(r["parsed_sense_id"] is not None or r["variant"] == "A" for r in rows)

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dry_run"] is True
    assert manifest["template_version"] == "sd-v1"
    assert manifest["variants"] == ["A", "B", "C", "oracle"]

    metrics = evaluate_run(run_dir, tmp_path)
    assert set(metrics["variants"]) == {"A", "B", "C", "oracle"}
    # stub answers pick the first candidate id of the prompt
    assert metrics["variants"]["B"]["citation_accuracy"] == 0.5  # q1 right, q2 cites 10
    assert metrics["variants"]["C"]["citation_accuracy"] == 1.0  # first lemma candidate is gold
    assert metrics["variants"]["oracle"]["citation_accuracy"] == 1.0
    assert metrics["variants"]["B"]["recall_at_k"]["1"] == 0.5
    assert metrics["variants"]["B"]["recall_at_k"]["3"] == 1.0


def test_runner_loads_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEXAI_TEST_DOTENV_KEY", raising=False)
    (tmp_path / ".env").write_text("ELEXAI_TEST_DOTENV_KEY=from-dotenv\n", encoding="utf-8")
    runner_mod._load_env(tmp_path)
    assert os.environ.get("ELEXAI_TEST_DOTENV_KEY") == "from-dotenv"
