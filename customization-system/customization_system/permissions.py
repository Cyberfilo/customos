"""Permission checks.

The customization-system needs Accessibility for two reasons:
  - CGEventTap (focus_pair_hotkey) requires Accessibility on macOS 14+ for
    session-level taps.
  - AXUIElement reads against other processes (dock_dim_unused: Dock items;
    focus_pair_hotkey: window position/size of arbitrary apps) require
    Accessibility.

We do NOT need Screen Recording: dock_dim_unused uses AX, not CGWindowList
pixels. We also do NOT need Input Monitoring on macOS 14+; session-level
event taps are gated by Accessibility alone since Catalina.

If Accessibility is missing, we emit a precise, copy-pasteable instruction
and refuse to start. We never try to bypass.
"""
from __future__ import annotations

from dataclasses import dataclass

from ApplicationServices import AXIsProcessTrusted


@dataclass
class PermissionStatus:
    accessibility: bool

    @property
    def all_granted(self) -> bool:
        return self.accessibility


def check_permissions() -> PermissionStatus:
    return PermissionStatus(accessibility=bool(AXIsProcessTrusted()))


def render_missing(status: PermissionStatus) -> str:
    if status.all_granted:
        return ""
    lines = [
        "",
        "Missing macOS permissions. customization-system cannot run safely without these.",
        "",
    ]
    if not status.accessibility:
        lines += [
            "  Accessibility is REQUIRED.",
            "    System Settings → Privacy & Security → Accessibility",
            "    Add (or toggle on) the binary that's running this process.",
            "    For `uv run customization-system run` that's typically the",
            "    Python interpreter at:",
            "        $(uv run python -c 'import sys; print(sys.executable)')",
            "    After granting, re-run `customization-system run`.",
            "",
        ]
    return "\n".join(lines)
