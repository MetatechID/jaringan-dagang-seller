#!/bin/bash
# Smoke test for jd-bot-bridge HTTP shim.
#
# Self-contained: builds a sqlite stub with the minimum CRM tables,
# boots the shim against it, then drives a round-trip:
#
#   1. POST /ingest with a customer message
#   2. GET  /replies?conversation=<id>
#   3. Assert the message round-trips with sender='customer'
#   4. Simulate a bot reply directly into sqlite, GET /replies again,
#      assert the bot message is visible with sender='bot'.
#
# Does NOT require:
#   - nullclaw (we never invoke the worker)
#   - Postgres (sqlite stub is enough for the wire-shape contract)
#   - Network access (everything is on 127.0.0.1)
#
# Usage:
#   bash test/smoke.sh          # one-shot, prints PASS/FAIL
#
# Exit code: 0 = pass, non-zero = fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TMPDIR_REAL="$(mktemp -d -t jd-bot-smoke.XXXXXX)"
DB_PATH="$TMPDIR_REAL/state.db"
PORT="${SMOKE_PORT:-18088}"
TOKEN="smoke-token-$(date +%s)"

cleanup() {
  if [ -n "${SHIM_PID:-}" ]; then
    kill "$SHIM_PID" >/dev/null 2>&1 || true
    wait "$SHIM_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMPDIR_REAL"
}
trap cleanup EXIT

note() { printf '[smoke] %s\n' "$*"; }
fail() { printf '[smoke] FAIL: %s\n' "$*" >&2; exit 1; }

