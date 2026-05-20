# jd-bot-bridge

The VM-side bot bridge that ties **nullclaw** (LLM agent runtime), **jd-sell-mcp** (B3, the selling tools), and the **CRM** (C1/C2/C4 Chatwoot-style tables in seller Postgres) into a working selling chatbot.

```
   Buyer chat UI                       CRM (seller Postgres tables)
   safiya.beliaman.com/chat            contacts / conversations / messages
        │  POST /api/chat (Vercel)              ▲                ▲
        │  Bearer BRIDGE_INGEST_TOKEN           │ writes         │ reads
        ▼                                       │                │
   bot.beliaman.com  (Caddy TLS)                │                │
        │                                       │                │
        ▼                                       │                │
   bridge.sh http     POST /ingest    ─────────┘                │
   (127.0.0.1:8088)   GET  /replies   ───────────────────────────┘
                                                                  │
                                                                  │ polls
                                                                  ▼
   bridge.sh worker  ──── nullclaw agent ────► jd-sell MCP (127.0.0.1:7801)
                                                       │
                                                       ▼
                                                Beli Aman BAP
                                                (Beckn /search, /select, ...)
```

Implements Task **B4**.

## Why three units?

- **`jd-bot-nullclaw.service`** — runs `/usr/local/bin/nullclaw daemon` with our config. Loopback only; the worker shells out to its `agent` subcommand per conversation.
- **`jd-bot-bridge-http.service`** — runs `bridge.sh http`, a stdlib-only Python HTTP server. Stateless; one instance is enough. Bears the `Bearer BRIDGE_INGEST_TOKEN` auth gate.
- **`jd-bot-bridge-worker.service`** — runs `bridge.sh worker`, a bash poll loop using `psql` + `flock` + `timeout -k`. Safe to run multiple replicas (per-conversation `flock` + the `WHERE state='bot_active'` re-check inside the INSERT transaction prevent races).

## Wire-shape ↔ CRM mapping

The chat UI uses `sender = "customer" | "bot" | "agent"`; the CRM schema uses `sender = "contact" | "bot" | "agent"`. The HTTP shim translates **customer ↔ contact** at the wire boundary so each side stays in its own vocabulary.

## Hard rules baked into the code

These come from `docs/crm-bridge-contract.md` and the brief:

- The bridge inserts `sender IN ('contact', 'bot')` only. Agent messages flow through the CRM API (C2), never through the bridge.
- Before INSERTing a bot reply, the worker checks `conversation.state = 'bot_active'` **inside the same transaction** as the INSERT. If a human took over (state flipped to `human_handoff`), the INSERT silently no-ops. See `insert_bot_reply()` in `bridge.sh`.
- All bridge-side INSERTs carry an `external_id` for idempotency replay (partial-unique-index `ON CONFLICT DO NOTHING`).
- `flock -n /tmp/jdbot-<conv_uuid>.lock` serialises a single conversation across worker replicas on the same VM. Different conversations proceed in parallel.
- `timeout -k 30 120 nullclaw agent ...` — nullclaw ignores SIGTERM, so the SIGKILL escalation is what actually stops a hung run (proven from `~/Code/pandai/services/yard-supervisor/`).

## Operator runbook

### 1. Provision the VM (task B1, user-blocked)

Out of scope here. The runbook assumes:

- An Ubuntu 24.04 LTS VM on metatech.id infra.
- DNS: `bot.beliaman.com` A/AAAA → VM public IP.
- Outbound HTTPS to Neon (seller Postgres), the BAP, and the Qwen vLLM endpoint.

### 2. Install dependencies

```sh
sudo apt-get update
sudo apt-get install -y \
    python3.11 python3.11-venv \
    postgresql-client \
    jq sqlite3 flock coreutils curl
```

Install nullclaw (the Zig binary):

