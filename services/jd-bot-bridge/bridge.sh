#!/bin/bash
# jd-bot bridge — dual entrypoint.
#
#   bridge.sh http     - exec the Python FastAPI shim (bridge_http.py).
#   bridge.sh worker   - run the polling worker loop in bash + psql.
#   bridge.sh smoke    - run a self-contained smoke test against a temp DB.
#
# Why split: HTTP shim and worker are separately scalable (multiple
# worker replicas OK with SKIP LOCKED; one HTTP shim is enough). Both
# processes share /etc/jd-bot/bridge.env (loaded by systemd).
#
# References for the design:
#   docs/crm-bridge-contract.md   (the operating manual — senders, enums,
#       state machine, idempotency keys)
#   ~/Code/pandai/services/yard-supervisor/supervisor.sh  (proven nullclaw
#       + Postgres polling pattern in bash; we borrow the idioms only)
#
# Hard rules from the brief, baked in:
#   - Bridge writes sender IN ('contact','bot') only. Never 'agent'.
#   - Before INSERTing a bot reply, FOR UPDATE the conversation row and
#     re-check state='bot_active'. If not, abort (the WHERE EXISTS on
#     the INSERT does this in a single statement).
#   - flock per-conversation so two worker replicas can't double-fire on
#     the same conversation. The SQL is store-wide so they coexist fine
#     on different conversations.
#   - timeout -k 30 120 nullclaw : nullclaw ignores SIGTERM, so escalate
#     to SIGKILL after a grace period. Proven from pandai supervisor.
#   - All bridge-INSERTed messages set external_id for idempotency replay.

set -uo pipefail

# ─── Constants & env ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PERSONA_FILE="${PERSONA_FILE:-$SCRIPT_DIR/persona.md}"
NULLCLAW="${NULLCLAW:-/usr/local/bin/nullclaw}"
NULLCLAW_TIMEOUT_SEC="${NULLCLAW_TIMEOUT_SEC:-120}"
NULLCLAW_KILL_AFTER_SEC="${NULLCLAW_KILL_AFTER_SEC:-30}"
WORKER_POLL_INTERVAL_SEC="${WORKER_POLL_INTERVAL_SEC:-4}"
WORKER_BATCH_SIZE="${WORKER_BATCH_SIZE:-8}"
WORKER_HISTORY_LIMIT="${WORKER_HISTORY_LIMIT:-12}"
LOCK_DIR="${LOCK_DIR:-/tmp}"
LOG_PREFIX="[jd-bot]"
# Fallback bot reply when nullclaw times out / is unreachable. Bounded
# to 1 per conversation per minute via fallback_recent() so the customer
# isn't stranded but we don't spam either.
FALLBACK_TEXT="${FALLBACK_TEXT:-(maaf, asisten sedang sibuk — coba lagi sebentar)}"

log() { echo "$LOG_PREFIX $(date -u +%FT%TZ) $*" >&2; }

# Resolve python3 with a venv preference. The HTTP shim runs FastAPI;
# operators are expected to set PYTHON to the venv interpreter via
# /etc/jd-bot/bridge.env. The fallback search is for dev / smoke.
_find_python() {
  if [ -n "${PYTHON:-}" ] && [ -x "$PYTHON" ]; then
    printf '%s' "$PYTHON"
    return
  fi
  for cand in python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      command -v "$cand"
      return
    fi
  done
  printf '/usr/bin/python3'
}

# psql command array — same idiom as pandai's supervisor.sh. -At =
# tuples-only, unaligned. -X = ignore .psqlrc. -q = quiet (no NOTICE).
# -v ON_ERROR_STOP=1 so a bad SQL fails fast instead of silently
# returning partial output. The caller passes DATABASE_URL via env.
PSQL=(psql "${DATABASE_URL:-}" -At -X -q -v ON_ERROR_STOP=1)

# Escape a single-quoted SQL string. Doubles any embedded single-quote.
# For JSON bodies that may contain quotes, use a dollar-quoted heredoc
# (see insert_bot_reply); for short, controlled values, sqlescape is fine.
sqlescape() { printf '%s' "${1//\'/\'\'}"; }

# ─── Worker: poll + reply ─────────────────────────────────────────────────

# pending_conversations — find conversations where state='bot_active'
# AND the most-recent message is a contact message (i.e. unanswered).
# Emits one tab-separated row per conversation:
#   conv_id  store_id  channel  last_contact_msg_id  last_contact_text
#
# Pre-filter on conversations.state='bot_active' BEFORE pulling messages,
# so we don't scan dead/resolved threads. The DISTINCT ON walks
# messages.conversation_id for just the bot_active set; the
# (conversation_id, created_at DESC) lookup hits the partial index on
# the messages table.
pending_conversations() {
  "${PSQL[@]}" -F$'\t' -c "
    WITH active AS (
      SELECT id, store_id, channel
      FROM conversations
      WHERE state = 'bot_active'
      ORDER BY last_message_at NULLS FIRST
      LIMIT $WORKER_BATCH_SIZE * 4
    ),
    last_per_conv AS (
      SELECT DISTINCT ON (m.conversation_id)
             m.conversation_id, m.id, m.sender, m.content, m.created_at
      FROM messages m
      JOIN active a ON a.id = m.conversation_id
      ORDER BY m.conversation_id, m.created_at DESC
    )
    SELECT a.id, a.store_id, a.channel, lpc.id, lpc.content->>'text'
    FROM active a
    JOIN last_per_conv lpc ON lpc.conversation_id = a.id
    WHERE lpc.sender = 'contact'
    LIMIT $WORKER_BATCH_SIZE;
  " 2>/dev/null
}