# ─── 1. Build sqlite stub ───────────────────────────────────────────────
# Mirror the C1 schema's relevant columns. Postgres-isms (gen_random_uuid,
# JSONB, partial unique indexes, enum types) are reduced to sqlite
# equivalents: TEXT-typed enums + a unique index for idempotency.
note "creating sqlite stub at $DB_PATH"
sqlite3 "$DB_PATH" <<'SQL'
CREATE TABLE stores (
  id TEXT PRIMARY KEY,
  subscriber_id TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE inboxes (
  id TEXT PRIMARY KEY,
  store_id TEXT NOT NULL REFERENCES stores(id),
  name TEXT NOT NULL,
  channel TEXT NOT NULL,
  config TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE contacts (
  id TEXT PRIMARY KEY,
  store_id TEXT NOT NULL REFERENCES stores(id),
  external_id TEXT,
  name TEXT,
  email TEXT,
  phone TEXT,
  avatar_url TEXT,
  attributes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX uq_contacts_store_external_id
  ON contacts(store_id, external_id) WHERE external_id IS NOT NULL;
CREATE TABLE conversations (
  id TEXT PRIMARY KEY,
  store_id TEXT NOT NULL REFERENCES stores(id),
  inbox_id TEXT NOT NULL REFERENCES inboxes(id),
  contact_id TEXT NOT NULL REFERENCES contacts(id),
  channel TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'bot_active',
  external_id TEXT,
  assignee_user_id TEXT,
  last_message_at TEXT,
  last_message_preview TEXT,
  unread_agent_count INTEGER NOT NULL DEFAULT 0,
  handoff_at TEXT,
  resolved_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX uq_conversations_store_external_id
  ON conversations(store_id, external_id) WHERE external_id IS NOT NULL;
CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  store_id TEXT NOT NULL REFERENCES stores(id),
  sender TEXT NOT NULL,
  sender_user_id TEXT,
  content TEXT NOT NULL,
  external_id TEXT,
  delivery TEXT NOT NULL DEFAULT 'na',
  delivered_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX uq_messages_conv_external_id
  ON messages(conversation_id, external_id) WHERE external_id IS NOT NULL;

-- Seed: Safiya store + one website inbox.
INSERT INTO stores (id, subscriber_id, name) VALUES (
  '11111111-1111-4111-8111-111111111111',
  'safiyafood.jaringan-dagang.id',
  'Safiya Food'
);
INSERT INTO inboxes (id, store_id, name, channel) VALUES (
  '22222222-2222-4222-8222-222222222222',
  '11111111-1111-4111-8111-111111111111',
  'Safiya Website',
  'website'
);
SQL

# ─── 2. Boot the shim against sqlite ────────────────────────────────────
note "starting shim on 127.0.0.1:$PORT"
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  fail "python3 not found on PATH"
fi
DATABASE_URL="sqlite://$DB_PATH" \
BRIDGE_INGEST_TOKEN="$TOKEN" \
PORT="$PORT" \
BIND_HOST=127.0.0.1 \
LOG_LEVEL=WARNING \
  "$PYTHON" "$ROOT_DIR/bridge_http.py" >"$TMPDIR_REAL/shim.log" 2>&1 &
SHIM_PID=$!

# Wait for /health to come up.
for i in $(seq 1 50); do
  if curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" \
       2>/dev/null | grep -q '^200$'; then
    break
  fi
  sleep 0.1
  if [ "$i" = "50" ]; then
    cat "$TMPDIR_REAL/shim.log" >&2
    fail "shim never became healthy"
  fi
done
note "shim healthy"

# ─── 3. /ingest a customer message ──────────────────────────────────────
CUSTOMER_ID="33333333-3333-4333-8333-333333333333"
note "POST /ingest"
# Write body to file + capture HTTP status separately (portable across
# GNU + BSD; macOS `head -n -1` doesn't accept negative counts).
INGEST_BODY_FILE="$TMPDIR_REAL/ingest.body"
INGEST_STATUS=$(curl -s -X POST "http://127.0.0.1:$PORT/ingest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"brand\":\"safiyafood\",\"customer_id\":\"$CUSTOMER_ID\",\"text\":\"halo, ada kurma?\"}" \
  -o "$INGEST_BODY_FILE" -w '%{http_code}')
INGEST_BODY=$(cat "$INGEST_BODY_FILE")
[ "$INGEST_STATUS" = "200" ] || fail "ingest expected 200, got $INGEST_STATUS  body=$INGEST_BODY"
CONV_ID=$(echo "$INGEST_BODY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["conversation_id"])')
[ -n "$CONV_ID" ] || fail "ingest returned no conversation_id"
note "conversation_id=$CONV_ID"

# ─── 4. /replies returns the customer message ───────────────────────────
note "GET /replies (first poll)"
REP_BODY_FILE="$TMPDIR_REAL/replies.body"
REP_STATUS=$(curl -s "http://127.0.0.1:$PORT/replies?conversation=$CONV_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -o "$REP_BODY_FILE" -w '%{http_code}')
REP_BODY=$(cat "$REP_BODY_FILE")
[ "$REP_STATUS" = "200" ] || fail "replies expected 200, got $REP_STATUS  body=$REP_BODY"
COUNT=$(echo "$REP_BODY" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["messages"]))')
[ "$COUNT" = "1" ] || fail "expected 1 message, got $COUNT  body=$REP_BODY"
SENDER=$(echo "$REP_BODY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["messages"][0]["sender"])')
[ "$SENDER" = "customer" ] || fail "expected sender=customer (wire), got $SENDER"
TEXT=$(echo "$REP_BODY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["messages"][0]["content"]["text"])')
[ "$TEXT" = "halo, ada kurma?" ] || fail "text mismatch: got '$TEXT'"
note "customer message round-trips with sender=customer (DB contact)"

# ─── 5. Simulate a bot reply directly into sqlite ───────────────────────
note "INSERTing simulated bot reply"
# Use an explicit '+1 second' so the bot message strictly post-dates the
# customer message — sqlite datetime('now') has 1-second resolution, so
# back-to-back inserts can collide and the ORDER BY id tiebreak depends
# on UUID lexicographic order.
sqlite3 "$DB_PATH" <<SQL
INSERT INTO messages (id, conversation_id, store_id, sender, content, external_id, created_at, updated_at)
VALUES (
  '44444444-4444-4444-8444-444444444444',
  '$CONV_ID',
  '11111111-1111-4111-8111-111111111111',
  'bot',
  '{"text":"Halo! Ada beberapa pilihan kurma...","blocks":[]}',
  'jdbot-reply-test',
  datetime('now', '+1 second'),
  datetime('now', '+1 second')
);
SQL

note "GET /replies (after bot reply)"
REP2_BODY_FILE="$TMPDIR_REAL/replies2.body"
REP2_STATUS=$(curl -s "http://127.0.0.1:$PORT/replies?conversation=$CONV_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -o "$REP2_BODY_FILE" -w '%{http_code}')
REP2_BODY=$(cat "$REP2_BODY_FILE")
[ "$REP2_STATUS" = "200" ] || fail "replies #2 expected 200, got $REP2_STATUS"
COUNT2=$(echo "$REP2_BODY" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["messages"]))')
[ "$COUNT2" = "2" ] || fail "expected 2 messages, got $COUNT2"
LAST_SENDER=$(echo "$REP2_BODY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["messages"][-1]["sender"])')
[ "$LAST_SENDER" = "bot" ] || fail "expected last sender=bot, got $LAST_SENDER"
note "bot reply visible via /replies"

# ─── 6. Auth negative path ──────────────────────────────────────────────
note "POST /ingest without bearer"
UNAUTH_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "http://127.0.0.1:$PORT/ingest" \
  -H "Content-Type: application/json" -d '{"brand":"safiyafood"}')
[ "$UNAUTH_STATUS" = "401" ] || fail "expected 401 without bearer, got $UNAUTH_STATUS"

# ─── 7. Unknown brand ────────────────────────────────────────────────────
note "POST /ingest with unknown brand"
NOT_FOUND_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "http://127.0.0.1:$PORT/ingest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"brand\":\"doesnotexist\",\"customer_id\":\"$CUSTOMER_ID\",\"text\":\"hi\"}")
[ "$NOT_FOUND_STATUS" = "404" ] || fail "expected 404 for unknown brand, got $NOT_FOUND_STATUS"

# ─── 8. /replies on unknown conversation ────────────────────────────────
note "GET /replies for unknown conversation"
UNK_CONV="55555555-5555-4555-8555-555555555555"
UNK_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  "http://127.0.0.1:$PORT/replies?conversation=$UNK_CONV" \
  -H "Authorization: Bearer $TOKEN")
[ "$UNK_STATUS" = "404" ] || fail "expected 404 for unknown conversation, got $UNK_STATUS"

# ─── 9. Idempotent re-ingest on same external_id path ───────────────────
note "POST /ingest twice — second one upserts conversation, contact stays the same"
INGEST2=$(curl -s -X POST "http://127.0.0.1:$PORT/ingest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"brand\":\"safiyafood\",\"customer_id\":\"$CUSTOMER_ID\",\"text\":\"sekarang minyak zaitun\"}")
CONV_ID2=$(echo "$INGEST2" | python3 -c 'import sys,json;print(json.load(sys.stdin)["conversation_id"])')
[ "$CONV_ID2" = "$CONV_ID" ] || fail "expected same conv_id on second ingest, got $CONV_ID2 vs $CONV_ID"

# Now verify only ONE contact row exists.
CONTACT_COUNT=$(sqlite3 "$DB_PATH" "SELECT count(*) FROM contacts WHERE external_id = 'web-$CUSTOMER_ID';")
[ "$CONTACT_COUNT" = "1" ] || fail "expected exactly 1 contact, got $CONTACT_COUNT"

echo
echo "[smoke] PASS"
