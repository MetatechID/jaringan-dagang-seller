# jd-sell-mcp

HTTP MCP tool server that lets a chatbot (nullclaw + Qwen) sell Safiya
products by calling the deployed Beli Aman BAP. Loopback-only by default.

```
nullclaw (Qwen)
   │  MCP JSON-RPC over HTTP (loopback)
   ▼
jd-sell-mcp  (this service, port 7801)
   │  HTTPS + Bearer BOT_API_TOKEN
   ▼
Beli Aman BAP  (https://safiya.beliaman.com/api/v1/*)
   │  Beckn /search, /select, /init, /confirm (signed)
   ▼
Safiya BPP (seller)
```

Implements Task **B3** of the Beli Aman implementation plan. Pairs with
B3a (the deployed BAP REST surface) and is consumed by B4 (the
nullclaw `bridge.sh`).

## Architecture decisions

- **Hand-rolled MCP JSON-RPC 2.0** (`mcp_protocol.py`, ~120 LOC) rather
  than the official Python `mcp` SDK. We expose exactly three methods
  (`initialize`, `tools/list`, `tools/call`); the SDK's resources/prompts/
  sampling layers are unused. Small audit surface is a security win in
  this position (LLM bridges to a payment-issuing BAP).
- **Bot never holds Beckn keys.** Every tool proxies to the BAP REST
  surface; the BAP signs envelopes for the seller BPP.
- **State in SQLite** keyed on `conversation_id` (UUID from the bot).
  WAL journal mode for concurrent reader/writer safety. One row per
  active chat.

## MCP tool surface

| Tool | Input | Output |
|---|---|---|
| `search_products` | `{conversation_id, query, category?, city?}` | Markdown top-5 + JSON catalog |
| `get_product` | `{conversation_id, item_id}` | Detail markdown + JSON (cache-only, no HTTP) |
| `cart_add` | `{conversation_id, items:[{item_id, qty}]}` | Quote markdown + JSON |
| `cart_view` | `{conversation_id}` | Quote markdown + JSON |
| `start_checkout` | `{conversation_id, billing, shipping}` | QR + invoice markdown + JSON |
| `payment_status` | `{conversation_id}` | "Status pembayaran: ..." + JSON |

All summaries are in **Bahasa Indonesia** (the bot replies to Indonesian
customers).

## Environment variables

| Var | Required | Default | Notes |
|---|---|---|---|
| `BAP_BASE_URL` | yes | `http://localhost:8003` (dev) | e.g. `https://safiya.beliaman.com` |
| `BOT_API_TOKEN` | **yes** | (unset → BAP rejects) | Must match the BAP's `BOT_API_TOKEN` exactly |
| `MCP_PORT` | no | `7801` | Loopback only by default |
| `MCP_BIND_HOST` | no | `127.0.0.1` | Do NOT change to `0.0.0.0` without thinking |
| `STATE_DB_PATH` | no | `/var/lib/jd-sell-mcp/state.db` → fallback `/tmp/jd-sell-mcp.db` | |
| `CATALOG_CACHE_TTL_SEC` | no | `300` | Search-cache TTL feeding `get_product` |
| `BAP_TIMEOUT_SEC` | no | `15` | Per-request HTTP timeout |
| `LOG_LEVEL` | no | `INFO` | |

## Local development

```sh
cd services/jd-sell-mcp
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Run the tests:
.venv/bin/python -m pytest tests/ -q

# Boot the server pointed at the deployed BAP:
export BAP_BASE_URL=https://safiya.beliaman.com
export BOT_API_TOKEN=<the same token configured on Vercel for the BAP>
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 7801

# Smoke:
curl -X POST http://127.0.0.1:7801/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

## VM deployment (B1)

After B1 provisions the VM:

```sh
# 1. Python 3.11+
sudo apt-get install -y python3.11 python3.11-venv

# 2. System user + persistent data dir
sudo useradd --system --shell /usr/sbin/nologin jd-bot
sudo mkdir -p /var/lib/jd-sell-mcp
sudo chown jd-bot:jd-bot /var/lib/jd-sell-mcp

# 3. Code + venv
sudo -u jd-bot git clone <seller-repo> /opt/jd-sell-mcp-repo
sudo -u jd-bot python3.11 -m venv /opt/jd-sell-mcp-repo/services/jd-sell-mcp/.venv
sudo -u jd-bot /opt/jd-sell-mcp-repo/services/jd-sell-mcp/.venv/bin/pip install \
  -r /opt/jd-sell-mcp-repo/services/jd-sell-mcp/requirements.txt

# 4. Env file (mode 0600, root-readable, jd-bot-readable)
sudo tee /etc/jd-sell-mcp.env <<'EOF'
BAP_BASE_URL=https://safiya.beliaman.com
BOT_API_TOKEN=<the same token configured on Vercel for the BAP>
STATE_DB_PATH=/var/lib/jd-sell-mcp/state.db
MCP_PORT=7801
EOF
sudo chmod 600 /etc/jd-sell-mcp.env

# 5. systemd unit
sudo tee /etc/systemd/system/jd-sell-mcp.service <<'EOF'
[Unit]
Description=jd-sell MCP tool server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jd-bot
WorkingDirectory=/opt/jd-sell-mcp-repo/services/jd-sell-mcp
EnvironmentFile=/etc/jd-sell-mcp.env
ExecStart=/opt/jd-sell-mcp-repo/services/jd-sell-mcp/.venv/bin/uvicorn \
  main:app --host 127.0.0.1 --port 7801
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/jd-sell-mcp

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now jd-sell-mcp
sudo systemctl status jd-sell-mcp
```

**No Caddy snippet.** This service binds loopback only; nullclaw runs on
the same VM and reaches it via `http://127.0.0.1:7801/mcp`. Do NOT proxy
it to the public internet — the bot is anonymous-tier; if you need
internet access to MCP, gate it behind a proper auth layer first.

## Nullclaw wiring

In nullclaw's config, declare this server as an HTTP MCP backend:

```toml
[agents.defaults.mcp.servers.selling]
type = "http"
url  = "http://127.0.0.1:7801/mcp"
```

## YAGNI scope (deferred)

- Image upload tool (no use case yet on the sell path)
- IGM / refund / RSP tools (out of B3 scope)
- Per-bot auth on the MCP endpoint (loopback boundary; nullclaw runs on
  the same host)
- Multiple BPPs (Safiya is the only one wired today)
