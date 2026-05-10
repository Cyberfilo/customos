"""LLM analysis layer.

Pattern: each analytical question turns aggregated stats into a prompt with a
strict JSON schema. We send only aggregates — never raw URLs, message bodies,
or file contents — unless settings.privacy.deep_content_analysis is True.
"""
from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger
from pydantic import BaseModel

from macprofile.settings import get_settings


# ---- Provider abstraction ----

class LLM:
    def call_json(self, *, system: str, user_payload: dict, schema: dict, max_tokens: int) -> dict:
        raise NotImplementedError


class AnthropicLLM(LLM):
    def __init__(self, model: str):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    def call_json(self, *, system, user_payload, schema, max_tokens):
        prompt = (
            "Respond ONLY with a JSON object that conforms to this schema. "
            "Do not include code fences or explanation.\n\n"
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
    def __init__(self, model: str):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model

    def call_json(self, *, system, user_payload, schema, max_tokens):
        full_schema = {
            "name": "macprofile_analysis",
            "schema": schema,
            "strict": False,
        }
        # Use the Responses API for the latest models. text.format with json_schema
        # is the structured-output entry point.
        resp = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, default=str),
                },
            ],
            max_output_tokens=max_tokens,
            text={"format": {"type": "json_schema", **full_schema}},
        )
        # output_text is a convenience accessor that joins text blocks
        text = getattr(resp, "output_text", None)
        if not text:
            # Fallback: walk output array
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
            text = text[: -3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first { ... } substring
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def get_llm() -> LLM:
    s = get_settings()
    choice = s.chosen_llm()
    if choice == "anthropic":
        return AnthropicLLM(s.llm.anthropic_model)
    if choice == "openai":
        return OpenAILLM(s.llm.openai_model)
    raise RuntimeError("No LLM configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")


# ---- Analyses ----

class WorkflowLabel(BaseModel):
    sequence: list[str]
    frequency: int
    label: str
    automation_candidate: bool
    confidence: float
    rationale: str


def label_workflows(top_sequences: list[dict[str, Any]], llm: LLM) -> list[WorkflowLabel]:
    s = get_settings()
    schema = {
        "type": "object",
        "properties": {
            "workflows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sequence": {"type": "array", "items": {"type": "string"}},
                        "frequency": {"type": "integer"},
                        "label": {"type": "string"},
                        "automation_candidate": {"type": "boolean"},
                        "confidence": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["sequence", "frequency", "label", "automation_candidate", "confidence", "rationale"],
                },
            }
        },
        "required": ["workflows"],
    }
    system = (
        "You are a behavioural analyst. You receive frequent ordered sequences "
        "of foreground macOS app bundle IDs from one user. Label each sequence "
        "with a likely workflow (e.g. 'morning email triage', 'coding with docs', "
        "'social break', 'idle context-switch'). Mark automation_candidate=true "
        "for sequences that look like inefficient repeated context-switches that "
        "could be automated or grouped into a workspace. Output strict JSON."
    )
    payload = {"sequences": top_sequences[:30]}
    out = llm.call_json(
        system=system, user_payload=payload, schema=schema, max_tokens=s.llm.max_output_tokens,
    )
    return [WorkflowLabel(**w) for w in out.get("workflows", [])]


class WorkMode(BaseModel):
    name: str
    apps: list[str]
    description: str


def label_work_modes(cohabitation: list[dict[str, Any]], app_affinity: list[dict[str, Any]], llm: LLM) -> list[WorkMode]:
    s = get_settings()
    schema = {
        "type": "object",
        "properties": {
            "modes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "apps": {"type": "array", "items": {"type": "string"}},
                        "description": {"type": "string"},
                    },
                    "required": ["name", "apps", "description"],
                },
            }
        },
        "required": ["modes"],
    }
    system = (
        "Group the user's apps into 3-7 mental 'work modes' (e.g. 'deep work', "
        "'communication', 'leisure'). Each mode has 2-6 apps that frequently "
        "appear in focus within the same 30-minute window."
    )
    payload = {
        "cohabitation_pairs": cohabitation[:60],
        "app_focus_counts": [{"bundle": a["bundle"], "events": a["focus_events"]} for a in app_affinity[:25]],
    }
    out = llm.call_json(
        system=system, user_payload=payload, schema=schema, max_tokens=s.llm.max_output_tokens,
    )
    return [WorkMode(**m) for m in out.get("modes", [])]


class RhythmDescription(BaseModel):
    workday_window: str
    leisure_window: str
    notable_quirks: list[str]
    summary: str


