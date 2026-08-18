# Webhook Telegram ↔ Gemini (FastAPI) — Proptech Marketplace

Webhook de Telegram en Python + FastAPI, conectado a **Gemini** (Google AI
Studio) como modelo de IA gratuito para pruebas. Cuando el agente de tu
compañero esté listo, se reemplaza por ese agente sin tocar el resto del
proyecto (ver sección 7).

## Mapa de archivos y cómo se conectan

```
config.py            <-- lee el .env, lo usan telegram_service.py y ai_service.py
telegram_service.py  <-- llama a la API de Telegram (enviar mensajes)
ai_service.py         <-- llama a la API de Gemini (generar respuesta)
chat_history.py       <-- guarda el historial de conversación por chat_id
main.py               <-- servidor FastAPI: recibe el webhook y conecta los anteriores
run.ps1               <-- script que automatiza todo el arranque (ver sección 3)
stop.ps1              <-- desregistra el webhook al terminar de probar
```

Flujo de una petición:

```
Telegram --POST--> main.py (/webhook/telegram)
                       |
                       |-- valida el secreto (config.py)
                       |-- delega a handle_message()
                                |
                                |-- chat_history.get_history(chat_id)  -> recupera mensajes previos
                                |-- ai_service.ask_ai(texto, historial) -> pide respuesta a Gemini con contexto
                                |-- chat_history.add_message(...)      -> guarda el nuevo turno
                                |-- telegram_service.send_message()    -> entrega la respuesta al usuario
```

`main.py` es el único archivo que "orquesta": importa la función de
`ai_service.py` y la de `telegram_service.py`. Ni `ai_service.py` ni
`telegram_service.py` se conocen entre sí — intencional, para poder cambiar
el proveedor de IA sin tocar cómo hablas con Telegram, y viceversa.

---

## 1. Configuración inicial (una sola vez por persona/máquina)

Esta sección es para la **primera vez** que alguien del equipo prueba el
proyecto en su computador. Cada paso incluye qué hace el comando y qué
deberías ver si salió bien — si en algo te sale algo distinto, no sigas al
siguiente paso, revisa primero.

Requisito previo: tener **Python 3.10 o más reciente** instalado. Verifica
con:
```powershell
python --version
```
Si da error de "no se reconoce", instala Python desde
https://www.python.org/downloads/ (marca la casilla "Add Python to PATH"
durante la instalación).

### Paso 1 — Crear el bot en Telegram

1. Abre Telegram, busca **@BotFather**.
2. Envíale `/newbot`.
3. Te pide un nombre visible (ej. `Proptech Agente IA`) y un username único
   terminado en `bot` (ej. `proptech_agente_bot`).
4. Te devuelve un **token**, algo como `8840321755:AAEIq...`. Cópialo, lo
   vas a necesitar en el Paso 5.

⚠️ **Este token es un secreto.** No lo compartas en el chat del equipo, ni
en commits de Git, ni en capturas de pantalla. Si por accidente lo expones,
revócalo de inmediato: @BotFather → `/mybots` → tu bot → **API Token** →
**Revoke current token**.

### Paso 2 — Conseguir la API key de Gemini

1. Ve a https://aistudio.google.com/apikey con tu cuenta de Google.
2. **Create API Key** → copia la key generada (capa gratuita).

Mismo cuidado que con el token de Telegram: es un secreto, no lo compartas
fuera del `.env`.

### Paso 3 — Instalar `cloudflared`

Esto es lo que expone tu servidor local a internet para que Telegram pueda
alcanzarlo (Telegram exige una URL pública con HTTPS).

```powershell
winget install --id Cloudflare.cloudflared --source winget
```

**Por qué `--source winget` explícito:** por defecto `winget` busca en dos
catálogos (`msstore` y `winget`), y en algunas redes (universitarias,
corporativas) la consulta al catálogo de Microsoft Store falla por DNS
aunque el paquete sí exista en el catálogo de `winget`. Forzar la fuente
evita ese error.

