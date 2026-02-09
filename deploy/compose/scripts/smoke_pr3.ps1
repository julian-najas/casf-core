<#
.SYNOPSIS
  PR3 — Integration Smoke (compose-level). Zero mocks.
.DESCRIPTION
  Validates:
    1. Stack healthy
    2. /healthz OK
    3. DENY by invariant (READ_ONLY + WRITE)
    4. FAIL-CLOSED (Redis down + twilio.send_sms)
  Exit 0 = PASSED, 1 = FAILED.
#>

$ErrorActionPreference = "Continue"

function Fail($msg) {
  Write-Host "FAIL: $msg" -ForegroundColor Red
  docker compose -f $COMPOSE_FILE start redis 2>&1 | Out-Null
  exit 1
}

function Ok($msg) {
  Write-Host "PASS: $msg" -ForegroundColor Green
}

$COMPOSE_FILE = Join-Path $PSScriptRoot "..\docker-compose.yml"
$VERIFIER     = "http://localhost:8088"

Write-Host "== PR3: Integration Smoke ==" -ForegroundColor Cyan

# ── 1) Stack healthy ────────────────────────────────────
Write-Host "`n== docker compose ps =="
$ps = docker compose -f $COMPOSE_FILE ps --format "{{.Name}}:{{.Health}}" 2>&1 | Where-Object { $_ -is [string] }
$ps | ForEach-Object { Write-Host "  $_" }
$unhealthy = $ps | Where-Object { $_ -and $_ -notmatch "healthy" }
if ($unhealthy) { Fail "Servicios no healthy: $($unhealthy -join ', ')" }
Ok "Todos los servicios healthy"

# ── 2) /healthz ─────────────────────────────────────────
Write-Host "`n== verifier /healthz =="
try {
  $h = Invoke-RestMethod "$VERIFIER/healthz" -TimeoutSec 5
  if ($h.status -ne "ok") { Fail "healthz != ok" }
} catch {
  Fail "healthz no responde: $_"
}
Ok "healthz OK (pg=$($h.checks.postgres) redis=$($h.checks.redis) opa=$($h.checks.opa))"

# ── 3) DENY por invariant: READ_ONLY + WRITE ────────────
Write-Host "`n== VERIFY DENY (READ_ONLY + create_appointment) =="
$denyBody = @{
  request_id = [guid]::NewGuid().ToString()
  tool       = "cliniccloud.create_appointment"
  mode       = "READ_ONLY"
  role       = "receptionist"
  subject    = @{ patient_id = "p1" }
  args       = @{}
  context    = @{ tenant_id = "t-demo"; timestamp = "2026-02-09T10:00:00Z"; source = "smoke" }
} | ConvertTo-Json -Depth 5

try {
  $r1 = Invoke-RestMethod -Method POST -Uri "$VERIFIER/verify" -ContentType "application/json" -Body $denyBody
} catch {
  Fail "POST /verify (deny case) fallo: $_"
}

if ($r1.decision -ne "DENY") { Fail "Esperado DENY, obtenido $($r1.decision)" }
Ok "DENY decision correcta (violations=$($r1.violations -join ','))"

# ── 4) ALLOW + audit event ──────────────────────────────
Write-Host "`n== VERIFY ALLOW (READ_ONLY + list_appointments) =="
$allowBody = @{
  request_id = [guid]::NewGuid().ToString()
  tool       = "cliniccloud.list_appointments"
  mode       = "READ_ONLY"
  role       = "receptionist"
  subject    = @{ patient_id = "p1" }
  args       = @{}
  context    = @{ tenant_id = "t-demo"; timestamp = "2026-02-09T10:00:00Z"; source = "smoke" }
} | ConvertTo-Json -Depth 5

$countBefore = (docker exec compose-postgres-1 psql -U casf -d casf -t -A -c "SELECT count(*) FROM audit_events;").Trim()
try {
  $r2 = Invoke-RestMethod -Method POST -Uri "$VERIFIER/verify" -ContentType "application/json" -Body $allowBody
} catch {
  Fail "POST /verify (allow case) fallo: $_"
}

if ($r2.decision -ne "ALLOW") { Fail "Esperado ALLOW, obtenido $($r2.decision)" }
$countAfter = (docker exec compose-postgres-1 psql -U casf -d casf -t -A -c "SELECT count(*) FROM audit_events;").Trim()
if ([int]$countAfter -le [int]$countBefore) { Fail "Audit no genero evento ($countBefore -> $countAfter)" }
Ok "ALLOW + audit OK ($countBefore -> $countAfter)"

# ── 5) FAIL-CLOSED: Redis down + twilio.send_sms ────────
Write-Host "`n== STOP redis =="
docker compose -f $COMPOSE_FILE stop redis 2>&1 | Out-Null
Start-Sleep -Seconds 3

$smsBody = @{
  request_id = [guid]::NewGuid().ToString()
  tool       = "twilio.send_sms"
  mode       = "ALLOW"
  role       = "receptionist"
  subject    = @{ patient_id = "p999" }
  args       = @{ to = "+34600000000"; template_id = "t1" }
  context    = @{ tenant_id = "t-demo"; timestamp = "2026-02-09T10:00:00Z"; source = "smoke" }
} | ConvertTo-Json -Depth 5

Write-Host "`n== VERIFY SMS with redis down (FAIL-CLOSED) =="
try {
  $r3 = Invoke-RestMethod -Method POST -Uri "$VERIFIER/verify" -ContentType "application/json" -Body $smsBody
} catch {
  Fail "POST /verify (sms fail-closed) fallo: $_"
}

if ($r3.decision -ne "DENY")                         { Fail "Esperado DENY, obtenido $($r3.decision)" }
if ($r3.violations -notcontains "FAIL_CLOSED")        { Fail "No aparece FAIL_CLOSED en violations" }
Ok "FAIL-CLOSED SMS OK (violations=$($r3.violations -join ','))"

# ── 6) Restore ──────────────────────────────────────────
Write-Host "`n== START redis =="
docker compose -f $COMPOSE_FILE start redis 2>&1 | Out-Null
Start-Sleep -Seconds 5

try {
  $h2 = Invoke-RestMethod "$VERIFIER/healthz" -TimeoutSec 5
  if ($h2.checks.redis -ne "ok") { Fail "/healthz no se recupero tras restart redis" }
} catch {
  Fail "/healthz fallo tras restart redis: $_"
}
Ok "Redis restaurado, /healthz recovered"

# ── Result ───────────────────────────────────────────────
Write-Host "`nPR3 PASSED" -ForegroundColor Green
exit 0
