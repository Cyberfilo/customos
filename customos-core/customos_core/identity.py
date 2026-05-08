"""Identifier normalization shared by profile-extractor (producer) and
customization-system (consumer).

Why this lives in customos-core (not in either subsystem):
  Identifiers cross the seam between the two subsystems. The extractor
  writes a `bundle` field into `profile.json` after lowercasing it; the
  customization-system reads the same string from macOS surfaces (Dock,
  NSWorkspace, AXURL) which return canonical (mixed-case) form. If only
  one side normalizes — or each side normalizes differently — the
  comparison silently misses. ADR-0006 captures the dock-dimming bug
  this exact drift produced.

Helpers in this module are deliberately pure: no I/O, no settings, no
warehouse access. Callers that need state-bearing wrappers (e.g.
`hash_contact` with a per-install salt loaded from disk) build them
on top.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit


_BUNDLE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def normalize_bundle_id(b: str) -> str:
    """Canonicalize a macOS bundle ID.

    For inputs that look like reverse-DNS bundle IDs ([A-Za-z0-9._-]+),
    strip surrounding whitespace and lowercase. Non-matching inputs are
    returned trimmed but otherwise untouched — never lossy.

    The function is idempotent: ``normalize(normalize(x)) == normalize(x)``.
    """
    if not b:
        return ""
    b = b.strip()
    if _BUNDLE_RE.match(b):
        return b.lower()
    return b


def canonicalize_url(url: str) -> tuple[str, str]:
    """Return ``(canonical_url, domain)`` for grouping purposes.

    Strips query string and fragment (deliberate noise reduction —
    URL-canonicalization for grouping, not for fetching). Lowercases the
    scheme and hostname. Defaults the path to ``"/"`` if the URL has none.
    Returns ``(url, "")`` on parse failure rather than raising.
    """
    try:
        s = urlsplit(url)
        domain = (s.hostname or "").lower()
        path = s.path or "/"
        canonical = urlunsplit((s.scheme.lower(), domain, path, "", ""))
        return canonical, domain
    except Exception:
        return url, ""


def hash_contact(identifier: str, *, salt: str) -> str:
    """One-way hash for a phone number / email / handle.

    Output format: ``"c_" + sha256(salt + normalize(identifier))[:16]``,
    where ``normalize`` lowercases and strips internal whitespace. The
    same person produces the same hash across data sources (Messages,
    Mail, etc.) provided the salt is the same.

    The salt is parameterized so this helper is stateless — callers that
    keep a per-install salt (e.g. profile-extractor's
    ``settings.privacy.contact_hash_salt``) wrap this with their own
    salt-loading code.

    Generalisation note (ADR-0006): the original
    ``profile-extractor/macprofile/normalize/identity.py`` read the salt
    from ``get_settings()``. The lift to customos-core promoted the salt
    to a keyword argument so the function has no extractor dependency;
    the extractor now holds the salt and passes it in.
    """
    norm = re.sub(r"\s+", "", identifier.strip().lower())
    h = hashlib.sha256()
    h.update(salt.encode())
    h.update(norm.encode())
    return "c_" + h.hexdigest()[:16]


__all__ = ["normalize_bundle_id", "canonicalize_url", "hash_contact"]