Si aun así falla, instala manualmente:
1. Ve a https://github.com/cloudflare/cloudflared/releases/latest
2. Descarga `cloudflared-windows-amd64.exe`
3. Renómbralo a `cloudflared.exe`, colócalo en una carpeta fija como
   `C:\cloudflared\` (fuera de la carpeta del proyecto — es una herramienta
   del sistema, no parte del código)
4. Agrégala al PATH: busca "variables de entorno" en el menú de inicio →
   **Editar las variables de entorno del sistema** → **Variables de
   entorno** → en tu usuario, selecciona **Path** → **Editar** → **Nuevo**
   → pega la ruta de la carpeta → Aceptar → **cierra y vuelve a abrir
   PowerShell** (el cambio no aplica hasta que reabres la terminal).

**Verificación** (debe funcionar sin importar cuál de los dos caminos
usaste):
```powershell
cloudflared --version
```
Debería mostrar algo como `cloudflared version 2024.x.x (built ...)`. Si
sale "no se reconoce como comando", el PATH no quedó bien configurado —
revisa el paso anterior.

### Paso 4 — Permitir que PowerShell ejecute scripts locales

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**Qué hace este comando:** por defecto, muchas instalaciones de Windows
traen PowerShell configurado para **bloquear cualquier script `.ps1`**
(incluyendo `run.ps1`, `stop.ps1`, y el propio script que activa el
entorno virtual de Python) — es una medida de seguridad para evitar que
scripts maliciosos descargados de internet se ejecuten solos. Este comando
lo cambia a un punto intermedio (`RemoteSigned`): tus propios scripts
locales se permiten sin problema, pero un script descargado de internet
necesitaría estar firmado digitalmente para correr.

Te va a preguntar confirmación:
```
¿Está seguro de que desea realizar este cambio?
[S] Sí  [N] No  [S] Suspender  [?] Ayuda (el valor predeterminado es "S"):
```
Escribe `S` y Enter.

**Esto se configura una sola vez por usuario de Windows**, no por
proyecto — queda guardado en tu perfil y aplica a cualquier terminal de
PowerShell que abras después, en cualquier carpeta. Si cambias de
computador o de cuenta de Windows, hay que repetirlo ahí.

**Verificación:**
```powershell
Get-ExecutionPolicy -Scope CurrentUser
```
Debe responder `RemoteSigned`.

### Paso 5 — Preparar el proyecto

Parado en la carpeta del proyecto (donde están `main.py`, `requirements.txt`, etc.):

```powershell
python -m venv venv
```
**Qué hace:** crea una copia aislada de Python solo para este proyecto, en
una carpeta nueva `venv/`. Evita que las librerías de este proyecto
choquen con las de otros proyectos tuyos. No imprime nada si sale bien.

```powershell
.\venv\Scripts\Activate.ps1
```
**Qué hace:** activa esa copia aislada — desde este momento, en esta
misma ventana de terminal, los comandos `python` y `pip` usan la versión
del proyecto en vez de la global de tu sistema.

**Verificación:** tu línea de comandos debe cambiar y mostrar `(venv)` al
inicio:
```
(venv) PS C:\...\telegram-webhook-python>
```
Si no aparece, probablemente el Paso 4 no se aplicó bien — revisa con
`Get-ExecutionPolicy -Scope CurrentUser` otra vez.

⚠️ Esta activación **dura solo mientras esa ventana esté abierta**. Si
cierras la terminal, tienes que repetir este comando (no hace falta volver
a crear el `venv`, solo activarlo).

```powershell
pip install -r requirements.txt
```
**Qué hace:** instala las 4 librerías que el proyecto necesita (FastAPI,
uvicorn, httpx, python-dotenv), leyendo la lista desde `requirements.txt`.
Vas a ver varias líneas de `Collecting...` / `Installing...` — es normal,
termina con `Successfully installed ...`.

```powershell
copy .env.example .env
```
**Qué hace:** crea tu archivo de configuración real a partir de la
plantilla. `.env` es el que de verdad lee el proyecto (`config.py`); nunca
se sube a Git (está en `.gitignore`) porque va a tener tus secretos.

```powershell
notepad .env
```
Abre el archivo para editarlo. Reemplaza los 3 valores de ejemplo por los
reales que conseguiste en los Pasos 1 y 2:
```
TELEGRAM_BOT_TOKEN=<el token que te dio BotFather>
TELEGRAM_WEBHOOK_SECRET=<inventa una cadena larga y random>
GEMINI_API_KEY=<la key de Google AI Studio>
```
Para el `TELEGRAM_WEBHOOK_SECRET`, cualquier cadena larga sirve — puedes
generar una con:
```powershell
python -c "import secrets; print(secrets.token_hex(24))"
```
Guarda el archivo (Ctrl+S) y cierra Notepad.

---

## 2. Correr el proyecto (camino rápido) ⚡

Con el `.env` ya lleno, desde la carpeta del proyecto:

```powershell
.\run.ps1
```

Esto hace automáticamente lo que antes eran 3 pasos manuales en 3 ventanas:
1. Levanta `uvicorn` en una ventana nueva
2. Levanta `cloudflared tunnel` en otra ventana nueva
3. Detecta la URL pública generada por Cloudflare
4. Registra esa URL como webhook en Telegram (`setWebhook`)

Al final deberías ver:
```
Listo! Webhook registrado correctamente.
URL: https://algo-random.trycloudflare.com/webhook/telegram

