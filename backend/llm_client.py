"""LLM Client abstraction - supports OpenAI and Anthropic (Claude).

Switch between providers via LLM_PROVIDER env var.
Both use structured JSON output for agent responses.
"""
import os
import json
import time
import logging
from typing import Any

logger = logging.getLogger("release_agent")


class LLMClient:
    """Unified LLM client that works with OpenAI or Anthropic."""

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()

        if self.provider == "anthropic":
            self._init_anthropic()
        else:
            self._init_openai()

    def _init_openai(self):
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env")
        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.embedding_model = "text-embedding-3-small"
        logger.info(f"Using OpenAI: {self.model}")

    def _init_anthropic(self):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self.embedding_model = None  # Anthropic doesn't have embeddings; use OpenAI for RAG
        logger.info(f"Using Anthropic: {self.model}")

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> str:
        """Send a chat completion request. Returns raw content string."""
        if self.provider == "anthropic":
            return self._chat_anthropic(messages, temperature, timeout)
        return self._chat_openai(messages, temperature, timeout)

    def _chat_openai(
        self, messages: list[dict], temperature: float, timeout: int
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=temperature,
            timeout=timeout,
        )
        return response.choices[0].message.content or ""

    def _chat_anthropic(
        self, messages: list[dict], temperature: float, timeout: int
    ) -> str:
        # Anthropic uses system as a separate param, not in messages
        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append(m)

        # Add JSON instruction to system prompt (Anthropic doesn't have JSON mode)
        if system_msg:
            system_msg += "\n\nIMPORTANT: Respond with ONLY a valid JSON object. No markdown, no explanation, just JSON."

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_msg,
            messages=user_messages,
            temperature=temperature,
        )
        content = response.content[0].text

        # Strip markdown code fences if present (Claude sometimes wraps in ```json)
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        return content

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings. Always uses OpenAI (Anthropic has no embedding API)."""
        if self.provider == "anthropic":
            # For Anthropic users, we still need OpenAI for embeddings
            # OR fall back to a simple TF-IDF approach
            openai_key = os.getenv("OPENAI_API_KEY", "")
            if openai_key:
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)
                response = client.embeddings.create(
                    model="text-embedding-3-small", input=texts
                )
                return [item.embedding for item in response.data]
            else:
                # Fallback: simple bag-of-words embedding (no API needed)
                logger.warning("No OPENAI_API_KEY for embeddings, using local fallback")
                return _local_embeddings(texts)
        else:
            response = self.client.embeddings.create(
                model=self.embedding_model, input=texts
            )
            return [item.embedding for item in response.data]


def _local_embeddings(texts: list[str], dim: int = 384) -> list[list[float]]:
    """Simple TF-IDF-like local embeddings as fallback (no API needed).
    
    This is a basic bag-of-words approach for when no embedding API is available.
    Quality is lower than transformer embeddings but sufficient for small corpora.
    """
    import hashlib
    import numpy as np

    embeddings = []
    for text in texts:
        # Create a pseudo-embedding by hashing word trigrams
        words = text.lower().split()
        vec = np.zeros(dim)
        for i in range(len(words)):
            # Unigram
            h = int(hashlib.md5(words[i].encode()).hexdigest(), 16)
            vec[h % dim] += 1.0
            # Bigram
            if i + 1 < len(words):
                bigram = f"{words[i]} {words[i+1]}"
                h = int(hashlib.md5(bigram.encode()).hexdigest(), 16)
                vec[h % dim] += 0.5
        # Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        embeddings.append(vec.tolist())
    return embeddings
