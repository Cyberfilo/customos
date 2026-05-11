"""Global hotkey that tiles two apps 50/50 on the main screen.

Architecture:
  - CGEventTap on the session keyboard stream intercepts key-down events.
  - On match against the configured (key, modifiers), we suppress the event
    (return None) and schedule the tile action on the main queue so the
    event-tap callback returns quickly (it has a hard timeout enforced by
    the system).
  - Tiling launches missing apps via `open -b <bundle>`, polls for AX
    visibility, then sets AXPosition + AXSize on each app's focused window.

Permissions:
  - The event tap requires Accessibility (Settings -> Privacy & Security ->
    Accessibility). On macOS 26 (Tahoe) the Input-Monitoring grant is no
    longer required for session-level event taps; Accessibility alone is
    enough.

Revert:
  - Disable + invalidate the tap, remove its run-loop source.
"""
from __future__ import annotations

import subprocess
import time
from typing import Any

from AppKit import NSScreen, NSWorkspace
from customos_core.identity import normalize_bundle_id
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    kAXErrorSuccess,
    kAXFocusedWindowAttribute,
    kAXPositionAttribute,
    kAXSizeAttribute,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    kAXWindowsAttribute,
)
from CoreFoundation import (
    CFMachPortCreateRunLoopSource,
    CFMachPortInvalidate,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRemoveSource,
    kCFRunLoopCommonModes,
)
from Foundation import NSOperationQueue
from loguru import logger
from Quartz import (
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventTapCreate,
    CGEventTapEnable,
    CGPoint,
    CGSize,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGEventKeyDown,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

from customization_system.executor import CustomizationExecutor


# US-QWERTY virtual keycodes used by macOS CGEvent. Source: Carbon Events.h.
_KEYCODES: dict[str, int] = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
    "9": 25, "7": 26, "8": 28, "0": 29, "o": 31,
    "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "space": 49, "return": 36, "tab": 48, "escape": 53,
}

_MODIFIER_FLAGS: dict[str, int] = {
    "cmd": kCGEventFlagMaskCommand,
    "command": kCGEventFlagMaskCommand,
    "option": kCGEventFlagMaskAlternate,
    "alt": kCGEventFlagMaskAlternate,
    "shift": kCGEventFlagMaskShift,
    "control": kCGEventFlagMaskControl,
    "ctrl": kCGEventFlagMaskControl,
}

_RELEVANT_MASK = (
    kCGEventFlagMaskCommand
    | kCGEventFlagMaskAlternate
    | kCGEventFlagMaskShift
    | kCGEventFlagMaskControl
)


def _resolve_hotkey(spec: dict[str, Any] | None) -> tuple[int, int]:
    """Return (keycode, expected_modifier_mask) from a parameters dict."""
    if not spec:
        spec = {"key": "t", "modifiers": ["cmd", "option"]}
    key = spec["key"].lower()
    if key not in _KEYCODES:
        raise ValueError(f"Unsupported hotkey key {key!r}; known keys: {sorted(_KEYCODES)}")
    mask = 0
    for m in spec["modifiers"]:
        flag = _MODIFIER_FLAGS.get(m.lower())
        if flag is None:
            raise ValueError(f"Unknown modifier {m!r}")
        mask |= flag
    return _KEYCODES[key], mask


def _pid_for_bundle(bundle_id: str) -> int | None:
    target = normalize_bundle_id(bundle_id)
    ws = NSWorkspace.sharedWorkspace()
    for app in ws.runningApplications():
        if normalize_bundle_id(app.bundleIdentifier() or "") == target:
            return int(app.processIdentifier())
    return None


def _ensure_running(bundle_id: str, timeout_s: float = 4.0) -> int | None:
    bundle_id = normalize_bundle_id(bundle_id)
    pid = _pid_for_bundle(bundle_id)
    if pid is not None:
        return pid
    logger.info("launching app for tile", bundle=bundle_id)
    subprocess.Popen(["open", "-g", "-b", bundle_id])
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pid = _pid_for_bundle(bundle_id)
        if pid is not None:
            # Give the app a moment to spawn its main window.
            time.sleep(0.4)
            return pid
        time.sleep(0.1)
    logger.warning("app did not launch within timeout", bundle=bundle_id)
    return None


