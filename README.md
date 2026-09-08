# Webhook Telegram ↔ Agente Conversacional — Proptech Marketplace

Monorepo con dos paquetes en un **workspace de `uv`**:
- **Webhook** (raíz del repo): recibe mensajes de Telegram, expuesto vía FastAPI.
- **`apps/agent`**: el agente conversacional (LangChain + LangGraph + Gemini),
  con búsqueda de propiedades, agendamiento de visitas, y ahora
  **notificaciones por correo** cuando se agenda una cita.

Ambos comparten un solo entorno virtual y un solo `uv.lock` — un comando
(`uv sync`) instala todo, y el webhook importa al agente directamente como
un paquete de Python normal (sin llamadas HTTP entre los dos).

## Mapa de archivos y cómo se conectan

```
pyproject.toml         <-- raíz del workspace de uv (ver sección 5)
uv.lock                 <-- un solo lockfile para TODO el proyecto

config.py               <-- lee el .env
telegram_service.py    <-- llama a la API de Telegram (enviar mensajes)
ai_service.py            <-- llama a Gemini directo; ya NO se usa en el flujo normal (legacy)
chat_history.py          <-- historial de conversación por chat_id, a nivel webhook
main.py                  <-- servidor FastAPI: recibe el webhook y llama al agente
run.ps1 / stop.ps1       <-- scripts de arranque/apagado (ver sección 2)

apps/agent/
  pyproject.toml         <-- dependencias propias del agente
  src/agent/
    core_langchain.py    <-- handle_turn() — punto de entrada que usa main.py
    tools_langchain.py   <-- herramientas del agente (buscar, agendar, etc.)
    notifications.py     <-- NUEVO: envío de correo cuando se agenda una cita
    llm.py                <-- selección de modelo (fake / gemini)
    fakes/                <-- catálogo, disponibilidad, reservas (en memoria)
```

Flujo de un mensaje real:

```
Telegram --POST--> main.py (/webhook/telegram)
                       |
                       |-- valida el secreto (config.py)
                       |-- delega a handle_message()
                                |
                                |-- agent.core_langchain.handle_turn(chat_id, "telegram", texto)
                                |         |
                                |         |-- el agente decide si busca propiedades,
                                |         |   responde preguntas, o agenda una cita
                                |         |
                                |         |-- si agenda: tools_langchain.schedule_meeting()
                                |                   |
                                |                   |-- crea la cita (FakeBooking)
                                |                   |-- notifications.notify_agent_appointment()
                                |                             |
                                |                             |-- manda el correo por SMTP
                                |
                                |-- telegram_service.send_message() -> entrega la respuesta
```

---

## 1. Configuración inicial (una sola vez por persona/máquina)

### Requisito previo — instalar `uv`

`uv` reemplaza tanto a `pip` como a `venv`: maneja las dependencias Y el
entorno virtual con un solo comando.

```powershell
winget install --id astral-sh.uv --source winget
```

**Verificación:**
```powershell
uv --version
```
Si sale "no se reconoce como comando", cierra y vuelve a abrir PowerShell
(el PATH se actualiza al reabrir), o instala manualmente siguiendo
https://docs.astral.sh/uv/getting-started/installation/

### Paso 1 — Crear el bot en Telegram

1. Abre Telegram, busca **@BotFather**.
2. Envíale `/newbot`.
3. Te pide un nombre visible (ej. `Proptech Agente IA`) y un username único
   terminado en `bot` (ej. `proptech_agente_bot`).
4. Te devuelve un **token**, algo como `8840321755:AAEIq...`. Cópialo.

⚠️ **Este token es un secreto.** No lo compartas en el chat del equipo, ni
en commits de Git, ni en capturas de pantalla. Si por accidente lo expones,
revócalo de inmediato: @BotFather → `/mybots` → tu bot → **API Token** →
**Revoke current token**.

### Paso 2 — Conseguir la API key de Gemini

1. Ve a https://aistudio.google.com/apikey con tu cuenta de Google.
2. **Create API Key** → copia la key generada (capa gratuita).

