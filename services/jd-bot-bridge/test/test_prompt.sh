#!/bin/bash
# test_prompt.sh — demonstrates the prompt the bridge builds from a sample
# conversation. Useful for nullclaw operators to eyeball the exact prompt
# the LLM sees per turn.
#
# Uses the same sqlite stub as smoke.sh, seeds a 3-turn conversation,
# then invokes bridge.sh's build_prompt() against it.
#
# Usage:
#   bash test/test_prompt.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TMPDIR_REAL="$(mktemp -d -t jd-bot-prompt.XXXXXX)"
DB_PATH="$TMPDIR_REAL/state.db"
cleanup() { rm -rf "$TMPDIR_REAL"; }
trap cleanup EXIT

# Skip if psql is missing — build_prompt() in bridge.sh shells out to
# psql, and the worker is Postgres-only by design (the HTTP shim is the
# only DB-portable piece; the worker stays bash + psql for parity with
# pandai). We still want this script to be a no-op signal in environments
# that don't have psql installed.
if ! command -v psql >/dev/null 2>&1; then
  echo "[prompt] psql not on PATH — skipping (the worker is Postgres-only;"
  echo "         the HTTP shim has its own sqlite-backed smoke test in"
  echo "         test/smoke.sh)."
  exit 0
fi

# Use a pg_temp database if PG_TEST_DSN is provided; otherwise just
# print a static stub prompt so the operator can read the structure
# without provisioning Postgres.
if [ -z "${PG_TEST_DSN:-}" ]; then
  cat <<EOF
[prompt] PG_TEST_DSN not set — emitting a static example prompt instead.
[prompt] To exercise the real build_prompt() against a temporary
[prompt] Postgres database, run:
[prompt]   PG_TEST_DSN=postgres://localhost/jdbot_test bash test/test_prompt.sh

────────────────────────────────────────────────────────────────────────
EXAMPLE PROMPT (what nullclaw would receive, given a 3-turn history)
────────────────────────────────────────────────────────────────────────

$(cat "$ROOT_DIR/persona.md")

---

## Riwayat percakapan (oldest → newest, 12 terakhir)
[customer] halo, ada kurma?
[asisten] Halo! Sebentar saya cek dulu...
[customer] yang medjool ada?

---

Pesan customer baru: "berapa harganya?"

Jawab sebagai asisten belanja Safiya. Pakai tools (search_products,
cart_*, start_checkout, payment_status) kalau perlu data dari katalog.
Jangan menebak. Output: balasan langsung untuk customer (markdown OK).
EOF
  exit 0
fi

# Live path: drive bridge.sh against a real (temporary) Postgres.
export DATABASE_URL="$PG_TEST_DSN"
echo "[prompt] PG_TEST_DSN set — exercising build_prompt() against $DATABASE_URL"

# Source bridge.sh's functions without executing the entrypoint.
# We set mode to 'worker' but never call run_worker — instead we
# manually invoke build_prompt with a known fixture.
# shellcheck disable=SC1090,SC1091
. /dev/stdin <<EOF
$(sed '/^case "\$mode"/,$d' "$ROOT_DIR/bridge.sh")
EOF

# Seed.
CONV_ID="$(uuidgen | tr 'A-Z' 'a-z')"
STORE_ID="$(uuidgen | tr 'A-Z' 'a-z')"
psql "$DATABASE_URL" >/dev/null <<SQL
CREATE TABLE IF NOT EXISTS messages_stub (
  id text PRIMARY KEY,
  conversation_id text NOT NULL,
  sender text NOT NULL,
  content jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO messages_stub VALUES
 ('m1', '$CONV_ID', 'contact', '{"text":"halo, ada kurma?"}', now() - interval '5 min'),
 ('m2', '$CONV_ID', 'bot',     '{"text":"Halo! Sebentar saya cek dulu..."}', now() - interval '4 min'),
 ('m3', '$CONV_ID', 'contact', '{"text":"yang medjool ada?"}', now() - interval '3 min');
SQL

echo
echo "── Generated prompt ─────────────────────────────────────────────"
build_prompt "$CONV_ID" "berapa harganya?"
