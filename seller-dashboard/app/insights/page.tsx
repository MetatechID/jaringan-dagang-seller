"use client";

import { useEffect, useState } from "react";

import {
  fetchInsightsOverview,
  fetchSegments,
  fetchCrossMerchant,
  type InsightsOverview,
  type SegmentBreakdown,
  type CrossMerchantInsights,
  type CustomerSegment,
} from "@/lib/api";
import { formatIDR } from "@/lib/format";
import LoadingSpinner from "@/components/LoadingSpinner";

const SEGMENT_LABEL: Record<CustomerSegment, string> = {
  CHAMPION: "Champion", HIGH_LTV: "High LTV", REPEAT: "Repeat",
  NEW: "New", ONE_TIME: "One-time", AT_RISK: "At Risk", INACTIVE: "Inactive",
};
const SEGMENT_COLOR: Record<CustomerSegment, string> = {
  CHAMPION: "bg-emerald-500", HIGH_LTV: "bg-violet-500", REPEAT: "bg-blue-500",
  NEW: "bg-amber-500", ONE_TIME: "bg-gray-400", AT_RISK: "bg-red-500", INACTIVE: "bg-gray-300",
};

export default function InsightsPage() {
  const [overview, setOverview] = useState<InsightsOverview | null>(null);
  const [segments, setSegments] = useState<SegmentBreakdown | null>(null);
  const [cross, setCross] = useState<CrossMerchantInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchInsightsOverview(days).then(setOverview),
      fetchSegments().then(setSegments),
      fetchCrossMerchant().then(setCross),
    ])
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [days]);

  if (loading) return <LoadingSpinner />;
  if (!overview) return <div className="p-6 text-sm text-red-600">No data</div>;

  const m = overview.metrics;
  const ba = m.beli_aman;

  return (
    <div className="p-6 lg:p-8 space-y-8 max-w-6xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Insights</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Buyer behavior + anonymized cross-merchant patterns from the Beli Aman network
          </p>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={365}>Last year</option>
        </select>
      </div>

      {/* Top-line metrics */}
      <section>
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">
          Past {overview.window_days} days
        </h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label="Orders" value={String(m.total_orders)} />
          <Stat label="Revenue" value={formatIDR(m.total_revenue_idr)} accent="default" />
          <Stat label="Unique buyers" value={String(m.unique_buyers)} />
          <Stat label="Avg order value" value={formatIDR(m.average_order_value_idr)} />
        </div>
      </section>

      {/* Beli Aman vs Direct comparison */}
      <section>
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">
          Beli Aman performance
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-xl border-2 border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xl">🛡️</span>
              <h4 className="font-bold text-emerald-800">via Beli Aman</h4>
              <span className="ml-auto px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-xs font-bold">
                {ba.pct_of_orders}% of orders
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Cell label="Orders" value={String(ba.orders)} />
              <Cell label="Buyers" value={String(ba.buyers)} />
              <Cell label="Revenue" value={formatIDR(ba.revenue_idr)} />
              <Cell label="AOV" value={formatIDR(ba.average_order_value_idr)} />
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xl">📦</span>
              <h4 className="font-bold text-gray-700">Direct + Beckn</h4>
              <span className="ml-auto px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 text-xs font-bold">
                {(100 - ba.pct_of_orders).toFixed(1)}% of orders
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Cell label="Orders" value={String(m.total_orders - ba.orders)} />
              <Cell label="Buyers" value={String(m.unique_buyers - ba.buyers)} />
              <Cell label="Revenue" value={formatIDR(m.total_revenue_idr - ba.revenue_idr)} />
              <Cell label="AOV" value={formatIDR(
                m.total_orders - ba.orders > 0
                  ? Math.round((m.total_revenue_idr - ba.revenue_idr) / (m.total_orders - ba.orders))
                  : 0,
              )} />
            </div>
          </div>
        </div>
      </section>

      {/* Repeat buyer rate */}
      <section className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="flex items-center justify-between gap-4 mb-2">
          <h4 className="font-bold text-gray-900">Repeat-buyer rate</h4>
          <span className="text-2xl font-bold text-brand-700">{m.repeat_buyer_pct}%</span>
        </div>
        <p className="text-sm text-gray-500">
          {m.repeat_buyer_count} of {m.unique_buyers} buyers placed more than one order in the
          past {overview.window_days} days.
        </p>
        <div className="mt-3 h-2 bg-gray-100 rounded-full overflow-hidden">
          <div className="h-full bg-brand-500" style={{ width: `${m.repeat_buyer_pct}%` }} />
        </div>
      </section>

      {/* Segment breakdown */}
      {segments && segments.total_buyers > 0 ? (
        <section>
          <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">
            Customer segments ({segments.total_buyers} buyers all-time)
          </h3>
          <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-3">
            {segments.segments.map((s) => {
              const pct = (s.buyer_count / segments.total_buyers) * 100;
              return (
                <div key={s.segment}>
                  <div className="flex items-center justify-between text-sm mb-1">
                    <span className="font-semibold text-gray-700">
                      {SEGMENT_LABEL[s.segment]}
                    </span>
                    <span className="text-gray-500">
                      {s.buyer_count} buyers · {formatIDR(s.revenue_idr)}
                    </span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${SEGMENT_COLOR[s.segment]}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {/* Cross-merchant insights */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500">
            🌐 Cross-merchant insights (anonymized)
          </h3>
          {cross?.available ? (
            <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-xs font-semibold">
              Live · {cross.buyer_cohort_size} buyers
            </span>
          ) : null}
        </div>

        {!cross?.available ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 bg-gray-50 p-8 text-center">
            <div className="text-3xl mb-2">🔒</div>
            <h4 className="font-bold text-gray-700">Insights unlock as your cohort grows</h4>
            <p className="text-sm text-gray-500 mt-2 max-w-md mx-auto">{cross?.reason}</p>
            <div className="mt-4">
              <span className="text-xs text-gray-500">Current: </span>
              <span className="font-semibold text-gray-700">{cross?.current_buyer_count || 0}</span>
              <span className="text-xs text-gray-500"> / </span>
              <span className="font-semibold text-gray-700">{cross?.threshold || 3}</span>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Patterns */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {cross.patterns?.map((p) => (
                <div key={p.pattern} className="rounded-xl border border-gray-200 bg-white p-5">
                  <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold">
                    {p.pattern}
                  </div>
                  <div className="text-base font-bold text-gray-900 mt-1">{p.headline}</div>
                  <p className="text-sm text-gray-600 mt-2">{p.detail}</p>
                </div>
              ))}
            </div>

            {/* Demographics */}
            {cross.demographic_aggregates ? (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <DemoBlock
                  title="Geography"
                  rows={cross.demographic_aggregates.geography}
                />
                <DemoBlock
                  title="Device"
                  rows={cross.demographic_aggregates.device_mix}
                />
                <DemoBlock
                  title="Payment method"
                  rows={cross.demographic_aggregates.payment_method_mix}
                />
              </div>
            ) : null}

            <div className="rounded-lg bg-gray-50 border border-gray-200 px-4 py-3 text-xs text-gray-500 flex items-start gap-2">
              <span>🔐</span>
              <span>{cross.privacy_note} {cross.data_freshness}</span>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "default" | "emerald";
}) {
  return (
    <div className={`rounded-xl border p-4 ${
      accent === "emerald" ? "border-emerald-200 bg-emerald-50/50" : "border-gray-200 bg-white"
    }`}>
      <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold">{label}</div>
      <div className="text-xl font-bold text-gray-900 mt-1">{value}</div>
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
        {label}
      </div>
      <div className="font-bold text-gray-900 mt-0.5">{value}</div>
    </div>
  );
}

function DemoBlock({ title, rows }: { title: string; rows: { label: string; pct: number }[] }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">
        {title}
      </div>
      <div className="space-y-2">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-gray-700">{r.label}</span>
              <span className="font-semibold text-gray-900">{r.pct}%</span>
            </div>
            <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-brand-500" style={{ width: `${r.pct}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
