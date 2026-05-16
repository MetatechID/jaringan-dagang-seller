# Catalog Importer — Spreadsheet-Based Onboarding from BigSeller, Shopee, Tokopedia, Lazada

**Status:** draft, awaiting implementation
**Author:** primary session, 2026-05-16
**Repo scope:** `jaringan-dagang-seller` (this repo only — no buyer/network changes)
**Related work:** parent_item_id SKU grouping (commit `fe49a4d`, this session), per-provider `/on_search` push (verified Task 12 this session)

## 1. Problem

Tokos onboarding to Jaringan Dagang already manage their catalogs in other systems — most commonly BigSeller (an omnichannel SEA hub that pushes to Shopee/Tokopedia/Lazada/TikTok Shop), or directly in those marketplaces. Re-entering 50–500 products by hand on first signup is a friction wall.

We need a UI in the seller dashboard that lets a toko owner upload a spreadsheet export from BigSeller (or directly from Shopee / Tokopedia / Lazada) and seed their Jaringan catalog from it. Re-uploading the same export later should update stock and price without creating duplicates.

This is a v1 import-only feature. Outbound channel sync (Jaringan → Shopee/Tokopedia) is a v2+ ambition and is out of scope here, though the data model is chosen so v2 reuses the same primitives.

## 2. Non-goals

- Direct BigSeller API integration. BigSeller has no public partner API; pursuit requires a business deal and is out of scope.
- Outbound channel sync (Jaringan pushes to Shopee/Tokopedia). v2+.
- Real-time stock decrement from external marketplaces. Re-upload is the v1 refresh mechanism.
- Image hosting / CDN migration. We store source image URLs as-is; tokos can re-upload to Jaringan storage later via the existing product editor.
- Automatic category creation. The source category text is recorded as a hint; tokos assign Jaringan categories manually.

## 3. User-facing flow

A new menu item **Import** (or a button on `/products`) opens a 3-step wizard at `/products/import`.

**Step 1 — Pick source.** Card grid of five tiles:

- BigSeller (XLSX)
- Shopee (XLSX)
- Tokopedia (XLSX)
- Lazada (XLSX)
- Generic (CSV or XLSX) — includes a "Download template" link to a starter XLSX with canonical column headers.

Each tile shows a one-line hint on where to find the export in the source platform (e.g. "BigSeller → Products → Bulk Export → XLSX").

**Step 2 — Upload.** Drag-and-drop accepting `.xlsx` and `.csv`, max 10 MB. On drop the file is POSTed to `/api/imports` along with the chosen source. Server parses synchronously and returns an `import_job_id` plus a preview within ~2 seconds for typical files (≤ 500 rows).

**Step 3 — Review preview & confirm.** Three sections on one page:

1. **Target store** — dropdown of the user's stores; defaults to current toko context if set.
2. **Column mapping** — table with canonical fields on the left (Name\*, SKU code\*, Price\*, Stock\*, Image URL, Parent group, Variant value, Weight g, Description, Category) and the detected source column on the right. The source-adapter preset is pre-applied; rows are editable so the toko can fix mismatches. Required fields that are unmapped show a yellow row and block confirm.
3. **Detected items** — first 20 rows with a per-row badge:
   - 🟢 **New** — will be created
   - 🔵 **Update** — matches an existing SKU; diff column shows the change ("stock 12 → 8")
   - 🟡 **Warning** — non-blocking issue (price=0, image URL unreachable, stock missing → treated as 0)
   - 🔴 **Error** — blocking issue (duplicate SKU within file, missing required field)
4. **Summary bar:** `N new · N update · N warn · N error · N total`. Confirm button disabled if any row has 🔴.

On confirm, POST `/api/imports/{id}/confirm` runs the applier and redirects to `/products?imported=<job_id>` with a toast: "Imported 138 products (3 warnings). [View report]". The report page is a read-only view of the import_job row (deferred — v1 just toasts; report page can be a follow-up).

## 4. Architecture

Three layers, isolated so each can be tested independently:

