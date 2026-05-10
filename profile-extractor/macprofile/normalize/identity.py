"""Identifier normalization shim.

Pure normalization (bundle IDs, URL canonicalization, contact hashing) lives
in `customos_core.identity` so the customization-system shares the same
canonical forms (see ADR-0006). This module is a thin compatibility shim:

  * `normalize_bundle_id` and `canonicalize_url` are re-exports — pure
    functions with no extractor state, identical signatures.
  * `hash_contact` keeps the extractor's old zero-arg signature: it loads
    the per-install salt from `settings.privacy.contact_hash_salt` and
    delegates to `customos_core.identity.hash_contact`. The lifted
    function takes `salt` as a keyword argument; this wrapper supplies
    it. Existing call sites in `extractors/{messages,mail}.py` keep
    working unchanged.
"""
from __future__ import annotations

from customos_core.identity import canonicalize_url
from customos_core.identity import hash_contact as _hash_contact_with_salt
from customos_core.identity import normalize_bundle_id

from macprofile.settings import get_settings


def hash_contact(identifier: str) -> str:
    """One-way hash for a phone number / email / handle. Stable across runs."""
    salt = get_settings().privacy.contact_hash_salt
    return _hash_contact_with_salt(identifier, salt=salt)


__all__ = ["canonicalize_url", "hash_contact", "normalize_bundle_id"]
