from app.core.config import Settings


def test_secrets_are_masked_in_repr_and_str():
    s = Settings(
        openai_api_key="sk-super-secret-key",
        google_client_secret="GOCSPX-super-secret",
        session_signing_secret="signing-super-secret",
    )

    dump = repr(s) + str(s)

    assert "sk-super-secret-key" not in dump
    assert "GOCSPX-super-secret" not in dump
    assert "signing-super-secret" not in dump


def test_secret_values_are_still_recoverable_via_get_secret_value():
    s = Settings(
        openai_api_key="sk-super-secret-key",
        google_client_secret="GOCSPX-super-secret",
        session_signing_secret="signing-super-secret",
    )

    assert s.openai_api_key.get_secret_value() == "sk-super-secret-key"
    assert s.google_client_secret.get_secret_value() == "GOCSPX-super-secret"
    assert s.session_signing_secret.get_secret_value() == "signing-super-secret"


def test_unset_secret_fields_remain_none():
    s = Settings(openai_api_key=None, google_client_secret=None, session_signing_secret=None)

    assert s.openai_api_key is None
    assert s.google_client_secret is None
    assert s.session_signing_secret is None
