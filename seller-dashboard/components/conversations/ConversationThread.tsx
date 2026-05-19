"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  assign as apiAssign,
  fetchConversation,
  fetchContact,
  fetchMessages,
  postAgentMessage,
  reopenConversation,
  resolveConversation,
  takeOver,
  type Conversation,
  type Contact,
  type Message,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import LoadingSpinner from "@/components/LoadingSpinner";
import MessageBubble from "./MessageBubble";
import Composer from "./Composer";
import { useVisiblePolling } from "./useVisiblePolling";

const POLL_INTERVAL_MS = 4_000;

function ThreadStateBadge({ state }: { state: Conversation["state"] }) {
  const cfg: Record<Conversation["state"], { bg: string; text: string; label: string }> = {
    bot_active: { bg: "bg-emerald-100", text: "text-emerald-800", label: "Bot active" },
    human_handoff: { bg: "bg-amber-100", text: "text-amber-800", label: "Human handoff" },
    resolved: { bg: "bg-gray-200", text: "text-gray-700", label: "Resolved" },
  };
  const c = cfg[state] ?? cfg.bot_active;
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${c.bg} ${c.text}`}>
      {c.label}
    </span>
  );
}

export interface ConversationThreadProps {
  conversationId: string;
}

export default function ConversationThread({ conversationId }: ConversationThreadProps) {
  const { me } = useAuth();
  const [conv, setConv] = useState<Conversation | null>(null);
  const [contact, setContact] = useState<Contact | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"takeOver" | "resolve" | "reopen" | "assign" | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const lastIdRef = useRef<string | null>(null);
  // C3 review fix — Polling race on conversation switch.
  //
  // A single AbortController is scoped to "this conversation view" (i.e. one
  // (conversationId) cycle). It is created by the initial-load effect below
  // and reused by `pollTick` for every in-flight fetch. On cleanup (conv id
  // change or unmount) the controller is aborted, which cancels any
  // outstanding initial-load AND polling fetches. This closes the race where
  // the user switched from conv A to conv B while an A-pollTick was in
  // flight: previously the A-fetch would resolve after B's load applied its
  // state, calling `setMessages((prev) => [...prev, ...A_fresh])` against
  // B's `prev`, polluting the thread and corrupting `lastIdRef`. Now the
  // A-fetch rejects with AbortError before any setState runs.
  //
  // Visibility-pause semantics still hold: the polling interval is paused by
  // `useVisiblePolling` while the tab is hidden, but the controller itself
  // is NOT aborted on hide — so when the tab returns to visible, the next
  // tick uses the same live controller (no first-tick no-op, no zombie
  // controller leak).
  const abortRef = useRef<AbortController | null>(null);

  // Load conversation + contact + initial messages whenever the id changes.
  useEffect(() => {
    const ac = new AbortController();
    abortRef.current = ac;
    setLoading(true);
    setMessages([]);
    setConv(null);
    setContact(null);
    setError(null);
    lastIdRef.current = null;

    (async () => {
      try {
        const c = await fetchConversation(conversationId, { signal: ac.signal });
        setConv(c);
        // Fetch contact for header name; tolerate failure.
        try {
          const ct = await fetchContact(c.contact_id, { signal: ac.signal });
          setContact(ct);
        } catch {
          /* keep undefined */
        }
        const msgs = await fetchMessages(conversationId, { limit: 200, signal: ac.signal });
        setMessages(msgs);
        if (msgs.length > 0) lastIdRef.current = msgs[msgs.length - 1].id;
        // After paint, scroll to bottom.
        setTimeout(() => scrollToBottom(true), 0);
      } catch (e) {
        if ((e as DOMException)?.name === "AbortError") return;
        setError(e instanceof Error ? e.message : "Failed to load conversation");
      } finally {
        setLoading(false);
      }
    })();

    return () => {
      ac.abort();
      if (abortRef.current === ac) abortRef.current = null;
    };
  }, [conversationId]);

  // Poll for new messages on a short interval; pause when tab hidden. The
  // `after_id` cursor + append keeps payloads tiny and avoids flicker.
  //
  // Every fetch here is gated by `abortRef.current.signal` — the SAME
  // controller used by the initial-load effect — so a conv id change (or
  // unmount) cancels any in-flight polling fetch before its setState runs.
  // See the comment on `abortRef` above for the full rationale.
  const pollTick = useCallback(async () => {
    if (!conv) return;
    const ac = abortRef.current;
    // No controller means the owning effect has torn down (mid-switch);
    // skip this tick — the new effect will install a fresh controller.
    if (!ac) return;
    const signal = ac.signal;
    try {
      const fresh = await fetchMessages(conversationId, {
        after_id: lastIdRef.current ?? undefined,
        limit: 100,
        signal,
      });
      if (signal.aborted) return;
      if (fresh.length > 0) {
        setMessages((prev) => {
          const seen = new Set(prev.map((m) => m.id));
          const merged = [...prev];
          for (const m of fresh) if (!seen.has(m.id)) merged.push(m);
          return merged;
        });
        lastIdRef.current = fresh[fresh.length - 1].id;
        // Auto-scroll only if user is near bottom (within 100px). Avoid
        // yanking them away if they scrolled up to read older context.
        if (isNearBottom()) scrollToBottom(false);
      }
      // Also refresh conversation state in case server-side handoff happened.
      const refreshed = await fetchConversation(conversationId, { signal });
      if (signal.aborted) return;
      setConv(refreshed);
    } catch (e) {
      // AbortError is the user-initiated cancel (conv switch / unmount) —
      // silently skip; do not surface as a polling error.
      if ((e as DOMException)?.name === "AbortError") return;
      /* swallow other polling errors */
    }
  }, [conv, conversationId]);

  useVisiblePolling(pollTick, POLL_INTERVAL_MS, !!conv);

  function isNearBottom(): boolean {
    const el = scrollRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 100;
  }

  function scrollToBottom(instant: boolean) {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: instant ? "auto" : "smooth" });
  }

  async function handleTakeOver() {
    if (!conv) return;
    setBusy("takeOver");
    setError(null);
    try {
      const updated = await takeOver(conv.id);
      setConv(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Take-over failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleResolve() {
    if (!conv) return;
    setBusy("resolve");
    setError(null);
    try {
      const updated = await resolveConversation(conv.id);
      setConv(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resolve failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleReopen() {
    if (!conv) return;
    setBusy("reopen");
    setError(null);
    try {
      const updated = await reopenConversation(conv.id);
      setConv(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reopen failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleAssignToMe() {
    if (!conv || !me) return;
    setBusy("assign");
    setError(null);
    setAssignOpen(false);
    try {
      const updated = await apiAssign(conv.id, me.id);
      setConv(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Assign failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleSend(text: string) {
    if (!conv) return;
    try {
      const msg = await postAgentMessage(conv.id, { text });
      setMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev;
        return [...prev, msg];
      });
      lastIdRef.current = msg.id;
      // After local insert, refresh conversation in case state flipped.
      try {
        const refreshed = await fetchConversation(conv.id);
        setConv(refreshed);
      } catch {
        /* non-fatal */
      }
      setTimeout(() => scrollToBottom(false), 0);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Resolved → can't send. Composer will display the thrown message.
        throw new Error("This conversation is resolved. Reopen it to reply.");
      }
      throw e;
    }
  }

  if (loading) return <LoadingSpinner />;
  if (error && !conv) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-gray-500">
        {error}
      </div>
    );
  }
  if (!conv) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-gray-500">
        Conversation not found.
      </div>
    );
  }

  const contactName = contact?.name || "Anonymous";
  const showTakeOver = conv.state === "bot_active";
  const showReopen = conv.state === "resolved";
  const composerDisabled = conv.state === "resolved";
  const composerHint =
    conv.state === "bot_active"
      ? "Bot active — your reply will take over the conversation."
      : conv.state === "resolved"
      ? "Resolved — reopen to reply."
      : undefined;

  return (
    <div className="flex h-full flex-col min-h-0">
      {/* Header */}
      <header className="flex items-center justify-between gap-3 border-b border-gray-200 bg-white px-5 py-3">
        <div className="min-w-0 flex items-center gap-3">
          {contact?.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={contact.avatar_url}
              alt=""
              className="h-9 w-9 rounded-full object-cover"
            />
          ) : (
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gray-200 text-xs font-bold text-gray-600">
              {(contactName[0] || "?").toUpperCase()}
            </div>
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-gray-900">{contactName}</p>
            <div className="mt-0.5 flex items-center gap-2">
              <ThreadStateBadge state={conv.state} />
              {conv.channel && (
                <span className="text-[10px] uppercase tracking-wide text-gray-400">
                  {conv.channel}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {showTakeOver && (
            <button
              onClick={handleTakeOver}
              disabled={busy !== null}
              className="rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-amber-600 disabled:opacity-50"
            >
              {busy === "takeOver" ? "…" : "Take over"}
            </button>
          )}
          {showReopen ? (
            <button
              onClick={handleReopen}
              disabled={busy !== null}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50"
            >
              {busy === "reopen" ? "…" : "Reopen"}
            </button>
          ) : (
            <button
              onClick={handleResolve}
              disabled={busy !== null}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {busy === "resolve" ? "…" : "Resolve"}
            </button>
          )}

          {/* Assign — minimum viable: assign to me. Future: list store
              members; we don't have that endpoint cheap yet (see report). */}
          <div className="relative">
            <button
              onClick={() => setAssignOpen((v) => !v)}
              disabled={busy !== null}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {busy === "assign" ? "…" : "Assign"}
            </button>
            {assignOpen && (
              <div
                className="absolute right-0 top-full z-30 mt-1 min-w-[160px] rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
                onMouseLeave={() => setAssignOpen(false)}
              >
                <button
                  onClick={handleAssignToMe}
                  className="block w-full px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-50"
                  disabled={!me}
                >
                  Assign to me
                </button>
                {conv.assignee_user_id && (
                  <p className="border-t border-gray-100 px-3 py-1.5 text-[10px] text-gray-400">
                    Current assignee: {conv.assignee_user_id === me?.id ? "you" : conv.assignee_user_id.slice(0, 8) + "…"}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Banner errors */}
      {error && (
        <div className="border-b border-red-100 bg-red-50 px-5 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 min-h-0">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-gray-400">
            No messages yet.
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                agentName={m.sender_user_id === me?.id ? me.display_name || me.email : null}
              />
            ))}
          </div>
        )}
      </div>

      {/* Composer */}
      <Composer
        onSend={handleSend}
        disabled={composerDisabled}
        hint={composerHint}
        hintAction={
          conv.state === "resolved" ? (
            <button
              onClick={handleReopen}
              className="rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm hover:bg-emerald-700"
            >
              Reopen
            </button>
          ) : null
        }
      />
    </div>
  );
}