Mismo cuidado que con el token de Telegram: es un secreto.

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
3. Renómbralo a `cloudflared.exe`, colócalo en `C:\cloudflared\` (fuera de
   la carpeta del proyecto)
4. Agrégala al PATH: menú inicio → "variables de entorno" → **Editar las
   variables de entorno del sistema** → **Variables de entorno** → en tu
   usuario, **Path** → **Editar** → **Nuevo** → pega la ruta de la carpeta
   → Aceptar → **cierra y vuelve a abrir PowerShell**

**Verificación:**
```powershell
cloudflared --version
```

### Paso 4 — Permitir que PowerShell ejecute scripts locales

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**Qué hace:** por defecto, muchas instalaciones de Windows bloquean
cualquier script `.ps1` (incluyendo `run.ps1` y `stop.ps1`) por seguridad.
Este comando permite tus propios scripts locales, y sigue exigiendo firma
digital para scripts descargados de internet.

Confirma con `S` cuando pregunte. **Se configura una sola vez por usuario
de Windows**, no por proyecto.

**Verificación:**
```powershell
Get-ExecutionPolicy -Scope CurrentUser
```
Debe responder `RemoteSigned`.

### Paso 5 — Preparar el proyecto

Parado en la raíz del repo (donde está `pyproject.toml`):

```powershell
uv sync
```

**Qué hace:** lee `pyproject.toml` y `uv.lock`, crea un entorno virtual en
`.venv/` (automático, no hay que activarlo a mano), e instala **todo** —
las dependencias del webhook (FastAPI, httpx...) y las del agente
(LangChain, LangGraph...) — en un solo paso, porque ambos son parte del
mismo workspace.

Vas a ver algo como:
```
Resolved 66 packages in ...
Installed 66 packages in ...
```

A diferencia de `venv` + `pip`, **no hay que activar nada manualmente** —
`uv run <comando>` (lo que usan `run.ps1` y el resto de esta guía) ya sabe
usar ese entorno automáticamente.

```powershell
copy .env.example .env
notepad .env
```

Llena los valores reales (ver Pasos 1 y 2 para el token de Telegram y la
key de Gemini). Por ahora deja `AGENT_LLM_MODE=fake` y
`NOTIFICATIONS_MODE=fake` — los cambiamos a los reales en la sección 6
cuando configures el correo.

---

## 2. Correr el proyecto (camino rápido) ⚡

Con el `.env` ya lleno:

```powershell
.\run.ps1
```

Automatiza: `uv sync` (por si hay dependencias nuevas) → levanta `uvicorn`
en una ventana nueva → levanta `cloudflared` en otra → detecta la URL
pública → la registra como webhook en Telegram, con reintentos si Telegram
tarda en resolver el DNS del túnel.

Al final deberías ver:
```
Listo! Webhook registrado correctamente.
URL: https://algo-random.trycloudflare.com/webhook/telegram
```

**Para terminar la sesión de pruebas**, cierra las dos ventanas (`Ctrl+C`
en cada una) y desregistra el webhook:
```powershell
.\stop.ps1
```

---

## 3. Correr el proyecto (paso a paso manual)

Útil si `run.ps1` falla y quieres ver en qué paso exacto está el problema.

**Terminal 1 — Servidor:**
```powershell
uv run uvicorn main:app --reload --port 3000
```
Verifica: `curl http://localhost:3000/` → `{"status":"ok",...}`

**Terminal 2 — Túnel:**
```powershell
cloudflared tunnel --url http://localhost:3000
```
Copia la URL `https://....trycloudflare.com`.

**Terminal 3 — Registrar el webhook:**
```powershell
Invoke-RestMethod -Uri "https://api.telegram.org/bot<TOKEN>/setWebhook" `
  -Method Post -ContentType "application/json" `
  -Body '{"url": "<TU_URL>/webhook/telegram", "secret_token": "<SECRET>"}'
```
Verifica: `Invoke-RestMethod -Uri "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`

---

## 4. Probar

Manda `/start` a tu bot, luego un mensaje real como *"Busco apartamento de
2 habitaciones en Laureles"*. Con `AGENT_LLM_MODE=fake`, las respuestas son
genéricas (para probar el canal sin gastar cuota de Gemini). Con
`AGENT_LLM_MODE=gemini`, el agente responde de verdad, busca en el catálogo,
y puede agendar visitas.

Para probar el agendamiento de una vez: pide una propiedad, pide
disponibilidad, y confirma agendar una visita — eso dispara el correo de
notificación (sección 6).

---

## 5. El workspace de `uv`: cómo quedó estructurado

`uv` permite que varios paquetes de Python vivan en el mismo repo,
compartiendo un solo entorno y un solo lockfile, pero manteniendo cada uno
su propio `pyproject.toml`. Así quedó configurado:

**`pyproject.toml` (raíz)** — define el proyecto del webhook y declara el
workspace:
```toml
[tool.uv.sources]
proptech-agent = { workspace = true }

[tool.uv.workspace]
members = ["apps/*"]
```
La primera línea le dice a `uv` que la dependencia `proptech-agent` no
viene de PyPI, sino que es el paquete que vive en `apps/agent` dentro de
este mismo repo. La segunda línea incluye todo lo que esté bajo `apps/` como
parte del workspace.

**`apps/agent/pyproject.toml`** — define el paquete del agente
(`proptech-agent`), con sus propias dependencias (LangChain, LangGraph,
`aiosmtplib` para el correo).

**Resultado práctico:** `main.py` puede hacer
`from agent.core_langchain import handle_turn` como si fuera cualquier
librería instalada — sin trucos de `sys.path`, sin copiar código. `uv sync`
en la raíz instala ambos paquetes y sus dependencias en un único
`.venv/`.

**Un solo `.env`:** como todo corre en el mismo proceso, `config.py` carga
un único `.env` en la raíz que trae tanto las variables del webhook
(`TELEGRAM_*`) como las del agente (`GOOGLE_API_KEY`, `AGENT_LLM_MODE`,
las de SMTP). El `apps/agent/.env.example` sigue existiendo por separado
solo para cuando alguien quiera correr el agente de forma aislada (modo
consola, tests) sin levantar el webhook.

---

## 6. Notificaciones por correo (SMTP)

Cuando el agente agenda una cita (herramienta `schedule_meeting` en
`apps/agent/src/agent/tools_langchain.py`), ahora manda un correo real al
agente inmobiliario humano avisándole — antes esto solo se guardaba en
memoria (`FakeNotifications`) y no llegaba a nadie.

### Cómo funciona

`apps/agent/src/agent/notifications.py` implementa `NotificationsPort`
(la interfaz que ya existía en `agent/ports/__init__.py`) usando
`aiosmtplib` — la versión asíncrona de `smtplib`, para no bloquear el
servidor mientras se conecta al proveedor de correo.

Cuál implementación se usa se decide por la variable `NOTIFICATIONS_MODE`
(mismo patrón que `AGENT_LLM_MODE` para elegir entre el modelo fake y
Gemini):
- `fake` (default) → no manda nada real, solo lo guarda en memoria. Útil
  para desarrollar sin generar correos de prueba constantemente.
- `email` → manda el correo real por SMTP.

El correo incluye: nombre y ubicación de la propiedad, precio, fecha/hora
de la visita, ID de la cita, y el `chat_id` del cliente (para que el
agente pueda ubicar la conversación).

### Opción A — Gmail con contraseña de aplicación (recomendada para probar rápido)

Gmail no deja usar tu contraseña normal para SMTP por seguridad; hay que
generar una "contraseña de aplicación" específica.

1. Activa la verificación en dos pasos en tu cuenta de Google (si no la
   tienes, Gmail no te deja crear contraseñas de aplicación):
   https://myaccount.google.com/security
2. Ve a https://myaccount.google.com/apppasswords
3. Genera una contraseña nueva (nombre sugerido: "Proptech SMTP"). Te da
   una contraseña de 16 caracteres — cópiala, no vuelve a mostrarse.
4. En tu `.env`:
   ```
   NOTIFICATIONS_MODE=email
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=tu_correo@gmail.com
   SMTP_PASSWORD=la_contraseña_de_16_caracteres_sin_espacios
   SMTP_FROM=tu_correo@gmail.com
   SMTP_USE_TLS=true
   AGENT_NOTIFICATION_EMAIL=correo_del_agente_inmobiliario@ejemplo.com
   ```

### Opción B — Mailtrap (sandbox de pruebas, no manda correos reales)

Si prefieres no usar una cuenta de Gmail real mientras desarrollan (para
no llenar una bandeja de entrada real con pruebas), Mailtrap simula el
envío: los correos "llegan" a una bandeja de pruebas en su web, nunca a un
destinatario real.

1. Crea una cuenta gratis en https://mailtrap.io
2. **Email Testing** → **Inboxes** → tu inbox → pestaña **SMTP Settings**
3. Copia el host, puerto, usuario y contraseña que te muestran ahí
4. En tu `.env`:
   ```
   NOTIFICATIONS_MODE=email
   SMTP_HOST=sandbox.smtp.mailtrap.io
   SMTP_PORT=587
   SMTP_USER=<el que te dio Mailtrap>
   SMTP_PASSWORD=<la que te dio Mailtrap>
   SMTP_FROM=noreply@proptech-marketplace.test
   SMTP_USE_TLS=true
   AGENT_NOTIFICATION_EMAIL=cualquier_correo@ejemplo.com
   ```
