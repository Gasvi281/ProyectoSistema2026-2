# run.ps1
# ---------------------------------------------------------------------------
# Automatiza el arranque completo del webhook: levanta el servidor FastAPI,
# levanta el tunel de Cloudflare, detecta la URL publica, y registra el
# webhook en Telegram automaticamente. Reemplaza tener que hacerlo a mano
# en 3 ventanas distintas.
#
# Uso: parado en la carpeta del proyecto, correr:
#   .\run.ps1
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

# 1. Cargar variables desde .env -----------------------------------------
if (-not (Test-Path ".env")) {
    Write-Error "No se encontro el archivo .env. Copia .env.example a .env y llena los valores primero."
    exit 1
}

$envVars = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)\s*$') {
        $envVars[$matches[1].Trim()] = $matches[2].Trim()
    }
}

$token = $envVars["TELEGRAM_BOT_TOKEN"]
$secret = $envVars["TELEGRAM_WEBHOOK_SECRET"]

if (-not $token -or -not $secret) {
    Write-Error "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_WEBHOOK_SECRET en el .env"
    exit 1
}

# 2. Sincronizar el entorno con uv -----------------------------------------
# "uv sync" instala/actualiza TODO el workspace (webhook + agente) en un
# solo entorno virtual compartido (.venv en la raiz), leyendo pyproject.toml
# y uv.lock. Es idempotente: si ya esta al dia, no hace nada.
Write-Host "Sincronizando entorno con uv..." -ForegroundColor Cyan
uv sync

# 3. Levantar uvicorn en una ventana nueva ---------------------------------
Write-Host "Levantando servidor FastAPI en el puerto 3000..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$PWD'; uv run uvicorn main:app --reload --port 3000"

Start-Sleep -Seconds 3

# 4. Levantar cloudflared en otra ventana, logueando su salida ------------
$logFile = Join-Path $env:TEMP "cloudflared_log.txt"
Remove-Item $logFile -ErrorAction SilentlyContinue

Write-Host "Levantando tunel de Cloudflare..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cloudflared tunnel --url http://localhost:3000 2>&1 | Tee-Object -FilePath '$logFile'"

# 5. Esperar a que aparezca la URL publica en el log -----------------------
Write-Host "Esperando a que Cloudflare asigne la URL publica..." -ForegroundColor Cyan
$tunnelUrl = $null
$attempts = 0

while (-not $tunnelUrl -and $attempts -lt 30) {
    Start-Sleep -Seconds 2
    $attempts++
    if (Test-Path $logFile) {
        $content = Get-Content $logFile -Raw
        if ($content -match "https://[a-zA-Z0-9\-]+\.trycloudflare\.com") {
            $tunnelUrl = $matches[0]
        }
    }
}

if (-not $tunnelUrl) {
    Write-Error "No se detecto la URL del tunel despues de 60 segundos. Revisa la ventana de cloudflared manualmente."
    exit 1
}

Write-Host "URL publica detectada: $tunnelUrl" -ForegroundColor Green

# 6. Esperar a que el tunel realmente resuelva y responda (DNS tarda un poco
#    en propagarse justo despues de que Cloudflare la muestra en el log) ----
Write-Host "Confirmando que el tunel ya esta accesible..." -ForegroundColor Cyan
$tunnelReady = $false
$readyAttempts = 0

while (-not $tunnelReady -and $readyAttempts -lt 15) {
    try {
        $null = Invoke-WebRequest -Uri $tunnelUrl -TimeoutSec 5 -ErrorAction Stop
        $tunnelReady = $true
    } catch {
        $readyAttempts++
        Start-Sleep -Seconds 2
    }
}

if (-not $tunnelReady) {
    Write-Error "El tunel no respondio despues de varios intentos. Verifica manualmente abriendo $tunnelUrl en el navegador."
    exit 1
}

Write-Host "Tunel accesible, registrando webhook..." -ForegroundColor Green

# 7. Registrar el webhook en Telegram automaticamente ----------------------
$webhookUrl = "$tunnelUrl/webhook/telegram"
$body = @{ url = $webhookUrl; secret_token = $secret } | ConvertTo-Json

Write-Host "Registrando el webhook en Telegram..." -ForegroundColor Cyan

# Reintenta unas veces por si Telegram todavia no puede resolver la URL
# justo en el primer intento (mismo motivo que arriba: propagacion de DNS).
$maxRetries = 5
$registered = $false

for ($i = 1; $i -le $maxRetries -and -not $registered; $i++) {
    try {
        $response = Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/setWebhook" `
            -Method Post -ContentType "application/json" -Body $body -ErrorAction Stop

        if ($response.ok) {
            $registered = $true
        } else {
            Write-Host "Intento $i fallo: $($response.description)" -ForegroundColor Yellow
            Start-Sleep -Seconds 3
        }
    } catch {
        Write-Host "Intento $i fallo (posible propagacion de DNS pendiente), reintentando..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
}

if ($registered) {
    Write-Host "`nListo! Webhook registrado correctamente." -ForegroundColor Green
    Write-Host "URL: $webhookUrl"
    Write-Host "`nYa puedes probar el bot en Telegram (manda /start o cualquier mensaje)."
} else {
    Write-Error "No se pudo registrar el webhook despues de $maxRetries intentos. Prueba el registro manual (README, seccion 3, Terminal 3)."
}