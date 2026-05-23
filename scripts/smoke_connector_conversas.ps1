# Smoke: Conversas Meta + guardrail de tasks (sem auto-dispatch por default)
# Uso: .\scripts\smoke_connector_conversas.ps1 [-ApiBase http://127.0.0.1:3100/api]

param(
    [string]$ApiBase = "http://127.0.0.1:3100/api",
    [string]$Email = "marcelo.rosas@vectracargo.com.br",
    [string]$Password = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "=== [1/3] Pytest guardrail inbound ===" -ForegroundColor Cyan
python -m pytest `
    tests/test_connector_inbound_policy.py `
    tests/test_connector_inbound_dispatch_guard.py `
    -q --tb=line
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== [2/3] Health ===" -ForegroundColor Cyan
$health = Invoke-RestMethod -Uri "$ApiBase/health" -Method Get
if ($health.status -ne "online") {
    Write-Host "FAIL health: $($health | ConvertTo-Json -Compress)" -ForegroundColor Red
    exit 2
}
Write-Host "OK health online" -ForegroundColor Green

if (-not $Password) {
    Write-Host ""
    Write-Host "=== [3/3] API autenticada (skip - informe -Password) ===" -ForegroundColor DarkGray
    Write-Host "Smoke unitario concluido." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "=== [3/3] Canais Meta + sessoes (JWT) ===" -ForegroundColor Cyan
$loginBody = @{ email = $Email; password = $Password } | ConvertTo-Json
$login = Invoke-RestMethod -Uri "$ApiBase/auth/login" -Method Post -Body $loginBody -ContentType "application/json"
$token = $login.accessToken
if (-not $token) { throw "login sem accessToken" }

$headers = @{
    Authorization = "Bearer $token"
    Origin        = "http://localhost:3000"
}

$channels = Invoke-RestMethod -Uri "$ApiBase/connectors/channels" -Headers $headers -Method Get
$metaSlugs = @("whatsapp", "instagram")
$bad = @($channels | Where-Object { $metaSlugs -notcontains $_.slug })
if ($bad.Count -gt 0) {
    Write-Host "AVISO: canais nao-Meta no catalogo (UI Clip filtra): $($bad.slug -join ', ')" -ForegroundColor Yellow
}
$activeMeta = @($channels | Where-Object { $metaSlugs -contains $_.slug -and $_.is_active -ne $false })
Write-Host "Canais Meta ativos: $($activeMeta.Count)" -ForegroundColor Green

$companyId = $login.user.companyId
if (-not $companyId) { throw "login sem companyId" }

$sessions = Invoke-RestMethod `
    -Uri "$ApiBase/companies/$companyId/connector-sessions?limit=20" `
    -Headers $headers -Method Get
$nonMeta = @($sessions | Where-Object { $metaSlugs -notcontains $_.channel })
if ($nonMeta.Count -gt 0) {
    Write-Host "Sessoes nao-Meta no DB (Clip filtra na UI): $($nonMeta.Count)" -ForegroundColor Yellow
}
Write-Host "Sessoes listadas: $($sessions.Count) (Meta na UI: whatsapp/instagram)" -ForegroundColor Green

Write-Host ""
Write-Host "Guardrail: VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH=false (default) - webhook nao cria task." -ForegroundColor DarkGray
Write-Host "Reply humano nao cria task (ver _do_reply em connectors.py)." -ForegroundColor DarkGray
Write-Host "Smoke concluido." -ForegroundColor Green
