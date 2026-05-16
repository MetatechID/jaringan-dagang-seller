"use client";

import { useCallback, useEffect, useState } from "react";

interface Refund {
  id: string;
  order_id: string;
  requested_by: string;
  reason_code: string;
  reason_text: string | null;
  requested_amount: number;
  status: string;
  seller_note: string | null;
  decided_at: string | null;
  decided_by: string | null;
  xendit_refund_id: string | null;
  error: string | null;
  created_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

const STATUS_FILTERS = ["pending", "approved", "denied", "refunded", "failed"] as const;

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  approved: "bg-blue-100 text-blue-800",
  refunded: "bg-green-100 text-green-800",
  denied: "bg-gray-100 text-gray-800",
  failed: "bg-red-100 text-red-800",
};

function formatIDR(n: number) {
  return "Rp " + n.toLocaleString("id-ID");
}

export default function RefundsPage() {
  const [refunds, setRefunds] = useState<Refund[]>([]);
  const [filter, setFilter] = useState<string>("pending");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    const q = filter ? `?status=${filter}` : "";
    const res = await fetch(`${API_BASE}/api/refunds${q}`);
    const json = await res.json();
    setRefunds(json.data || []);
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  async function decide(id: string, action: "approve" | "deny") {
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      const res = await fetch(`${API_BASE}/api/refunds/${id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: notes[id] || null }),
      });
      if (!res.ok) {
        const err = await res.text();
        alert(`${action} failed: ${err}`);
      } else {
        setNotes((n) => ({ ...n, [id]: "" }));
        await load();
      }
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Refund requests</h1>
          <p className="text-sm text-slate-500 mt-1">
            Buyer-initiated refunds via Beckn /update. Approving calls Xendit
            and emits /on_update back to the BAP.
          </p>
        </div>
        <button
          onClick={load}
          className="text-sm px-3 py-1.5 border rounded hover:bg-slate-50"
        >
          Reload
        </button>
      </div>

      <div className="flex gap-2 mb-4">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1.5 text-sm rounded-full border ${
              filter === s
                ? "bg-slate-900 text-white border-slate-900"
                : "bg-white text-slate-700 border-slate-200 hover:border-slate-400"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {refunds.length === 0 ? (
        <div className="text-sm text-slate-500 border rounded p-8 text-center">
          No {filter} refunds.
        </div>
      ) : (
        <div className="space-y-3">
          {refunds.map((r) => (
            <div key={r.id} className="border rounded-lg p-4 bg-white">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLORS[r.status] || ""}`}>
                      {r.status}
                    </span>
                    <span className="text-sm font-mono text-slate-500 truncate">
                      order {r.order_id}
                    </span>
                  </div>
                  <div className="text-sm">
                    <span className="font-medium">{r.reason_code}</span>
                    {r.reason_text && <span className="text-slate-600"> — {r.reason_text}</span>}
                  </div>
                  <div className="text-sm text-slate-600 mt-1">
                    Amount: <span className="font-medium">{formatIDR(r.requested_amount)}</span> · {r.requested_by} · {new Date(r.created_at).toLocaleString()}
                  </div>
                  {r.seller_note && (
                    <div className="text-sm text-slate-500 mt-1 italic">Note: {r.seller_note}</div>
                  )}
                  {r.xendit_refund_id && (
                    <div className="text-xs text-slate-400 mt-1 font-mono">xendit: {r.xendit_refund_id}</div>
                  )}
                  {r.error && (
                    <div className="text-xs text-red-600 mt-1">Error: {r.error}</div>
                  )}
                </div>
                {r.status === "pending" && (
                  <div className="flex items-center gap-2 shrink-0">
                    <input
                      type="text"
                      placeholder="optional note"
                      value={notes[r.id] || ""}
                      onChange={(e) => setNotes((n) => ({ ...n, [r.id]: e.target.value }))}
                      className="text-sm border rounded px-2 py-1 w-40"
                    />
                    <button
                      onClick={() => decide(r.id, "approve")}
                      disabled={busy[r.id]}
                      className="text-sm px-3 py-1.5 bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => decide(r.id, "deny")}
                      disabled={busy[r.id]}
                      className="text-sm px-3 py-1.5 bg-slate-700 text-white rounded hover:bg-slate-800 disabled:opacity-50"
                    >
                      Deny
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
