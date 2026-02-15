import json
import os

__all__ = [
    "PG_DSN",
    "REDIS_URL",
    "OPA_URL",
    "ANTI_REPLAY_ENABLED",
    "ANTI_REPLAY_TTL_SECONDS",
    "SMS_RATE_LIMIT",
    "SMS_RATE_WINDOW_S",
    "SMS_RATE_TENANT_OVERRIDES",
]


def env(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"{name} env var is required")
    return v


PG_DSN = env("PG_DSN")
REDIS_URL = env("REDIS_URL", "redis://redis:6379/0")
OPA_URL = env("OPA_URL", "http://opa:8181")

# Anti-replay idempotency
ANTI_REPLAY_ENABLED = env("ANTI_REPLAY_ENABLED", "true").lower() in ("1", "true", "yes")
ANTI_REPLAY_TTL_SECONDS = int(env("ANTI_REPLAY_TTL_SECONDS", "86400"))

# SMS rate-limit defaults (overridable per tenant)
SMS_RATE_LIMIT = int(env("SMS_RATE_LIMIT", "1"))
SMS_RATE_WINDOW_S = int(env("SMS_RATE_WINDOW_S", "3600"))

# Per-tenant overrides: JSON map of tenant_id -> {"limit": N, "window_s": N}
# Example: '{"t-enterprise": {"limit": 10, "window_s": 3600}}'
SMS_RATE_TENANT_OVERRIDES: dict[str, dict[str, int]] = json.loads(
    env("SMS_RATE_TENANT_OVERRIDES", "{}")
)
