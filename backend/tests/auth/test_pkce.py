import base64
import hashlib

from app.auth.pkce import generate_pkce_pair, generate_state


def test_generate_pkce_pair_challenge_matches_verifier():
    verifier, challenge = generate_pkce_pair()
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert challenge == expected


def test_generate_pkce_pair_verifier_length_in_spec_range():
    verifier, _ = generate_pkce_pair()
    assert 43 <= len(verifier) <= 128


def test_generate_state_is_url_safe_and_nonempty():
    state = generate_state()
    assert len(state) >= 16
    assert all(c.isalnum() or c in "-_" for c in state)


def test_generate_pkce_pair_is_random():
    v1, _ = generate_pkce_pair()
    v2, _ = generate_pkce_pair()
    assert v1 != v2
