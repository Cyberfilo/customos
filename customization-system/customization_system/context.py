"""Process-global runtime context for executors.

This is set once by the CLI before any executor is constructed, and read by
executors that need access to the profile (e.g. dock_dim_unused). It exists
to keep the CustomizationExecutor base class signature minimal (no
constructor parameters) while still letting executors pull in the data
they need.

Not thread-safe by design; the customization-system is single-process,
single-NSApplication.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

_PROFILE: dict[str, Any] | None = None
_PROFILE_PATH: Path | None = None


def set_profile(profile: dict[str, Any], path: Path) -> None:
    global _PROFILE, _PROFILE_PATH
    _PROFILE = profile
    _PROFILE_PATH = path


def get_profile() -> dict[str, Any]:
    if _PROFILE is None:
        raise RuntimeError(
            "Profile not loaded. The CLI should call set_profile() before "
            "any executor is applied."
        )
    return _PROFILE


def get_profile_path() -> Path:
    if _PROFILE_PATH is None:
        raise RuntimeError("Profile path not set.")
    return _PROFILE_PATH


def profile_generated_at() -> datetime:
    """Parse profile['generated_at'] (ISO timestamp) into a tz-aware datetime."""
    raw = get_profile().get("generated_at")
    if not raw:
        return datetime.now().astimezone()
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