```sh
# Replace with the exact release URL for nullclaw 2026.5.4
sudo curl -fSL -o /usr/local/bin/nullclaw \
    https://github.com/nullclaw/nullclaw/releases/download/v2026.5.4/nullclaw-linux-x86_64
sudo chmod +x /usr/local/bin/nullclaw
/usr/local/bin/nullclaw --version
```

### 3. Create the `jd-bot` system user + directories

```sh
sudo useradd --system --shell /usr/sbin/nologin --home /home/jd-bot --create-home jd-bot
sudo mkdir -p /opt/jd-bot /var/lib/jd-bot-bridge /var/lib/jd-bot /etc/jd-bot
sudo chown -R jd-bot:jd-bot /opt/jd-bot /var/lib/jd-bot-bridge /var/lib/jd-bot /home/jd-bot
sudo chown root:jd-bot /etc/jd-bot && sudo chmod 0750 /etc/jd-bot
```

### 4. Deploy the bridge code

From the seller repo checkout:

```sh
sudo cp services/jd-bot-bridge/bridge.sh /opt/jd-bot/
sudo cp services/jd-bot-bridge/bridge_http.py /opt/jd-bot/
sudo cp services/jd-bot-bridge/persona.md /opt/jd-bot/
sudo chmod 0755 /opt/jd-bot/bridge.sh /opt/jd-bot/bridge_http.py
sudo chmod 0644 /opt/jd-bot/persona.md
sudo chown -R jd-bot:jd-bot /opt/jd-bot
```

### 5. Configure nullclaw

```sh
sudo -u jd-bot mkdir -p /home/jd-bot/.nullclaw
sudo -u jd-bot envsubst < services/jd-bot-bridge/nullclaw-config.json \
    > /tmp/config.json && \
    sudo mv /tmp/config.json /home/jd-bot/.nullclaw/config.json && \
    sudo chown jd-bot:jd-bot /home/jd-bot/.nullclaw/config.json
```

`envsubst` substitutes `${QWEN_BASE_URL}`, `${QWEN_API_KEY}`, `${QWEN_MODEL_ID}` from the environment. Source `/etc/jd-bot/bridge.env` first if you want the same values as systemd will use:

```sh
set -a; source /etc/jd-bot/bridge.env; set +a
envsubst < services/jd-bot-bridge/nullclaw-config.json > /home/jd-bot/.nullclaw/config.json
```

### 6. Install Python deps (for the HTTP shim)

```sh
sudo -u jd-bot python3.11 -m venv /opt/jd-bot/.venv
sudo -u jd-bot /opt/jd-bot/.venv/bin/pip install --upgrade pip
sudo -u jd-bot /opt/jd-bot/.venv/bin/pip install psycopg2-binary==2.9.9
```

Note: the shim itself uses only the Python stdlib for HTTP (`http.server`). The single external dep is `psycopg2-binary` for the Postgres backend.

### 7. Create `/etc/jd-bot/bridge.env`

Mode 0640, owner `root:jd-bot`. **Do not commit secrets to git.**

```ini
# Seller-side Neon Postgres. Same database the CRM dashboard reads.
# Use the libpq URL form (not the asyncpg form); the bridge runs sync psycopg2.
DATABASE_URL=postgresql://<user>:<pw>@<host>/<db>?sslmode=require

# Shared bearer with the Vercel storefront proxy (B5). 32 hex bytes:
#   openssl rand -hex 32
BRIDGE_INGEST_TOKEN=<random hex string>

# nullclaw — paths are baked into bridge.sh but overridable:
NULLCLAW=/usr/local/bin/nullclaw
NULLCLAW_TIMEOUT_SEC=120
NULLCLAW_KILL_AFTER_SEC=30

# Worker tuning. Defaults are fine for v1.
WORKER_POLL_INTERVAL_SEC=4
WORKER_BATCH_SIZE=8
WORKER_HISTORY_LIMIT=12

# Python interpreter for the HTTP shim (the venv we created above).
PYTHON=/opt/jd-bot/.venv/bin/python

# Where the HTTP shim binds (loopback only — Caddy fronts it).
PORT=8088
BIND_HOST=127.0.0.1

# Qwen via vLLM — operator fills these from the RunPod (or equivalent)
# vLLM deployment. Same Qwen model used by ~/Code/pandai/.
QWEN_BASE_URL=https://<runpod-id>.proxy.runpod.net/v1
QWEN_API_KEY=<vllm bearer token>
QWEN_MODEL_ID=qwen2.5-7b-instruct
```

