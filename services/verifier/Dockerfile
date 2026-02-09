FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

ENV PYTHONPATH=/app/src

EXPOSE 8000
CMD ["uvicorn", "verifier.main:app", "--host", "0.0.0.0", "--port", "8000"]
