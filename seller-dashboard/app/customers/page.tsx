"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import {
  fetchCustomers,
  type CustomerSummary,
  type CustomerListResponse,
  type CustomerSegment,
} from "@/lib/api";
import { formatIDR } from "@/lib/format";
import LoadingSpinner from "@/components/LoadingSpinner";

const SEGMENT_STYLE: Record<CustomerSegment, { bg: string; fg: string; label: string }> = {
  CHAMPION: { bg: "bg-emerald-100", fg: "text-emerald-800", label: "Champion" },
  HIGH_LTV: { bg: "bg-violet-100", fg: "text-violet-800", label: "High LTV" },
  REPEAT: { bg: "bg-blue-100", fg: "text-blue-800", label: "Repeat" },
  NEW: { bg: "bg-amber-100", fg: "text-amber-800", label: "New" },
  ONE_TIME: { bg: "bg-gray-100", fg: "text-gray-700", label: "One-time" },
  AT_RISK: { bg: "bg-red-100", fg: "text-red-800", label: "At Risk" },
  INACTIVE: { bg: "bg-gray-100", fg: "text-gray-500", label: "Inactive" },
};

const SOURCE_FILTERS: { key: "all" | "beli_aman" | "direct"; label: string }[] = [
  { key: "all", label: "All Customers" },
  { key: "beli_aman", label: "via Beli Aman" },
  { key: "direct", label: "Direct" },
];

export default function CustomersPage() {
  const [data, setData] = useState<CustomerListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<"all" | "beli_aman" | "direct">("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    setLoading(true);
    fetchCustomers(source === "all" ? undefined : source)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [source]);

  const filtered = useMemo(() => {
    if (!data?.data) return [] as CustomerSummary[];
    if (!search) return data.data;
    const q = search.toLowerCase();
    return data.data.filter(
      (c) => c.name.toLowerCase().includes(q) || c.email.toLowerCase().includes(q),
    );
  }, [data, search]);

  if (loading) return <LoadingSpinner />;
  if (!data) return <div className="p-6 text-sm text-red-600">{error || "No data"}</div>;

  return (
    <div className="p-6 lg:p-8 space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900">Customers</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          {data.summary.total_customers} unique buyer{data.summary.total_customers !== 1 ? "s" : ""} across all orders
        </p>
      </div>

      {/* Top metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard label="Total customers" value={String(data.summary.total_customers)} />
        <MetricCard
          label="via Beli Aman"
          value={`${data.summary.beli_aman_customers}`}
          sub={`${data.summary.beli_aman_pct}% of total · verified Google ID`}
          accent="emerald"
        />
        <MetricCard label="Lifetime value" value={formatIDR(data.summary.total_lifetime_value_idr)} />
        <MetricCard
          label="Average LTV per customer"
          value={formatIDR(data.summary.average_lifetime_value_idr)}
        />
      </div>

      {/* Filter chips */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {SOURCE_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setSource(f.key)}
            className={`shrink-0 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors ${
              source === f.key
                ? "bg-brand-50 text-brand-700"
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            }`}
          >
            {f.label}
            {f.key === "beli_aman" ? (
              <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-xs ${
                source === f.key ? "bg-brand-100 text-brand-700" : "bg-emerald-100 text-emerald-700"
              }`}>
                {data.summary.beli_aman_customers}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <input
          type="text"
          placeholder="Search by name or email..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="input pl-3"
        />
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="card p-12 text-center text-sm text-gray-500">
          No customers match your filter yet. Once buyers place orders, they'll show up here.
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Customer</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Source</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Segment</th>
                  <th className="px-5 py-3 text-right font-medium text-gray-500">Orders</th>
                  <th className="px-5 py-3 text-right font-medium text-gray-500">LTV</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Last order</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((c) => {
                  const seg = SEGMENT_STYLE[c.segment] || SEGMENT_STYLE.INACTIVE;
                  return (
                    <tr
                      key={c.email}
                      className="group hover:bg-gray-50/50 transition-colors cursor-pointer"
                      onClick={() => (window.location.href = `/customers/${encodeURIComponent(c.email)}`)}
                    >
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          {c.photo_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={c.photo_url} alt="" className="w-9 h-9 rounded-full" />
                          ) : (
                            <div className="w-9 h-9 rounded-full bg-gray-200 grid place-items-center text-xs font-bold text-gray-500">
                              {c.name.slice(0, 1).toUpperCase()}
                            </div>
                          )}
                          <div>
                            <div className="font-semibold text-gray-900 group-hover:text-brand-700">
                              {c.name}
                            </div>
                            <div className="text-xs text-gray-500">{c.email}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-3.5">
                        {c.is_beli_aman_buyer ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 border border-emerald-100">
                            🛡️ Beli Aman
                          </span>
                        ) : (
                          <span className="inline-flex items-center rounded-full bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-600 border border-gray-100">
                            Direct
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3.5">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${seg.bg} ${seg.fg}`}>
                          {seg.label}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-right font-semibold text-gray-900">
                        {c.order_count}
                      </td>
                      <td className="px-5 py-3.5 text-right font-semibold text-gray-900">
                        {formatIDR(c.lifetime_value_idr)}
                      </td>
                      <td className="px-5 py-3.5 text-gray-500">
                        {c.days_since_last_order != null
                          ? c.days_since_last_order === 0
                            ? "today"
                            : `${c.days_since_last_order}d ago`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "emerald" | "violet";
}) {
  const accentClass =
    accent === "emerald"
      ? "border-emerald-200 bg-emerald-50/50"
      : accent === "violet"
        ? "border-violet-200 bg-violet-50/50"
        : "border-gray-200 bg-white";
  return (
    <div className={`rounded-xl border p-4 ${accentClass}`}>
      <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold">{label}</div>
      <div className="text-xl font-bold text-gray-900 mt-1">{value}</div>
      {sub ? <div className="text-xs text-gray-500 mt-1">{sub}</div> : null}
    </div>
  );
}
