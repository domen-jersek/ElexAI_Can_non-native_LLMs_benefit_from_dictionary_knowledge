"""Tests for the LLM client, cache and stub."""

from __future__ import annotations

import json

import httpx
import pytest

from elexai.config import LlmConfig
from elexai.llm.cache import ResponseCache
from elexai.llm.client import LlmClient, LlmError, StubLlmClient


def test_cache_key_stability_and_sensitivity(tmp_path):
    key1 = ResponseCache.make_key(model="m", params={"temperature": 0.0}, prompt="p")
    key2 = ResponseCache.make_key(model="m", params={"temperature": 0.0}, prompt="p")
    key3 = ResponseCache.make_key(model="m", params={"temperature": 0.0}, prompt="q")
    key4 = ResponseCache.make_key(model="m", params={"temperature": 1.0}, prompt="p")
    assert key1 == key2
    assert key1 != key3
    assert key1 != key4


def test_cache_roundtrip(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    key = ResponseCache.make_key(model="m", params={}, prompt="p")
    assert cache.get(key) is None
    cache.put(key, {"text": "hello"})
    assert cache.get(key)["text"] == "hello"
    # corrupt entry -> treated as miss
    (tmp_path / "cache" / f"{key}.json").write_text("{not json", encoding="utf-8")
    assert cache.get(key) is None


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": text}}]}
    )


def test_client_parses_response_and_caches(tmp_path, monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        assert body["model"] == "test/model"
        assert body["temperature"] == 0.0
        return _ok_response("SENSE_ID: 123\nODGOVOR: del celote.")

    monkeypatch.setenv("TEST_API_KEY", "secret")
    cfg = LlmConfig(base_url="https://example.invalid/v1", model="test/model", api_key_env="TEST_API_KEY")
    cache = ResponseCache(tmp_path / "cache")
    client = LlmClient(cfg, cache, transport=_mock_transport(handler))
    first = client.complete("prompt-1")
    second = client.complete("prompt-1")
    third = client.complete("prompt-2")

    assert first.text.startswith("SENSE_ID: 123")
    assert first.cache_hit is False
    assert second.cache_hit is True and second.latency_ms == 0.0
    assert third.cache_hit is False
    assert calls["n"] == 2  # one for prompt-1, one for prompt-2


def test_client_missing_key_raises():
    cfg = LlmConfig(base_url="https://example.invalid/v1", model="test/model", api_key_env="DOES_NOT_EXIST_KEY")
    client = LlmClient(cfg, None, transport=_mock_transport(lambda r: _ok_response("x")))
    with pytest.raises(LlmError, match="not set"):
        client.complete("prompt")


def test_client_retries_on_429(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return _ok_response("SENSE_ID: none\nODGOVOR: ok")

    monkeypatch.setenv("TEST_API_KEY", "secret")
    monkeypatch.setattr("time.sleep", lambda s: None)
    cfg = LlmConfig(base_url="https://example.invalid/v1", model="test/model", api_key_env="TEST_API_KEY")
    client = LlmClient(cfg, None, transport=_mock_transport(handler))
    result = client.complete("p")
    assert result.text.startswith("SENSE_ID: none")
    assert calls["n"] == 2


def test_stub_picks_first_candidate_and_none():
    stub = StubLlmClient(LlmConfig())
    with_candidates = "Možni pomeni:\nID: 999\nBeseda: kos\n\nID: 111\nBeseda: kos"
    out = stub.complete(with_candidates)
    assert "SENSE_ID: 999" in out.text
    out2 = stub.complete("brez kandidatov")
    assert "SENSE_ID: none" in out2.text
