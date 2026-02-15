# Performance Benchmarks

## Tool

[Locust](https://locust.io/) — Python-native, scriptable HTTP load generator.

## Quick start

```bash
# Start the full stack
make up

# Headless run (20 users, ramp 5/s, 30 s duration)
make bench

# Interactive Web UI
pip install locust
cd benchmarks && locust -H http://localhost:8088
# Open http://localhost:8089
```

## Scenarios

| Weight | Name | Endpoint | Expected |
|--------|------|----------|----------|
| 5 | `read_allow` | `POST /verify` (list_appointments, doctor) | ALLOW — fast, no audit write |
| 3 | `write_allow` | `POST /verify` (create_appointment, doctor) | ALLOW + Postgres audit |
| 2 | `write_deny` | `POST /verify` (send_sms, receptionist) | DENY — rate-limit / OPA |
| 1 | `healthz` | `GET /healthz` | 200 — dependency round-trip |

## Baseline targets (single Uvicorn worker, local Docker)

| Metric | Target | Notes |
|--------|--------|-------|
| p50 latency | < 15 ms | Read-path (no audit write) |
| p95 latency | < 50 ms | Write-path (Postgres + Redis) |
| p99 latency | < 100 ms | Includes OPA evaluation |
| Throughput | > 200 req/s | 20 concurrent users |
| Error rate | < 0.1 % | Excludes intentional DENY |

These baselines assume a local Docker Compose stack on a modern laptop.
Production targets depend on infrastructure sizing and should be
established via dedicated load-testing against staging.

## Interpreting results

Locust reports (terminal or HTML) include:

- **RPS** — requests per second by endpoint
- **Response time** — p50 / p95 / p99 / max per endpoint
- **Failure rate** — HTTP 5xx or connection errors
- **Distribution** — histogram of response times

Export HTML report:

```bash
locust --headless -u 20 -r 5 --run-time 60s \
    -H http://localhost:8088 \
    --html benchmarks/report.html
```

## CI integration

Benchmarks are **not** part of the default CI pipeline (they require the full
Docker Compose stack). Run them manually or in a dedicated performance CI job:

```yaml
- name: Performance smoke
  run: |
    make up
    sleep 10
    cd benchmarks && locust --headless -u 10 -r 5 --run-time 15s \
        -H http://localhost:8088 --exit-code-on-error 1
```
