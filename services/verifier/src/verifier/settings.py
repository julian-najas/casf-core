import os


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
