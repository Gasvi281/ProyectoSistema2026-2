<#
Solo dev: smoke test manual de /insights/chat contra el servicio ya levantado.

Uso (desde cualquier carpeta, con uvicorn corriendo en otra terminal):
  powershell -ExecutionPolicy Bypass -File apps/insights/scripts/smoke.ps1
  ... -Port 3002            # otro puerto

No imprime el token: solo su longitud y prefijo.
#>
param(
    [int]$Port = 8001,
    [string]$Message = "How is the agency doing?"
)

$Base = "http://localhost:$Port"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$script:Pass = 0
$script:Fail = 0

function Invoke-Api {
    param([string]$Method, [string]$Path, [hashtable]$Headers = @{}, [string]$Body = $null)
    $req = @{ Method = $Method; Uri = "$Base$Path"; Headers = $Headers; UseBasicParsing = $true; TimeoutSec = 120 }
    if ($Body) { $req.Body = [Text.Encoding]::UTF8.GetBytes($Body); $req.ContentType = "application/json" }
    try {
        $r = Invoke-WebRequest @req
        return @{ Status = [int]$r.StatusCode; Body = $r.Content }
    } catch {
        if ($_.Exception.Response) {
            return @{ Status = [int]$_.Exception.Response.StatusCode; Body = $null }
        }
        return @{ Status = 0; Body = $_.Exception.Message }
    }
}

function Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    if ($Ok) { $script:Pass++; Write-Host "[PASS] $Name $Detail" -ForegroundColor Green }
    else     { $script:Fail++; Write-Host "[FAIL] $Name $Detail" -ForegroundColor Red }
}

Write-Host "== Smoke insights en $Base ==" -ForegroundColor Cyan

# 1. Health
$r = Invoke-Api GET "/health"
Check "health -> 200" ($r.Status -eq 200) "(got $($r.Status))"
if ($r.Status -ne 200) {
    Write-Host "El servicio no responde. Levantalo primero:" -ForegroundColor Yellow
    Write-Host "  uv run --package proptech-insights uvicorn insights.main:app --port $Port --reload"
    exit 1
}

# 2. Sin token
$chatBody = (@{ message = $Message; conversation_id = $null } | ConvertTo-Json)
$r = Invoke-Api POST "/insights/chat" -Body $chatBody
Check "sin Authorization -> 401" ($r.Status -eq 401) "(got $($r.Status))"

# 3. Token basura (el gate consulta /me; puede tardar por cold start de Render)
$r = Invoke-Api POST "/insights/chat" -Headers @{ Authorization = "Bearer basura" } -Body $chatBody
Check "token basura -> 401" ($r.Status -eq 401) "(got $($r.Status); 502 = backend caido o dormido)"

# 4. Token real
Push-Location $RepoRoot
try { $t = (uv run --package proptech-insights python apps/insights/scripts/get_token.py | Out-String).Trim() }
finally { Pop-Location }
$tokOk = ($LASTEXITCODE -eq 0) -and $t.StartsWith("eyJ") -and $t.Length -gt 100
$prefix = if ($t.Length -ge 6) { $t.Substring(0, 6) } else { $t }
Check "get_token.py" $tokOk "(len=$($t.Length), prefix=$prefix)"
if (-not $tokOk) {
    Write-Host "Revisa SUPABASE_*, INSIGHTS_DEV_EMAIL/PASSWORD en apps/insights/.env (el error sale arriba)." -ForegroundColor Yellow
    Write-Host "Resultado: $script:Pass PASS, $script:Fail FAIL"
    exit 1
}
$auth = @{ Authorization = "Bearer $t" }

# 5. Turno 1 (conversacion nueva)
$r = Invoke-Api POST "/insights/chat" -Headers $auth -Body $chatBody
Check "chat turno 1 -> 200" ($r.Status -eq 200) "(got $($r.Status); 403 = el usuario no es TEAM_ADMIN activo)"
if ($r.Status -ne 200) { Write-Host "Resultado: $script:Pass PASS, $script:Fail FAIL"; exit 1 }
$j1 = $r.Body | ConvertFrom-Json
Check "conversation_id generado" ([bool]$j1.conversation_id) "($($j1.conversation_id))"
Check "sources con get_north_star" (@($j1.sources | Where-Object { $_.tool -eq "get_north_star" }).Count -ge 1) "(sources=$(@($j1.sources).Count))"
Write-Host "--- reply turno 1 ---" -ForegroundColor DarkGray
Write-Host $j1.reply
Write-Host "---------------------" -ForegroundColor DarkGray

# 6. Turno 2 (misma conversacion -> MemorySaver)
$body2 = (@{ message = "And what about follow-up?"; conversation_id = $j1.conversation_id } | ConvertTo-Json)
$r = Invoke-Api POST "/insights/chat" -Headers $auth -Body $body2
$j2 = if ($r.Status -eq 200) { $r.Body | ConvertFrom-Json } else { $null }
Check "chat turno 2 -> 200, mismo conversation_id" (($r.Status -eq 200) -and ($j2.conversation_id -eq $j1.conversation_id)) "(got $($r.Status))"
if ($j2) {
    Write-Host "--- reply turno 2 ---" -ForegroundColor DarkGray
    Write-Host $j2.reply
    Write-Host "---------------------" -ForegroundColor DarkGray
}

Write-Host ""
$color = if ($script:Fail -eq 0) { "Green" } else { "Red" }
Write-Host "Resultado: $script:Pass PASS, $script:Fail FAIL" -ForegroundColor $color
exit $script:Fail
