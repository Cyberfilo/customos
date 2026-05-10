"""Cross-device contamination filter.

iCloud Biome sync ingests events from a paired iPhone into the local Mac
store. We can't tell those events apart at extraction time (there is no
provenance bit on the SEGB record), so we filter them at analysis time
based on the target bundle ID.

Default policy: when in doubt, treat a bundle as macOS-native. False
positives here are recoverable — they just keep an event in the profile
that maybe shouldn't be there. False negatives (filtering out something
that *is* a Mac app) would silently delete real signal.

The list and the SQL clause must agree. They're produced together from
the same constants below.
"""
from __future__ import annotations

IOS_ONLY_BUNDLES: frozenset[str] = frozenset({
    # iOS app stores that have no macOS counterpart.
    "com.toyopagroup.picaboo",          # Snapchat (no Mac app)
    "com.burbn.instagram",              # Instagram (Mac is web-only)
    "com.zhiliaoapp.musically",         # TikTok iOS bundle
    "com.google.ios.youtube",
    # Apple iOS-only system surfaces.
    "com.apple.incallservice",          # iOS phone-call UI
    "com.apple.mobilesafari",
    "com.apple.mobilemail",
    "com.apple.mobileslideshow",        # iOS Photos
    # TODO uncertain — currently default to macOS-native, may need to move here:
    #   - com.apple.MobileSMS (Mac Messages and iOS Messages share this bundle id,
    #     so filtering would remove real Mac events; leaving in)
    #   - com.apple.facetime (universal across macOS/iOS; bundle shared, leaving in)
    #   - com.spotify.client (Mac and iOS share the bundle; leaving in)
})

IOS_ONLY_BUNDLE_PREFIXES: tuple[str, ...] = (
    # SpringBoard is iOS-only; every variant of transitionreason/lock-screen/
    # backlight/app-library lives under this prefix and signals iPhone activity.
    "com.apple.springboard.",
)


def is_macos_native(target: str | None, target_kind: str | None) -> bool:
    """True iff this event plausibly originated on the local Mac.

    Non-app events (file_access, web_visit, message_*, etc.) are always
    considered macOS-native — only `target_kind == "app"` is filtered, and
    only based on the bundle ID."""
    if target_kind != "app":
        return True
    if not target or target == "(unknown)":
        return True
    if target in IOS_ONLY_BUNDLES:
        return False
    for prefix in IOS_ONLY_BUNDLE_PREFIXES:
        if target.startswith(prefix):
            return False
    return True


def macos_native_sql() -> str:
    """SQL fragment that returns TRUE for macOS-native rows. Designed to be
    dropped inline into a WHERE clause.

    Note: this is a *positive* filter — every analyzer wraps it as
    `AND ({macos_native_sql()})` rather than negating any part of it."""
    bundle_in = ", ".join(f"'{b}'" for b in sorted(IOS_ONLY_BUNDLES))
    prefix_clauses = " AND ".join(
        f"target NOT LIKE '{p}%'" for p in IOS_ONLY_BUNDLE_PREFIXES
    )
    return (
        "("
        "target_kind <> 'app' "
        f"OR (target NOT IN ({bundle_in}) AND {prefix_clauses})"
        ")"
    )
