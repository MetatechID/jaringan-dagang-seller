"use client";

import { useCallback, useEffect, useState } from "react";
import {
  attachLabel,
  detachLabel,
  fetchContact,
  fetchConversation,
  fetchLabels,
  type Conversation,
  type ContactDetail,
  type Label,
} from "@/lib/api";
import { formatDate, formatIDR } from "@/lib/format";
import LoadingSpinner from "@/components/LoadingSpinner";

interface ContactPanelProps {
  conversationId: string;
}

export default function ContactPanel({ conversationId }: ContactPanelProps) {
  const [contact, setContact] = useState<ContactDetail | null>(null);
  const [conv, setConv] = useState<Conversation | null>(null);
  const [labels, setLabels] = useState<Label[]>([]);
  // Conversation-attached labels: we get the labels list, but not which are
  // attached. For now we maintain a local set; toggling persists via API.
  const [attachedIds, setAttachedIds] = useState<Set<string>>(new Set());
  const [pickerOpen, setPickerOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (signal?: AbortSignal) => {
    try {
      const c = await fetchConversation(conversationId, { signal });
      setConv(c);
      const ct = await fetchContact(c.contact_id, { signal });
      setContact(ct);
      const allLabels = await fetchLabels(c.store_id, { signal });
      setLabels(allLabels);
      setError(null);
    } catch (e) {
      if ((e as DOMException)?.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "Failed to load contact");
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setContact(null);
    setConv(null);
    setAttachedIds(new Set());
    void reload(ac.signal);
    return () => ac.abort();
  }, [reload]);

  async function toggleLabel(labelId: string, isAttached: boolean) {
    if (!conv) return;
    setAttachedIds((prev) => {
      const next = new Set(prev);
      if (isAttached) next.delete(labelId);
      else next.add(labelId);
      return next;
    });
    try {
      if (isAttached) {
        await detachLabel(conv.id, labelId);
      } else {
        await attachLabel(conv.id, labelId);
      }
    } catch (e) {
      // Roll back optimistic UI
      setAttachedIds((prev) => {
        const next = new Set(prev);
        if (isAttached) next.add(labelId);
        else next.delete(labelId);
        return next;
      });
      setError(e instanceof Error ? e.message : "Label update failed");
    }
  }

  if (loading) return <LoadingSpinner />;
  if (error && !contact) {
    return <div className="p-6 text-xs text-red-600">{error}</div>;
  }
  if (!contact || !conv) {
    return <div className="p-6 text-xs text-gray-400">No contact information.</div>;
  }

  const attributes = contact.attributes && typeof contact.attributes === "object"
    ? Object.entries(contact.attributes as Record<string, unknown>)
    : [];

  return (
    <div className="p-5 space-y-6">
      {/* Identity */}
      <section>
        <div className="flex items-center gap-3">
          {contact.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={contact.avatar_url} alt="" className="h-12 w-12 rounded-full object-cover" />
          ) : (
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-gray-200 text-sm font-bold text-gray-600">
              {(contact.name?.[0] || "?").toUpperCase()}
            </div>
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-gray-900">
              {contact.name || "Anonymous"}
            </p>
            {contact.email && (
              <p className="truncate text-xs text-gray-500">{contact.email}</p>
            )}
          </div>
        </div>
        <dl className="mt-4 space-y-2 text-xs">
          {contact.phone && (
            <Row label="Phone" value={contact.phone} />
          )}
          {contact.external_id && (
            <Row label="External ID" value={<code className="font-mono text-[11px]">{contact.external_id}</code>} />
          )}
          <Row
            label="First seen"
            value={contact.created_at ? formatDate(contact.created_at) : "—"}
          />
        </dl>
      </section>

      {/* Conversation meta */}
      <section>
        <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-2">
          Conversation
        </h3>
        <dl className="space-y-2 text-xs">
          <Row label="Channel" value={conv.channel || "—"} />
          <Row label="State" value={conv.state.replace("_", " ")} />
          <Row
            label="Assignee"
            value={conv.assignee_user_id ? <code className="font-mono text-[11px]">{conv.assignee_user_id.slice(0, 8)}…</code> : "—"}
          />
          <Row
            label="Started"
            value={conv.created_at ? formatDate(conv.created_at) : "—"}
          />
          <Row
            label="Last message"
            value={conv.last_message_at ? formatDate(conv.last_message_at) : "—"}
          />
        </dl>
      </section>

      {/* Labels */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-400">
            Labels
          </h3>
          <button
            onClick={() => setPickerOpen((v) => !v)}
            className="text-[11px] font-semibold text-brand-600 hover:text-brand-700"
          >
            {pickerOpen ? "Close" : "+ Add label"}
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {Array.from(attachedIds).length === 0 && !pickerOpen && (
            <span className="text-xs text-gray-400">No labels attached.</span>
          )}
          {Array.from(attachedIds).map((id) => {
            const l = labels.find((x) => x.id === id);
            if (!l) return null;
            return <LabelChip key={id} label={l} onRemove={() => toggleLabel(id, true)} />;
          })}
        </div>
        {pickerOpen && (
          <div className="mt-2 rounded-lg border border-gray-200 bg-gray-50 p-2 space-y-1">
            {labels.length === 0 && (
              <p className="text-xs text-gray-400 px-1">No labels in this store.</p>
            )}
            {labels.map((l) => {
              const attached = attachedIds.has(l.id);
              return (
                <button
                  key={l.id}
                  onClick={() => toggleLabel(l.id, attached)}
                  className={`flex w-full items-center justify-between rounded px-2 py-1 text-xs ${
                    attached ? "bg-brand-50 text-brand-700" : "text-gray-700 hover:bg-white"
                  }`}
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ backgroundColor: l.color || "#94a3b8" }}
                    />
                    {l.name}
                  </span>
                  {attached ? <span>✓</span> : null}
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* Attributes */}
      {attributes.length > 0 && (
        <section>
          <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-2">
            Attributes
          </h3>
          <dl className="space-y-1.5 text-xs">
            {attributes.map(([k, v]) => (
              <Row key={k} label={k} value={String(v)} />
            ))}
          </dl>
        </section>
      )}

      {/* Linked orders */}
      <section>
        <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-2">
          Linked orders ({contact.orders.length})
        </h3>
        {contact.orders.length === 0 ? (
          <p className="text-xs text-gray-400">
            No orders linked to this contact yet.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {contact.orders.map((o) => (
              <li key={o.id}>
                <a
                  href={`/orders/${o.id}`}
                  className="block rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs hover:border-brand-300 hover:bg-brand-50/30 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] text-brand-600">
                      #{o.beckn_order_id?.slice(0, 8) || o.id.slice(0, 8)}
                    </span>
                    <span className="font-semibold text-gray-900">
                      {formatIDR(o.total)}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between text-[10px] text-gray-500">
                    <span>{o.status}</span>
                    <span>{o.created_at ? formatDate(o.created_at) : ""}</span>
                  </div>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-gray-900 text-right break-all">{value}</dd>
    </div>
  );
}

function LabelChip({ label, onRemove }: { label: Label; onRemove: () => void }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs"
      style={
        label.color
          ? {
              backgroundColor: `${label.color}1a`, // ~10% alpha
              color: label.color,
            }
          : undefined
      }
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: label.color || "#94a3b8" }}
      />
      {label.name}
      <button
        onClick={onRemove}
        aria-label={`Remove ${label.name}`}
        className="ml-0.5 text-gray-400 hover:text-gray-700"
      >
        ×
      </button>
    </span>
  );
}
