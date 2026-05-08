"""Tests for customos_core.identity.

Covers the case-equivalence / no-op-on-canonical / idempotence properties
that ADR-0006 promises every cross-subsystem identifier comparison can rely
on. The dock-dimming regression test (Dock returning canonical-case bundle
IDs vs. profile storing lowercased ones) is at the bottom.
"""
from __future__ import annotations

import pytest

from customos_core.identity import (
    canonicalize_url,
    hash_contact,
    normalize_bundle_id,
)


# ---------------------------------------------------------------------------
# normalize_bundle_id
# ---------------------------------------------------------------------------

class TestNormalizeBundleId:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("com.apple.Safari", "com.apple.safari"),
            ("COM.APPLE.SAFARI", "com.apple.safari"),
            ("Com.Apple.SAFARI", "com.apple.safari"),
            ("net.whatsapp.WhatsApp", "net.whatsapp.whatsapp"),
            ("com.urban-vpn.mac", "com.urban-vpn.mac"),
            ("com.apple.iWork.Pages", "com.apple.iwork.pages"),
        ],
    )
    def test_case_insensitive(self, raw, expected):
        assert normalize_bundle_id(raw) == expected

    @pytest.mark.parametrize(
        "canonical",
        [
            "com.apple.safari",
            "com.apple.terminal",
            "com.apple.music",
            "net.whatsapp.whatsapp",
            "org.python.python",
        ],
    )
    def test_no_op_on_canonical(self, canonical):
        assert normalize_bundle_id(canonical) == canonical

    @pytest.mark.parametrize(
        "raw",
        [
            "com.apple.Safari",
            "COM.APPLE.SAFARI",
            "  com.apple.terminal  ",
            "com.apple.iWork.Pages",
            "com.urban-vpn.mac",
        ],
    )
    def test_idempotent(self, raw):
        once = normalize_bundle_id(raw)
        twice = normalize_bundle_id(once)
        assert once == twice

    def test_empty(self):
        assert normalize_bundle_id("") == ""

    def test_strips_surrounding_whitespace(self):
        assert normalize_bundle_id("  com.apple.Safari  ") == "com.apple.safari"

    def test_non_matching_input_is_returned_as_is(self):
        # Input with internal whitespace doesn't match the regex, so the
        # function refuses to lossy-normalize and returns the trimmed
        # input untouched. This is the "never lossy" property.
        weird = "com.apple Safari"
        assert normalize_bundle_id(weird) == weird

    def test_non_matching_input_is_idempotent(self):
        weird = "com.apple Safari"
        assert normalize_bundle_id(normalize_bundle_id(weird)) == weird


# ---------------------------------------------------------------------------
# canonicalize_url
# ---------------------------------------------------------------------------

class TestCanonicalizeUrl:
    def test_strips_query_and_fragment(self):
        url = "https://www.example.com/path?q=foo&r=bar#frag"
        canon, domain = canonicalize_url(url)
        assert canon == "https://www.example.com/path"
        assert domain == "www.example.com"

    def test_lowercases_scheme_and_host(self):
        url = "HTTPS://Www.EXAMPLE.com/Path"
        canon, domain = canonicalize_url(url)
        assert canon == "https://www.example.com/Path"
        assert domain == "www.example.com"

    def test_default_path_is_slash(self):
        url = "https://example.com"
        canon, domain = canonicalize_url(url)
        assert canon == "https://example.com/"
        assert domain == "example.com"

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/anthropics/anthropic-sdk-python",
            "http://localhost:8765/health",
            "https://www.icloud.com/calendar/",
        ],
    )
    def test_idempotent(self, url):
        once_url, _ = canonicalize_url(url)
        twice_url, _ = canonicalize_url(once_url)
        assert once_url == twice_url

    def test_no_op_on_already_canonical(self):
        url = "https://example.com/page"
        canon, _ = canonicalize_url(url)
        assert canon == url

    def test_garbage_does_not_raise(self):
        url, domain = canonicalize_url("not a url at all")
        # Returns either the trimmed input or a parsed-best-effort form;
        # the contract is just "no exception".
        assert isinstance(url, str)
        assert isinstance(domain, str)


# ---------------------------------------------------------------------------
# hash_contact
# ---------------------------------------------------------------------------

class TestHashContact:
    SALT = "test-salt-deadbeefcafebabe"

    def test_format(self):
        h = hash_contact("foo@example.com", salt=self.SALT)
        assert h.startswith("c_")
        assert len(h) == 18  # "c_" + 16 hex
        # hex part is lowercase 0-9a-f
        assert all(c in "0123456789abcdef" for c in h[2:])

    def test_deterministic(self):
        a = hash_contact("foo@example.com", salt=self.SALT)
        b = hash_contact("foo@example.com", salt=self.SALT)
        assert a == b

    def test_case_equivalent(self):
        lower = hash_contact("foo@example.com", salt=self.SALT)
        upper = hash_contact("FOO@EXAMPLE.COM", salt=self.SALT)
        assert lower == upper

    def test_whitespace_normalized(self):
        no_ws = hash_contact("foo@example.com", salt=self.SALT)
        outer_ws = hash_contact("  foo@example.com  ", salt=self.SALT)
        inner_ws = hash_contact("foo @ example . com", salt=self.SALT)
        assert no_ws == outer_ws
        # Inner whitespace is also stripped per the function's
        # `re.sub(r"\s+", "", ...)` step.
        assert no_ws == inner_ws

    def test_different_salts_different_outputs(self):
        a = hash_contact("foo@example.com", salt="salt-a")
        b = hash_contact("foo@example.com", salt="salt-b")
        assert a != b

    def test_idempotent_on_already_normalized(self):
        # Hashing the *output* of one call obviously gives a different
        # hash (it's a hash of a hash). The relevant idempotence here
        # is on the *input normalisation*: two calls with semantically
        # equivalent inputs must agree.
        first = hash_contact("FOO @ Example.COM", salt=self.SALT)
        second = hash_contact("foo@example.com", salt=self.SALT)
        assert first == second


# ---------------------------------------------------------------------------
# ADR-0006 regression test: dock-dimming bundle-ID drift
# ---------------------------------------------------------------------------

def test_dock_canonical_case_matches_profile_lowercase():
    """Reproduces the failure mode that motivated lifting these helpers.

    The Dock returns bundle IDs in canonical (mixed) case via AXURL +
    NSBundle (e.g. 'com.apple.Safari'). The profile-extractor lowercases
    every bundle ID before storage (e.g. 'com.apple.safari'). Pre-lift,
    a case-sensitive `==` lookup classified the user's most-used apps as
    "never seen" and the dock_dim_unused executor dimmed them. Post-lift,
    every consumer routes through `normalize_bundle_id`, so canonical
    and lowercase forms collide on the same key.
    """
    dock_form = "com.apple.Safari"  # what AXURL gives us
    profile_form = "com.apple.safari"  # what's in profile.json
    assert normalize_bundle_id(dock_form) == normalize_bundle_id(profile_form)
