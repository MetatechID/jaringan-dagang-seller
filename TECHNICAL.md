# Jaringan Dagang — Technical Architecture (Seller / BPP)

> The canonical whole-system doc lives in `jaringan-dagang-network/TECHNICAL.md`.
> The "System Overview", "Beckn Protocol", "Identity & ACL", and "Production
> Databases" sections below are mirrored across all three repos — keep them in
> sync. Everything under "This Repo" is seller-specific.

## System Overview

Jaringan Dagang is an Indonesian open-commerce network built on the **Beckn
protocol**. Three independently-deployed apps, one shared Firebase identity,
one Neon Postgres project (two logical databases).

```
                         Firebase project: beli-aman-prod
                          (one Google sign-in for everyone)
                                       │
        ┌──────────────────────────────┼───────────────────────────────┐
        ▼                              ▼                               ▼
┌───────────────────┐   signed   ┌───────────────────┐         ┌───────────────────┐
│ jaringan-dagang-  │   Beckn    │ jaringan-dagang-  │ registry│ jaringan-dagang-  │
│      buyer        │◀──HTTP────▶│   seller (HERE)   │◀──lookup│     network       │
│  "Beli Aman" BAP  │  Ed25519   │   BPP / catalog   │         │ registry+gateway  │
│ • storefronts     │            │ • seller dashboard│         │ • subscriber dir  │
│ • Vibe admin      │            │ • Beckn /search…  │         │ • Beckn gateway   │
│ • IDENTITY PROVIDER            │ • orders/refunds  │         │   search multicast│
│   (profiles+ACL)  │            │ • catalog source  │         │                   │
└─────────┬─────────┘            └─────────┬─────────┘         └─────────┬─────────┘
          │                                │                             │
          ▼ Neon db `beli_aman`            ▼ Neon db `neondb`            ▼ Neon (own)
     identity, ACL, escrow,           stores, products, skus,       subscribers
     disputes, mirror catalog         orders, refunds, beckn logs
          └──────────── one Neon project: ep-shy-heart-a1atpe0m (ap-southeast-1) ─┘
```

| App | Repo | Prod URLs | Vercel project |
|---|---|---|---|
| Buyer / BAP / **IdP** | `jaringan-dagang-buyer` | storefronts `*.beliaman.com`, `beli-aman.metatech.id`; API `api.beli-aman.metatech.id` | `beli-aman-bap`, `beli-aman-storefronts` |
| **Seller / BPP (this repo)** | `jaringan-dagang-seller` | dashboard `jaringan-dagang-seller.metatech.id`; API `jaringan-dagang-seller-api.metatech.id` (also `jaringan-dagang-seller.vercel.app`) | `jaringan-dagang-seller`, `seller-dashboard` |
| Network | `jaringan-dagang-network` | dashboard `jaringan-dagang.metatech.id` | (that repo) |

**Stack:** Python 3.13 · FastAPI · SQLAlchemy 2 async · asyncpg · Neon Postgres
· Next.js 14 (seller dashboard) · Vercel (serverless) · Firebase Auth (Google)
· Ed25519 (pynacl) for Beckn signing · Xendit (payments/refunds).

## Beckn Protocol

Beckn is a **discovery + transaction** protocol — NOT a sync or ACL protocol.
Every message is Ed25519-signed; the signer's public key is registered in the
network registry under a `subscriber_id`. The receiver looks it up
(Redis-cached 1h + bundled static fallback) and verifies. Replay-protected via
a 5-minute freshness window + `message_id` idempotency.

**Per-toko identity:** each toko is its own Beckn subscriber
(`<slug>.jaringan-dagang.id`) with its own keypair. The private key lives in
`stores.signing_private_key` (this DB). `/on_search` fans out one message per
provider, each signed by that toko. A toko with no key falls back to the
process key `bpp.jaringan-dagang.local`, and the message's `bpp_id` is rebranded
to the process subscriber so signature verification still matches.

