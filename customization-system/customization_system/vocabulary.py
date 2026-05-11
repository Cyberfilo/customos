"""The fixed catalog of available customizations.

The vocabulary is the contract between the LLM (which picks entries) and the
executor layer (which realizes them). Every entry MUST correspond to executor
code that can both apply and revert the customization at runtime. The LLM
cannot invent entries that aren't in this list — that's the whole point of a
fixed vocabulary.

To add a new customization: write a CustomizationExecutor subclass, then add
a VocabularyEntry referencing it. Validation (id existence + JSON-schema
conformance on parameters) is enforced in plan.py.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from customization_system.executor import CustomizationExecutor
from customization_system.executors.dock_dim_unused import DockDimUnusedExecutor
from customization_system.executors.focus_pair_hotkey import FocusPairHotkeyExecutor
from customization_system.executors.notch_now_playing import NotchNowPlayingExecutor


class VocabularyEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    category: str
    description: str
    profile_signals: str
    parameters_schema: dict
    executor_class: type[CustomizationExecutor] = Field(repr=False)


VOCABULARY: list[VocabularyEntry] = [
    VocabularyEntry(
        id="notch_now_playing",
        category="notch",
        description=(
            "Custom notch widget that displays the currently-playing track "
            "(title + artist) in a small floating panel positioned just "
            "under the MacBook Pro notch. Updates live via Apple Music and "
            "Spotify distributed notifications. Visible only while playback "
            "is active; hides itself otherwise."
        ),
        profile_signals=(
            "User listens to music during work hours; high media-play "
            "frequency in rhythms; com.apple.music or com.spotify.client "
            "appears in top apps; 'lunch media break' or similar listening "
            "patterns in idiosyncrasies."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "show_artist": {
                    "type": "boolean",
                    "description": "Whether to show the artist name below the track title.",
                    "default": True,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        executor_class=NotchNowPlayingExecutor,
    ),
    VocabularyEntry(
        id="dock_dim_unused",
        category="dock",
        description=(
            "Visually dim Dock icons for apps the user hasn't focused in "
            "the last N days, by overlaying a semi-transparent NSWindow "
            "above each stale icon's rect. Pure visual overlay — no "
            "modification to com.apple.dock or its persistent-apps list. "
            "Reverts cleanly when the process exits."
        ),
        profile_signals=(
            "User has a long-lived Dock with apps that haven't been "
            "focused recently (recency derived from profile.apps[*].last_seen). "
            "Most useful for users whose top-app distribution has a long "
            "tail of stale entries."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "days_threshold": {
                    "type": "integer",
                    "description": "Apps not focused within this many days are considered stale.",
                    "minimum": 1,
                    "default": 30,
                },
                "dim_opacity": {
                    "type": "number",
                    "description": "Opacity of the dimming overlay (0=transparent, 1=opaque black).",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.55,
                },
            },
            "required": ["days_threshold"],
            "additionalProperties": False,
        },
        executor_class=DockDimUnusedExecutor,
    ),
    VocabularyEntry(
        id="focus_pair_hotkey",
        category="hotkey",
        description=(
            "Register a global hotkey that, when pressed, tiles the "
            "frontmost windows of two specific apps 50/50 left/right on "
            "the active screen. Apps that aren't running are launched "
            "first. Implemented via CGEventTap (intercepts input) + the "
            "Accessibility API (sets window frame). Hotkey is unregistered "
            "on revert."
        ),
        profile_signals=(
            "User has frequent back-and-forth between two specific apps "
            "in their workflows (e.g. Terminal <-> Safari, or any pair "
            "appearing in profile.workflows as a high-frequency 3-gram). "
            "The two bundle IDs should come from the user's actual top "
            "Mac apps and observed workflow patterns."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "app_a": {
                    "type": "string",
                    "description": "Left-side app bundle ID (e.g. com.apple.terminal).",
                },
                "app_b": {
                    "type": "string",
                    "description": "Right-side app bundle ID (e.g. com.apple.safari).",
                },
                "hotkey": {
                    "type": "object",
                    "description": "Key combination. Default is Cmd+Option+T if omitted.",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Single character, e.g. 't'.",
                        },
                        "modifiers": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["cmd", "option", "control", "shift"],
                            },
                            "minItems": 1,
                        },
                    },
                    "required": ["key", "modifiers"],
                    "additionalProperties": False,
                },
            },
            "required": ["app_a", "app_b"],
            "additionalProperties": False,
        },
        executor_class=FocusPairHotkeyExecutor,
    ),
]


def get_entry(entry_id: str) -> VocabularyEntry | None:
    for e in VOCABULARY:
        if e.id == entry_id:
            return e
    return None
