from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_startup_calls_bootstrap_admin_when_email_configured(monkeypatch):
    email = "startup-admin@screen-factory-florida.com"
    monkeypatch.setattr(settings, "bootstrap_admin_email", email)
    with patch("app.main.bootstrap_admin") as mock_bootstrap:
        with TestClient(app):
            pass
        mock_bootstrap.assert_called_once()
        args = mock_bootstrap.call_args
        assert args[0][1] == email


def test_startup_skips_bootstrap_admin_when_email_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", None)
    with patch("app.main.bootstrap_admin") as mock_bootstrap:
        with TestClient(app):
            pass
        mock_bootstrap.assert_not_called()
