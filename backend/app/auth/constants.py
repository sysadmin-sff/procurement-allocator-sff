from datetime import timedelta

SESSION_IDLE_TTL = timedelta(hours=12)
"""Extended on every authenticated request. See ADR-0024 §3."""
SESSION_ABSOLUTE_TTL = timedelta(days=30)
"""Hard ceiling from UserSession.created_at, never extended. See ADR-0024 §3."""
OAUTH_FLOW_TTL = timedelta(minutes=10)
"""TTL of the oauth_flow cookie holding PKCE verifier + state. See ADR-0024 §1 п.2."""
