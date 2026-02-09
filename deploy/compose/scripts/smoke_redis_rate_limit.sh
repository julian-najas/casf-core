#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8088}"

echo "[smoke] Using compose dir: ${COMPOSE_DIR}"
cd "${COMPOSE_DIR}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1"; exit 1; }; }
need docker
need curl
need jq

echo "[smoke] docker compose up -d"
docker compose up -d

echo "[smoke] waiting /health..."
for i in $(seq 1 60); do
  if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
    echo "[smoke] verifier healthy"
    break
  fi
  sleep 1
  if [ "$i" -eq 60 ]; then
    echo "[smoke] verifier did not become healthy"
    docker compose logs verifier || true
    exit 1
  fi
done

sms_payload () {
  local req_id="$1"
  cat <<JSON
{
  "request_id": "${req_id}",
  "tool": "twilio.send_sms",
  "mode": "ALLOW",
  "role": "receptionist",
  "subject": { "patient_id": "p1" },
  "args": { "to": "+34600000000", "template_id": "t1" },
  "context": { "tenant_id": "t-demo" }
}
JSON
}

post_verify () {
  curl -fsS -X POST "${BASE_URL}/verify" \
    -H "Content-Type: application/json" \
    -d "$1"
}

echo "[smoke] 1) First SMS should be ALLOW"
r1="$(post_verify "$(sms_payload "s1")")"
echo "$r1" | jq -e '.decision=="ALLOW"' >/dev/null

echo "[smoke] 2) Second SMS within 1h should be DENY (Inv_NoSmsBurst)"
r2="$(post_verify "$(sms_payload "s2")")"
echo "$r2" | jq -e '.decision=="DENY"' >/dev/null
# tolerate either violations array or single violation field (depending on your contract)
echo "$r2" | jq -e '((.violations // []) | index("Inv_NoSmsBurst")) != null' >/dev/null

echo "[smoke] 3) Stop redis -> twilio.send_sms must FAIL-CLOSED (DENY)"
docker compose stop redis

r3="$(post_verify "$(sms_payload "s3")")" || true
# If your /verify returns 200 with decision=DENY, this will pass:
echo "$r3" | jq -e '.decision=="DENY"' >/dev/null
echo "$r3" | jq -e '((.violations // []) | index("FAIL_CLOSED")) != null' >/dev/null

echo "[smoke] OK"