Ya puedes probar el bot en Telegram (manda /start o cualquier mensaje).
```

Prueba mandándole un mensaje al bot en Telegram. Revisa las dos ventanas que
se abrieron (`uvicorn` y `cloudflared`) si algo no responde.

**Para terminar la sesión de pruebas**, cierra esas dos ventanas (`Ctrl+C`
en cada una) y desregistra el webhook:
```powershell
.\stop.ps1
```

> Cada vez que corras `run.ps1` de nuevo, Cloudflare genera una URL nueva y
> el script la vuelve a registrar solo — no tienes que hacer nada manual.

---

## 3. Correr el proyecto (paso a paso manual)

Útil si `run.ps1` falla y necesitas ver exactamente en qué paso está el
problema, o si prefieres controlar cada ventana tú mismo.

**Terminal 1 — Servidor:**
```powershell
.\venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 3000
```
Verifica: `curl http://localhost:3000/` → `{"status":"ok",...}`

**Terminal 2 — Túnel:**
```powershell
cloudflared tunnel --url http://localhost:3000
```
Copia la URL `https://....trycloudflare.com` que aparece en el recuadro.

**Terminal 3 — Registrar el webhook:**
```powershell
Invoke-RestMethod -Uri "https://api.telegram.org/bot<TOKEN>/setWebhook" `
  -Method Post -ContentType "application/json" `
  -Body '{"url": "<TU_URL>/webhook/telegram", "secret_token": "<SECRET>"}'
```
Verifica: `Invoke-RestMethod -Uri "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`

---

## 4. Probar

Manda `/start` a tu bot (responde un saludo fijo, sin pasar por Gemini),
luego un mensaje real como *"Busco apartamento de 2 habitaciones en
Laureles"*. Revisa:
- Ventana de `uvicorn` — debe imprimir el mensaje recibido
- Ventana de `cloudflared` — debe mostrar la petición entrante
- Telegram — debe llegar la respuesta de Gemini en segundos

---

## 5. Nota sobre el modelo de Gemini

Google ha ido retirando modelos de Gemini varias veces durante 2026
(`gemini-2.0-flash`, luego `gemini-2.5-flash`). Ahora mismo el proyecto usa
`gemini-3.5-flash` en `ai_service.py`. Si en el futuro vuelve a salir un
error `404` diciendo que el modelo ya no existe, ese es el único lugar que
hay que actualizar — cambia la línea `GEMINI_MODEL = "..."` por el nombre
vigente (revisa https://ai.google.dev/gemini-api/docs/models para la lista
actual).

---

## 6. Historial de conversación

El bot ahora recuerda los mensajes anteriores de cada chat dentro de la
misma sesión, gracias a `chat_history.py`. Esto significa que si el
usuario dice *"busco un apartamento de 2 habitaciones"* y luego *"en qué
zonas de Medellín lo tienes?"*, el modelo entiende que "lo" se refiere al
apartamento mencionado antes.

**Cómo funciona:**
- Se guarda en un diccionario en memoria (`{chat_id: [mensajes...]}`),
  no en una base de datos.
- Cada chat de Telegram tiene su propio historial, aislado de los demás.
- Se limita a los últimos 20 mensajes por chat (`MAX_HISTORY_MESSAGES` en
  `chat_history.py`) para no mandarle contexto infinito al modelo.
- `/start` borra el historial (empieza una conversación nueva).
- Agregamos también `/reset` como comando explícito para borrar el
  historial sin repetir el saludo de bienvenida.

**Limitación importante:** como es en memoria, **se pierde todo si
reinicias `uvicorn`** (por ejemplo, al parar y volver a correr `run.ps1`).
Para el sprint actual esto es aceptable — es solo para probar el canal de
comunicación. Si más adelante quieren que el historial sobreviva
reinicios o esté disponible entre distintas instancias del servidor (por
ejemplo, si lo despliegan con más de un proceso), eso requeriría mover el
historial a una base de datos (Redis es buena opción para esto por
velocidad; Postgres si prefieren guardarlo junto con los demás datos del
marketplace). Avísame si llegan a ese punto y lo armamos.