# build_prompt <conv_id> <text> — emit the full nullclaw prompt on stdout.
build_prompt() {
  local conv_id="$1" newtext="$2"
  local persona history
  persona=$(cat "$PERSONA_FILE" 2>/dev/null || echo "(persona missing)")

  # One line per past message, oldest first. Use jsonb extraction so we
  # get plain text regardless of which block types content has.
  history=$("${PSQL[@]}" -c "
    SELECT string_agg(
      CASE sender
        WHEN 'contact' THEN '[customer] '
        WHEN 'bot'     THEN '[asisten] '
        WHEN 'agent'   THEN '[tim Safiya] '
      END || coalesce(content->>'text',''),
      E'\n'
      ORDER BY created_at
    )
    FROM (
      SELECT sender, content, created_at
      FROM messages
      WHERE conversation_id = '$(sqlescape "$conv_id")'::uuid
      ORDER BY created_at DESC
      LIMIT $WORKER_HISTORY_LIMIT
    ) sub;
  " 2>/dev/null)
  [ -z "$history" ] && history="(belum ada riwayat)"

  cat <<EOF
$persona

---

## Riwayat percakapan (oldest → newest, $WORKER_HISTORY_LIMIT terakhir)
$history

---

Pesan customer baru: "$newtext"

Jawab sebagai asisten belanja Safiya. Pakai tools (search_products,
cart_*, start_checkout, payment_status) kalau perlu data dari katalog.
Jangan menebak. Output: balasan langsung untuk customer (markdown OK).
EOF
}

# call_nullclaw <session_key> <prompt> — invoke nullclaw with timeout.
#
# Stdout = nullclaw's reply. Empty on timeout / failure. timeout sends
# SIGTERM at the deadline, then SIGKILL after -k seconds; nullclaw
# ignores SIGTERM (proven from pandai), so the SIGKILL escalation is
# what actually stops a hung run.
call_nullclaw() {
  local session="$1" prompt="$2"
  if [ ! -x "$NULLCLAW" ]; then
    log "nullclaw binary not found at $NULLCLAW (set NULLCLAW env)"
    return 1
  fi
  timeout -k "${NULLCLAW_KILL_AFTER_SEC}" "${NULLCLAW_TIMEOUT_SEC}" \
    "$NULLCLAW" agent -s "$session" -m "$prompt" 2>/dev/null
}

# insert_bot_reply <conv_id> <store_id> <reply_text> <external_id>
#
# Inserts a bot message ONLY if conversation.state is still bot_active
# at the moment of insert. WHERE EXISTS (... FOR UPDATE-equivalent under
# the implicit lock taken by the UPDATE below) guarantees that an agent
# that flipped the state in parallel wins. ON CONFLICT DO NOTHING makes
# replay (same external_id) a silent no-op.
#
# Updates conversation.last_message_at + last_message_preview so the CRM
# list pane re-sorts to top.
insert_bot_reply() {
  local conv_id="$1" store_id="$2" reply="$3" ext_id="$4"
  local content_json preview
  content_json=$(jq -nc --arg t "$reply" '{text:$t, blocks:[]}')
  preview="${reply:0:280}"

  # Dollar-quote tags so embedded ' or " in JSON / preview text don't
  # need escaping. Tag suffix is a short unique-ish blob to avoid
  # collision with the content.
  local dq_c="c$(date +%s%N | tail -c 6)"
  local dq_p="p$(date +%s%N | tail -c 6)"

  if "${PSQL[@]}" >/dev/null 2>&1 <<SQL
BEGIN;
INSERT INTO messages (
  conversation_id, store_id, sender, content, delivery, external_id
)
SELECT '$(sqlescape "$conv_id")'::uuid,
       '$(sqlescape "$store_id")'::uuid,
       'bot',
       \$$dq_c\$$content_json\$$dq_c\$::jsonb,
       'na',
       '$(sqlescape "$ext_id")'
WHERE EXISTS (
  SELECT 1 FROM conversations
  WHERE id = '$(sqlescape "$conv_id")'::uuid
    AND state = 'bot_active'
  FOR UPDATE
)
ON CONFLICT (conversation_id, external_id) WHERE external_id IS NOT NULL
DO NOTHING;
UPDATE conversations
SET last_message_at = now(),
    last_message_preview = \$$dq_p\$$preview\$$dq_p\$
WHERE id = '$(sqlescape "$conv_id")'::uuid
  AND state = 'bot_active';
COMMIT;
SQL
  then
    return 0
  else
    log "insert_bot_reply: psql failed for conv ${conv_id:0:8}"
    return 1
  fi
}

# fallback_recent <conv_id> — non-empty if a fallback bot message was
# inserted within the last 60s. Bounds spam rate to 1/conv/minute.
fallback_recent() {
  local conv_id="$1"
  "${PSQL[@]}" -c "
    SELECT 1 FROM messages
    WHERE conversation_id = '$(sqlescape "$conv_id")'::uuid
      AND sender = 'bot'
      AND external_id LIKE 'jdbot-fallback-%'
      AND created_at > now() - interval '60 seconds'
    LIMIT 1;
  " 2>/dev/null
}

# process_one <conv_id> <store_id> <channel> <last_msg_id> <last_text>
process_one() {
  local conv_id="$1" store_id="$2" channel="$3" last_msg_id="$4" last_text="$5"

  # Per-conversation flock. -n = non-blocking; if another worker on the
  # same VM is already mid-flight on this conv, just skip — it'll be
  # picked up next tick. The lock file lives in /tmp; kernel cleans the
  # FD on process exit so a crashed worker doesn't leak the lock.
  local lockfile="$LOCK_DIR/jdbot-${conv_id}.lock"
  exec 9>"$lockfile" || {
    log "process_one: cannot open lock $lockfile"
    return 1
  }
  if ! flock -n 9; then
    return 0
  fi

  log "tick conv=${conv_id:0:8} last_msg=${last_msg_id:0:8} text=\"${last_text:0:60}\""

  local session_key="jdbot-${conv_id}"
  local prompt
  prompt=$(build_prompt "$conv_id" "$last_text")
  if [ -z "$prompt" ]; then
    log "process_one: empty prompt for conv ${conv_id:0:8}"
    flock -u 9; exec 9>&-
    return 1
  fi

  local reply
  reply=$(call_nullclaw "$session_key" "$prompt")
  # Trim trailing whitespace; nullclaw sometimes emits a trailing newline.
  reply="${reply%"${reply##*[![:space:]]}"}"

  # external_id ties the bot reply to the customer message it answers,
  # so a worker crash mid-process_one won't double-insert on replay.
  local ext_id="jdbot-reply-${last_msg_id}"

  if [ -z "$reply" ]; then
    log "process_one: nullclaw produced no reply for conv ${conv_id:0:8}"
    if [ -z "$(fallback_recent "$conv_id")" ]; then
      local fb_ext="jdbot-fallback-${last_msg_id}"
      insert_bot_reply "$conv_id" "$store_id" "$FALLBACK_TEXT" "$fb_ext" || true
    fi
    flock -u 9; exec 9>&-
    return 0
  fi

  if [ "$reply" = "SKIP" ]; then
    log "process_one: SKIP sentinel for conv ${conv_id:0:8}"
    flock -u 9; exec 9>&-
    return 0
  fi

  if insert_bot_reply "$conv_id" "$store_id" "$reply" "$ext_id"; then
    log "process_one: replied conv=${conv_id:0:8} ${#reply}ch"
  else
    log "process_one: insert failed conv=${conv_id:0:8}"
  fi

  flock -u 9; exec 9>&-
}

process_pending_replies() {
  local row conv_id store_id channel last_msg_id last_text
  while IFS=$'\t' read -r conv_id store_id channel last_msg_id last_text; do
    [ -z "$conv_id" ] && continue
    process_one "$conv_id" "$store_id" "$channel" "$last_msg_id" "$last_text"
  done < <(pending_conversations)
}

run_worker() {
  if [ -z "${DATABASE_URL:-}" ]; then
    log "FATAL: DATABASE_URL not set"
    exit 1
  fi
  log "worker starting (poll=${WORKER_POLL_INTERVAL_SEC}s, batch=${WORKER_BATCH_SIZE}, history=${WORKER_HISTORY_LIMIT})"
  log "nullclaw=$NULLCLAW timeout=${NULLCLAW_TIMEOUT_SEC}s kill_after=${NULLCLAW_KILL_AFTER_SEC}s"
  trap 'log "worker shutting down"; exit 0' INT TERM
  while true; do
    process_pending_replies
    sleep "$WORKER_POLL_INTERVAL_SEC"
  done
}

# ─── HTTP shim ──────────────────────────────────────────────────────────
run_http() {
  local py
  py="$(_find_python)"
  log "http shim starting (python=$py port=${PORT:-8088})"
  exec "$py" "$SCRIPT_DIR/bridge_http.py"
}

# ─── Smoke ──────────────────────────────────────────────────────────────
run_smoke() {
  exec bash "$SCRIPT_DIR/test/smoke.sh" "$@"
}

# ─── Entry point ────────────────────────────────────────────────────────
mode="${1:-}"
case "$mode" in
  http)   run_http ;;
  worker) run_worker ;;
  smoke)  run_smoke ;;
  '')
    echo "usage: bridge.sh {http|worker|smoke}" >&2
    exit 2
    ;;
  *)
    echo "unknown mode: $mode" >&2
    echo "usage: bridge.sh {http|worker|smoke}" >&2
    exit 2
    ;;
esac
