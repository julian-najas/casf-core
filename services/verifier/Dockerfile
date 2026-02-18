# ── Build stage ──────────────────────────────────────────
FROM python:3.11-slim@sha256:0b23cfb7425d065008b778022a17b1551c82f8b4866ee5a7a200084b7e2eafbf AS builder

WORKDIR /build
COPY requirements.lock pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock --prefix=/install \
 && pip install --no-cache-dir --no-deps --prefix=/install .

# ── Runtime stage ────────────────────────────────────────
FROM python:3.11-slim@sha256:0b23cfb7425d065008b778022a17b1551c82f8b4866ee5a7a200084b7e2eafbf AS runtime

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