```
seller-dashboard (Next.js)
    /products/import — wizard UI
              │ multipart upload + JSON
              ▼
app/api/imports (FastAPI router)
    POST   /imports               create job, parse, return preview
    GET    /imports/{id}          fetch job status + preview rows
    PATCH  /imports/{id}/mapping  update column_mapping; recomputes preview
    POST   /imports/{id}/confirm  apply to catalog; fire push-on-search
              │
              ▼
app/services/catalog_import/
    parser.py        xlsx/csv bytes → list[dict] (one dict per row)
    adapters/
        __init__.py  registry: get_adapter(source) → Adapter
        bigseller.py
        shopee.py
        tokopedia.py
        lazada.py
        generic.py
    normalizer.py    dict + adapter → ImportedItem (canonical dataclass)
    applier.py       list[ImportedItem] + store_id → DB writes
    beckn_hook.py    after-apply trigger: push-on-search per affected store
```

A new `ImportJob` table tracks each upload through its lifecycle.

### 4.1 Adapter contract

```python
class SourceAdapter(Protocol):
    name: str                    # "bigseller", "shopee", ...
    display_name: str            # "BigSeller"
    file_extensions: list[str]   # [".xlsx"]
    default_column_mapping: dict[str, str]
        # canonical_field → source_column_header
        # e.g. {"name": "Product Name", "sku_code": "SKU", "price": "Selling Price"}

    def detect(self, headers: list[str]) -> float:
        """Return 0..1 confidence that this adapter fits these column headers.
        Used only as a tiebreaker if the user picks 'Generic' and we want
        to suggest a better preset."""

    def normalize_row(self, row: dict, mapping: dict) -> ImportedItem:
        """Apply column mapping + source-specific parsing (currency format,
        variant cell shape, parent-grouping convention) to one row."""
```

Each adapter is ~50–100 lines. The generic adapter is the identity transform with no source-specific quirks.

### 4.2 Canonical `ImportedItem`

```python
@dataclass
class ImportedItem:
    source_item_id: str          # platform's parent product ID
    source_variant_id: str | None # platform's variant ID; None if no variants
    parent_group_key: str        # == source_item_id; groups variants
    name: str
    sku_code: str
    price: Decimal
    stock: int
    variant_name: str | None     # e.g. "Size"
    variant_value: str | None    # e.g. "500g"
    image_urls: list[str]
    weight_grams: int | None
    category_hint: str | None
    description: str | None
    warnings: list[str]
    errors: list[str]
```

### 4.3 Applier matching logic

Per `ImportedItem` in the confirmed job:

1. **Match by marketplace map** — look up `MarketplaceProductMap` where `(marketplace_name == source, marketplace_item_id == source_variant_id or source_item_id)`. Hit → update that SKU.
2. **Match by SKU code** — if no marketplace-map match, look up `SKU` by `sku_code` within `store_id`. Hit → update the SKU and backfill a `MarketplaceProductMap` row for future re-uploads.
3. **Create new** — otherwise, create a new SKU. Group by `parent_group_key`: if another row in the same job already created the parent Product, attach this SKU to it; otherwise create the Product and attach.

Update semantics: overwrite `price`, `stock`, `weight_grams`, `variant_value`. Do not touch `images` on update (toko may have curated Jaringan images). Do not auto-archive SKUs missing from the new file — surface them in the report only.

## 5. Data model

One new table:

```python
class ImportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"

    store_id: FK("stores.id", ondelete="CASCADE")
    source: Enum("bigseller","shopee","tokopedia","lazada","generic")
    status: Enum("uploaded","previewed","confirmed","applied","failed")
    filename: str                # original upload filename
    file_path: str               # /tmp path in v1; S3 in future
    column_mapping: JSONB        # {canonical_field: source_column}
    preview_rows: JSONB          # parsed+normalized snapshot, up to first 500 rows
    summary: JSONB               # {new, update, warn, error, total}
    error_message: str | None
    confirmed_at: datetime | None
    applied_at: datetime | None
```

Alembic migration creates this table. No changes to existing tables.

The existing `MarketplaceProductMap(sku_id, marketplace_name, marketplace_item_id)` is reused as the durable cross-platform anchor — see §4.3.

## 6. Beckn integration

The importer writes to the same `products` / `skus` / `product_images` tables that `/beckn/search` already reads. Wire format is unchanged. Four specific touchpoints:

**Provider identity.** Each `Store` is one Beckn `provider`. Import always targets one store; the source platform is invisible on the wire. Buyers see "Safiya Food", not "Safiya Food (via BigSeller)".

**Parent grouping.** BigSeller/Shopee/Tokopedia exports represent variants as multiple rows sharing a parent product ID. The applier sets `parent_item_id = source_item_id` on every grouped SKU. Jaringan's catalog builder (verified end-to-end in commit `fe49a4d`) already collapses these into one buyer-side product card with a variant picker. No new Beckn work — correct at import time.