---

## 7. Integración del agente de tu compañero

Cuando el agente esté listo, el cambio se limita principalmente a **un solo
archivo**: `ai_service.py`. El resto del proyecto (`main.py`,
`telegram_service.py`, `chat_history.py`, el manejo del webhook, la
verificación del secreto) no cambia nada.

### Qué necesitas saber del agente antes de integrarlo

1. **¿Cómo se expone?** ¿Es un endpoint HTTP propio (ej. `POST
   http://algun-servidor/agente`), una función de Python que puedes
   importar directamente, o algo más (una cola de mensajes, otro
   microservicio)? Esto determina si `ask_ai()` sigue siendo una llamada
   HTTP (como con Gemini) o se vuelve una llamada de función directa.
2. **¿Qué formato de entrada/salida espera?** ¿Recibe solo texto plano, o
   necesita el historial en un formato distinto al que ya maneja
   `chat_history.py`? Si el formato es distinto al de Gemini, hay que
   ajustar `_build_contents()` o la parte equivalente al armar la llamada.
3. **¿Necesita autenticación?** (API key propia, token interno, etc.)

### Ejemplo si el agente es un endpoint HTTP propio

Reemplazarías el contenido de `ai_service.py` por algo así — misma firma de
función (`ask_ai(texto, historial) -> respuesta`), así que `main.py` no se
entera del cambio:

```python
import httpx
from config import AGENTE_URL, AGENTE_API_KEY  # nuevas variables en config.py / .env

async def ask_ai(user_text: str, history: list[dict] | None = None) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            AGENTE_URL,
            headers={"Authorization": f"Bearer {AGENTE_API_KEY}"},
            json={"mensaje": user_text, "historial": history or []},
        )
    data = response.json()
    return data["respuesta"]  # ajusta según el formato real que devuelva el agente
```

### Ejemplo si el agente es código Python que corre en el mismo proyecto

Si tu compañero te pasa su agente como un módulo de Python (no un servicio
HTTP separado), la integración es aún más directa:

```python
from agente_de_mi_companero import procesar_mensaje  # su módulo

async def ask_ai(user_text: str, history: list[dict] | None = None) -> str:
    return await procesar_mensaje(user_text, historial=history or [])
```

### Pasos recomendados para la integración real

1. Pídele a tu compañero un ejemplo mínimo de cómo se llama su agente (un
   `curl` de ejemplo, o un fragmento de código) — con eso defines la forma
   exacta de `ask_ai()`.
2. Prueba el agente por separado primero (fuera del bot), para confirmar
   que responde bien antes de conectarlo al webhook.
3. Cambia `ai_service.py`, deja correr `uvicorn --reload` (recarga sola al
   guardar), y prueba con `/start` y un mensaje real, igual que hicimos con
   Gemini.
4. Si el agente tarda más que Gemini en responder, considera subir el
   `timeout` en la llamada HTTP (o el manejo async si es local) para que no
   se corte antes de tiempo.

---

## 8. Troubleshooting

| Síntoma | Dónde revisar |
|---|---|
| El bot no responde nada | `getWebhookInfo` → revisa `last_error_message` |
| Responde `/start` pero no lo demás | Log de `uvicorn` — probablemente error en `ai_service.py` |
| Error 401 al enviar mensajes (`sendMessage`) | El `TELEGRAM_BOT_TOKEN` del `.env` no coincide con el vigente — revisa si lo revocaste en BotFather |
| Error 401 al **recibir** mensajes (webhook) | El `secret_token` usado en `setWebhook` no coincide con el `.env` |
| `cloudflared` no muestra tráfico entrante | El `setWebhook` no se registró bien, o la URL cambió y no la reregistraste |
| Gemini responde 404 mencionando un modelo | El modelo quedó deprecado — ver sección 5 |
| Gemini responde 400/403 | Revisa que la API key esté activa y sin espacios extra en `.env` |
| `run.ps1` no detecta la URL del túnel | Corre el paso a paso manual (sección 3) para ver el error real de `cloudflared` |

Para desactivar el webhook cuando termines de probar:
```powershell
.\stop.ps1
```