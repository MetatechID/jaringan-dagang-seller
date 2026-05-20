# Operator Runbook — Jaringan Dagang / Beli Aman

Authoritative deployment + migration order for the ONDC + bot + CRM stack
across three repos and N Vercel projects. Generated 2026-05-20 after the
ONDC convergence + CRM + bot pipeline work. Reflects the **current `main`**
of each repo.

---

## Topology — what runs where

| Surface | URL | Project | Repo |
|---|---|---|---|
| Storefront (Safiya + chat UI) | https://safiya.beliaman.com | Vercel `beli-aman-storefronts` | jaringan-dagang-buyer / sites/partner-demos |
| Buyer BAP API (identity + Beckn) | https://api.beli-aman.metatech.id | Vercel `beli-aman-bap` | jaringan-dagang-buyer / apps/beli-aman-bap |
| Seller dashboard | https://jaringan-dagang-seller.metatech.id | Vercel `jaringan-dagang-seller` (the **dashboard** project) | jaringan-dagang-seller / seller-dashboard |
| Seller BPP API | https://jaringan-dagang-seller-api.metatech.id | Vercel `jaringan-dagang-seller` (the **api** project) | jaringan-dagang-seller / app |
| Network registry + gateway | (TBD per deploy) | — | jaringan-dagang-network |
| Bot VM (nullclaw + MCP + bridge) | https://bot.beliaman.com → 127.0.0.1:8088 | Nodehelix VM | jaringan-dagang-seller / services/{jd-sell-mcp,jd-bot-bridge} |

All Vercel projects share the same Firebase Auth project (`beli-aman-prod`).
All Postgres lives in Neon. Migration scripts in seller/buyer scripts/.

---

## Required env vars (per Vercel project)

### `beli-aman-storefronts` (storefront)
- `NEXT_PUBLIC_BAP_URL=https://api.beli-aman.metatech.id`
- `NEXT_PUBLIC_FIREBASE_*` — Firebase web SDK config (already set)
- **NEW (B5):** `BRIDGE_BASE_URL=https://bot.beliaman.com` — set AFTER VM is up.
- **NEW (B5):** `BRIDGE_INGEST_TOKEN=<random hex>` — same value as the VM env.
- (server-only, NOT `NEXT_PUBLIC_*`; the `/api/chat` proxy holds them)