**Post-apply push.** After commit, `beckn_hook.py` calls the existing `/api/admin/push-on-search?store_id=...` once per affected store. The BAP receives a per-provider `/on_search` and updates its mirror; buyer sees imported products within ~5 seconds.

**Pre-registry imports allowed.** If the store has no `subscriber_id` on the network registry, push-on-search no-ops. The import still succeeds locally, so a toko can seed its catalog before registry onboarding.

`MarketplaceProductMap` stays private to the seller DB; it is never serialized into Beckn payloads. It exists for re-upload matching today and outbound channel sync tomorrow.

## 7. Edge cases & decisions

| Case | Decision |
|------|----------|
| Currency format `Rp 12.500` vs `12500` vs `12,500.00` | Strip all non-digit non-decimal chars; assume IDR; round half-up to integer rupiah. |
| Duplicate `sku_code` within one upload | Hard error on the second occurrence. User fixes the file and re-uploads. |
| Stock missing or non-numeric | Warning; treat as 0. |
| Price = 0 | Warning, not error. Some draft listings are legitimately zero-priced. |
| SKU exists in DB but missing from upload | Surface in the report ("12 existing SKUs not in this file"). Do not auto-archive. |
| Image URL unreachable (HEAD 4xx/5xx) | Warning. Store URL anyway — could be transient or auth-gated. |
| File > 10 MB | Reject at upload with a clear error. v1 ceiling. |
| Non-UTF-8 CSV | Try UTF-8, fall back to latin-1, then cp1252. Hard fail with a clear error if none decode. |
| Multi-sheet XLSX | v1: use first sheet only; warn if there are others. BigSeller exports are single-sheet in practice. |
| Tokopedia exports use Indonesian column headers (e.g. `Nama Produk`) | Tokopedia adapter's `default_column_mapping` uses Indonesian headers. |
| Adapter unknown column | Ignored, surfaced in the preview as "unmapped columns: ..." informational note. |
| User edits column_mapping after preview | PATCH `/imports/{id}/mapping` re-runs `normalizer.py` against the cached parsed rows; no re-parse. |
| Concurrent imports to same store | Serialize per store in the applier with a Postgres advisory lock keyed on `store_id`. Second import waits. |
| Crash mid-apply | `ImportJob.status` stays `confirmed` (not `applied`). Manual rerun or report-and-abort; v1 does not auto-retry. Each row's create/update is in its own savepoint so partial application is acceptable and resumable. |

## 8. Testing strategy

**Unit tests** (`tests/services/catalog_import/`):

- One fixture XLSX per source (`fixtures/bigseller_safiya_sample.xlsx`, etc.) with 5–10 rows including a variant block.
- `parser_test.py` — XLSX/CSV → rows
- `adapters_test.py` — one test per adapter: rows → ImportedItem with expected normalization
- `applier_test.py` — three scenarios per match path (new / matched-by-map / matched-by-sku); uses an in-memory SQLite via the existing test DB harness.
- `normalizer_test.py` — currency parsing, stock fallback, duplicate detection, parent grouping.

**Integration test** (`tests/api/imports_test.py`):

- Full wizard happy path: upload → preview → confirm → assert DB state + that push-on-search was called for the right store. Mock the push hook.
- Re-upload path: import once, modify stock in fixture, re-upload, assert SKUs updated and no duplicates.

**Manual verification on production after deploy:**

- Real Safiya Food BigSeller export uploaded against the existing Safiya Store; confirm product count matches and buyer mirror reflects updates after push-on-search fires.

## 9. Rollout

Per `CLAUDE.md`: no feature flag, no shadow mode, no dual-write. Ship to `main` per task per the implementation plan, push to prod, run the manual verification step above. Toko owners discover the new menu item on next login.

## 10. Future work (not in this spec)

- Background apply for files > 500 rows (v1 is synchronous; large uploads can hit Vercel's 60s function limit).
- Outbound channel sync (Jaringan → Shopee/Tokopedia/Lazada), reusing `MarketplaceProductMap` as the bidirectional anchor.
- Import report page (read-only view of `import_jobs` row).
- Scheduled refresh (poll a Google Sheets URL nightly, fetch the latest export). Requires the toko to keep an export living somewhere.
- Image rehosting to Jaringan's CDN.
- Auto-detect source from uploaded file (currently the user picks first; `SourceAdapter.detect` is wired in but unused in v1 UI).