Los correos van a aparecer en el inbox de Mailtrap, no en una bandeja real
— ideal para el sprint mientras confirman que el envío funciona.

### Probar el envío

Con `AGENT_LLM_MODE=gemini` y `NOTIFICATIONS_MODE=email`, agenda una cita
completa por Telegram (busca una propiedad, pide disponibilidad, confirma
agendar). Revisa la consola de `uvicorn`:
- Si no aparece ningún error de `[notifications]`, el correo se mandó —
  revisa la bandeja (real o de Mailtrap) que configuraste en
  `AGENT_NOTIFICATION_EMAIL`.
- Si aparece `[notifications] Error enviando correo: ...`, el mensaje de
  error te dice la causa (credenciales inválidas, host incorrecto, etc.) —
  la cita se guarda igual, solo falla el aviso.

---

## 7. Nota sobre el modelo de Gemini

Google ha ido retirando modelos de Gemini varias veces durante 2026. El
agente usa la variable `GEMINI_MODEL` en el `.env` (default
`gemini-3.6-flash`); si en el futuro sale un error `404` diciendo que el
modelo ya no existe, ese es el único valor que hay que actualizar — no
hace falta tocar código. Revisa
https://ai.google.dev/gemini-api/docs/models para la lista vigente.

`ai_service.py` (el archivo que llamaba a Gemini directo, de antes de
integrar el agente) sigue en el repo intacto pero **ya no se usa en el
flujo normal** — se dejó por si sirve de referencia, pero `config.py`
todavía exige `GEMINI_API_KEY` en el `.env` por compatibilidad con él.

---

## 8. Historial de conversación

Hay **dos** sistemas de historial funcionando en paralelo, y vale la pena
tenerlo claro:

- **`chat_history.py`** (a nivel del webhook) — guarda los mensajes por
  `chat_id` de Telegram, usado para los comandos `/start` y `/reset`.
- **El agente mismo** — `core_langchain.py` usa `thread_id=client_id` con
  `MemorySaver` de LangGraph, manteniendo su propio historial internamente
  para razonar con contexto (recordar qué propiedad se mencionó antes,
  etc.).

Son redundantes en parte, pero no chocan — el segundo es el que realmente
afecta las respuestas del agente; el primero seguía existiendo porque
`main.py` no se tocó a fondo al integrar el agente. Si en algún momento
quieren simplificar, `chat_history.py` podría eliminarse del flujo
(`/start` y `/reset` seguirían funcionando llamando en su lugar al
historial del agente) — no es urgente para este sprint.

Ambos son **en memoria**: se pierden si reinicias `uvicorn`.

---

## 9. Troubleshooting

| Síntoma | Dónde revisar |
|---|---|
| `uv sync` falla con conflicto de versiones | Revisa que no hayas editado a mano `uv.lock` — bórralo y corre `uv lock` de nuevo para regenerarlo |
| `ModuleNotFoundError: agent` | `uv sync` no se corrió, o falta el `[tool.uv.sources]` en el `pyproject.toml` raíz — confirma que `apps/agent` aparece en `uv sync` como paquete instalado |
| El bot no responde nada | `getWebhookInfo` → revisa `last_error_message` |
| Responde `/start` pero no lo demás | Log de `uvicorn` — revisa `[main] Error llamando al agente: ...` |
| Error 401 al enviar mensajes (`sendMessage`) | El `TELEGRAM_BOT_TOKEN` del `.env` no coincide con el vigente |
| Error 401 al **recibir** mensajes (webhook) | El `secret_token` usado en `setWebhook` no coincide con el `.env` |
| `cloudflared` no muestra tráfico entrante | El `setWebhook` no se registró bien, o la URL cambió |
| Gemini responde 404 mencionando un modelo | El modelo quedó deprecado — ver sección 7 |
| `[notifications] Error enviando correo` | Revisa credenciales SMTP, o si Gmail: confirma que sea la contraseña de aplicación (16 caracteres), no la contraseña normal |
| El correo no llega pero no hay error | Revisa spam, y que `AGENT_NOTIFICATION_EMAIL` esté bien escrito; con Mailtrap, revisa el inbox en su web, no un correo real |
| `run.ps1` no detecta la URL del túnel | Corre el paso a paso manual (sección 3) |

Para desactivar el webhook cuando termines de probar:
```powershell
.\stop.ps1
```