def _set_window_frame(pid: int, x: float, y: float, w: float, h: float) -> bool:
    """Set the focused window's AXPosition + AXSize. Returns True on success."""
    app_el = AXUIElementCreateApplication(pid)
    if app_el is None:
        return False
    err, window = AXUIElementCopyAttributeValue(app_el, kAXFocusedWindowAttribute, None)
    if err != kAXErrorSuccess or window is None:
        # Fall back to the first AXWindows entry.
        err, windows = AXUIElementCopyAttributeValue(app_el, kAXWindowsAttribute, None)
        if err != kAXErrorSuccess or not windows:
            return False
        window = windows[0]
    pos = AXValueCreate(kAXValueCGPointType, CGPoint(x, y))
    size = AXValueCreate(kAXValueCGSizeType, CGSize(w, h))
    AXUIElementSetAttributeValue(window, kAXPositionAttribute, pos)
    AXUIElementSetAttributeValue(window, kAXSizeAttribute, size)
    return True


def _main_screen_visible_ax_rect() -> tuple[float, float, float, float]:
    """Return (x, y_top, width, height) of the main screen's visible area in AX coords."""
    screen = NSScreen.mainScreen()
    if screen is None:
        return 0.0, 0.0, 1440.0, 900.0
    sf = screen.frame()
    vf = screen.visibleFrame()
    ax_x = float(vf.origin.x)
    # AX origin = top-left; menu bar is at the top of frame.
    menu_bar_height = float(sf.size.height) - (float(vf.origin.y) + float(vf.size.height))
    ax_y = menu_bar_height
    return ax_x, ax_y, float(vf.size.width), float(vf.size.height)


class FocusPairHotkeyExecutor(CustomizationExecutor):
    def __init__(self) -> None:
        self._tap = None
        self._run_loop_source = None
        self._expected_keycode: int | None = None
        self._expected_mask: int | None = None
        self._app_a: str | None = None
        self._app_b: str | None = None
        self._tile_in_flight = False

    # ---- apply / revert ----

    def apply(self, parameters: dict[str, Any]) -> None:
        self._app_a = parameters["app_a"]
        self._app_b = parameters["app_b"]
        self._expected_keycode, self._expected_mask = _resolve_hotkey(parameters.get("hotkey"))

        def _callback(proxy, event_type, event, refcon):
            try:
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                flags = CGEventGetFlags(event)
                if (
                    keycode == self._expected_keycode
                    and (flags & _RELEVANT_MASK) == self._expected_mask
                ):
                    if not self._tile_in_flight:
                        self._tile_in_flight = True
                        # Defer to the main queue so this callback returns
                        # promptly; the system will disable the tap if we
                        # block here.
                        NSOperationQueue.mainQueue().addOperationWithBlock_(self._do_tile)
                    return None  # suppress the keystroke
            except Exception:
                logger.exception("hotkey callback error")
            return event

        mask = 1 << kCGEventKeyDown
        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            mask,
            _callback,
            None,
        )
        if tap is None:
            raise RuntimeError(
                "CGEventTapCreate returned NULL. Grant Accessibility to this "
                "process in System Settings -> Privacy & Security -> Accessibility."
            )
        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        self._tap = tap
        self._run_loop_source = source
        logger.info(
            "hotkey armed",
            app_a=self._app_a,
            app_b=self._app_b,
            keycode=self._expected_keycode,
            mask=self._expected_mask,
        )

    def revert(self) -> None:
        if self._tap is not None:
            try:
                CGEventTapEnable(self._tap, False)
                CFMachPortInvalidate(self._tap)
            except Exception:
                logger.exception("error disabling event tap")
        if self._run_loop_source is not None:
            try:
                CFRunLoopRemoveSource(
                    CFRunLoopGetCurrent(), self._run_loop_source, kCFRunLoopCommonModes
                )
            except Exception:
                logger.exception("error removing run-loop source")
        self._tap = None
        self._run_loop_source = None
        logger.info("hotkey disarmed")

    # ---- tiling ----

    def _do_tile(self) -> None:
        try:
            assert self._app_a is not None and self._app_b is not None
            pid_a = _ensure_running(self._app_a)
            pid_b = _ensure_running(self._app_b)
            x, y, w, h = _main_screen_visible_ax_rect()
            half = w / 2.0
            if pid_a is not None:
                ok_a = _set_window_frame(pid_a, x, y, half, h)
                logger.info("tiled left", app=self._app_a, ok=ok_a)
                # Bring the app to the front so its tiled window is focused.
                self._activate(self._app_a)
            if pid_b is not None:
                ok_b = _set_window_frame(pid_b, x + half, y, half, h)
                logger.info("tiled right", app=self._app_b, ok=ok_b)
                self._activate(self._app_b)
        except Exception:
            logger.exception("tiling failed")
        finally:
            self._tile_in_flight = False

    @staticmethod
    def _activate(bundle_id: str) -> None:
        target = normalize_bundle_id(bundle_id)
        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            if normalize_bundle_id(app.bundleIdentifier() or "") == target:
                app.activateWithOptions_(0)
                return
