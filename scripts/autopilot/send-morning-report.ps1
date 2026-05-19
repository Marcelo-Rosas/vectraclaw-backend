# AUTOPILOT — Envio PDF morning report via Meta WhatsApp Cloud API
#
# Fluxo:
#   1. Gera PDF do MD via Docker ephemeral (Regra Ouro #5 — sem instalar nada no host)
#   2. Lê credenciais Meta direto do .env (compartilhado com backend)
#   3. Upload media → recebe media_id
#   4. Dispatch document message com caption sumário
#
# Uso:
#   .\send-morning-report.ps1 -MdPath ".\docs\AUTOPILOT-MORNING-REPORT-2026-05-19.md" `
#                              -Caption "[AUTOPILOT 06:00] N PRs mergeados, X smokes ok"
#
# Pré-requisitos:
#   - Docker Desktop rodando
#   - .env com META_PHONE_NUMBER_ID + META_ACCESS_TOKEN (do adapter meta-whatsapp)
#   - Número destino padrão = 5521975602969 (Marcelo)

param(
    [Parameter(Mandatory=$true)][string]$MdPath,
    [Parameter(Mandatory=$true)][string]$Caption,
    [string]$ToNumber = "5521975602969",
    [string]$EnvPath = "C:\Users\marce\VectraClaw\.env"
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptRoot)
$LogPath = Join-Path $RepoRoot "daemon-autopilot.log"

