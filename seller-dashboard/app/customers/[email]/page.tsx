"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { fetchCustomer, type CustomerDetail, type CustomerSegment } from "@/lib/api";
import { formatIDR, formatDate } from "@/lib/format";
import LoadingSpinner from "@/components/LoadingSpinner";

const SEGMENT_STYLE: Record<CustomerSegment, { bg: string; fg: string; label: string; blurb: string }> = {
  CHAMPION: {
    bg: "bg-emerald-100", fg: "text-emerald-800", label: "Champion",
    blurb: "High-value repeat buyer. Reach out — they're your most loyal.",
  },
  HIGH_LTV: {
    bg: "bg-violet-100", fg: "text-violet-800", label: "High LTV",
    blurb: "Has spent significantly. Worth nurturing back to active.",
  },
  REPEAT: {
    bg: "bg-blue-100", fg: "text-blue-800", label: "Repeat",
    blurb: "Returning buyer. Strong product fit signal.",
  },
  NEW: {
    bg: "bg-amber-100", fg: "text-amber-800", label: "New",
    blurb: "Recent first purchase. Send a welcome / education flow.",
  },
  ONE_TIME: {
    bg: "bg-gray-100", fg: "text-gray-700", label: "One-time",
    blurb: "Bought once, hasn't returned. Re-engagement target.",
  },
  AT_RISK: {
    bg: "bg-red-100", fg: "text-red-800", label: "At Risk",
    blurb: "Hasn't ordered in 90+ days. Win-back campaign candidate.",
  },
  INACTIVE: {
    bg: "bg-gray-100", fg: "text-gray-500", label: "Inactive",
    blurb: "No recent activity.",
  },
};

export default function CustomerDetailPage() {
  const params = useParams<{ email: string }>();
  const email = decodeURIComponent(params.email as string);

  const [detail, setDetail] = useState<CustomerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCustomer(email)
      .then((r) => setDetail(r.data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [email]);

  if (loading) return <LoadingSpinner />;
  if (error || !detail) return (
    <div className="p-6 text-center text-sm text-red-600">{error || "Customer not found"}</div>
  );

  const seg = SEGMENT_STYLE[detail.segment] || SEGMENT_STYLE.INACTIVE;

  return (
    <div className="p-6 lg:p-8 max-w-5xl space-y-6">
      <div className="flex items-center gap-2 text-sm">
        <Link href="/customers" className="text-gray-500 hover:text-gray-700">Customers</Link>
        <span className="text-gray-300">/</span>
        <span className="text-gray-900 font-medium">{detail.name}</span>
      </div>

      {/* Identity card */}
      <div className="card p-6 flex items-start gap-5">
        {detail.photo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={detail.photo_url} alt="" className="w-16 h-16 rounded-full" />
        ) : (
          <div className="w-16 h-16 rounded-full bg-brand-100 grid place-items-center text-2xl font-bold text-brand-700">
            {detail.name.slice(0, 1).toUpperCase()}
          </div>
        )}
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-2xl font-bold text-gray-900">{detail.name}</h1>
            {detail.is_beli_aman_buyer ? (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-xs font-semibold border border-emerald-100">
                ✓ Verified Google · via Beli Aman
              </span>
            ) : null}
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${seg.bg} ${seg.fg}`}>
              {seg.label}
            </span>
          </div>
          <div className="text-gray-500 text-sm mt-1">{detail.email}</div>
          {detail.phone ? <div className="text-gray-500 text-sm">{detail.phone}</div> : null}
          <p className="text-xs text-gray-500 mt-3 italic">{seg.blurb}</p>
        </div>
      </div>

      {/* Top metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Metric label="Total orders" value={String(detail.order_count)} />
        <Metric label="Lifetime value" value={formatIDR(detail.lifetime_value_idr)} accent />
        <Metric
          label="First order"
          value={detail.first_order_at ? formatDate(detail.first_order_at) : "—"}
        />
        <Metric
          label="Last order"
          value={
            detail.days_since_last_order != null
              ? detail.days_since_last_order === 0
                ? "today"
                : `${detail.days_since_last_order}d ago`
              : "—"
          }
        />
      </div>

      {/* Order history */}
      <section>
        <h3 className="text-sm font-bold text-gray-900 mb-2 uppercase tracking-wider">
          Order history ({detail.orders.length})
        </h3>
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                <th className="px-5 py-3 text-left font-medium text-gray-500">Order</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500">Source</th>
                <th className="px-5 py-3 text-right font-medium text-gray-500">Total</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500">Status</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500">Escrow</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {detail.orders.map((o) => (
                <tr
                  key={o.id}
                  className="hover:bg-gray-50/50 transition-colors cursor-pointer"
                  onClick={() => (window.location.href = `/orders/${o.id}`)}
                >
                  <td className="px-5 py-3.5 font-mono text-xs text-brand-700 font-medium">
                    #{(o.beckn_order_id || o.id).slice(0, 8)}
                  </td>
                  <td className="px-5 py-3.5">
                    {o.bap_id ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 border border-emerald-100">
                        🛡️ Beli Aman
                      </span>
                    ) : (
                      <span className="text-xs text-gray-500">Direct</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-right font-semibold text-gray-900">
                    {formatIDR(o.total)}
                  </td>
                  <td className="px-5 py-3.5">
                    <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 border border-blue-100">
                      {o.status}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    {o.escrow_status === "none" ? (
                      <span className="text-xs text-gray-400">—</span>
                    ) : (
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                        o.escrow_status === "held" ? "bg-amber-50 text-amber-700 border border-amber-100" :
                        o.escrow_status === "released" ? "bg-emerald-50 text-emerald-700 border border-emerald-100" :
                        "bg-red-50 text-red-700 border border-red-100"
                      }`}>
                        {o.escrow_status.toUpperCase()}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-gray-500">{formatDate(o.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Beli Aman value-prop note */}
      {detail.is_beli_aman_buyer ? (
        <div className="rounded-xl border-2 border-emerald-100 bg-gradient-to-br from-emerald-50/40 to-white p-5">
          <div className="flex items-start gap-3">
            <div className="text-2xl">🛡️</div>
            <div>
              <h4 className="font-bold text-emerald-800">This buyer came via Beli Aman</h4>
              <p className="text-sm text-gray-700 mt-1">
                Their identity is Google-verified. Email is authentic. You own this customer
                relationship — Beli Aman doesn't get between you. On marketplaces this same buyer
                would be anonymous.
              </p>
              <p className="text-xs text-gray-500 mt-2">
                {detail.beli_aman_pct}% of their orders with you came via Beli Aman.
              </p>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl border p-4 ${accent ? "border-violet-200 bg-violet-50/50" : "border-gray-200 bg-white"}`}>
      <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold">{label}</div>
      <div className={`text-lg font-bold mt-1 ${accent ? "text-violet-700" : "text-gray-900"}`}>{value}</div>
    </div>
  );
}
