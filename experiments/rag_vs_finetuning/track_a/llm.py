"""
experiments/rag_vs_finetuning/track_a/llm.py
Isolated base-LLM client for Track A (Phase P7).

Talks to the project's base model qwen2.5:7b-instruct via Ollama /api/chat using
the standard library only (no production import, no LangChain). A deterministic
MockLLM is provided so the default test suite never requires Ollama. Generation
defaults are deterministic (temperature 0, top_p 1, seed 0).
"""
from __future__ import annotations

import json
from typing import Protocol

from experiments.rag_vs_finetuning.track_a.models import GenerationConfig


class LLMError(Exception):
    pass


class LLM(Protocol):
    config: GenerationConfig
    def generate(self, system: str, user: str) -> str: ...


class OllamaLLM:
    """Base model via Ollama /api/chat. Not exercised by the offline suite."""

    def __init__(self, *, base_url: str = "http://localhost:11434",
                 model: str = "qwen2.5:7b-instruct", temperature: float = 0.0,
                 top_p: float = 1.0, max_tokens: int = 512, seed: int = 0,
                 timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.config = GenerationConfig(model=model, temperature=temperature,
                                       top_p=top_p, max_tokens=max_tokens, seed=seed)

    def generate(self, system: str, user: str) -> str:
        from urllib.request import Request, urlopen  # lazy stdlib
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "num_predict": self.config.max_tokens,
                "seed": self.config.seed,
            },
        }
        req = Request(f"{self.base_url}/api/chat",
                      data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read())
        except Exception as exc:  # pragma: no cover - network path
            raise LLMError(f"Ollama generation failed: {exc}") from exc
        return body.get("message", {}).get("content", "").strip()


class MockLLM:
    """Deterministic offline stand-in that grounds strictly in the given user
    text (echoes the first context line) — for tests only."""

    def __init__(self, *, model: str = "mock-llm", canned: str | None = None):
        self.config = GenerationConfig(model=model)
        self._canned = canned

    def generate(self, system: str, user: str) -> str:
        if self._canned is not None:
            return self._canned
        if "(no relevant context was retrieved)" in user:
            return "I don't have that information in the provided sources."
        # deterministic: return the first context block's content line
        for line in user.splitlines():
            if line and not line.startswith(("Retrieved context", "[chunk_id", "Question",
                                             "Answer using")):
                return f"Based on the retrieved context: {line.strip()}"
        return "I don't have that information in the provided sources."