```sh
sudo install -m 0640 -o root -g jd-bot /tmp/bridge.env /etc/jd-bot/bridge.env
```

| Env var | Source / comes from |
|---|---|
| `DATABASE_URL` | Same Neon URL as seller API (A1/A2). Bridge uses sync psycopg2 form (`postgresql://`), not asyncpg. |
| `BRIDGE_INGEST_TOKEN` | Generated locally (`openssl rand -hex 32`); mirror to Vercel storefront env (B5). |
| `BOT_API_TOKEN` | Same as the BAP env (B3a). Used by jd-sell-mcp via its own env file — not directly by the bridge. |
| `QWEN_BASE_URL`, `QWEN_API_KEY`, `QWEN_MODEL_ID` | From the vLLM deployment that powers pandai today; reuse the same RunPod for now. |
| `NULLCLAW`, `WORKER_*`, `PORT` | Defaults baked into `bridge.sh`; override only for tuning. |

### 8. Install systemd units

```sh
sudo cp services/jd-bot-bridge/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jd-bot-nullclaw
sudo systemctl enable --now jd-bot-bridge-http
sudo systemctl enable --now jd-bot-bridge-worker
```

Verify:

```sh
sudo systemctl status jd-bot-nullclaw jd-bot-bridge-http jd-bot-bridge-worker
curl -s http://127.0.0.1:8088/health
# → {"ok":true,"service":"jd-bot-bridge"}
```

### 9. Caddy reverse-proxy

```sh
sudo cp services/jd-bot-bridge/caddyfile.snippet \
    /etc/caddy/Caddyfile.d/jd-bot.caddy
sudo systemctl reload caddy
```

Or, if you use a single `/etc/caddy/Caddyfile`, append the snippet's `bot.beliaman.com { ... }` block and reload.

### 10. Pre-create the website inbox (one-time per store)

The bridge writes `Conversation.inbox_id` referencing a row in the `inboxes` table. The CRM contract (`docs/crm-bridge-contract.md` §1) requires the operator to provision the inbox first. Either:

- via the CRM UI (Task C3 dashboard) — sign in as a super-admin and create an inbox for the Safiya store with `channel='website'`; or
- via the CRM API:

```sh
curl -X POST https://<seller>/api/inboxes \
    -H "Authorization: Bearer <firebase-id-token>" \
    -H "Content-Type: application/json" \
    -d '{
        "store_id": "<safiya store uuid>",
        "name": "Safiya Website Chat",
        "channel": "website",
        "config": {"origin": "https://safiya.beliaman.com"}
    }'
```

The bridge auto-resolves `(store, channel='website') → inbox_id` and caches the result for 5 min. If no inbox exists, `/ingest` returns 404.

### 11. Wire up the Vercel storefront (B5)

On Vercel:

```sh
vercel env add BRIDGE_BASE_URL production https://bot.beliaman.com
vercel env add BRIDGE_INGEST_TOKEN production <same hex string as the VM>
vercel --prod
```

The storefront's `/api/chat` proxy will now forward to the bridge.

### 12. End-to-end smoke

Open `https://safiya.beliaman.com/safiyafood/chat`, type `ada kurma apa?`, wait ~20-60 s. The bot reply should appear; observe in the CRM dashboard at `jaringan-dagang-seller.metatech.id/conversations`.

### 13. Monitor

