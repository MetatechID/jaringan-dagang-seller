"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fetchOrder,
  isBeliAman,
  updateOrderStatus,
  type EscrowStatus,
  type Order,
  type OrderStatus,
} from "@/lib/api";
import { formatIDR, formatDate } from "@/lib/format";
import StatusBadge from "@/components/StatusBadge";
import LoadingSpinner from "@/components/LoadingSpinner";

const STATUS_STEPS: { key: OrderStatus; label: string }[] = [
  { key: "created", label: "Created" },
  { key: "accepted", label: "Accepted" },
  { key: "in_progress", label: "In Progress" },
  { key: "completed", label: "Completed" },
];

const STATUS_INDEX: Record<OrderStatus, number> = {
  created: 0,
  accepted: 1,
  in_progress: 2,
  completed: 3,
  cancelled: -1,
};

const NEXT_ACTIONS: Record<
  string,
  { label: string; nextStatus: OrderStatus; color: string } | null
> = {
  created: { label: "Accept Order", nextStatus: "accepted", color: "btn-primary" },
  accepted: { label: "Mark Shipped", nextStatus: "in_progress", color: "btn-primary" },
  in_progress: { label: "Complete Order", nextStatus: "completed", color: "btn-primary" },
  completed: null,
  cancelled: null,
};

