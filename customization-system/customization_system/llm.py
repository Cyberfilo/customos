"""LLM provider abstraction.

Mirrors profile-extractor/macprofile/analyze/llm.py at the call-site shape so
the two subsystems converge on the same pattern.

Provider selection: Anthropic if ANTHROPIC_API_KEY is set; otherwise OpenAI
if OPENAI_API_KEY is set; otherwise raise. The CustomOS profile-extractor
already uses both SDKs the same way, so we don't duplicate model defaults
in code — the caller supplies them.
"""
from __future__ import annotations

import json
import os


class LLM:
    name: str = "abstract"
    model: str = ""

    def call_json(self, *, system: str, user_payload: dict, schema: dict, max_tokens: int) -> dict:
        raise NotImplementedError


class AnthropicLLM(LLM):
    name = "anthropic"

    def __init__(self, model: str = "claude-opus-4-7") -> None:
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model

    def call_json(self, *, system, user_payload, schema, max_tokens):
        prompt = (
            "Respond ONLY with a JSON object that conforms to this schema. "
            "Do not include code fences, markdown, or commentary.\n\n"
            f"Schema:\n{json.dumps(schema, indent=2)}\n\n"
            f"Input data:\n{json.dumps(user_payload, default=str)}"
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(blk.text for blk in resp.content if getattr(blk, "type", "") == "text")
        return _force_json(text)


class OpenAILLM(LLM):
    name = "openai"

    def __init__(self, model: str = "gpt-5") -> None:
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model

    def call_json(self, *, system, user_payload, schema, max_tokens):
        full_schema = {
            "name": "customization_system_plan",
            "schema": schema,
            "strict": False,
        }
        resp = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, default=str)},
            ],
            max_output_tokens=max_tokens,
            text={"format": {"type": "json_schema", **full_schema}},
        )
        text = getattr(resp, "output_text", None)
        if not text:
            chunks: list[str] = []
            for item in getattr(resp, "output", []) or []:
                for c in getattr(item, "content", []) or []:
                    t = getattr(c, "text", None)
                    if t:
                        chunks.append(t)
            text = "".join(chunks)
        return _force_json(text or "{}")


def _force_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def get_llm() -> LLM:
    """Pick a provider based on which API key is present (Anthropic > OpenAI)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAILLM()
    raise RuntimeError(
        "No LLM provider configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )
