# smoke_redis_rate_limit.ps1
# Script PowerShell equivalente al smoke_redis_rate_limit.sh

$ErrorActionPreference = 'Stop'

$COMPOSE_DIR = Join-Path $PSScriptRoot ".."
$BASE_URL = $env:BASE_URL
if (-not $BASE_URL) { $BASE_URL = "http://localhost:8088" }

Write-Host "[smoke] Using compose dir: $COMPOSE_DIR"
Set-Location $COMPOSE_DIR

function need($cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Missing dependency: $cmd"
        exit 1
    }
}

need docker
need curl


Write-Host "[smoke] docker compose up -d"
docker compose up -d

Write-Host "[smoke] waiting /health..."
$healthy = $false
for ($i = 1; $i -le 60; $i++) {
    try {
        $resp = curl -fsS "$BASE_URL/health"
        Write-Host "[smoke] verifier healthy"
        $healthy = $true
        break
    } catch {
        Write-Host ('[smoke][debug] Intento {0}: fallo al acceder a {1}/health' -f $i, $BASE_URL)
        try {
            $raw = curl "$BASE_URL/health"
            Write-Host "[smoke][debug] Respuesta recibida: $raw"
        } catch { Write-Host "[smoke][debug] No se pudo obtener respuesta en intento $i" }
        Start-Sleep -Seconds 1
        if ($i -eq 60) {
            Write-Host "[smoke] verifier did not become healthy"
            docker compose logs verifier
            exit 1
        }
    }
}

function sms_payload($req_id) {
    return @{
        request_id = $req_id
        tool = "twilio.send_sms"
        mode = "ALLOW"
        role = "receptionist"
        subject = @{ patient_id = "p1" }
        args = @{ to = "+34600000000"; template_id = "t1" }
        context = @{ tenant_id = "t-demo" }
    } | ConvertTo-Json -Compress
}

function post_verify($payload) {
    return curl -fsS -X POST "$BASE_URL/verify" -H "Content-Type: application/json" -d $payload
}

Write-Host "[smoke] 1) First SMS should be ALLOW"

$r1 = post_verify (sms_payload "s1") | ConvertFrom-Json
if ($r1.decision -ne "ALLOW") { Write-Host "[smoke] FAIL: 1st SMS no es ALLOW"; exit 1 }

Write-Host "[smoke] 2) Second SMS within 1h should be DENY (Inv_NoSmsBurst)"

$r2 = post_verify (sms_payload "s2") | ConvertFrom-Json
if ($r2.decision -ne "DENY") { Write-Host "[smoke] FAIL: 2nd SMS no es DENY"; exit 1 }
if (-not ($r2.violations -contains "Inv_NoSmsBurst")) { Write-Host "[smoke] FAIL: No Inv_NoSmsBurst"; exit 1 }

Write-Host "[smoke] 3) Stop redis -> twilio.send_sms must FAIL-CLOSED (DENY)"
docker compose stop redis


try {
    $r3 = post_verify (sms_payload "s3") | ConvertFrom-Json
} catch { $r3 = $null }
if (-not $r3) { Write-Host "[smoke] FAIL: No response para 3er SMS"; exit 1 }
if ($r3.decision -ne "DENY") { Write-Host "[smoke] FAIL: 3er SMS no es DENY"; exit 1 }
if (-not ($r3.violations -contains "FAIL_CLOSED")) { Write-Host "[smoke] FAIL: No FAIL_CLOSED"; exit 1 }

Write-Host "[smoke] OK"
