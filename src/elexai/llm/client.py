"""OpenAI-compatible LLM client with retries and an on-disk cache.

Works with OpenRouter, vLLM, Ollama, etc.: ``base_url`` and ``model`` come from
the experiment config (``elexai.config.LlmConfig``); the API key is read from
the environment variable named by the config (default ``OPENROUTER_API_KEY``).

``StubLlmClient`` is a deterministic offline client used by ``--dry-run`` and
by the test suite; it exercises the same interface and produces parseable
answers (it picks the first candidate ID when a candidate list is present).
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass

import httpx

from elexai.config import LlmConfig
from elexai.llm.cache import ResponseCache


class LlmError(RuntimeError):
    pass


@dataclass
class LlmResult:
    text: str
    latency_ms: float
    cache_hit: bool
    model: str


class LlmClient:
    def __init__(
        self,
        cfg: LlmConfig,
        cache: ResponseCache | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.cfg = cfg
        self.cache = cache
        self._client = httpx.Client(
            base_url=cfg.base_url, timeout=cfg.timeout_s, transport=transport
        )

    def _params(self) -> dict:
        return {"temperature": self.cfg.temperature, "max_tokens": self.cfg.max_tokens}

    def complete(self, prompt: str) -> LlmResult:
        params = self._params()
        key: str | None = None
        if self.cache is not None:
            key = ResponseCache.make_key(model=self.cfg.model, params=params, prompt=prompt)
            hit = self.cache.get(key)
            if hit is not None:
                return LlmResult(
                    text=hit["text"], latency_ms=0.0, cache_hit=True, model=self.cfg.model
                )

        api_key = os.environ.get(self.cfg.api_key_env, "")
        if not api_key:
            raise LlmError(
                f"environment variable {self.cfg.api_key_env!r} is not set "
                f"(add it to .env / your environment before running)"
            )

        payload: dict = {
            "model": self.cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            **params,
        }
        if self.cfg.seed is not None:
            payload["seed"] = self.cfg.seed
        headers = {"Authorization": f"Bearer {api_key}"}

        last_exc: Exception | None = None
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                response = self._client.post("/chat/completions", json=payload, headers=headers)
                if response.status_code in (429, 500, 502, 503, 504):
                    raise LlmError(f"HTTP {response.status_code}: {response.text[:300]}")
                response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                latency_ms = (time.perf_counter() - t0) * 1000
                if self.cache is not None and key is not None:
                    self.cache.put(
                        key,
                        {
                            "model": self.cfg.model,
                            "params": params,
                            "prompt": prompt,
                            "text": text,
                            "latency_ms": latency_ms,
                        },
                    )
                return LlmResult(
                    text=text, latency_ms=latency_ms, cache_hit=False, model=self.cfg.model
                )
            except Exception as exc:  # noqa: BLE001 - retry any transport/protocol error
                last_exc = exc
                time.sleep(min(2**attempt + random.random(), 10.0))
        raise LlmError(f"LLM call failed after retries: {last_exc}")

    def close(self) -> None:
        self._client.close()


class StubLlmClient:
    """Deterministic offline client for ``--dry-run`` and tests."""

    def __init__(self, cfg: LlmConfig):
        self.cfg = cfg

    def complete(self, prompt: str) -> LlmResult:
        ids = re.findall(r"^ID: (\d+)$", prompt, flags=re.M)
        sense_id = ids[0] if ids else "none"
        text = f"SENSE_ID: {sense_id}\nODGOVOR: (dry run) izbran pomen {sense_id}."
        return LlmResult(text=text, latency_ms=0.0, cache_hit=False, model="stub")

    def close(self) -> None:
        pass
