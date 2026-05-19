"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  fetchConversations,
  fetchInboxes,
  fetchLabels,
  type Conversation,
  type Inbox,
  type Label,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatRelative } from "@/lib/format";
import ConvFilters, { type FilterTab, tabToStateFilter } from "./ConvFilters";
import { useVisiblePolling } from "./useVisiblePolling";

const POLL_INTERVAL_MS = 8_000;

/**
 * Resolve the store_id we pass to the conversations list call.
 *
 *  - non-super-admin: always the currently-selected store from localStorage.
 *    `null` shortcuts to "all" but a non-super hitting the API without a
 *    store_id gets 400, so we never let that happen.
 *  - super-admin with a store filter chosen: that store id.
 *  - super-admin on "all": `null` → omit query param entirely.
 */
function resolveStoreFilter(
  isSuperAdmin: boolean,
  superAdminStoreFilter: string | "all"
): string | null | undefined {
  if (isSuperAdmin) {
    return superAdminStoreFilter === "all" ? null : superAdminStoreFilter;
  }
  // Non-super: fall back to the selected store in localStorage. `undefined`
  // → buildStoreQuery() reads localStorage.
  return undefined;
}

function initialsOf(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

function ConversationStateBadge({ state }: { state: Conversation["state"] }) {
  const config: Record<Conversation["state"], { bg: string; text: string; label: string }> = {
    bot_active: { bg: "bg-emerald-50", text: "text-emerald-700", label: "Bot" },
    human_handoff: { bg: "bg-amber-50", text: "text-amber-700", label: "Human" },
    resolved: { bg: "bg-gray-100", text: "text-gray-600", label: "Resolved" },
  };
  const c = config[state] ?? config.bot_active;
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ${c.bg} ${c.text}`}>
      {c.label}
    </span>
  );
}

interface ContactCache {
  [contactId: string]: { name: string | null; avatar_url: string | null };
}

export default function InboxList() {
  const router = useRouter();
  const params = useParams();
  const selectedId = (params?.id as string | undefined) ?? null;
  const { me, myStores } = useAuth();
  const isSuperAdmin = !!me?.is_super_admin;

  const [tab, setTab] = useState<FilterTab>("open");
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [selectedInboxId, setSelectedInboxId] = useState<string>("");
  const [selectedLabelId, setSelectedLabelId] = useState<string>("");
  const [superStoreFilter, setSuperStoreFilter] = useState<string | "all">("all");

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [contactCache, setContactCache] = useState<ContactCache>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const storeFilter = resolveStoreFilter(isSuperAdmin, superStoreFilter);

  // Loads conversation list with the active filter set. Abortable so the
  // polling tick can drop a stale call if filters change mid-flight.
  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const { states, mineOnly } = tabToStateFilter(tab);

        // We can't OR two states in a single backend call (state= takes one
        // value). For the "open" / "mine" tabs we fetch both states and merge.
        const results: Conversation[] = [];
        for (const state of states) {
          const data = await fetchConversations({
            store_id: storeFilter,
            state,
            assignee_user_id: mineOnly && me?.id ? me.id : undefined,
            inbox_id: selectedInboxId || undefined,
            label_id: selectedLabelId || undefined,
            limit: 100,
            signal,
          });
          results.push(...data);
        }
        // Re-sort merged result by last_message_at desc.
        results.sort((a, b) => {
          const at = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
          const bt = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
          return bt - at;
        });
        setConversations(results);
        setError(null);
      } catch (e) {
        if ((e as DOMException)?.name === "AbortError") return;
        setError(e instanceof Error ? e.message : "Failed to load conversations");
      } finally {
        setLoading(false);
      }
    },
    [tab, storeFilter, selectedInboxId, selectedLabelId, me?.id]
  );

  // Initial + filter-driven load with abort-on-change.
  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    void load(ac.signal);
    return () => ac.abort();
  }, [load]);

  // Load inboxes/labels for the current store filter. Cheap, no need to poll.
  useEffect(() => {
    const ac = new AbortController();
    Promise.all([
      fetchInboxes(storeFilter, { signal: ac.signal }).catch(() => [] as Inbox[]),
      fetchLabels(storeFilter, { signal: ac.signal }).catch(() => [] as Label[]),
    ]).then(([ix, lx]) => {
      setInboxes(ix);
      setLabels(lx);
    });
    return () => ac.abort();
  }, [storeFilter]);

  // Polling — re-fetch list every POLL_INTERVAL_MS while tab is visible.
  useVisiblePolling(() => load(), POLL_INTERVAL_MS, true);

  // Hydrate contact names lazily — we render initials/anonymous until we have one.
  // Backend contact-by-id is a cheap call; we batch via Promise.all and
  // dedupe per id with the cache.
  useEffect(() => {
    const missing = conversations
      .map((c) => c.contact_id)
      .filter((id) => !(id in contactCache));
    if (missing.length === 0) return;

    // Dedupe in one pass.
    const unique = Array.from(new Set(missing));
    let cancelled = false;

    (async () => {
      const updates: ContactCache = {};
      // Sequential to keep request volume sane on long lists; each is small.
      for (const id of unique) {
        if (cancelled) return;
        try {
          const { fetchContact } = await import("@/lib/api");
          const c = await fetchContact(id);
          updates[id] = { name: c.name, avatar_url: c.avatar_url };
        } catch {
          updates[id] = { name: null, avatar_url: null };
        }
      }
      if (!cancelled) {
        setContactCache((prev) => ({ ...prev, ...updates }));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [conversations, contactCache]);

  const stores = useMemo(
    () => myStores.map((s) => ({ id: s.id, name: s.name })),
    [myStores]
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="px-4 pt-4 pb-2">
        <h2 className="text-sm font-bold text-gray-900">Conversations</h2>
        <p className="text-[11px] text-gray-500 mt-0.5">
          {loading ? "Loading…" : `${conversations.length} thread${conversations.length === 1 ? "" : "s"}`}
        </p>
      </div>

      <ConvFilters
        tab={tab}
        onTabChange={setTab}
        inboxes={inboxes}
        selectedInboxId={selectedInboxId}
        onInboxChange={setSelectedInboxId}
        labels={labels}
        selectedLabelId={selectedLabelId}
        onLabelChange={setSelectedLabelId}
        stores={isSuperAdmin ? stores : undefined}
        selectedStoreId={isSuperAdmin ? superStoreFilter : undefined}
        onStoreChange={isSuperAdmin ? (v) => setSuperStoreFilter(v) : undefined}
      />

      {/* List */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {error && (
          <div className="m-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        {loading && conversations.length === 0 ? (
          <SkeletonList />
        ) : conversations.length === 0 ? (
          <div className="px-6 py-12 text-center text-xs text-gray-400">
            No conversations
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {conversations.map((c) => {
              const contact = contactCache[c.contact_id];
              const name = contact?.name || "Anonymous";
              const isSelected = c.id === selectedId;
              return (
                <li key={c.id}>
                  <button
                    onClick={() => router.push(`/conversations/${c.id}`)}
                    className={`flex w-full items-start gap-3 px-3 py-3 text-left transition-colors ${
                      isSelected
                        ? "bg-brand-50/70"
                        : "hover:bg-gray-50"
                    }`}
                  >
                    {/* Avatar */}
                    <div className="shrink-0">
                      {contact?.avatar_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={contact.avatar_url}
                          alt=""
                          className="h-9 w-9 rounded-full object-cover"
                        />
                      ) : (
                        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gray-200 text-[11px] font-bold text-gray-600">
                          {initialsOf(contact?.name)}
                        </div>
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p
                          className={`truncate text-sm font-semibold ${
                            isSelected ? "text-brand-700" : "text-gray-900"
                          }`}
                        >
                          {name}
                        </p>
                        <span className="shrink-0 text-[10px] text-gray-400">
                          {formatRelative(c.last_message_at)}
                        </span>
                      </div>

                      <p className="mt-0.5 truncate text-xs text-gray-500">
                        {c.last_message_preview || (
                          <span className="italic text-gray-300">No messages yet</span>
                        )}
                      </p>

                      <div className="mt-1.5 flex items-center gap-1.5">
                        <ConversationStateBadge state={c.state} />
                        {c.channel && (
                          <span className="text-[10px] uppercase tracking-wide text-gray-400">
                            {c.channel}
                          </span>
                        )}
                        {c.unread_agent_count > 0 && (
                          <span
                            className="ml-auto inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-600 px-1 text-[10px] font-bold text-white"
                            title={`${c.unread_agent_count} unread`}
                          >
                            {c.unread_agent_count}
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

function SkeletonList() {
  return (
    <ul className="divide-y divide-gray-100">
      {Array.from({ length: 6 }).map((_, i) => (
        <li key={i} className="flex items-start gap-3 px-3 py-3">
          <div className="h-9 w-9 shrink-0 animate-pulse rounded-full bg-gray-200" />
          <div className="flex-1 space-y-1.5">
            <div className="h-3 w-2/3 animate-pulse rounded bg-gray-200" />
            <div className="h-2.5 w-full animate-pulse rounded bg-gray-100" />
            <div className="h-2 w-1/3 animate-pulse rounded bg-gray-100" />
          </div>
        </li>
      ))}
    </ul>
  );
}
