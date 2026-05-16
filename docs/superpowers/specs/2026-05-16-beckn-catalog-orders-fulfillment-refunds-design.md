# Jaringan Dagang: Beckn-Native Catalog, Orders, Fulfillment & Refunds

**Date**: 2026-05-16
**Status**: Spec — pending implementation plan
**Scope**: Cross-repo (`jaringan-dagang-buyer`, `jaringan-dagang-network`, `jaringan-dagang-seller`)
**Protocol**: Beckn (Ed25519-signed envelopes, registry-mediated trust). Network is an Indonesian Beckn instance ("ION") to be — no external network spec to conform to yet.

---

## 1. Goal

Make the seller dashboard the system-of-record for every toko's catalog, orders, fulfillment, payments, and refunds. Retire the JSON product files in `jaringan-dagang-buyer`. Wire all cross-app data flow through signed Beckn HTTP so each app keeps its own Postgres and stays correctly synced.

**Concretely, after this work:**
- Buyer storefront pages for `safiyafood`, `antarestar`, `gendes`, `yourbrand` render from seller's Postgres via a cryptographically-verified mirror in buyer's Postgres — not from JSON on disk.
- Purchases flow `/select` → `/init` → `/confirm` (Beckn) with race-safe inventory decrement at seller. The `seller_bridge` HTTP shortcut is retired.
- Live delivery status flows Biteship → seller → `/on_status` → buyer's order page.
- Refunds flow buyer dispute → seller approve/deny → Xendit refund → escrow release, with finality on Xendit's settled webhook.

## 2. Non-goals