**Catalog sync (eventual + strong at the boundary):** this seller DB is the
**system of record**. Buyer keeps a hint-only mirror. Push: `/on_search`
emitted on every product write. Pull: buyer worker calls `/search` every 5 min.
Strong consistency only at money steps — `/select`+`/init` re-quote live
price/stock; `/confirm` decrements inventory inside a `SELECT … FOR UPDATE` txn.

**Order + refund flow** (replaces the legacy `seller_bridge` HTTP shortcut):
`/select → /init → /confirm`; refunds `/update {refund_request}` → seller
`RefundRequest` → seller approves → Xendit refund → `/on_update`.

## Identity & ACL — "Sign in with Beli Aman"

Beli Aman BAP is the network **Identity Provider**. One Google sign-in
(Firebase `beli-aman-prod`) is the identity for buyers AND seller-dashboard
operators AND Vibe-admin editors.

- Canonical user table: `beli_aman.profiles` (+ `is_super_admin`).
- Canonical ACL: `beli_aman.store_memberships` — `(email → store_id/store_slug
  → role)`, roles `owner` | `staff`. Pending invites (`profile_id NULL`)
  auto-claim on first sign-in.
- Super admins (`hallucinogenplus@gmail.com`, `lwastuargo@gmail.com`) bypass
  all membership checks.

The seller dashboard does **not** own auth. `lib/auth-context.tsx` signs in via
the shared Firebase app, calls the IdP `GET /api/v1/me` + `/api/v1/me/stores`
(`NEXT_PUBLIC_IDENTITY_API_URL`, default `https://api.beli-aman.metatech.id`),
then joins store details from this repo's `GET /api/stores`. Super admins see
all stores. The seller-side `users`/`store_memberships` tables still exist but
are **vestigial** — Beli Aman is the source of truth.

## Production Databases

One **Neon** project (serverless Postgres, AWS `ap-southeast-1`), host
`ep-shy-heart-a1atpe0m.ap-southeast-1.aws.neon.tech`, role `neondb_owner`, two
logical databases:

| DB | App | Tables (key) |
|---|---|---|
| `beli_aman` | Beli Aman BAP (IdP) | `profiles`, `store_memberships`, escrow, disputes, `mirror_*`, beckn logs |
| **`neondb`** (this repo) | Seller BPP | `stores`, `products`, `skus`, `sku_images`, `orders`, `refund_requests`, `import_jobs`, `beckn_*_logs`, vestigial `users`/`store_memberships` |

Local `.env` points at `localhost:5432` — **dev only**. Vercel `DATABASE_URL`
overrides to Neon `neondb` in prod. Connection string:
`postgresql+asyncpg://neondb_owner:<pw>@ep-shy-heart-a1atpe0m.ap-southeast-1.aws.neon.tech/neondb?ssl=require`.
**Schema is NOT managed by Alembic.** It's applied via `Base.metadata.create_all`
through `POST /api/admin/migrate` (admin-token gated). The lifespan auto-create
is gated behind `CREATE_TABLES_ON_STARTUP=1` (off in prod) to avoid cold-start
DB hits taking down every route.

## This Repo: Seller (BPP + Catalog + Dashboard)

Two deployables from one repo:
- **API** (`app/`, FastAPI) → Vercel project `jaringan-dagang-seller`,
  `jaringan-dagang-seller-api.metatech.id`. The BPP + catalog system of record.
- **Dashboard** (`seller-dashboard/`, Next.js 14) → Vercel project
  `seller-dashboard`, `jaringan-dagang-seller.metatech.id`.

### Catalog model
`Store → Product → SKU → SKUImage`. A Product is the buyable concept; SKUs are
its variants (size/flavor). Images are **per-variant** on the SKU. The dashboard
is **URL-only** for images — no file upload / CDN. `Store.subscriber_id` /
`Store.subscriber_url` make the toko a Beckn subscriber;
`Store.signing_private_key` holds its Ed25519 key.

### Beckn surface (`app/beckn/`)
- `endpoints.py` — `/search /select /init /confirm /status /update` + `/on_*`.
  `_process_and_callback` does the per-provider `/on_search` fan-out, signing
  per-toko via `signer_for_subscriber_id` (rebrands to the process bpp_id when a
  toko has no key).