```sh
sudo journalctl -u jd-bot-bridge-worker -f
sudo journalctl -u jd-bot-bridge-http -f
sudo journalctl -u jd-bot-nullclaw -f
```

## Local development

Run the smoke test (no nullclaw, no Postgres needed — sqlite stub):

```sh
bash test/smoke.sh
```

Read the prompt structure the worker builds:

```sh
bash test/test_prompt.sh
```

Run the worker against a real Neon database (DANGER — will insert bot messages into the live `messages` table). Don't do this except in a scratch DB:

```sh
DATABASE_URL=postgresql://localhost/jdbot_dev \
NULLCLAW=/usr/local/bin/nullclaw \
PERSONA_FILE=./persona.md \
    bash bridge.sh worker
```

## File map

| Path | Role |
|---|---|
| `bridge.sh` | Bash entrypoint. `bridge.sh http` execs the Python shim; `bridge.sh worker` runs the polling loop in pure bash + `psql`. |
| `bridge_http.py` | Stdlib HTTP server (no FastAPI/uvicorn dep). Two endpoints + `/health`. Auto-detects sqlite vs Postgres in `DATABASE_URL`. |
| `persona.md` | Indonesian sales-assistant prompt loaded by both nullclaw (system prompt via `system_file`) and the worker (per-turn prompt assembly). |
| `nullclaw-config.json` | Template; operator runs `envsubst` to materialise into `/home/jd-bot/.nullclaw/config.json`. |
| `systemd/*.service` | Three units: nullclaw daemon, HTTP shim, worker. All `Restart=on-failure`, `NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths` pinned to data dirs. |
| `caddyfile.snippet` | TLS reverse proxy for `bot.beliaman.com` → `127.0.0.1:8088`. Healthcheck wired. |
| `test/smoke.sh` | Self-contained HTTP-shim test against a sqlite stub. No external deps. Exits 0 on PASS. |
| `test/test_prompt.sh` | Eyeball-the-prompt helper. Prints what the worker assembles for a sample 3-turn history. |

## YAGNI / out of scope (v1)

- **WhatsApp ingress** — covered by B6. When that ships, `/ingest` may grow a `channel='whatsapp'` path; today only `website` is honoured.
- **HMAC signing on `/ingest`** — Bearer is enough for an internal-ish endpoint (Vercel proxy → bridge). The BAP signs Beckn envelopes downstream; that's where signing belongs.
- **Metrics dashboard** — `journalctl` is the source of truth for v1.
- **Outbound delivery queue for agent messages** — the C4 contract document (`docs/crm-bridge-contract.md` §4) describes how a future bridge would poll `messages WHERE sender='agent' AND delivery='pending'` and deliver them through the channel. The current code does NOT do this — agent messages are surfaced in the CRM dashboard via the C2 API, and the chat UI polls and renders them directly. This work belongs to B6 when WhatsApp ingress also lands (the queue is only meaningful for non-website channels).
- **Auto-reopen on contact-message-into-resolved** — per `docs/crm-bridge-contract.md` §9, this is bridge work. Today the bridge will create a new contact message but leave `state=resolved`; the worker's `state='bot_active'` filter then ignores it. Operator must reopen manually via the CRM. Tracked as a B4 follow-up.

## References

- `~/Code/jaringan-dagang-seller/docs/crm-bridge-contract.md` — the operating manual.
- `~/Code/jaringan-dagang-seller/app/models/conversation.py` — the C1 schema this bridge writes against.
- `~/Code/jaringan-dagang-seller/services/jd-sell-mcp/` — the MCP tool server nullclaw calls.
- `~/Code/jaringan-dagang-buyer/sites/partner-demos/app/api/chat/route.ts` — the Vercel storefront proxy that calls `/ingest` and `/replies`.
- `~/Code/pandai/services/yard-supervisor/supervisor.sh` — the proven nullclaw + bash + Postgres polling pattern this bridge borrows idioms from.
