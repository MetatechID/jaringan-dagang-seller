"use client";

import type { Inbox, Label, ConversationState } from "@/lib/api";

export type FilterTab = "open" | "mine" | "resolved";

export interface ConvFiltersProps {
  tab: FilterTab;
  onTabChange: (tab: FilterTab) => void;
  inboxes: Inbox[];
  selectedInboxId: string | "";
  onInboxChange: (id: string | "") => void;
  labels: Label[];
  selectedLabelId: string | "";
  onLabelChange: (id: string | "") => void;
  // Super-admin only — undefined means "not a super-admin" so the dropdown is hidden.
  stores?: { id: string; name: string }[];
  selectedStoreId?: string | "all";
  onStoreChange?: (id: string | "all") => void;
}

const TABS: { key: FilterTab; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "mine", label: "Mine" },
  { key: "resolved", label: "Resolved" },
];

export function tabToStateFilter(tab: FilterTab): {
  states: ConversationState[];
  mineOnly: boolean;
} {
  if (tab === "open") return { states: ["bot_active", "human_handoff"], mineOnly: false };
  if (tab === "mine") return { states: ["bot_active", "human_handoff"], mineOnly: true };
  return { states: ["resolved"], mineOnly: false };
}

export default function ConvFilters({
  tab,
  onTabChange,
  inboxes,
  selectedInboxId,
  onInboxChange,
  labels,
  selectedLabelId,
  onLabelChange,
  stores,
  selectedStoreId,
  onStoreChange,
}: ConvFiltersProps) {
  return (
    <div className="space-y-2 px-3 pt-3 pb-2 border-b border-gray-100">
      {/* Tabs */}
      <div className="flex items-center gap-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => onTabChange(t.key)}
            className={`flex-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
              tab === t.key
                ? "bg-brand-50 text-brand-700"
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Compact dropdowns */}
      <div className="grid grid-cols-2 gap-1.5">
        <select
          value={selectedInboxId}
          onChange={(e) => onInboxChange(e.target.value)}
          className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500/30"
          aria-label="Filter by inbox"
        >
          <option value="">All inboxes</option>
          {inboxes.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>
        <select
          value={selectedLabelId}
          onChange={(e) => onLabelChange(e.target.value)}
          className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500/30"
          aria-label="Filter by label"
        >
          <option value="">All labels</option>
          {labels.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </div>

      {stores && onStoreChange && (
        <select
          value={selectedStoreId ?? "all"}
          onChange={(e) => onStoreChange(e.target.value as string)}
          className="w-full rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500/30"
          aria-label="Filter by store"
        >
          <option value="all">All stores (super-admin)</option>
          {stores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
