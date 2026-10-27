# Homelitics — AI Agents

AI layer of **Homelitics**, a two-sided proptech marketplace that connects home seekers with real estate agencies.
This repository contains the two AI services built by the AI/Bot line of the team:

| Service | Path | Who uses it | What it does |
|---|---|---|---|
| **Telegram assistant** (E6) | repo root + `apps/agent/` | Clients (buyers/renters) | Conversational property search and visit scheduling over Telegram (HU-21, HU-22) |
| **Insights agent** | `apps/insights/` | Agency `TEAM_ADMIN`s, from the web panel | Read-only decision support over the agency's leads, funnel and listings (HU-18) |

Both services are **channels on top of the same Homelitics backend** (FastAPI + Supabase, separate repository). They do not own any business data: every lead, appointment and listing is read from or written to the backend API.

---

## Table of contents

1. [Repository structure](#1-repository-structure)
2. [Architecture](#2-architecture)
3. [Getting started](#3-getting-started)
4. [Running the Telegram assistant](#4-running-the-telegram-assistant)
5. [Running the insights agent](#5-running-the-insights-agent)
6. [Configuration reference](#6-configuration-reference)
7. [Testing](#7-testing)
8. [Observability (Langfuse)](#8-observability-langfuse)
9. [Troubleshooting](#9-troubleshooting)
10. [Known technical debt](#10-known-technical-debt)

---

## 1. Repository structure

The repo is a **`uv` workspace**: several Python packages share one virtual environment (`.venv/`) and one lockfile (`uv.lock`), but each keeps its own `pyproject.toml`.

```
.
├── pyproject.toml          # Workspace root + Telegram webhook package (proptech-webhook)
├── uv.lock                 # Single lockfile for the whole workspace
├── env.example             # Template for the root .env (webhook + agent)
├── main.py                 # FastAPI app: Telegram webhook → handle_turn()
├── config.py               # Loads .env, validates required variables
├── telegram_service.py     # Sends messages through the Telegram Bot API
├── chat_history.py         # Per-chat history used by /start and /reset
├── ai_service.py           # Legacy direct Gemini call (not used in the normal flow)
├── run.ps1 / stop.ps1      # Local start/stop scripts (uvicorn + cloudflared + setWebhook)
│
└── apps/
    ├── agent/              # proptech-agent — conversational assistant (LangChain + LangGraph)
    │   ├── prompts/system.md
    │   ├── scripts/        # chat.py (console chat), smoke tests
    │   ├── src/agent/
    │   │   ├── core_langchain.py   # handle_turn() — the single public entry point
    │   │   ├── tools_langchain.py  # Tools exposed to the LLM
    │   │   ├── booking.py, agent_slots.py, leads.py, listing_search.py, ...
    │   │   ├── backend_auth.py, jwt_provider.py   # Bot service-account auth
    │   │   ├── notifications.py    # Email notifications (SMTP)
    │   │   ├── ports/              # Interfaces (ports)
    │   │   └── fakes/              # In-memory implementations for dev/tests
    │   └── tests/
    │
    ├── insights/           # proptech-insights — insights agent for TEAM_ADMINs
    │   ├── env.example
    │   ├── prompts/system.md
    │   ├── scripts/        # get_token.py, smoke.ps1
    │   ├── src/insights/
    │   │   ├── main.py     # FastAPI app: /health, /insights/chat
    │   │   ├── gate.py     # TEAM_ADMIN gate (runs before any LLM call)
    │   │   ├── agent.py    # LangGraph agent
    │   │   └── tools.py    # Read-only analytics tools
    │   └── tests/
    │
    └── shared/             # proptech-shared — LLM, HTTP and observability helpers
        └── src/shared/
```

---

## 2. Architecture

### 2.1 Telegram assistant

```
Telegram ──POST──▶ main.py  /webhook/telegram
                    │  1. validate X-Telegram-Bot-Api-Secret-Token
                    │  2. reply 200 immediately, process in background
                    ▼
            agent.core_langchain.handle_turn(chat_id, "telegram", text)
                    │  LangGraph agent (Gemini) + MemorySaver (per chat)
                    │  picks tools:
                    │    search_properties / answer_property_question
                    │    create_or_get_lead → check_agent_availability → book_appointment
                    │    request_visit (manual fallback, notifies the agent by email)
                    ▼
            Homelitics backend API  (bot service account JWT + X-Agency-Id)
                    │
                    ▼
            telegram_service.send_message()  ──▶  Telegram
```

Key design rules:

- **Single integration seam:** `handle_turn(client_id, channel, message) → AgentReply`. Telegram is only a delivery channel; the agent does not know about Telegram.
- **One bot per agency:** each deployment is pinned to one agency through `AGENCY_ID`, so a client only sees that agency's listings.
- **Ports and adapters:** every backend dependency has a `fake` and an `http` implementation, selected with a `*_MODE` env var. This lets the agent run and be tested without a backend.
- **Bot authentication:** the bot logs in as a dedicated service account (`BOT_EMAIL` / `BOT_PASSWORD`) and sends `X-Agency-Id` on every request; `client_id` is always explicit in payloads.

### 2.2 Insights agent

```
Agency web panel ──POST /insights/chat (Bearer <user JWT>)──▶ insights.main
                    │  gate.require_team_admin → GET /me on the backend
                    │    (401/403 before any LLM call if not an active TEAM_ADMIN)
                    ▼
            LangGraph agent (Gemini) + read-only tools:
              get_north_star, get_funnel, list_leads, list_agents,
              get_agent_response_times, get_lost_reasons,
              get_listing_performance, segment_demand
                    │  each tool forwards the user's own JWT to the backend
                    ▼
            { reply, conversation_id, sources[] }
```

- **Read-only:** the insights agent never writes to the backend.
- **The user's permissions apply:** it reuses the caller's token, so it can only see what that `TEAM_ADMIN` can see.
- **Traceable answers:** every reply includes `sources` (tool, endpoint and parameters used).

---

## 3. Getting started

### 3.1 Prerequisites (once per machine)

| Tool | Install (Windows / PowerShell) | Check |
|---|---|---|
| `uv` (packages + virtualenv) | `winget install --id astral-sh.uv --source winget` | `uv --version` |
| `cloudflared` (public HTTPS tunnel, Telegram only) | `winget install --id Cloudflare.cloudflared --source winget` | `cloudflared --version` |
| Allow local scripts | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` | `Get-ExecutionPolicy -Scope CurrentUser` |

> `--source winget` avoids a DNS failure against the Microsoft Store catalog on some university/corporate networks. If `winget` still fails, download the binary from the [cloudflared releases page](https://github.com/cloudflare/cloudflared/releases/latest) and add its folder to `PATH`.

### 3.2 Credentials you will need

- **Telegram bot token** — talk to [@BotFather](https://t.me/BotFather), send `/newbot`, copy the token.
- **Gemini API key** — create one at <https://aistudio.google.com/apikey>.
- **Bot service account** (`BOT_EMAIL`, `BOT_PASSWORD`) and **`AGENCY_ID`** — ask the Backend Lead.

> ⚠️ These are secrets. Never commit them, paste them in team chats, or show them in screenshots. If a Telegram token leaks, revoke it: @BotFather → `/mybots` → your bot → **API Token** → **Revoke current token**.

### 3.3 Install

From the repository root:

```powershell
uv sync
```

This creates `.venv/` and installs every workspace package (`webhook`, `agent`, `insights`, `shared`). There is nothing to activate manually: `uv run <command>` uses that environment.

### 3.4 Environment files

| File | Template | Used by |
|---|---|---|
| `.env` (root) | `env.example` | Telegram webhook + agent (they run in the same process) |
| `apps/insights/.env` | `apps/insights/env.example` | Insights agent |
| `apps/agent/.env` | `apps/agent/.env.example` | Only when running the agent standalone (console / tests) |

```powershell
copy env.example .env
notepad .env
```

Start with every `*_MODE=fake` to check the channel works, then switch to `gemini` / `http` (see [section 6](#6-configuration-reference)).

---

## 4. Running the Telegram assistant

### 4.1 Quick start

```powershell
.\run.ps1
```

The script runs `uv sync`, starts `uvicorn` on port 3000, opens a `cloudflared` tunnel, detects the public URL and registers it as the Telegram webhook (with retries). When you are done, close both windows (`Ctrl+C`) and unregister the webhook:

```powershell
.\stop.ps1
```

### 4.2 Manual start (useful for debugging `run.ps1`)

```powershell
# Terminal 1 — server
uv run uvicorn main:app --reload --port 3000
# check: curl http://localhost:3000/   →  {"status":"ok", ...}

# Terminal 2 — tunnel
cloudflared tunnel --url http://localhost:3000

# Terminal 3 — register the webhook
Invoke-RestMethod -Uri "https://api.telegram.org/bot<TOKEN>/setWebhook" `
  -Method Post -ContentType "application/json" `
  -Body '{"url": "<TUNNEL_URL>/webhook/telegram", "secret_token": "<TELEGRAM_WEBHOOK_SECRET>"}'
# check: Invoke-RestMethod -Uri "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

### 4.3 Without Telegram (console)

```powershell
uv run python apps/agent/scripts/chat.py
```

### 4.4 Try it

Send `/start` to the bot, then something like *"I'm looking for a 2-bedroom apartment in Laureles"*. With `AGENT_LLM_MODE=fake` replies are canned (no Gemini quota used). With `AGENT_LLM_MODE=gemini` and the `http` modes, the bot searches the agency's real catalog and can book a visit end to end.

Bot commands: `/start` (greeting, clears history) and `/reset` (clears history).

---

## 5. Running the insights agent

```powershell
copy apps\insights\env.example apps\insights\.env
uv run uvicorn insights.main:app --reload --port 8001
```

Endpoints:

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | — | Liveness check |
| `POST` | `/insights/chat` | `Bearer <TEAM_ADMIN JWT>` | Body: `{ "message": "...", "conversation_id": null }` |

Dev helpers:

```powershell
# Get a TEAM_ADMIN JWT (uses INSIGHTS_DEV_EMAIL / INSIGHTS_DEV_PASSWORD)
uv run python apps/insights/scripts/get_token.py

# Smoke test against the running service
powershell -ExecutionPolicy Bypass -File apps/insights/scripts/smoke.ps1 -Port 8001
```

Set `INSIGHTS_CORS_ORIGINS` to the web panel's origin(s) so the browser can call the service.

---

## 6. Configuration reference

### 6.1 Telegram webhook + agent (root `.env`)

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Token from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Recommended | Random string; Telegram sends it back so we can reject forged requests |
| `GEMINI_API_KEY` | Yes | Still required at startup by `config.py` (legacy, see [section 10](#10-known-technical-debt)) |
| `GOOGLE_API_KEY` | For `gemini` mode | Gemini key used by the agent (can be the same as above) |
| `GEMINI_MODEL` | No | Default `gemini-3.6-flash`. If Gemini returns `404` for a model, update only this value ([model list](https://ai.google.dev/gemini-api/docs/models)) |
| `AGENT_LLM_MODE` | No | `fake` (keyword replies, no quota) \| `gemini` |
| `AGENT_DEBUG` | No | `true` prints every tool call, its arguments and its result |
| `BACKEND_URL` | For `http` modes | e.g. `https://homelitics-api.onrender.com` |
| `BOT_EMAIL`, `BOT_PASSWORD` | For `http` modes | Bot service account (must be set together) |
| `AGENCY_ID` | For `http` modes | Agency this bot deployment belongs to (sent as `X-Agency-Id`) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | For `http` modes | Used to log the service account in |

**Provider modes** — each one is `fake` (in memory, no backend) or `http` (real backend):

| Variable | Controls |
|---|---|
| `AGENT_SLOTS_MODE` | Agent availability (`check_agent_availability`) |
| `APPOINTMENT_BOOKING_MODE` | Booking (`book_appointment`) |
| `CLIENT_RESOLVER_MODE` | Telegram chat → backend client (`POST /clients`) |
| `LEAD_MODE` | Lead creation (`create_or_get_lead`) |
| `LISTING_AGENCY_RESOLVER_MODE` | Listing → agency resolution |
| `LISTING_SEARCH_MODE` | Property search (`search_properties`) |

> If `LEAD_MODE=http`, then `LISTING_AGENCY_RESOLVER_MODE` and `LISTING_SEARCH_MODE` must also be `http`. The app checks this at startup and refuses to start with an invalid combination.

**Email notifications** (sent when a client asks for a visit through `request_visit`):

| Variable | Description |
|---|---|
| `NOTIFICATIONS_MODE` | `fake` (stored in memory, default) \| `email` (real SMTP) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` | SMTP server settings |
| `AGENT_NOTIFICATION_EMAIL` | Real estate agent who receives the notification |

Two common SMTP setups:

- **Gmail** — enable 2-step verification, create an [app password](https://myaccount.google.com/apppasswords), then use `smtp.gmail.com:587` with that 16-character password (not your normal password).
- **Mailtrap** (sandbox, nothing reaches a real inbox) — create a free inbox at <https://mailtrap.io> and copy its SMTP settings (`sandbox.smtp.mailtrap.io:587`).

A failed email never blocks the conversation: the error is logged as `[notifications] ...` and the flow continues.

### 6.2 Insights agent (`apps/insights/.env`)

| Variable | Description |
|---|---|
| `BACKEND_URL` | Homelitics backend (default `https://homelitics-api.onrender.com`) |
| `INSIGHTS_LLM_MODE` | `fake` (no network) \| `gemini` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini credentials and model |
| `INSIGHTS_LLM_MAX_RETRIES` | Total attempts per Gemini call (min 1). Exhausted retries return `502` |
| `INSIGHTS_LLM_TIMEOUT` | Timeout per attempt, in seconds (default 60) |
| `INSIGHTS_CORS_ORIGINS` | Comma-separated allowed origins for the web panel |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `INSIGHTS_DEV_EMAIL`, `INSIGHTS_DEV_PASSWORD` | Dev only, for `scripts/get_token.py` |

---

## 7. Testing

Tests use `pytest` + `pytest-asyncio` and run against the `fake` providers, so they need no backend, no Gemini key and no Telegram.

```powershell
# Conversational agent
cd apps/agent;    uv run pytest; cd ../..

# Insights agent
cd apps/insights; uv run pytest; cd ../..
```

Manual smoke scripts (they hit real services): `apps/agent/scripts/smoke_gemini.py`, `apps/agent/scripts/smoke_test_auth.py`, `apps/insights/scripts/smoke.ps1`.

---

## 8. Observability (Langfuse)

Both services can send traces to [Langfuse](https://cloud.langfuse.com): one trace per turn / request, with nested spans for each LLM call and tool, grouped by conversation.

1. Create a project at <https://cloud.langfuse.com> → **Settings** → **API keys**.
2. Add to the corresponding `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=https://cloud.langfuse.com   # only change for self-hosted
   ```
3. Restart the service.

Tracing is **opt-in and fail-open**: without keys it is disabled with no errors and no change in behavior, and a Langfuse outage never breaks a conversation.

---

## 9. Troubleshooting

| Symptom | Where to look |
|---|---|
| `uv sync` fails with a version conflict | Don't edit `uv.lock` by hand. Delete it and run `uv lock` to regenerate it |
| `ModuleNotFoundError: agent` / `insights` / `shared` | Run `uv sync` at the repo root and check that the package appears as installed |
| App refuses to start mentioning `*_MODE` | Invalid provider combination — see the note in [6.1](#61-telegram-webhook--agent-root-env) |
| Bot does not answer at all | `getWebhookInfo` → check `last_error_message` |
| Bot answers `/start` but nothing else | `uvicorn` log → look for `[main] Error llamando al agente: ...` |
| `401` when **sending** messages | `TELEGRAM_BOT_TOKEN` does not match the current token |
| `401` when **receiving** messages | The `secret_token` used in `setWebhook` does not match `TELEGRAM_WEBHOOK_SECRET` |
| `cloudflared` shows no incoming traffic | Webhook not registered, or the tunnel URL changed (it changes on every run) |
| `run.ps1` does not detect the tunnel URL | Use the manual start ([4.2](#42-manual-start-useful-for-debugging-runps1)) |
| Gemini returns `404` mentioning a model | Model retired — update `GEMINI_MODEL` |
| Insights returns `401` / `403` | Missing token, expired token, or the user is not an active `TEAM_ADMIN` |
| Insights returns `502` | Backend unreachable or Gemini retries exhausted |
| `[notifications] ...` error | Check SMTP credentials; for Gmail use the app password |
| Email not received, no error | Check spam and `AGENT_NOTIFICATION_EMAIL`; with Mailtrap check its web inbox |

---

## 10. Known technical debt

- **`ai_service.py` is legacy.** It is no longer used in the normal flow, but `config.py` still requires `GEMINI_API_KEY` at startup because of it.
- **Two conversation histories.** `chat_history.py` (webhook, only for `/start` and `/reset`) and LangGraph's `MemorySaver` inside the agent (the one that actually drives replies). Both are in memory and are lost when the server restarts.
- **Retired tools still in the code.** `check_availability` and `schedule_meeting` were removed from `get_tools()` in Sprint 3 in favor of the real HU-22 route, but their definitions remain as dead code.
- **`sys.path` workaround in `main.py`.** The agent package is already installed by the `uv` workspace, so this line is redundant.
