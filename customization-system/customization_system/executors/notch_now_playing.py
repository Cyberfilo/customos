"""Floating widget under the notch showing the current track and artist.

Architecture:
  - One borderless NSWindow at the top-center of the main screen, just below
    the menu bar / notch. Rounded translucent background; one NSTextField for
    "♪ Track — Artist".
  - NSDistributedNotificationCenter observer listens to:
      * com.apple.iTunes.playerInfo            (Apple Music.app)
      * com.spotify.client.PlaybackStateChanged (Spotify)
    Both apps post a userInfo dict containing 'Name', 'Artist',
    'Player State' ('Playing' | 'Paused' | 'Stopped'). When state is
    Playing, we show the panel; otherwise hide.

Why not MediaRemote.framework:
  - MRMediaRemoteGetNowPlayingInfo was restricted in macOS 14.4 (Sonoma).
    Third-party processes no longer receive now-playing data via that
    private API. Distributed notifications are the only reliable public
    source on macOS 14.4+ (incl. Tahoe 26.x).

Limitations of the minimal v1:
  - No album artwork, no controls (play/pause/skip). The vocabulary entry
    description mentions both as future capabilities. They are deliberately
    out of scope this session to avoid the notch widget dominating it.
  - No initial seed: if music is already playing when we start, the panel
    stays hidden until the next state change. Adding an AppleScript-based
    seed is a small follow-up.

Revert:
  - Remove the distributed-notification observer; close the window.
"""
from __future__ import annotations

from typing import Any

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSLineBreakByTruncatingTail,
    NSMakeRect,
    NSScreen,
    NSStatusWindowLevel,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSDistributedNotificationCenter, NSObject
from loguru import logger

from customization_system.executor import CustomizationExecutor


_PANEL_W = 280.0
_PANEL_H = 30.0


class _NowPlayingObserver(NSObject):
    """ObjC-visible target for NSDistributedNotificationCenter."""

    def initWithCallback_(self, callback):  # noqa: N802 (ObjC selector form)
        self = objc.super(_NowPlayingObserver, self).init()
        if self is None:
            return None
        self._callback = callback  # type: ignore[attr-defined]
        return self

    def handle_(self, notification):  # noqa: N802 (ObjC selector form)
        try:
            raw = notification.userInfo()
            info = dict(raw) if raw is not None else {}
            self._callback(info)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("now-playing handler error")


class NotchNowPlayingExecutor(CustomizationExecutor):
    def __init__(self) -> None:
        self._window: NSWindow | None = None
        self._label: NSTextField | None = None
        self._observer: _NowPlayingObserver | None = None
        self._show_artist: bool = True

    # ---- apply / revert ----

    def apply(self, parameters: dict[str, Any]) -> None:
        self._show_artist = bool(parameters.get("show_artist", True))
        self._window, self._label = _build_window()
        # Start hidden; first Playing notification will reveal.
        self._window.orderOut_(None)

        observer = _NowPlayingObserver.alloc().initWithCallback_(self._on_now_playing)
        center = NSDistributedNotificationCenter.defaultCenter()
        center.addObserver_selector_name_object_(
            observer, "handle:", "com.apple.iTunes.playerInfo", None
        )
        center.addObserver_selector_name_object_(
            observer, "handle:", "com.spotify.client.PlaybackStateChanged", None
        )
        self._observer = observer
        logger.info("notch widget armed (hidden until first playback notification)")

    def revert(self) -> None:
        if self._observer is not None:
            try:
                NSDistributedNotificationCenter.defaultCenter().removeObserver_(self._observer)
            except Exception:
                logger.exception("error removing distributed-notification observer")
            self._observer = None
        if self._window is not None:
            try:
                self._window.orderOut_(None)
                self._window.close()
            except Exception:
                logger.exception("error closing notch window")
            self._window = None
            self._label = None
        logger.info("notch widget reverted")

    # ---- notification handling ----

    def _on_now_playing(self, info: dict) -> None:
        state = str(info.get("Player State", "")).lower()
        name = info.get("Name") or ""
        artist = info.get("Artist") or ""
        logger.info("now playing notification", state=state, name=name, artist=artist)
        if state == "playing" and name:
            if self._show_artist and artist:
                text = f"♪  {name} — {artist}"
            else:
                text = f"♪  {name}"
            if self._label is not None:
                self._label.setStringValue_(text)
            if self._window is not None:
                self._window.orderFrontRegardless()
        else:
            if self._window is not None:
                self._window.orderOut_(None)


def _build_window() -> tuple[NSWindow, NSTextField]:
    screen = NSScreen.mainScreen()
    if screen is None:
        x, y = 100.0, 100.0
    else:
        sf = screen.frame()
        vf = screen.visibleFrame()
        x = sf.origin.x + (sf.size.width - _PANEL_W) / 2.0
        # 4px below the top of the visible area (i.e. below menu bar / notch).
        y = vf.origin.y + vf.size.height - _PANEL_H - 4.0

    rect = NSMakeRect(x, y, _PANEL_W, _PANEL_H)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect,
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False,
    )
    win.setLevel_(NSStatusWindowLevel + 1)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setOpaque_(False)
    win.setHasShadow_(True)
    win.setIgnoresMouseEvents_(True)
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorIgnoresCycle
    )

    # Rounded translucent black content view.
    content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _PANEL_W, _PANEL_H))
    content.setWantsLayer_(True)
    layer = content.layer()
    layer.setBackgroundColor_(
        NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.85).CGColor()
    )
    layer.setCornerRadius_(_PANEL_H / 2.0)

    # Track text — single line, truncate-tail.
    pad = 10.0
    label = NSTextField.alloc().initWithFrame_(
        NSMakeRect(pad, (_PANEL_H - 18.0) / 2.0, _PANEL_W - 2 * pad, 18.0)
    )
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setTextColor_(NSColor.whiteColor())
    label.setFont_(NSFont.systemFontOfSize_(12.0))
    label.setAlignment_(1)  # NSTextAlignmentCenter
    label.setStringValue_("")
    label.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
    content.addSubview_(label)

    win.setContentView_(content)
    return win, label