export default function OrderDetailPage() {
  const params = useParams();
  const orderId = params.id as string;

  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchOrder(orderId)
      .then(setOrder)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [orderId]);

  async function handleStatusUpdate(newStatus: OrderStatus) {
    setError(null);
    setUpdating(true);
    try {
      const updated = await updateOrderStatus(orderId, newStatus);
      setOrder(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update status");
    } finally {
      setUpdating(false);
    }
  }

  if (loading) return <LoadingSpinner />;
  if (!order) {
    return (
      <div className="p-8 text-center text-sm text-gray-500">
        Order not found.
      </div>
    );
  }

  const currentStepIndex = STATUS_INDEX[order.status];
  const nextAction = NEXT_ACTIONS[order.status];
  const isCancelled = order.status === "cancelled";

  function formatAddress(addr: Record<string, unknown> | null): string {
    if (!addr) return "-";
    const parts = [
      addr.street,
      addr.area_code,
      addr.city,
      addr.state,
      addr.country,
    ].filter(Boolean);
    if (parts.length > 0) return parts.join(", ");
    // Fallback: just stringify
    return JSON.stringify(addr);
  }

  return (
    <div className="p-6 lg:p-8 max-w-4xl space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <Link href="/orders" className="text-gray-500 hover:text-gray-700">
          Orders
        </Link>
        <svg className="w-4 h-4 text-gray-300" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
        </svg>
        <span className="text-gray-900 font-medium font-mono text-xs">
          #{order.beckn_order_id?.slice(0, 8) || order.id.slice(0, 8)}
        </span>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Order header */}
      <div className="card p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-bold text-gray-900">
                Order #{order.beckn_order_id?.slice(0, 8) || order.id.slice(0, 8)}
              </h2>
              <StatusBadge status={order.status} />
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Placed on {formatDate(order.created_at)}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {!isCancelled && nextAction && (
              <button
                onClick={() => handleStatusUpdate(nextAction.nextStatus)}
                disabled={updating}
                className={nextAction.color}
              >
                {updating ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                ) : null}
                {nextAction.label}
              </button>
            )}
            {!isCancelled && order.status !== "completed" && (
              <button
                onClick={() => handleStatusUpdate("cancelled")}
                disabled={updating}
                className="btn-danger"
              >
                Cancel Order
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Beli Aman Escrow panel — only when this order came via the Beli Aman BAP */}
      {isBeliAman(order) ? <BeliAmanEscrowPanel order={order} /> : null}

      {/* Status timeline */}
      {!isCancelled && (
        <div className="card p-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-6">
            Order Progress
          </h3>
          <div className="flex items-center">
            {STATUS_STEPS.map((step, i) => {
              const isCompleted = i <= currentStepIndex;
              const isCurrent = i === currentStepIndex;
              const isLast = i === STATUS_STEPS.length - 1;

              return (
                <div key={step.key} className={`flex items-center ${isLast ? "" : "flex-1"}`}>
                  {/* Circle */}
                  <div className="flex flex-col items-center">
                    <div
                      className={`flex h-9 w-9 items-center justify-center rounded-full border-2 transition-colors ${
                        isCompleted
                          ? "border-brand-600 bg-brand-600 text-white"
                          : "border-gray-200 bg-white text-gray-400"
                      } ${isCurrent ? "ring-4 ring-brand-100" : ""}`}
                    >
                      {isCompleted && i < currentStepIndex ? (
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={3} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                        </svg>
                      ) : (
                        <span className="text-xs font-bold">{i + 1}</span>
                      )}
                    </div>
                    <span
                      className={`mt-2 text-xs font-medium ${
                        isCompleted ? "text-brand-700" : "text-gray-400"
                      }`}
                    >
                      {step.label}
                    </span>
                  </div>

                  {/* Connector line */}
                  {!isLast && (
                    <div className="flex-1 mx-2">
                      <div
                        className={`h-0.5 rounded-full transition-colors ${
                          i < currentStepIndex ? "bg-brand-600" : "bg-gray-200"
                        }`}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {isCancelled && (
        <div className="card border-red-200 bg-red-50 p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-100">
              <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-semibold text-red-800">Order Cancelled</p>
              <p className="text-sm text-red-600">
                This order has been cancelled and cannot be modified.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Order items */}
        <div className="card p-6 space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">Order Items</h3>
          {order.items && Array.isArray(order.items) && order.items.length > 0 ? (
            <div className="space-y-3">
              {order.items.map((item: Record<string, unknown>, i: number) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {(item.name as string) || (item.product_name as string) || `Item ${i + 1}`}
                    </p>
                    <p className="text-xs text-gray-500">
                      Qty: {(item.quantity as number) || 1}
                      {item.sku_code ? ` \u00b7 SKU: ${item.sku_code}` : ""}
                    </p>
                  </div>
                  <span className="text-sm font-semibold text-gray-900">
                    {formatIDR(
                      ((item.price as number) || 0) *
                        ((item.quantity as number) || 1)
                    )}
                  </span>
                </div>
              ))}
              <div className="border-t border-gray-100 pt-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-900">
                  Total
                </span>
                <span className="text-base font-bold text-gray-900">
                  {formatIDR(order.total)}
                </span>
              </div>
            </div>
          ) : (
            <div className="rounded-lg bg-gray-50 px-4 py-6 text-center">
              <p className="text-sm text-gray-400">No item details available</p>
              <p className="mt-1 text-lg font-bold text-gray-900">
                {formatIDR(order.total)}
              </p>
            </div>
          )}
        </div>

        {/* Customer info */}
        <div className="card p-6 space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">
            Customer Information
          </h3>
          <div className="space-y-3">
            <div>
              <p className="text-xs font-medium text-gray-500">Name</p>
              <p className="text-sm text-gray-900">
                {order.buyer_name || "-"}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500">Phone</p>
              <p className="text-sm text-gray-900">
                {order.buyer_phone || "-"}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500">Email</p>
              <p className="text-sm text-gray-900">
                {order.buyer_email || "-"}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500">
                Shipping Address
              </p>
              <p className="text-sm text-gray-900">
                {formatAddress(order.shipping_address)}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500">
                Billing Address
              </p>
              <p className="text-sm text-gray-900">
                {formatAddress(order.billing_address)}
              </p>
            </div>
          </div>
        </div>

        {/* Payment info */}
        {order.payment && (
          <div className="card p-6 space-y-4">
            <h3 className="text-sm font-semibold text-gray-900">
              Payment
            </h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Amount</span>
                <span className="text-sm font-semibold text-gray-900">
                  {formatIDR(order.payment.amount)}
                </span>
              </div>
              {order.payment.method && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-500">Method</span>
                  <span className="text-sm text-gray-900">
                    {order.payment.method}
                  </span>
                </div>
              )}
              {order.payment.channel && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-500">Channel</span>
                  <span className="text-sm text-gray-900">
                    {order.payment.channel}
                  </span>
                </div>
              )}
              {order.payment.status && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-500">Status</span>
                  <span className="badge bg-emerald-50 text-emerald-700">
                    {order.payment.status}
                  </span>
                </div>
              )}
              {order.payment.paid_at && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-500">Paid At</span>
                  <span className="text-sm text-gray-900">
                    {formatDate(order.payment.paid_at)}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Fulfillment info */}
        {order.fulfillment && (
          <div className="card p-6 space-y-4">
            <h3 className="text-sm font-semibold text-gray-900">
              Fulfillment
            </h3>
            <div className="space-y-3">
              {order.fulfillment.courier_code && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-500">Courier</span>
                  <span className="text-sm text-gray-900 uppercase">
                    {order.fulfillment.courier_code}
                    {order.fulfillment.courier_service
                      ? ` - ${order.fulfillment.courier_service}`
                      : ""}
                  </span>
                </div>
              )}
              {order.fulfillment.awb_number && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-500">AWB Number</span>
                  <span className="text-sm font-mono text-gray-900">
                    {order.fulfillment.awb_number}
                  </span>
                </div>
              )}
              {order.fulfillment.shipping_cost != null && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-500">Shipping Cost</span>
                  <span className="text-sm font-semibold text-gray-900">
                    {formatIDR(order.fulfillment.shipping_cost)}
                  </span>
                </div>
              )}
              {order.fulfillment.status && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-500">Status</span>
                  <span className="text-sm text-gray-900">
                    {order.fulfillment.status}
                  </span>
                </div>
              )}
              {order.fulfillment.tracking_url && (
                <a
                  href={order.fulfillment.tracking_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-secondary text-xs w-full text-center"
                >
                  Track Shipment
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Beli Aman Escrow panel — read-only on the seller side. Only the BAP can
 * mutate escrow state, so the "Release escrow" button is intentionally
 * disabled with a tooltip explaining why.
 * ------------------------------------------------------------------------- */

function BeliAmanEscrowPanel({ order }: { order: Order }) {
  const status = order.escrow_status;
  const amount = order.escrow_amount_idr ?? Math.round(order.total);

  const statusConf: Record<
    EscrowStatus,
    { bg: string; text: string; label: string; ring: string }
  > = {
    none: { bg: "bg-gray-100", text: "text-gray-700", ring: "ring-gray-200", label: "—" },
    held: { bg: "bg-amber-100", text: "text-amber-800", ring: "ring-amber-200", label: "HELD" },
    released: { bg: "bg-emerald-100", text: "text-emerald-800", ring: "ring-emerald-200", label: "RELEASED" },
    refunded: { bg: "bg-red-100", text: "text-red-800", ring: "ring-red-200", label: "REFUNDED" },
  };
  const c = statusConf[status] || statusConf.none;

  return (
    <div className="card p-6 border-2 border-emerald-100 bg-gradient-to-br from-emerald-50/40 to-white">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-emerald-100 grid place-items-center text-xl">🛡️</div>
          <div>
            <h3 className="text-sm font-bold text-emerald-800">Beli Aman Escrow</h3>
            <p className="text-xs text-gray-500">via {order.bap_id}</p>
          </div>
        </div>
        <span
          className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold ${c.bg} ${c.text} ring-1 ${c.ring}`}
        >
          {c.label}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Amount held</div>
          <div className="text-lg font-bold text-gray-900 mt-0.5">{formatIDR(amount)}</div>
        </div>
        <div className="md:col-span-2">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Buyer (verified)</div>
          <div className="flex items-center gap-2 mt-1">
            {order.buyer_photo_url ? (
              <img src={order.buyer_photo_url} alt="" className="w-7 h-7 rounded-full" />
            ) : (
              <div className="w-7 h-7 rounded-full bg-gray-200" />
            )}
            <div>
              <div className="text-sm font-semibold text-gray-900">{order.buyer_name || "Unknown"}</div>
              <div className="text-xs text-gray-500">{order.buyer_email}</div>
            </div>
            <span
              className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[10px] font-semibold border border-emerald-100"
              title="Identity verified via Google"
            >
              ✓ Google
            </span>
          </div>
        </div>
      </div>

      {/* Lifecycle timeline */}
      <ol className="space-y-2 text-sm">
        <TimelineItem done label="Buyer paid via Beli Aman" />
        <TimelineItem done={status !== "none"} label="Order received by seller" />
        <TimelineItem
          done={status === "released" || ["in_progress", "completed"].includes(order.status)}
          label={
            order.status === "completed"
              ? "Delivered & released"
              : order.status === "in_progress"
                ? "Shipping in progress"
                : "Awaiting shipment"
          }
        />
        <TimelineItem
          done={status === "released"}
          label={
            status === "released"
              ? "Funds released to seller"
              : "Auto-release scheduled · D+3 after delivery"
          }
        />
      </ol>

      <div className="mt-4 pt-4 border-t border-emerald-100">
        <div className="flex items-center justify-between gap-4">
          <p className="text-xs text-gray-500 max-w-md">
            Funds release automatically D+3 after delivery, or earlier when buyer confirms receipt. Only Beli Aman can release escrow — sellers are <strong>informed</strong>, not in control.
          </p>
          <button
            type="button"
            disabled
            title="Read-only: only Beli Aman BAP can release escrow"
            className="px-3 py-1.5 rounded-md bg-gray-100 text-gray-400 text-xs font-semibold cursor-not-allowed"
          >
            Release escrow
          </button>
        </div>
      </div>

      <details className="mt-3 text-xs text-gray-600">
        <summary className="cursor-pointer text-emerald-700 hover:text-emerald-800">
          What is Beli Aman?
        </summary>
        <p className="mt-2 leading-relaxed">
          Beli Aman is the buyer-protection layer on Jaringan Dagang. It holds buyer payment in
          escrow until goods are received, gives sellers verified Google-identified buyer data, and
          surfaces orders here in your dashboard with a {`"via Beli Aman"`} badge.
        </p>
      </details>
    </div>
  );
}

function TimelineItem({ done, label }: { done: boolean; label: string }) {
  return (
    <li className="flex items-center gap-2.5">
      <span
        className={`w-5 h-5 rounded-full grid place-items-center text-xs font-bold ${
          done ? "bg-emerald-500 text-white" : "bg-gray-200 text-gray-400"
        }`}
      >
        {done ? "✓" : ""}
      </span>
      <span className={done ? "text-gray-900" : "text-gray-400"}>{label}</span>
    </li>
  );
}
