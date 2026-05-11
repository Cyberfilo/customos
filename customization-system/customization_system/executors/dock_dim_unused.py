"""Dim Dock icons for apps the user hasn't focused in N days.

Per-icon overlay strategy:
  - Find the Dock process via NSWorkspace, build an AXUIElement.
  - Walk descendants and collect those with AXSubrole = "AXApplicationDockItem".
  - For each item, read its AXURL (file:// path to the .app), and resolve the
    bundle ID via NSBundle. AXPosition + AXSize give the icon's rect in
    AX (top-left origin) screen coordinates.
  - Cross-reference each bundle ID against profile.apps[*].last_seen.
    Apps absent from the profile or older than the threshold are "stale".
  - For each stale icon, create a borderless ignore-mouse semi-transparent
    NSWindow positioned exactly over the icon's rect.

Permissions:
  - Reading AX from another process needs the Accessibility grant.
  - No Screen Recording needed for this approach (we don't read pixel data;
    AX gives us positions directly). The vocabulary entry hint about
    Screen Recording was overcautious — kept the permission probe anyway
    because CGWindowList could become useful for the "icon recents" area
    that AX doesn't expose.

Revert:
  - Close all overlay windows; release strong refs.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSMakeRect,
    NSScreen,
    NSStatusWindowLevel,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
)
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXValueGetValue,
    kAXChildrenAttribute,
    kAXErrorSuccess,
    kAXPositionAttribute,
    kAXSizeAttribute,
    kAXSubroleAttribute,
    kAXURLAttribute,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)
from Foundation import NSBundle
from customos_core.identity import normalize_bundle_id
from loguru import logger

from customization_system.context import get_profile, profile_generated_at
from customization_system.executor import CustomizationExecutor


_DOCK_ITEM_SUBROLE = "AXApplicationDockItem"


def _dock_pid() -> int | None:
    target = normalize_bundle_id("com.apple.dock")
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if normalize_bundle_id(app.bundleIdentifier() or "") == target:
            return int(app.processIdentifier())
    return None


def _ax_attr(element, name):
    err, value = AXUIElementCopyAttributeValue(element, name, None)
    if err != kAXErrorSuccess:
        return None
    return value


def _walk_descendants(root, out: list, max_depth: int = 6) -> None:
    if max_depth <= 0:
        return
    children = _ax_attr(root, kAXChildrenAttribute)
    if not children:
        return
    for c in children:
        out.append(c)
        _walk_descendants(c, out, max_depth - 1)


def _dock_items(dock_pid: int) -> list:
    app_el = AXUIElementCreateApplication(dock_pid)
    descendants: list = []
    _walk_descendants(app_el, descendants)
    items = []
    for el in descendants:
        subrole = _ax_attr(el, kAXSubroleAttribute)
        if subrole == _DOCK_ITEM_SUBROLE:
            items.append(el)
    return items


def _bundle_id_from_url(url) -> str | None:
    if url is None:
        return None
    path = url.path() if hasattr(url, "path") else None
    if not path:
        return None
    bundle = NSBundle.bundleWithPath_(path)
    if bundle is None:
        return None
    raw = bundle.bundleIdentifier()
    if not raw:
        return None
    return normalize_bundle_id(raw)


def _icon_rect_ax(item) -> tuple[float, float, float, float] | None:
    """Return (x, y, w, h) in AX coords for the icon, or None."""
    pos_value = _ax_attr(item, kAXPositionAttribute)
    size_value = _ax_attr(item, kAXSizeAttribute)
    if pos_value is None or size_value is None:
        return None
    ok_p, point = AXValueGetValue(pos_value, kAXValueCGPointType, None)
    ok_s, size = AXValueGetValue(size_value, kAXValueCGSizeType, None)
    if not ok_p or not ok_s:
        return None
    return float(point.x), float(point.y), float(size.width), float(size.height)


def _ax_y_to_ns_y(ax_y: float, ax_h: float) -> float:
    """Convert AX (top-left origin) Y to NSWindow (bottom-left origin) Y."""
    screen = NSScreen.mainScreen()
    sh = float(screen.frame().size.height) if screen else 900.0
    return sh - ax_y - ax_h


def _make_is_stale(threshold_days: int):
    """Return a predicate `is_stale(bundle_id) -> bool`.

    Both keys (profile-side) and lookup arguments (OS-side) are routed
    through `customos_core.identity.normalize_bundle_id`, so canonical-case
    Dock entries (e.g. 'com.apple.Safari') collide on the same key as
    lowercased profile entries (e.g. 'com.apple.safari'). See ADR-0006.
    """
    profile = get_profile()
    generated_at = profile_generated_at().replace(tzinfo=None)
    threshold = timedelta(days=threshold_days)
    last_seen: dict[str, datetime] = {}
    for app in profile.get("apps", []):
        ts = app.get("last_seen")
        bundle = app.get("bundle")
        if not ts or not bundle:
            continue
        try:
            last_seen[normalize_bundle_id(bundle)] = datetime.fromisoformat(ts)
        except (ValueError, KeyError):
            continue

    def is_stale(bundle_id: str) -> bool:
        key = normalize_bundle_id(bundle_id or "")
        if key not in last_seen:
            return True
        return (generated_at - last_seen[key]) >= threshold

    return is_stale


class DockDimUnusedExecutor(CustomizationExecutor):
    def __init__(self) -> None:
        self._overlays: list = []

    def apply(self, parameters: dict[str, Any]) -> None:
        threshold_days = int(parameters.get("days_threshold", 30))
        opacity = float(parameters.get("dim_opacity", 0.55))

        is_stale = _make_is_stale(threshold_days)

        pid = _dock_pid()
        if pid is None:
            raise RuntimeError("Dock process not found")
        items = _dock_items(pid)
        logger.info("dock items discovered", count=len(items))

        dimmed = 0
        for item in items:
            url = _ax_attr(item, kAXURLAttribute)
            bundle_id = _bundle_id_from_url(url)
            if not bundle_id:
                continue
            if not is_stale(bundle_id):
                continue
            rect = _icon_rect_ax(item)
            if rect is None:
                continue
            ax_x, ax_y, w, h = rect
            ns_y = _ax_y_to_ns_y(ax_y, h)
            win = self._make_overlay(ax_x, ns_y, w, h, opacity)
            self._overlays.append(win)
            dimmed += 1
            logger.info("dimming dock icon", bundle=bundle_id, x=ax_x, y=ax_y, w=w, h=h)

        logger.info("dock dim apply complete", dimmed=dimmed, total=len(items))

    def revert(self) -> None:
        for win in self._overlays:
            try:
                win.orderOut_(None)
                win.close()
            except Exception:
                logger.exception("error closing overlay")
        self._overlays.clear()
        logger.info("dock dim reverted")

    @staticmethod
    def _make_overlay(x: float, y: float, w: float, h: float, opacity: float) -> "NSWindow":
        rect = NSMakeRect(x, y, w, h)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        # NSStatusWindowLevel sits above the Dock on macOS.
        win.setLevel_(NSStatusWindowLevel + 1)
        win.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.0, opacity))
        win.setOpaque_(False)
        win.setHasShadow_(False)
        win.setIgnoresMouseEvents_(True)
        win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        win.orderFront_(None)
        return win
