"""Unified Pydantic event schema. Every signal in the warehouse is one of these."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

TargetKind = Literal["app", "url", "file", "contact", "event", "device", "topic", "other"]
Category = Literal[
    "app_focus",
    "app_launch",
    "app_intent",
    "app_activity",
    "app_usage",
    "file_access",
    "file_recent",
    "web_visit",
    "tab_state",
    "bookmark",
    "shell_command",
    "calendar_event",
    "note",
    "reminder",
    "photo",
    "message_sent",
    "message_received",
    "mail_seen",
    "notification",
    "media_play",
    "device_state",
    "screen_time",
    "user_focus",
    "system_log",
]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    ts: datetime
    ts_local: datetime
    source: str
    category: Category
    actor: str = "user"
    target: str
    target_kind: TargetKind = "other"
    duration_sec: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_hash: str

    def to_row(self) -> dict[str, Any]:
        d = self.model_dump()
        if d["ts"].tzinfo is None:
            d["ts"] = d["ts"].replace(tzinfo=timezone.utc)
        d["metadata"] = _safe_json(d["metadata"])
        return d


def _safe_json(obj: Any) -> str:
    import json
    def default(o: Any):
        if isinstance(o, (bytes, bytearray)):
            return o.hex()
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=default, ensure_ascii=False)