def describe_rhythm(rhythms_payload: dict[str, Any], llm: LLM) -> RhythmDescription:
    s = get_settings()
    schema = {
        "type": "object",
        "properties": {
            "workday_window": {"type": "string"},
            "leisure_window": {"type": "string"},
            "notable_quirks": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
        },
        "required": ["workday_window", "leisure_window", "notable_quirks", "summary"],
    }
    system = (
        "You receive hourly histograms (24 ints per category) and weekday counts "
        "(7 ints, 0=Mon) for one macOS user in Europe/Rome. Describe the rhythm: "
        "when is the workday window, when is leisure, what unusual hour patterns "
        "exist (e.g. midnight coding, early-morning email)."
    )
    out = llm.call_json(
        system=system, user_payload=rhythms_payload, schema=schema, max_tokens=s.llm.max_output_tokens,
    )
    return RhythmDescription(**out)


class InferredProject(BaseModel):
    name: str
    paths: list[str]
    last_active: str | None = None
    phase: str
    rationale: str


def infer_projects(directory_hotspots: list[dict[str, Any]], llm: LLM) -> list[InferredProject]:
    s = get_settings()
    schema = {
        "type": "object",
        "properties": {
            "projects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "last_active": {"type": ["string", "null"]},
                        "phase": {"type": "string", "enum": ["early-explore", "deep-build", "polish", "dormant"]},
                        "rationale": {"type": "string"},
                    },
                    "required": ["name", "paths", "phase", "rationale"],
                },
            }
        },
        "required": ["projects"],
    }
    system = (
        "Each row is a directory the user touched and how often. Cluster these "
        "into distinct named projects. Estimate phase based on access volume + "
        "recency (early-explore, deep-build, polish, dormant)."
    )
    payload = {"directories": directory_hotspots[:40]}
    out = llm.call_json(
        system=system, user_payload=payload, schema=schema, max_tokens=s.llm.max_output_tokens,
    )
    return [InferredProject(**p) for p in out.get("projects", [])]


class BrowsingProfile(BaseModel):
    style: str
    research_share: float
    leisure_share: float
    reference_share: float
    tab_hoarding_score: float
    notable_domains_classification: list[dict[str, Any]]


def describe_browsing(domains: list[dict[str, Any]], tab_state: dict[str, Any], llm: LLM) -> BrowsingProfile:
    s = get_settings()
    schema = {
        "type": "object",
        "properties": {
            "style": {"type": "string"},
            "research_share": {"type": "number"},
            "leisure_share": {"type": "number"},
            "reference_share": {"type": "number"},
            "tab_hoarding_score": {"type": "number"},
            "notable_domains_classification": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string"},
                        "kind": {"type": "string"},
                    },
                    "required": ["domain", "kind"],
                },
            },
        },
        "required": [
            "style", "research_share", "leisure_share", "reference_share",
            "tab_hoarding_score", "notable_domains_classification",
        ],
    }
    system = (
        "Characterise the user's browsing style. For each top domain, classify it "
        "as 'research', 'leisure', 'reference', 'tooling' or 'communication'. "
        "Estimate proportions and a tab-hoarding score 0..1 based on tab counts."
    )
    out = llm.call_json(
        system=system,
        user_payload={"domains": domains[:30], "tab_state": tab_state},
        schema=schema,
        max_tokens=s.llm.max_output_tokens,
    )
    return BrowsingProfile(**out)


class Hook(BaseModel):
    trigger: str
    action: str
    rationale: str
    confidence: float


class IdiosyncrasyOutput(BaseModel):
    quirks: list[str]
    hooks: list[Hook]


def find_quirks_and_hooks(profile_summary: dict[str, Any], llm: LLM) -> IdiosyncrasyOutput:
    s = get_settings()
    schema = {
        "type": "object",
        "properties": {
            "quirks": {"type": "array", "items": {"type": "string"}},
            "hooks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "trigger": {"type": "string"},
                        "action": {"type": "string"},
                        "rationale": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["trigger", "action", "rationale", "confidence"],
                },
            },
        },
        "required": ["quirks", "hooks"],
    }
    system = (
        "Spot idiosyncratic patterns in this user's mac usage and propose actionable "
        "customisation hooks for a personalisation app. A hook is (trigger, action, "
        "rationale). Triggers must be expressible as boolean conditions over the "
        "warehouse signals (e.g. 'safari_window_count > 2 AND oldest_tab_age_days > 5'). "
        "Hooks should be specific to this user's behaviour, not generic. Output 5-10 hooks."
    )
    out = llm.call_json(
        system=system, user_payload=profile_summary, schema=schema, max_tokens=s.llm.max_output_tokens,
    )
    return IdiosyncrasyOutput(**out)