- `handlers.py` — `handle_confirm` derives the store from the cart's first SKU
  (NOT a default-store fallback — that bug sent orders to Matchamu), caches
  ORM columns before the payment service call, then
  `order.status = ACCEPTED; flush; refresh`. `handle_update` routes
  `refund_request` → `refund_service`. Inventory decrement is race-safe via
  `inventory_service` (`SELECT … FOR UPDATE`).
- `catalog_builder.py` — `Provider.id = store.subscriber_id or str(store.id)`
  (buyer maps providers to slugs, so this must be the subscriber_id, not a
  UUID); `Item.parent_item_id = str(product.id)` so the buyer groups 36 SKUs
  into 16 products; variant tags as
  `{"descriptor":{"code":"name"},"value":…}`; `descriptor.name = product.name`
  (no variant suffix).

### Catalog import (`app/catalog_import/`, UI `/products/import`)
3-step wizard: upload Excel/CSV → map columns → confirm. `parser.py` (openpyxl)
+ 5 `SourceAdapter`s (BigSeller, Shopee, Tokopedia, Lazada, Generic) via an
adapter registry; `normalizer.py` summarizes into mutually-exclusive buckets;
`ImportJob` model / `import_jobs` table tracks runs. Products written through
the same `push_catalog_after_commit` path as the products API so imports also
emit `/on_search`.

### Admin (`app/api/admin.py`, gated by `ADMIN_MIGRATE_TOKEN`)
`POST /api/admin/migrate` (create_all), `GET /api/admin/db-tables`,
`POST /api/admin/rotate-store-key` (generates Ed25519, stores in
`Store.signing_private_key`, accepts `subscriber_id`+`subscriber_url`),
`POST /api/admin/seed-membership` (legacy seller-side ACL — superseded by the
BAP IdP). **No hardcoded token fallback** — returns 503 if the env var is unset.

### Key Files
- `app/beckn/{endpoints,handlers,catalog_builder}.py` — the BPP
- `app/api/admin.py` — migrate / key rotation / db introspection
- `app/catalog_import/` — importer (parser, adapters, normalizer)
- `app/services/{payment,refund,inventory}_service.py` — money + stock
- `seller-dashboard/lib/auth-context.tsx` — Firebase + IdP federation
- `seller-dashboard/lib/firebase.ts` — Firebase config baked as NEXT_PUBLIC
  defaults (apiKey/authDomain/projectId are public, not secret)
- `seller-dashboard/components/Sidebar.tsx` — nav incl. **Team** (`/settings/team`)
- `packages/beckn-protocol/python/` — vendored signer/envelope (pynacl Ed25519)

### Key Design Decisions
- **DB schema via admin endpoint, not Alembic.** Pre-production, no users,
  ship-fast. `create_all` is idempotent; `migrate` is the one-button apply.
- **Order store is derived from the cart, never defaulted.** A
  `_get_default_store` fallback silently misattributed orders.
- **`db.refresh` after commit, but cache columns first.** Async lazy-load on an
  expired ORM object raises `MissingGreenlet` on Vercel — read needed columns
  before `commit`, or re-`SELECT` instead of touching the expired object.
- **Auth is delegated to Beli Aman.** The dashboard never holds its own user
  table; ACL is one network-wide concept.

## Known Caveats / TODO
- Per-toko signing live for Safiya only; rotate others via
  `POST /api/admin/rotate-store-key`.
- `/on_search` push is awaited inline on Vercel → can hit function timeouts on
  large catalogs. The buyer still completes the upsert (data correct); only the
  seller's success flag is unreliable. Move to a queue / `waitUntil`.
- Vercel "Security Checkpoint" bot-challenge intermittently blocks automated
  curl of the dashboard domain; the API domain is unaffected.
- Seller-side `users`/`store_memberships` are vestigial — do not add new ACL
  logic there; use the BAP IdP.
