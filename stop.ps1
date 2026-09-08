# stop.ps1
# ---------------------------------------------------------------------------
# Desregistra el webhook de Telegram. Util al terminar una sesion de pruebas,
# para que Telegram deje de intentar mandar mensajes a una URL de Cloudflare
# que ya cerraste.
#
# Uso: .\stop.ps1
# Nota: esto NO cierra las ventanas de uvicorn ni de cloudflared, esas las
# cierras manualmente (Ctrl+C en cada una).
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Write-Error "No se encontro el archivo .env"
    exit 1
}

$envVars = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)\s*=\s*(.*)\s*$') {
        $envVars[$matches[1].Trim()] = $matches[2].Trim()
    }
}

$token = $envVars["TELEGRAM_BOT_TOKEN"]

$response = Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/deleteWebhook"

if ($response.ok) {
    Write-Host "Webhook desregistrado correctamente." -ForegroundColor Green
} else {
    Write-Error "Error al desregistrar el webhook: $($response | ConvertTo-Json)"
}
