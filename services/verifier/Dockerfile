# ── Build stage ──────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml /build/pyproject.toml
COPY src /build/src
RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir --prefix=/install .

# ── Runtime stage ────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: run as non-root
RUN groupadd --gid 10001 appuser \
 && useradd --uid 10001 --gid appuser --shell /bin/false --create-home appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY src /app/src

ENV PYTHONPATH=/app/src

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uvicorn", "verifier.main:app", "--host", "0.0.0.0", "--port", "8000"]
