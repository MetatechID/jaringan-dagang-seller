# Bridge ↔ CRM Contract Tests Map (Task C4)

This is a flat checklist of the contract invariants from
[`crm-bridge-contract.md`](./crm-bridge-contract.md) and the tests that
enforce each one. Reviewers can scan top-to-bottom and confirm "every
clause has a regression test" without re-reading the seller suite.

All tests live in `tests/`. Tests marked **(PG)** are gated on
`CRM_TEST_PG_DSN` and skip cleanly when unset; they run against a real
Postgres because the invariant they pin is Postgres-only (`FOR UPDATE`,
partial-unique indexes, real transaction isolation).

## Contract item → test

* **§1 Tables & ownership matrix — tables/enums exist with the right
  columns, FK targets, ondelete behaviour, defaults:** every test in
  `tests/test_crm_schema.py` (`test_contact_columns`,
  `test_inbox_columns`, `test_conversation_columns_and_fks`,
  `test_message_columns_and_fks`, `test_label_columns`,
  `test_conversation_labels_join_table`, etc.). Enum value sets pinned by
  `test_channel_enum_values_and_name`, `test_conversation_state_enum_values_and_name`,
  `test_message_sender_enum_values_and_name`,
  `test_message_delivery_enum_values_and_name`. Postgres-side type names
  pinned by `test_postgres_enum_type_names_pinned`.

* **§1 Defaults (`state=bot_active`, `delivery=na`, `unread_agent_count=0`):**
  `test_conversation_state_default_is_bot_active`,
  `test_message_delivery_default_is_na`,
  `test_conversation_unread_agent_count_defaults_to_zero` (all in
  `tests/test_crm_schema.py`).

* **§2 State machine — `bot_active → human_handoff` via take-over:**
  `tests/test_crm_api.py::TestTakeOver::test_bot_active_to_human_handoff`.

* **§2 State machine — `take-over` idempotent on already `human_handoff`
  (no re-stamp of `handoff_at` / `assignee_user_id`):**
  `tests/test_crm_api.py::TestTakeOver::test_human_handoff_is_idempotent`.

* **§2 State machine — `take-over` on `resolved` → 409:**
  `tests/test_crm_api.py::TestTakeOver::test_resolved_returns_409`.

* **§2 State machine — `resolve` clears `assignee_user_id`, stamps
  `resolved_at`:** `tests/test_crm_api.py::TestResolve::test_active_to_resolved`.

* **§2 State machine — `resolve` idempotent (no re-stamp):**
  `tests/test_crm_api.py::TestResolve::test_already_resolved_is_idempotent`.

* **§2 State machine — `reopen` preserves `assignee_user_id` and
  `handoff_at` for audit:**
  `tests/test_crm_api.py::TestReopen::test_resolved_to_bot_active_preserves_assignee_and_handoff`.

* **§2 State machine — `reopen` idempotent on already `bot_active`:**
  `tests/test_crm_api.py::TestReopen::test_already_active_is_idempotent`.

* **§3 Atomic handoff — first agent message flips state + writes message
  in one transaction (unit-level proof, no Postgres):**
  `tests/test_crm_api.py::TestPostAgentMessageHeadlineContract::test_bot_active_flips_to_human_handoff_and_inserts_message`.

* **§3 Atomic handoff — second agent message on `human_handoff` does NOT
  re-stamp `handoff_at` / `assignee_user_id`:**
  `tests/test_crm_api.py::TestPostAgentMessageHeadlineContract::test_human_handoff_does_not_clobber_handoff_at_or_assignee`.

* **§3 Atomic handoff — POST agent message on `resolved` → 409:**
  `tests/test_crm_api.py::TestPostAgentMessageHeadlineContract::test_resolved_returns_409`.

* **§3 Atomic handoff — mid-handler exception rolls BOTH writes back
  (the headline atomicity guarantee, end-to-end, real Postgres):**
  `tests/test_crm_api.py::test_handoff_atomicity_real_postgres` **(PG)**.

* **§3 Atomic handoff — route does NOT call commit/rollback itself
  (lets `get_db()` own atomic boundary):**
  `tests/test_crm_api.py::TestPostAgentMessageHeadlineContract::test_mid_transaction_failure_propagates_so_get_db_rolls_back`.

* **§4 Delivery queue — freshly-POSTed agent message becomes pollable
  with `sender='agent', delivery='pending'` (real Postgres):**
  `tests/test_crm_api.py::test_agent_message_appears_in_pending_delivery_queue` **(PG)**. *(Gap filled in C4.)*

* **§4 Delivery queue — `ix_messages_sender_delivery_created_at`
  composite index is declared on the model:**
  `tests/test_crm_schema.py::test_message_pending_delivery_composite_index_exists`. *(Added in C4.)*

* **§4 Delivery queue — `ix_messages_delivery` exists (covers single-column
  delivery filters):** `tests/test_crm_schema.py::test_message_columns_and_fks`
  (asserts `cols["delivery"].index is True`).

* **§5 Idempotency — partial unique index on `(store_id, external_id)`
  for `contacts` / `conversations`:**
  `tests/test_crm_schema.py::test_contact_unique_partial_index_on_store_external_id`
  and `test_conversation_unique_partial_index_on_store_external_id`.

* **§5 Idempotency — partial unique index on `(conversation_id,
  external_id)` for `messages`:**
  `tests/test_crm_schema.py::test_message_unique_partial_index_on_conversation_external_id`.

* **§5 Idempotency — duplicate insert raises `IntegrityError` (real
  Postgres):**
  `tests/test_crm_schema.py::test_idempotency_contract_postgres_only` **(PG)**.

* **§7 Rich content shape — JSONB passes blocks through unchanged
  (`product_card`, `image`, …):**
  `tests/test_crm_api.py::TestSerializers::test_message_content_jsonb_passes_through_unchanged`.

* **§8 Multi-tenant — super-admin without `store_id` returns `None`
  (cross-store view):**
  `tests/test_crm_api.py::TestStoreScopeResolution::test_super_admin_without_store_id_yields_none`.

* **§8 Multi-tenant — non-super without `store_id` → 400:**
  `tests/test_crm_api.py::TestStoreScopeResolution::test_non_super_without_store_id_is_400`.

* **§8 Multi-tenant — non-super with inaccessible store → 403:**
  `tests/test_crm_api.py::TestStoreScopeResolution::test_non_super_with_inaccessible_store_is_403`.

* **§8 Multi-tenant — non-super single-row read on inaccessible
  conversation → 404 (not 403; no existence leak):**
  `tests/test_crm_api.py::TestConversationVisibilityIsolation::test_load_conversation_for_inaccessible_store_returns_404`.

* **§8 Multi-tenant — label cross-store attach → 404:**
  `tests/test_crm_api.py::TestAttachLabel::test_cross_store_label_is_404`.

* **§9 Mutable resources NOT in the SWR cache prefix list (handoff
  staleness lock):**
  `tests/test_crm_api.py::test_crm_routes_not_in_cacheable_prefixes`.

## Test counts (C4 baseline)

* Before C4: **179 passed, 2 skipped** (the two skips are the PG-gated
  C1 idempotency test and the PG-gated C2 atomicity test, both run
  against Neon by setting `CRM_TEST_PG_DSN`).
* After C4: **181 passed, 3 skipped** (added one schema-side test for
  the new composite index, and one PG-gated test for the pending-queue
  pollability).