function Log {
    param([string]$Level, [string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts [$Level] $Msg"
    Write-Host $line
    Add-Content -Path $LogPath -Value $line
}

# ---------------------------------------------------------------------------
# 1. Resolve credenciais Meta — Regra Vault SSOT (W4/W5): tudo em vault,
#    resolvido via RPC SECURITY DEFINER get_vault_secret(uuid, company_id)
# ---------------------------------------------------------------------------
Log "INFO" "Carregando .env (SUPABASE_URL + SERVICE_ROLE_KEY apenas)..."

$envVars = @{}
if (Test-Path $EnvPath) {
    Get-Content $EnvPath | ForEach-Object {
        if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') {
            $envVars[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
        }
    }
}

$SupabaseUrl = $envVars["SUPABASE_URL"]
$ServiceKey = $envVars["SUPABASE_SERVICE_ROLE_KEY"]
$VectraCompanyId = "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2"
$ApiVersion = "v25.0"

if (-not $SupabaseUrl -or -not $ServiceKey) {
    Log "ERROR" "SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY ausente no .env"
    exit 1
}

# Pega field_values_json do adapter meta-whatsapp (com vault:// refs)
Log "INFO" "Resolvendo company_adapter_values meta-whatsapp..."
$adapterUri = "$SupabaseUrl/rest/v1/company_adapter_values?select=field_values_json&adapter_id=eq.94b68e6a-0949-4908-8b52-e1ee911e600f&company_id=eq.$VectraCompanyId&is_active=eq.true&limit=1"

$adapterResp = & curl.exe -s `
    -H "apikey: $ServiceKey" `
    -H "Authorization: Bearer $ServiceKey" `
    -H "Accept-Profile: vectraclip" `
    $adapterUri

try {
    $adapterArr = $adapterResp | ConvertFrom-Json
    $fieldValues = $adapterArr[0].field_values_json
} catch {
    Log "ERROR" "Falha parse adapter values: $adapterResp"
    exit 1
}

function Resolve-VaultRef {
    param([string]$RefOrLiteral)
    if (-not $RefOrLiteral) { return $null }
    if ($RefOrLiteral -notmatch '^vault://(.+)$') { return $RefOrLiteral }
    $vaultId = $Matches[1]
    $rpcUri = "$SupabaseUrl/rest/v1/rpc/get_vault_secret"
    $rpcBody = @{ p_vault_secret_id = $vaultId; p_company_id = $VectraCompanyId } | ConvertTo-Json -Compress
    $rpcResp = & curl.exe -s -X POST $rpcUri `
        -H "apikey: $ServiceKey" `
        -H "Authorization: Bearer $ServiceKey" `
        -H "Content-Profile: vectraclip" `
        -H "Content-Type: application/json" `
        -d $rpcBody
    return ($rpcResp -replace '"','').Trim()
}

$PhoneNumberId = Resolve-VaultRef $fieldValues.phone_number_id
$AccessToken = Resolve-VaultRef $fieldValues.access_token

if (-not $PhoneNumberId -or -not $AccessToken) {
    Log "ERROR" "Vault resolution falhou. phone=$($PhoneNumberId.Length) token=$($AccessToken.Length)"
    exit 1
}
Log "INFO" "Credenciais Meta resolvidas via vault (phone=$($PhoneNumberId.Length)b, token=$($AccessToken.Length)b)"

# ---------------------------------------------------------------------------
# 2. Gera PDF via Docker ephemeral (Regra Ouro #5)
# ---------------------------------------------------------------------------
if (-not (Test-Path $MdPath)) {
    # Fallback: envia mensagem texto avisando que autopilot não gerou relatório
    Log "WARN" "MD source ausente ($MdPath) — enviando text fallback"
    $fallbackBody = @{
        messaging_product = "whatsapp"
        recipient_type = "individual"
        to = $ToNumber
        type = "text"
        text = @{
            preview_url = $false
            body = "[AUTOPILOT 06:00] Sem relatório gerado essa noite. Provável: sessão Claude desconectou ou autopilot abortou. Veja daemon-autopilot.log + docs/SESSION-2026-05-18-NIGHT-AUTOPILOT.md se existir."
        }
    } | ConvertTo-Json -Depth 5 -Compress

    $envVars = @{}
    if (Test-Path $EnvPath) {
        Get-Content $EnvPath | ForEach-Object {
            if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') {
                $envVars[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
            }
        }
    }
    $supaUrl = $envVars["SUPABASE_URL"]
    $svcKey = $envVars["SUPABASE_SERVICE_ROLE_KEY"]
    $compId = "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2"
    $adapterUri = "$supaUrl/rest/v1/company_adapter_values?select=field_values_json&adapter_id=eq.94b68e6a-0949-4908-8b52-e1ee911e600f&company_id=eq.$compId&is_active=eq.true&limit=1"
    $adRes = & curl.exe -s -H "apikey: $svcKey" -H "Authorization: Bearer $svcKey" -H "Accept-Profile: vectraclip" $adapterUri | ConvertFrom-Json
    $fv = $adRes[0].field_values_json
    function _r($x) {
        if ($x -notmatch '^vault://(.+)$') { return $x }
        $vid = $Matches[1]
        $b = @{ p_vault_secret_id = $vid; p_company_id = $compId } | ConvertTo-Json -Compress
        return ((& curl.exe -s -X POST "$supaUrl/rest/v1/rpc/get_vault_secret" -H "apikey: $svcKey" -H "Authorization: Bearer $svcKey" -H "Content-Profile: vectraclip" -H "Content-Type: application/json" -d $b) -replace '"','').Trim()
    }
    $pid_ = _r $fv.phone_number_id; $tok = _r $fv.access_token
    & curl.exe -s -X POST "https://graph.facebook.com/v25.0/$pid_/messages" -H "Authorization: Bearer $tok" -H "Content-Type: application/json" -d $fallbackBody | Out-Null
    Log "INFO" "Fallback text enviado"
    exit 0
}

$mdAbsPath = (Resolve-Path $MdPath).Path
$pdfPath = [System.IO.Path]::ChangeExtension($mdAbsPath, ".pdf")
$pdfRelative = (Resolve-Path -Path (Split-Path $mdAbsPath)).Path
$mdFileName = Split-Path $mdAbsPath -Leaf
$pdfFileName = Split-Path $pdfPath -Leaf

Log "INFO" "Pre-processando emojis pra ASCII tags (pandoc/latex mínimo não tem fontes Unicode)..."

# pandoc/latex mínimo não tem fontes Unicode — preprocess: substitui emojis
# comuns por tags ASCII pra renderização limpa. Lista mínima — adicionar
# conforme necessidade. Salva em arquivo temporário (.preprocessed.md).
$emojiMap = @{
    '✅' = '[OK]';   '❌' = '[X]';    '⚠️' = '[!]';   '⚠' = '[!]'
    '🔴' = '[P0]';  '🟡' = '[P1]';  '🟢' = '[P2]'
    '📦' = '';      '🚚' = '';      '🎉' = '';     '📊' = '';     '🚀' = ''
    '⭐' = '*';     '→'  = '->';    '←'  = '<-';   '↑' = '^';     '↓' = 'v'
    '•'  = '-';     '─'  = '-';     '═'  = '='
    '⇄'  = '<->';   '⇨' = '=>';    '⇒' = '=>';   '⇐' = '<='
    '°'  = ' deg';  '²' = '2';     '³' = '3'
}
$mdContent = Get-Content $mdAbsPath -Raw -Encoding UTF8
foreach ($k in $emojiMap.Keys) {
    $mdContent = $mdContent.Replace($k, $emojiMap[$k])
}

# Strip agressivo de QUALQUER char > U+02FF (mantém latin extended + IPA)
# Conserva ASCII + acentos pt-BR + pontuação básica
$strippedSb = New-Object System.Text.StringBuilder
foreach ($ch in $mdContent.ToCharArray()) {
    if ([int]$ch -le 0x02FF) {
        [void]$strippedSb.Append($ch)
    } else {
        [void]$strippedSb.Append('?')
    }
}
$mdContent = $strippedSb.ToString()
$preprocessedPath = [System.IO.Path]::ChangeExtension($mdAbsPath, ".preprocessed.md")
$preprocessedFileName = Split-Path $preprocessedPath -Leaf
Set-Content -Path $preprocessedPath -Value $mdContent -Encoding UTF8 -NoNewline

Log "INFO" "Gerando PDF via Docker pandoc/latex: $preprocessedFileName -> $pdfFileName"

# Copia header LaTeX customizado (tabularx wraping) pra mesma pasta do MD
$headerSrc = Join-Path $ScriptRoot "pandoc-header.tex"
$headerTmp = Join-Path $pdfRelative "_pandoc-header.tex"
Copy-Item -Path $headerSrc -Destination $headerTmp -Force

docker run --rm `
    -v "${pdfRelative}:/data" `
    pandoc/latex `
    -V geometry:a4paper `
    -V geometry:margin=2cm `
    -V fontsize=10pt `
    -V colorlinks=true `
    -V linkcolor=blue `
    -H "/data/_pandoc-header.tex" `
    "/data/$preprocessedFileName" -o "/data/$pdfFileName" 2>&1 | Tee-Object -FilePath $LogPath -Append | Out-Host

# Limpa header temp
if (Test-Path $headerTmp) { Remove-Item $headerTmp -Force }

# Limpa arquivo temporário
if (Test-Path $preprocessedPath) {
    Remove-Item $preprocessedPath -Force
}

if (-not (Test-Path $pdfPath)) {
    Log "ERROR" "PDF não foi gerado em $pdfPath"
    exit 1
}
$pdfSize = (Get-Item $pdfPath).Length
Log "INFO" "PDF gerado: $pdfPath ($pdfSize bytes)"

# ---------------------------------------------------------------------------
# 3. Upload media pra Meta Graph API
# ---------------------------------------------------------------------------
Log "INFO" "Upload media pra Meta Graph API..."

$uploadUri = "https://graph.facebook.com/$ApiVersion/$PhoneNumberId/media"

# Multipart form via curl.exe (Invoke-WebRequest com multipart é dor)
$uploadOutput = & curl.exe -s -X POST $uploadUri `
    -H "Authorization: Bearer $AccessToken" `
    -F "messaging_product=whatsapp" `
    -F "type=application/pdf" `
    -F "file=@${pdfPath};type=application/pdf"

Log "DEBUG" "Upload response: $uploadOutput"

try {
    $uploadJson = $uploadOutput | ConvertFrom-Json
    $mediaId = $uploadJson.id
} catch {
    Log "ERROR" "Resposta upload não é JSON válido: $uploadOutput"
    exit 1
}

if (-not $mediaId) {
    Log "ERROR" "media_id não retornado. Resposta: $uploadOutput"
    exit 1
}
Log "INFO" "media_id=$mediaId"

# ---------------------------------------------------------------------------
# 4. Dispatch document message
# ---------------------------------------------------------------------------
Log "INFO" "Enviando document message pra $ToNumber..."

$messagesUri = "https://graph.facebook.com/$ApiVersion/$PhoneNumberId/messages"

$captionTrunc = if ($Caption.Length -gt 1020) { $Caption.Substring(0, 1020) + "..." } else { $Caption }

$payload = @{
    messaging_product = "whatsapp"
    recipient_type = "individual"
    to = $ToNumber
    type = "document"
    document = @{
        id = $mediaId
        caption = $captionTrunc
        filename = $pdfFileName
    }
} | ConvertTo-Json -Depth 5 -Compress

$sendResp = & curl.exe -s -X POST $messagesUri `
    -H "Authorization: Bearer $AccessToken" `
    -H "Content-Type: application/json" `
    -d $payload

Log "DEBUG" "Send response: $sendResp"

try {
    $sendJson = $sendResp | ConvertFrom-Json
    $wamid = $sendJson.messages[0].id
    if ($wamid) {
        Log "INFO" "OK enviado. wamid=$wamid"
        exit 0
    } else {
        Log "ERROR" "Resposta sem messages[0].id: $sendResp"
        exit 1
    }
} catch {
    Log "ERROR" "Resposta send não é JSON válido: $sendResp"
    exit 1
}