- Multi-courier support beyond Biteship.
- Non-Xendit payment providers.
- Buyer-side dispute chat / messaging (status changes only).
- Cross-BPP search aggregation (only one BPP service today).
- Joining any external open-commerce network (ION doesn't exist yet; design is ION-ready).

## 3. System topology

```
┌────────────────────────────┐      ┌──────────────────────────────┐
│  jaringan-dagang-buyer     │      │   jaringan-dagang-network    │
│  Beli Aman BAP             │      │   Registry + Gateway         │
│  Postgres: beli_aman       │◄────►│   Postgres: jaringan_dagang  │
│  (profiles, addresses,     │ regi │   (subscribers + pubkeys)    │
│   orders, escrow ledger,   │ stry │                              │
│   disputes,                │ look │   No catalog. No orders.     │
│   CATALOG MIRROR)          │ ups  │   Stateless router otherwise.│
└────────┬───────────────────┘      └────────────▲─────────────────┘
         │                                       │
         │  Signed Beckn HTTP (Ed25519)          │ registry lookup
         ▼                                       │ for pubkey
┌──────────────────────────────────────┐         │
│  jaringan-dagang-seller (BPP)        │─────────┘
│  Postgres: seller_db                 │
│  Stores, Products, SKUs, Orders,     │  ◄── SYSTEM OF RECORD for
│  Fulfillment, Payment, Disputes,     │      catalog, orders,
│  RefundRequest (new)                 │      fulfillment, refunds
└──────────────────────────────────────┘
```

**Ownership rules** (enforced by code review + integration tests):
1. Seller DB is the only writer to product/SKU/inventory and the only writer to its own Order/Fulfillment/Payment/RefundRequest rows.
2. Buyer DB owns buyer-side state (profiles, addresses, escrow ledger, disputes) and a **read-only catalog mirror** that is hint-only — never authoritative.
3. Network DB owns only subscribers + public keys (unchanged from today).
4. No DB ever talks to another DB directly. All cross-app data flow goes over signed Beckn HTTP.

## 4. Architecture: cross-cutting Beckn infrastructure

Without this, nothing else is verifiable. Build first.

### 4.1 Shared package `packages/beckn-protocol`

Promote from optional dep (today: `apps/beli-aman-bap/main.py:29` conditional import) to required dep in buyer + seller. Add:

| Function | Purpose |
|---|---|
| `sign_request(body: bytes, private_key) -> str` | Ed25519 over canonical JSON; returns `Authorization` header value per Beckn spec |
| `verify_request(headers, raw_body, public_key) -> bool` | Verifies signature, rejects if `created < now - 300s`, rejects replayed nonce |
| `envelope(action, bap_id, bpp_id, transaction_id, message_id, payload) -> dict` | Builds `context` block |
| `RegistryClient(registry_url)` | `lookup_pubkey(subscriber_id) -> bytes`; Redis-cached TTL 1h; invalidated on registry change event |
| `canonical_json(obj) -> bytes` | Deterministic JSON serialization for signing |

### 4.2 Per-app Beckn middleware

**Inbound** (both buyer's `/api/v1/beckn/*` and seller's `/beckn/*`):
- Run `verify_signature_middleware` first. 401 on failure.
- Dedupe: every Beckn envelope's `message_id` recorded in `beckn_inbound_log(message_id, received_at, response_body, status_code)` per app. Replays return cached response, do not re-execute.

**Outbound**: all Beckn POSTs go through `sign_and_send(envelope, target_url)`:
- Signs with this app's private key.
- Retries on 5xx: 3 attempts, exponential backoff (1s, 4s, 16s).
- Records every attempt in `beckn_outbound_log(message_id, target, attempt, status_code, sent_at, response_body)`.
- Failed deliveries surface in seller dashboard's `/admin/beckn-outbox` view.

### 4.3 Key management

- Each app loads its Ed25519 private key from env `BECKN_SIGNING_PRIVATE_KEY` or mounted secret file.
- Public key derived; on startup if registry has no record or mismatch, app self-registers/updates via `POST /subscribe`.
- Dev keypairs committed under `dev/keys/` in each repo, clearly labeled "NOT FOR PROD." All three apps boot signed-and-verified out of the box on `make dev`.

### 4.4 Network registry — data prep

Today: Safiya Food registered as BPP (commit `6387431`); Beli Aman as BAP (`d459928`).

Add: `Antarestar`, `Gendes`, `YourBrand` as BPP subscribers, each with their own pubkey (each toko gets its own keypair, even though they share the seller service today — keeps multi-tenant boundary clean for the future when stores might be sharded).

Implementation: `scripts/register-subscribers.py` in the network repo, idempotent, can rerun safely. Reads from a `subscribers.yaml` config (subscriber_id, type, domain, city, url, pubkey path).

## 5. Catalog migration (drop JSON → seller = source)

### 5.1 Schema

**Seller** (no changes; tables exist):
- `Store`, `Product`, `SKU`, `SKUImage`, `ProductImage` per current models in `app/models/`.

**Buyer** (new mirror tables in `beli_aman` DB; Alembic migration):
- `mirror_stores(id, bpp_id, slug, name, logo_url, domain, city, last_pushed_at, last_pulled_at, catalog_version)`
- `mirror_products(id, store_id FK, name, sku, status, attributes JSONB, last_synced_at)`
- `mirror_skus(id, product_id FK, variant_name, variant_value, sku_code, price, original_price, stock, weight_grams, last_synced_at)`
- `mirror_sku_images(id, sku_id FK, url, position, is_primary)`
- `mirror_product_images(id, product_id FK, url, position, is_primary)`

`last_synced_at` per row enables out-of-order push reconciliation: incoming push with older timestamp is ignored.

### 5.2 Backfill

Generalize existing `scripts/seed-safiyafood.py` (which already loads from sibling buyer JSON) into:

```
scripts/seed-from-buyer-catalog.py [--slug SLUG | --all]
```

- Idempotent: UPSERT on `(store_id, sku_code)`.
- Run once per toko after subscribers are registered.
- After all four run, seller's Postgres has 4 stores × ~15-20 products each as the source of truth.

### 5.3 Storefront cutover

Today: `apps/beli-aman-bap/routers/brands.py:45` → `catalog_service.list_products(slug)` → reads JSON.

Change: `catalog_service` reads from `mirror_*` tables. Same response shape — `brands.py` route handler unchanged.

Fallback during rollout: env `CATALOG_SOURCE=json|mirror|mirror-with-json-fallback`. Cutover sequence:
1. Deploy with `CATALOG_SOURCE=json` (no behavior change).
2. Seed mirrors via push + initial pull. Verify counts.
3. Flip to `mirror-with-json-fallback`. Observe for 24h.
4. Flip to `mirror`. Delete JSON files (`apps/beli-aman-bap/catalog/*.json`). Remove the env var.

### 5.4 Refresh paths (push + pull + revalidate)

**Push (primary)** — seller emits `/on_search` after every product write:
- Hook in seller's `app/api/products.py` `POST/PUT/DELETE`: after commit, build a delta `/on_search` envelope (`{added: [...], updated: [...], removed: [...]}`) and `sign_and_send` to every subscribed BAP. Initially: one BAP (Beli Aman). Architecture allows N.
- Buyer's `POST /api/v1/beckn/on_search` handler signature-verifies, dedupes on `message_id`, applies delta to mirror.

**Pull (safety net)** — buyer worker every 5 min:
- For each store in `mirror_stores`, `sign_and_send` a Beckn `/search` to seller.
- Seller's existing `/beckn/search` returns full catalog as `/on_search` callback.
- Buyer reconciles: compares server response vs mirror, upserts diffs, marks `last_pulled_at`.

**Checkout revalidation (strong consistency)** — at `/select` (add to cart) and `/init` (begin checkout), buyer sends a synchronous Beckn round-trip with only the cart SKUs. Seller returns live price + stock. Any mismatch → buyer rejects with user-visible error.

### 5.5 Performance budget

- Storefront pageview: <50ms p95 (mirror = Postgres index lookup).
- Catalog edit → buyer mirror: <1s p95 via push; ≤5min worst case via pull fallback.
- Beckn signature verify: <5ms (Ed25519 is fast; pubkey cached).

## 6. Order placement via Beckn (replaces `seller_bridge`)

### 6.1 Mapping buyer states to Beckn actions

Buyer's existing order state machine (`apps/beli-aman-bap/models/order.py`) is preserved. Each transition that crosses the network gets a Beckn call.

| Buyer state | Beckn action | Behavior |
|---|---|---|
| (add to cart) | `POST /select` → `/on_select` | Seller re-prices cart, confirms stock, returns Biteship shipping options |
| `PRE_AUTH` | (local) | Buyer creates Order row, items snapshot |
| `AUTHED` | `POST /init` → `/on_init` | Buyer attaches address + chosen shipping; seller locks a 10-min price quote (`quote_token`) |
| `CART_REVIEWED` | (local) | Final review screen |
| `ESCROW_HELD` | `POST /confirm` → `/on_confirm` | Xendit invoice paid → buyer sends `payment_proof` + `quote_token` → seller runs inventory txn (see 6.2) → creates Order row → returns canonical `bpp_order_id` |
| (on auto-release D+3 or buyer confirms receipt) | `POST /update {status: COMPLETED}` → `/on_update` | |
| `ESCROW_RELEASED` | (local) | |

### 6.2 Race-safe inventory at `/confirm` (seller side)

```python
async with db.begin():
    skus = await db.scalars(
        select(SKU)
        .where(SKU.id.in_(sku_ids))
        .with_for_update()                         # row locks
    )
    sku_by_id = {s.id: s for s in skus}
    for item in items:
        s = sku_by_id[item.sku_id]
        if s.stock < item.qty:
            raise OutOfStock(sku_id=s.id, available=s.stock)
        s.stock -= item.qty
    order = Order(store_id=..., status="CREATED",
                  bap_id=ctx.bap_id, beckn_order_id=...,
                  items=items_snapshot, ...)
    db.add(order)
# commit on context exit
return on_confirm_ok(bpp_order_id=order.id)
```

Postgres row locks (`FOR UPDATE`) prevent double-decrement under concurrent `/confirm`. On `OutOfStock`, return `/on_confirm` with `ack=False, error=OUT_OF_STOCK`; buyer flips order to `PRE_AUTH_FAILED`, refunds escrow, surfaces to user.

After successful commit, seller pushes a delta `/on_search` to update buyer mirror stock.

### 6.3 Idempotency

Every `/confirm` carries `(bap_id, transaction_id, message_id)`. Seller's inbound dedupe (§4.2) ensures a retried `/confirm` does not double-decrement; it returns the cached `/on_confirm` from the first attempt.

### 6.4 Retiring `seller_bridge`

Feature flag `BECKN_ORDER_FLOW`:
- `off` (default today) — buyer uses `seller_bridge` only.
- `shadow` — buyer sends both `/confirm` AND `seller_bridge` POST. Bridge result is authoritative. Daily diff report (`scripts/diff-bridge-vs-beckn.py`) compares outcomes; tolerated for ~1 week.
- `on` — buyer sends `/confirm` only; bridge endpoint at `app/api/escrow_orders.py` returns 410 Gone.
- After 2 weeks on `on`: delete `apps/beli-aman-bap/services/seller_bridge.py` + the `/api/internal/escrow-orders` route, drop the flag.

## 7. Delivery status pipe (Biteship → seller → buyer)

### 7.1 Seller side

- New route `POST /webhooks/biteship` in seller:
  - Verify Biteship HMAC signature.
  - Idempotency-keyed on Biteship's `event_id`.
  - Update matching `FulfillmentRecord` (`awb_number`, `status`, `tracking_url`, `last_event_at`).
- On status change, enqueue `BecknStatusEmit(order_id)` job:
  - Build `/on_status` envelope with the updated fulfillment fragment.
  - `sign_and_send` to `Order.bap_id` (resolve URL via `RegistryClient`).

### 7.2 Buyer side

- New route `POST /api/v1/beckn/on_status`:
  - Signature-verify + dedupe.
  - Look up `Order` by `bpp_order_id`. Update new columns `Order.fulfillment_status`, `Order.tracking_url`, `Order.fulfillment_last_event_at` (Alembic migration).
  - Emit SSE on `order:{id}:fulfillment` channel so the open buyer order page updates live.

### 7.3 Polling fallback

Buyer worker every 30 min: for any order whose `fulfillment_status NOT IN (DELIVERED, RETURNED, CANCELLED)`, send Beckn `/status`. Seller replies via `/on_status` per normal path.

### 7.4 Schema changes

Buyer DB additions:
- `Order.fulfillment_status` enum (mirrors seller's `FulfillmentRecord.status`: `PENDING|PICKED_UP|IN_TRANSIT|DELIVERED|RETURNED|CANCELLED`)
- `Order.tracking_url`
- `Order.fulfillment_last_event_at`

Seller DB: no new columns. Use existing `FulfillmentRecord`.

## 8. Refund workflow

### 8.1 Schema

**Seller — new table `RefundRequest`:**
- `id` (UUID), `order_id` (FK to Order), `requested_by` (`buyer|seller`), `reason_code` (enum: `ITEM_NOT_RECEIVED|ITEM_DAMAGED|WRONG_ITEM|CHANGED_MIND|OTHER`), `reason_text`, `requested_amount`, `status` (enum: `PENDING|APPROVED|DENIED|REFUNDED|FAILED`), `seller_note`, `decided_at`, `decided_by`, `xendit_refund_id`, `created_at`, `updated_at`.
- Partial unique index: `WHERE status IN ('PENDING', 'APPROVED')` on `order_id` — only one open request per order.

**Buyer — extend existing `Dispute`** (`apps/beli-aman-bap/models/`):
- Add `bpp_refund_request_id` to correlate buyer dispute ↔ seller RefundRequest.
- Add `status` extension if needed: `REQUESTED|APPROVED|DENIED|REFUND_PENDING|REFUNDED|REFUND_FAILED`.

### 8.2 Flow

```
1. Buyer order page → "Request refund" button (enabled only if
   escrow_status=HELD, not RELEASED, no open Dispute).
2. Buyer creates Dispute → sends Beckn /update with
   message.order.fulfillment_state.descriptor.code = "refund_request"
   and message.order.items = [refund items] + reason.
3. Seller /update handler:
   - Verify sig, dedupe.
   - Resolve Order by beckn_order_id.
   - Create RefundRequest(status=PENDING).
   - Return /on_update with bpp_refund_request_id.
4. Seller dashboard /orders/[id]/refunds shows PENDING requests.
   "Refund pending" filter chip in /orders list (badge with count).
5a. Seller clicks Approve:
    - DB transaction:
        - RefundRequest.status = APPROVED
        - Call Xendit refund API → xendit_refund_id
        - Order.escrow_status = REFUNDED
        - PaymentRecord.status = REFUNDED
    - Emit /on_update {status: REFUND_APPROVED, xendit_refund_id} to buyer.
5b. Seller clicks Deny:
    - RefundRequest.status = DENIED, seller_note saved.
    - Emit /on_update {status: REFUND_DENIED, seller_note}.
6. Buyer /on_update handler updates Dispute.status, flips
   escrow ledger entry, shows result on order page.
7. Xendit refund-settled webhook hits seller:
   - RefundRequest.status = REFUNDED (final).
   - Emit final /on_update {status: REFUNDED} to buyer for finality.
8. If Xendit refund fails:
   - RefundRequest.status = FAILED, error captured.
   - Surfaced in seller dashboard with "Retry refund" button.
   - Order/escrow not flipped until Xendit confirms.
```

### 8.3 Dashboard UI additions

**Seller:**
- New `/orders` filter chip: "Refund pending" (badge w/ count in nav).
- New tab on `/orders/[id]`: "Refunds" — lists RefundRequest history; PENDING ones have Approve/Deny actions with note field.
- Existing escrow panel gets a "Refund history" row.
- New `/admin/beckn-outbox` view (also serves §4.2): stuck-message retry UI.

**Buyer:**
- Order detail page: "Request refund" button + reason selector + amount picker (default = full).
- `DisputeBanner` component shows status of any open/closed refund request.

### 8.4 Failure modes

- Xendit refund fails after APPROVED → RefundRequest left in `APPROVED` w/ `xendit_refund_id=null` and error logged, "Retry" button in dashboard. Order/escrow not flipped.
- Buyer sends `/update` while order already REFUNDED → seller returns idempotent `/on_update` with current state.
- Auto-expire policy: dispute auto-approves if seller doesn't decide in 7 days. **Off by default**, configurable per-store. Out of scope for v1 to actually enable; schema supports it.

## 9. Migration & rollout

Phased. Each phase independently shippable and reversible via feature flag.

| Phase | Scope | Flag | Rollback |
|---|---|---|---|
| **1: Foundations** | Promote `beckn-protocol` package; inbound/outbound logs + middleware in log-only mode; register all 4 BPPs in registry. | n/a | revert migrations + middleware import |
| **2: Catalog one-way** | Run seeder for all 4 tokos; mirror tables + push/pull/handlers; flip storefront read source. | `CATALOG_SOURCE=json\|mirror-with-fallback\|mirror` | env flip back to `json` |
| **3: Orders via Beckn** | `/select`+`/init`+`/confirm` round-trips + inventory txn + shadow mode. | `BECKN_ORDER_FLOW=off\|shadow\|on` | env flip back to `off` |
| **4: Delivery pipe** | Biteship webhook + `/on_status` + buyer SSE + polling fallback. | `FULFILLMENT_PIPE=off\|on` | env flip back to `off` |
| **5: Refunds** | RefundRequest table + UI on both sides + Xendit refund + `/update`/`/on_update`. | `REFUND_FLOW=off\|on` | env flip back to `off` |

Phase 3 specifically runs in `shadow` for ~1 week with daily diff reports before flipping `on`. Phase 5 has no shadow mode (no legacy path to compare against).

## 10. Testing strategy

### 10.1 Unit (per app)

- Beckn helpers: signature roundtrip, replay rejection (>300s old), idempotency dedupe, canonical JSON byte-stable across runs.
- Seller inventory txn: pytest-asyncio with two concurrent `/confirm` tasks racing for the last unit — assert exactly one ACKs, one NACKs.
- Refund state machine: every valid transition + every illegal transition rejected.

### 10.2 Integration (per app, real Postgres)

- Buyer `/on_search`: signed payload → mirror updated; bad sig → 401, mirror untouched.
- Seller `/confirm`: valid quote_token → order + decrement; expired token → NACK; stale signature → 401; replay returns cached response.
- Seller Biteship webhook → FulfillmentRecord update + `/on_status` enqueued (mock outbound).

### 10.3 End-to-end (all 3 apps + dependencies)

Top-level `e2e/` dir with `docker-compose.e2e.yml`: boots network + seller + buyer + their 3 Postgres + Redis + Xendit/Biteship sandboxes (or stubs).

Scenarios:
1. Product edit on seller → visible on buyer storefront within 2s (push) or 5min (pull).
2. Buyer places order end-to-end → seller order created, stock decremented, buyer escrow held, both order pages consistent.
3. Two buyers race for last unit → one wins, one gets OUT_OF_STOCK UX.
4. Biteship marks `delivered` → buyer order page shows `DELIVERED` within 5s.
5. Buyer requests refund → seller approves → Xendit refund mocked → buyer dispute closed.
6. Beckn message replay (resend a `/confirm`) → no double-decrement.
7. Bad signature → 401, no state change.

Run on CI for PRs that touch the Beckn package or any of the affected routes in any repo.

### 10.4 Manual demo checklists

One Markdown checklist per phase in `docs/superpowers/specs/checklists/<phase>.md`. Walked through pre-launch by a human.

## 11. Open risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Full `/on_search` payload size if catalog grows. | Push deltas only (`{added,updated,removed}`); reserve full dumps for pull. |
| 2 | Clock skew breaks 5-min signature freshness window. | NTP on all hosts; log skew on every inbound verify; alert if drift >60s. |
| 3 | Seller's 10-min `/on_init` quote vs Xendit's ~24h invoice TTL. | Buyer refreshes quote (re-`/init`) right before showing pay button. |
| 4 | Mirror drift over time even with push+pull. | Weekly reconciler job: full `/search` + row-by-row diff + alert on mismatch. |
| 5 | Slug vs UUID vs subscriber_id ambiguity. | Mirror_stores keeps all three: `bpp_id` (subscriber_id), `slug` (URL-friendly), `id` (UUID local PK). |
| 6 | Dual-write window in Phase 3 shadow mode could see drift if bridge succeeds and Beckn fails (or vice versa). | Daily diff report flags mismatches; do not flip `on` until 7 consecutive clean days. |
| 7 | Xendit refund webhook lost. | Reconciler job polls Xendit refund status for any RefundRequest in `APPROVED` state >24h. |

## 12. Files touched (approximate)

**network** (~3 files, 1 script):
- `scripts/register-subscribers.py` (new)
- `subscribers.yaml` (new config)

**seller** (~25 files):
- `app/beckn/middleware.py` (new) — sig verify
- `app/beckn/outbound.py` (new) — sign_and_send + retry
- `app/models/beckn_log.py` (new) — inbound/outbound logs
- `app/models/refund.py` (new) — RefundRequest
- `app/api/products.py` — emit `/on_search` on writes
- `app/api/escrow_orders.py` — deprecate (Phase 3)
- `app/beckn/endpoints.py` — implement select/init/confirm/update bodies; idempotency
- `app/api/webhooks/biteship.py` (new) — webhook handler + status emit
- `app/api/refunds.py` (new) — seller refund actions
- `app/services/refund_service.py` (new) — Xendit refund + transitions
- `seller-dashboard/app/orders/[id]/refunds/page.tsx` (new)
- `seller-dashboard/app/orders/page.tsx` — "Refund pending" filter
- `seller-dashboard/app/admin/beckn-outbox/page.tsx` (new)
- `alembic/versions/*` — new tables
- `scripts/seed-from-buyer-catalog.py` (new, generalized from `seed-safiyafood.py`)

**buyer** (~20 files):
- `apps/beli-aman-bap/beckn/middleware.py` (new)
- `apps/beli-aman-bap/beckn/outbound.py` (new)
- `apps/beli-aman-bap/models/mirror.py` (new)
- `apps/beli-aman-bap/models/beckn_log.py` (new)
- `apps/beli-aman-bap/routers/beckn.py` (new) — on_search, on_select, on_init, on_confirm, on_status, on_update
- `apps/beli-aman-bap/routers/brands.py` — switch to mirror reads
- `apps/beli-aman-bap/services/catalog.py` — read from mirror
- `apps/beli-aman-bap/services/seller_bridge.py` — deprecate (Phase 3)
- `apps/beli-aman-bap/services/order_flow.py` (new) — Beckn select/init/confirm orchestration
- `apps/beli-aman-bap/workers/catalog_puller.py` (new) — 5-min `/search` worker
- `apps/beli-aman-bap/workers/status_poller.py` (new) — 30-min `/status` worker
- `sites/partner-demos/app/[brand]/orders/[id]/page.tsx` — DisputeBanner, request-refund button, SSE for live status
- `alembic/versions/*` — mirror_* tables, Order.fulfillment_status, Dispute.bpp_refund_request_id

**shared** (`packages/beckn-protocol`):
- Sign/verify/envelope/RegistryClient helpers; canonical JSON; types for select/init/confirm/status/update message shapes.

## 13. Definition of done

- All four tokos render in buyer storefront from mirror, JSON files deleted.
- A new product added in seller dashboard appears on buyer storefront in <5s.
- An end-to-end purchase decrements stock atomically at seller; concurrent races produce exactly one winner.
- A Biteship status change is visible on the buyer order page within 5s.
- A buyer-initiated refund completes through Xendit and shows REFUNDED on both sides.
- `seller_bridge` code path deleted.
- All e2e scenarios in §10.3 green on CI.