### `beli-aman-bap` (BAP API)
- `DATABASE_URL` — Neon `beli_aman` DB
- `FIREBASE_PROJECT_ID`, `FIREBASE_SERVICE_ACCOUNT_JSON` — Firebase admin
- `REGISTRY_URL` — network registry public URL (when network is deployed)
- `GATEWAY_URL` — network gateway public URL
- `BECKN_SIGNING_PRIVATE_KEY` (base64) — BAP's Ed25519 signing key
- `subscriber_id=beli-aman.bap.jaringan-dagang.id` (canonical per A3)
- `subscriber_url=https://api.beli-aman.metatech.id/api/v1/beckn`
- **NEW (B3a):** `BOT_API_TOKEN=<random ≥32-byte hex>` — same value the bot VM uses.
- `BECKN_WORKERS_ENABLED=false` (Vercel serverless; auto-set in api/index.py)
- `SKIP_CREATE_ALL=true` (Vercel serverless; auto-set in api/index.py — closes prod hotfix #2 from 2026-05-20)

### `jaringan-dagang-seller` API project
- `DATABASE_URL` — Neon `seller_db` (or whatever the BPP uses)
- `FIREBASE_PROJECT_ID`, `FIREBASE_SERVICE_ACCOUNT_JSON`
- `REGISTRY_URL`, `GATEWAY_URL`
- `BPP_SUBSCRIBER_ID=bpp.jaringan-dagang.id` (canonical single-tenant fallback)
- `BPP_SUBSCRIBER_URL=https://jaringan-dagang-seller-api.metatech.id/beckn`
- `BECKN_DOMAIN=nic2004:52110` (base, the per-store ONDC resolver yields ONDC:RET11 for Safiya)
- `BECKN_CORE_VERSION=1.1.0`
- `BECKN_CITY_CODE=std:021`
- `BECKN_COUNTRY_CODE=IDN`
- `XENDIT_API_KEY` — Xendit production secret
- `XENDIT_CALLBACK_TOKEN` — Xendit webhook verification token
- `BITESHIP_API_KEY` — courier API
- **NEW (A4):** `CATALOG_SOURCE=json` (default; flip to `mirror-with-fallback` then `mirror` per phased rollout)
- **NEW (A4):** `BECKN_ORDER_FLOW=off` (default; flip to `shadow` then `on` per phased rollout)
- **NEW (A4):** `QUOTE_TOKEN_SECRET=<stable random>` — REQUIRED in prod or rolling deploys invalidate quote tokens

### `jaringan-dagang-seller` dashboard project
- `NEXT_PUBLIC_BPP_API_URL=https://jaringan-dagang-seller-api.metatech.id`
- `NEXT_PUBLIC_IDENTITY_BASE=https://api.beli-aman.metatech.id`
- `NEXT_PUBLIC_FIREBASE_*` — Firebase web SDK

### Bot VM `/etc/jd-bot/bridge.env` (chmod 0640 root:jd-bot)
- `DATABASE_URL` — same Neon URL as the seller API (CRM tables live there)
- `BRIDGE_INGEST_TOKEN` — same value Vercel storefront uses
- `BAP_BASE_URL=https://api.beli-aman.metatech.id`
- `BOT_API_TOKEN` — same value Vercel BAP uses
- `QWEN_BASE_URL` — vLLM endpoint (pandai's RunPod or new)
- `QWEN_API_KEY` — vLLM bearer
- `QWEN_MODEL_ID=qwen2.5-7b-instruct` (or whichever is loaded)
- `NULLCLAW_BIN=/usr/local/bin/nullclaw`

---

## Migration scripts — execute in THIS ORDER against live Neon

All are idempotent (`IF NOT EXISTS`) and dry-run-by-default. Each requires
`DATABASE_URL` env + `--apply` flag. Run from the repo root.

1. **A3 canonical subscriber_id** — migrates 3 legacy `bpp.*.local` store IDs:
   ```sh
   cd ~/Code/jaringan-dagang-seller
   DATABASE_URL=postgresql+asyncpg://<seller-neon> \
     python scripts/migrate-subscriber-ids.py --apply
   ```

2. **A7 catalog image base** — adds `stores.image_base_url` + backfills Safiya:
   ```sh
   cd ~/Code/jaringan-dagang-seller
   DATABASE_URL=postgresql+asyncpg://<seller-neon> \
     python scripts/add-image-base-url-column.py --apply
   ```

3. **A7 image URL migration** — rewrites legacy absolute → relative:
   ```sh
   cd ~/Code/jaringan-dagang-seller
   DATABASE_URL=postgresql+asyncpg://<seller-neon> \
     python scripts/migrate-image-urls.py --apply
   # Optional: also drop the SAF-SYNC test artifact:
   DATABASE_URL=... python scripts/migrate-image-urls.py --apply --prune-test-artifacts
   ```

4. **A4 mirror tables (buyer)** — creates `mirror_*` tables on the BAP DB:
   ```sh
   cd ~/Code/jaringan-dagang-buyer
   DATABASE_URL=postgresql+asyncpg://<bap-neon> \
     python apps/beli-aman-bap/scripts/add-mirror-tables.py --apply
   ```

5. **A4 payment invoice URL** — adds `payments.xendit_invoice_url` on seller:
   ```sh
   cd ~/Code/jaringan-dagang-seller
   DATABASE_URL=postgresql+asyncpg://<seller-neon> \
     python scripts/add-payment-invoice-url-column.py --apply
   ```

6. **C1 CRM tables** — creates `contacts`, `inboxes`, `conversations`, `messages`, `labels`, `conversation_labels`:
   ```sh
   cd ~/Code/jaringan-dagang-seller
   DATABASE_URL=postgresql+asyncpg://<seller-neon> \
     python scripts/add-crm-tables.py --apply
   ```

7. **C4 pending-queue index** — composite index for bridge polling perf:
   ```sh
   cd ~/Code/jaringan-dagang-seller
   DATABASE_URL=postgresql+asyncpg://<seller-neon> \
     python scripts/add-crm-pending-message-index.py --apply
   ```

8. **B3a bot REST tables** — `bot_search_sessions`, `bot_carts`:
   ```sh
   cd ~/Code/jaringan-dagang-buyer
   DATABASE_URL=postgresql+asyncpg://<bap-neon> \
     python apps/beli-aman-bap/scripts/add-bot-rest-tables.py --apply
   ```

After all 8, redeploy each Vercel project so the lifespan reconciliation
hooks (`stores.image_base_url`, `payments.xendit_invoice_url`) catch the
column adds idempotently. The defensive lifespan-time `ALTER ... IF NOT
EXISTS` will run regardless, so the order above is robustness, not
correctness.

---

## Subscriber-registry seeding

After (1) above:
```sh
cd ~/Code/jaringan-dagang-network
# Ensure the network registry is reachable at REGISTRY_URL
python scripts/register-subscribers.py
# Idempotent — 400 "already registered" is treated as success.
```

This populates the network registry with all canonical `*.jaringan-dagang.id`
subscribers (BAP + 6 BPPs + 1 fallback). Required before /search calls work
through the gateway.

---

## VM (B1) — bot pipeline deployment

After scripts (1-7) above, provision the bot VM at
https://nodehelix.metatech.id/dashboard/nodelight (4c/8GB Linux).

```sh
# 1. Base
useradd -r -s /bin/false jd-bot
mkdir -p /opt/jd-bot /var/lib/jd-bot /var/lib/jd-bot-bridge /etc/jd-bot
chown jd-bot:jd-bot /opt/jd-bot /var/lib/jd-bot /var/lib/jd-bot-bridge
chmod 0750 /etc/jd-bot

# 2. nullclaw binary (B2)
curl -L -o /usr/local/bin/nullclaw https://github.com/nullclaw/nullclaw/releases/download/2026.5.4/nullclaw-linux-amd64
chmod +x /usr/local/bin/nullclaw

# 3. Python deps
apt-get install -y python3.11 python3.11-venv python3-pip postgresql-client jq util-linux
python3 -m venv /opt/jd-bot/venv
/opt/jd-bot/venv/bin/pip install psycopg2-binary fastapi httpx uvicorn pydantic

# 4. Caddy
apt-get install -y caddy
# Drop the caddyfile.snippet from services/jd-bot-bridge/caddyfile.snippet
# into /etc/caddy/Caddyfile, replace cert email.

# 5. Code
git clone https://github.com/MetatechID/jaringan-dagang-seller.git /opt/jd-bot/repo
cd /opt/jd-bot/repo
cp services/jd-bot-bridge/persona.md /opt/jd-bot/
cp services/jd-bot-bridge/bridge.sh services/jd-bot-bridge/bridge_http.py /opt/jd-bot/
chmod +x /opt/jd-bot/bridge.sh

# 6. Nullclaw config
sudo -u jd-bot mkdir -p /home/jd-bot/.nullclaw
envsubst < services/jd-bot-bridge/nullclaw-config.json \
  > /home/jd-bot/.nullclaw/config.json
chown -R jd-bot:jd-bot /home/jd-bot/.nullclaw
chmod 0600 /home/jd-bot/.nullclaw/config.json

# 7. MCP server
cp -r services/jd-sell-mcp /opt/jd-bot/jd-sell-mcp
cd /opt/jd-bot/jd-sell-mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 8. Env file
cat > /etc/jd-bot/bridge.env <<EOF
DATABASE_URL=postgresql://<seller-neon-pooled>
BRIDGE_INGEST_TOKEN=<random-hex>     # mirror to Vercel storefront
BAP_BASE_URL=https://api.beli-aman.metatech.id
BOT_API_TOKEN=<same-as-vercel-bap>
QWEN_BASE_URL=https://<runpod-host>/v1
QWEN_API_KEY=<vllm-bearer>
QWEN_MODEL_ID=qwen2.5-7b-instruct
NULLCLAW_BIN=/usr/local/bin/nullclaw
EOF
chmod 0640 /etc/jd-bot/bridge.env
chown root:jd-bot /etc/jd-bot/bridge.env

# 9. systemd
cp services/jd-bot-bridge/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jd-bot-nullclaw jd-bot-bridge-http jd-bot-bridge-worker

# 10. DNS
# Point bot.beliaman.com A record to the VM's public IP, then:
caddy reload

# 11. Verify
curl https://bot.beliaman.com/health
# → {"ok":true,"service":"jd-bot-bridge"}

# 12. Inbox provisioning (one-time per opted-in store)
psql $DATABASE_URL <<SQL
INSERT INTO inboxes (id, store_id, name, channel, created_at, updated_at)
SELECT gen_random_uuid(), s.id, s.name || ' Website', 'website', NOW(), NOW()
FROM stores s
WHERE s.subscriber_id = 'safiyafood.jaringan-dagang.id'
ON CONFLICT DO NOTHING;
SQL

# 13. Vercel storefront wiring
# On beli-aman-storefronts Vercel project, set:
#   BRIDGE_BASE_URL=https://bot.beliaman.com
#   BRIDGE_INGEST_TOKEN=<same as VM>
# Redeploy.

# 14. End-to-end test
# Open https://safiya.beliaman.com/safiyafood/chat
# Type: "ada kurma sukari?"
# Wait ~20-60s (Qwen latency)
# Bot should reply with product card markdown via MCP
# Observe in https://jaringan-dagang-seller.metatech.id/conversations (super-admin)
```

---

## Rollout phases (after VM is up)

Phase 1 — Catalog read source (per A4 spec § 9):
1. Run scripts (1-7) above.
2. Deploy buyer BAP. Verify mirror tables populated via /search → /on_search push from seller.
3. Flip seller dashboard env: `CATALOG_SOURCE=mirror-with-fallback`. Observe 24h.
4. Flip to `CATALOG_SOURCE=mirror`. Delete `apps/beli-aman-bap/catalog/*.json` once happy.

Phase 2 — Beckn order flow:
1. Flip both seller AND BAP env: `BECKN_ORDER_FLOW=shadow`. The legacy `seller_bridge` remains authoritative; the Beckn `/confirm` path runs in parallel and is logged in `beckn_outbound_log`.
2. Run `scripts/diff-bridge-vs-beckn.py` (TBD) daily; observe 7 clean days.
3. Flip to `BECKN_ORDER_FLOW=on`. Legacy bridge endpoint 410s.
4. After 2 weeks on `on`: delete `apps/beli-aman-bap/services/seller_bridge.py` + drop the flag.

Phase 3 — Bot live:
1. Storefront chat at `/chat` already deployed (B5). Once `BRIDGE_BASE_URL` is set on Vercel, /api/chat resolves correctly.
2. Bot replies appear within ~20-60s (Qwen latency on RunPod).
3. CRM dashboard at /conversations observes; agents can take over via the C2 "Take over" endpoint.

Phase 4 — Pruning & cleanup:
1. Drop SAF-SYNC test artifact: `migrate-image-urls.py --apply --prune-test-artifacts`.
2. Run subscriber-id migration if any legacy `bpp.*.local` rows persist.

---

## Schema drift remaining (not blocking)

- `order_events.order_id` is `VARCHAR(36)` in the model but live `orders.id` is `UUID`. `create_all` would fail on it; today `SKIP_CREATE_ALL=true` on Vercel sidesteps. Fix later: change `OrderEvent.order_id` mapped_column to `UUID` type to match live.

---

## Known unfinished work

- **A5 (IGM)** — Issue & Grievance Management Beckn-protocol module. Schema scaffolding partially exists (`Dispute.bpp_refund_request_id`, `Order.escrow_status`); /issue + /on_issue endpoints + refund-completion wiring deferred.
- **A6 (RSP + Score)** — settlement reconciliation + reputation. Largest deferred. Required for full ONDC compliance long-term.
- **B6 (WhatsApp)** — channel adapter that writes inbound WA into the CRM `messages` table. Bridge code is channel-blind so only the WA-inbound writer is needed.
- **Customer-facing /orders page** — currently 404s on storefront. Separate gap.
- **Monorepo consolidation** — three-repo chaos directly caused 3 prod outages today. Migrate to one workspace after B1/B4/B6 stabilize.

---

## Today's prod hotfixes (2026-05-20)

For posterity:

1. `5214645` — added `firebase-admin` to root `requirements.txt` (Vercel installs from root, not BAP-local).
2. `1303f0f` — re-vendored buyer beckn_protocol (parallel fix).
3. `fa155aa` — `SKIP_CREATE_ALL=true` in serverless to dodge schema-drift traceback on every cold start.
4. `ff042aa` — seller lifespan idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for recently-added columns (Store.image_base_url, Payment.xendit_invoice_url).
