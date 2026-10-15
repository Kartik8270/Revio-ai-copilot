"""Thin, provider-agnostic LLM layer.

The PoC works fully offline (no key needed). If ANTHROPIC_API_KEY or OPENAI_API_KEY is set the
reply drafter and the structured extractor use a real model. Cynbit's public stack lists OpenAI and
LangChain; this layer is intentionally ~60 lines so it can be swapped for LangChain/LiteLLM.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int = 400) -> str: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("REVIO_LLM_MODEL", "claude-haiku-5-5")

    def complete(self, system: str, user: str, max_tokens: int = 400) -> str:
        r = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=0.3, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()


class OpenAIProvider:
    """OpenAI-compatible chat completions over plain HTTPS (works with any compatible gateway)."""

    name = "openai"

    def __init__(self, model: str | None = None):
        self.key = os.environ["OPENAI_API_KEY"]
        self.base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.getenv("REVIO_LLM_MODEL", "gpt-4o-mini")

    def complete(self, system: str, user: str, max_tokens: int = 400) -> str:
        body = json.dumps({
            "model": self.model, "max_tokens": max_tokens, "temperature": 0.3,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"].strip()


def get_provider() -> LLMProvider | None:
    """Pick a provider from env; None means 'run offline with templates'."""
    choice = os.getenv("REVIO_LLM_PROVIDER", "").lower()
    try:
        if choice == "anthropic" or (not choice and os.getenv("ANTHROPIC_API_KEY")):
            return AnthropicProvider()
        if choice == "openai" or (not choice and os.getenv("OPENAI_API_KEY")):
            return OpenAIProvider()
    except Exception:  # missing SDK / key -> degrade gracefully
        return None
    return None
