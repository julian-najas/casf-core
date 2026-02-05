# casf-core

CASF-core is a Zero-Trust Verification Service for PHI/PII automation.
It validates intent (tool/role/mode) before any execution and writes an append-only audit trail.

## Quickstart
docker compose -f deploy/compose/docker-compose.yml up --build

## Endpoint
POST http://localhost:8000/verify
