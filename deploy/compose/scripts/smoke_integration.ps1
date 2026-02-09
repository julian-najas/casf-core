<#
.SYNOPSIS
  CASF Integration Smoke Test — compose-level, zero mocks.
.DESCRIPTION
  Validates the full decision pipeline:
    1. All services healthy
    2. DENY by invariant (READ_ONLY + WRITE → Mode_ReadOnly_NoWrite)
    3. ALLOW + audit event generated
    4. FAIL-CLOSED when Redis is down (twilio.send_sms → DENY)
    5. /healthz degrades when Redis is down
  Exit code 0 = PASS, 1 = FAIL.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$COMPOSE_FILE = Join-Path $PSScriptRoot "..\docker-compose.yml"
$VERIFIER     = "http://localhost:8088"
$pass         = 0
$fail         = 0

# Suppress Docker Compose stderr warnings (e.g. "version is obsolete")
$env:COMPOSE_IGNORE_ORPHANS = "true"

# ── Helpers ──────────────────────────────────────────────

function Write-Check  { param([string]$msg) Write-Host "`n--- CHECK: $msg ---" -ForegroundColor Cyan }
function Write-Pass   { param([string]$msg) Write-Host "  PASS: $msg" -ForegroundColor Green; $script:pass++ }
function Write-Fail   { param([string]$msg) Write-Host "  FAIL: $msg" -ForegroundColor Red;   $script:fail++ }

function Post-Verify {
    param(
        [string]$Tool,
        [string]$Mode = "ALLOW",
        [string]$Role = "receptionist"
    )
    $body = @{
        request_id = [guid]::NewGuid().ToString()
        tool       = $Tool
        mode       = $Mode
        role       = $Role
        subject    = @{ patient_id = "p1" }
        args       = @{ to = "+34600000000"; template_id = "t1" }
        context    = @{ tenant_id = "t-demo"; timestamp = "2026-02-09T10:00:00Z"; source = "smoke" }
    } | ConvertTo-Json -Depth 5

    $resp = Invoke-WebRequest -Uri "$VERIFIER/verify" -Method POST `
        -Body $body -ContentType "application/json" -UseBasicParsing
    return @{
        StatusCode = $resp.StatusCode
        Body       = ($resp.Content | ConvertFrom-Json)
    }
}

function Get-AuditCount {
    $out = docker exec compose-postgres-1 psql -U casf -d casf -t -A -c "SELECT count(*) FROM audit_events;"
    return [int]$out.Trim()
}

# ── 0. Pre-flight: all services healthy ──────────────────

Write-Check "All services healthy"

$ps = docker compose -f $COMPOSE_FILE ps --format "{{.Name}}:{{.Health}}" 2>&1 | Where-Object { $_ -is [string] }
$unhealthy = $ps | Where-Object { $_ -and $_ -notmatch "healthy" }
if ($unhealthy) {
    Write-Fail "Unhealthy services: $($unhealthy -join ', ')"
} else {
    Write-Pass "All 4 services healthy"
}

# ── 1. /healthz returns OK ──────────────────────────────

Write-Check "GET /healthz → 200 + all checks ok"

try {
    $hz = Invoke-RestMethod -Uri "$VERIFIER/healthz" -Method GET
    if ($hz.status -eq "ok" -and $hz.checks.postgres -eq "ok" -and $hz.checks.redis -eq "ok" -and $hz.checks.opa -eq "ok") {
        Write-Pass "/healthz all green"
    } else {
        Write-Fail "/healthz unexpected body: $($hz | ConvertTo-Json -Compress)"
    }
} catch {
    Write-Fail "/healthz error: $_"
}

# ── 2. DENY by invariant: READ_ONLY + WRITE tool ────────

Write-Check "POST /verify (READ_ONLY + create_appointment) → DENY"

try {
    $r = Post-Verify -Tool "cliniccloud.create_appointment" -Mode "READ_ONLY"
    if ($r.Body.decision -eq "DENY") {
        Write-Pass "decision=DENY  violations=$($r.Body.violations -join ',')"
    } else {
        Write-Fail "Expected DENY, got $($r.Body.decision)"
    }
} catch {
    Write-Fail "Request failed: $_"
}

# ── 3. ALLOW + audit event generated ────────────────────

Write-Check "POST /verify (READ_ONLY + list_appointments) → ALLOW + audit row"

$countBefore = Get-AuditCount
try {
    $r = Post-Verify -Tool "cliniccloud.list_appointments" -Mode "READ_ONLY"
    if ($r.Body.decision -eq "ALLOW") {
        Write-Pass "decision=ALLOW  allowed_outputs=$($r.Body.allowed_outputs -join ',')"
    } else {
        Write-Fail "Expected ALLOW, got $($r.Body.decision)"
    }
} catch {
    Write-Fail "Request failed: $_"
}

$countAfter = Get-AuditCount
if ($countAfter -gt $countBefore) {
    Write-Pass "Audit event appended ($countBefore → $countAfter)"
} else {
    Write-Fail "No audit event generated ($countBefore → $countAfter)"
}

# ── 4. FAIL-CLOSED: stop Redis → twilio.send_sms → DENY ─

Write-Check "Stop Redis → POST /verify (twilio.send_sms) → DENY FAIL_CLOSED"

docker compose -f $COMPOSE_FILE stop redis 2>&1 | Out-Null
Start-Sleep -Seconds 3

try {
    $r = Post-Verify -Tool "twilio.send_sms" -Mode "ALLOW"
    if ($r.Body.decision -eq "DENY" -and ($r.Body.violations -contains "FAIL_CLOSED")) {
        Write-Pass "decision=DENY  violations=$($r.Body.violations -join ',')"
    } else {
        Write-Fail "Expected DENY+FAIL_CLOSED, got decision=$($r.Body.decision) violations=$($r.Body.violations -join ',')"
    }
} catch {
    Write-Fail "Request failed: $_"
}

# ── 5. /healthz degrades when Redis is down ──────────────

Write-Check "GET /healthz → 503 (Redis down)"

try {
    $null = Invoke-WebRequest -Uri "$VERIFIER/healthz" -Method GET -UseBasicParsing
    Write-Fail "/healthz returned 200 but Redis is down"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 503) {
        Write-Pass "/healthz returned 503 (correct degradation)"
    } else {
        Write-Fail "/healthz unexpected error: $_"
    }
}

# ── 6. Restore Redis ────────────────────────────────────

Write-Check "Restore Redis"
docker compose -f $COMPOSE_FILE start redis 2>&1 | Out-Null
Start-Sleep -Seconds 8

try {
    $hz = Invoke-RestMethod -Uri "$VERIFIER/healthz" -Method GET
    if ($hz.checks.redis -eq "ok") {
        Write-Pass "/healthz recovered after Redis restart"
    } else {
        Write-Fail "/healthz still degraded after Redis restart"
    }
} catch {
    Write-Fail "/healthz failed after Redis restart: $_"
}

# ── Summary ──────────────────────────────────────────────

Write-Host "`n=============================" -ForegroundColor White
Write-Host "  PASSED: $pass" -ForegroundColor Green
Write-Host "  FAILED: $fail" -ForegroundColor $(if ($fail -gt 0) { "Red" } else { "Green" })
Write-Host "=============================" -ForegroundColor White

if ($fail -gt 0) {
    Write-Host "`nSMOKE FAILED" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`nSMOKE PASSED" -ForegroundColor Green
    exit 0
}
