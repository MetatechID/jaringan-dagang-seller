"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { fetchOrders, type Order, type OrderStatus } from "@/lib/api";
import { formatIDR, formatDate } from "@/lib/format";
import StatusBadge from "@/components/StatusBadge";
import LoadingSpinner from "@/components/LoadingSpinner";
import EmptyState from "@/components/EmptyState";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    fetchOrders()
      .then(setOrders)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    return orders
      .filter((o) => {
        const matchStatus =
          statusFilter === "all" || o.status === statusFilter;
        const matchSearch =
          !search ||
          (o.buyer_name &&
            o.buyer_name.toLowerCase().includes(search.toLowerCase())) ||
          o.id.includes(search) ||
          (o.beckn_order_id && o.beckn_order_id.includes(search));
        return matchStatus && matchSearch;
      })
      .sort(
        (a, b) =>
          new Date(b.created_at || 0).getTime() -
          new Date(a.created_at || 0).getTime()
      );
  }, [orders, statusFilter, search]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: orders.length };
    for (const o of orders) {
      counts[o.status] = (counts[o.status] || 0) + 1;
    }
    return counts;
  }, [orders]);

  if (loading) return <LoadingSpinner />;

  const STATUS_TABS: { key: string; label: string }[] = [
    { key: "all", label: "All" },
    { key: "created", label: "Created" },
    { key: "accepted", label: "Accepted" },
    { key: "in_progress", label: "In Progress" },
    { key: "completed", label: "Completed" },
    { key: "cancelled", label: "Cancelled" },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-900">Orders</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          {orders.length} order{orders.length !== 1 ? "s" : ""} total
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Status tabs */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setStatusFilter(tab.key)}
            className={`shrink-0 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors ${
              statusFilter === tab.key
                ? "bg-brand-50 text-brand-700"
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            }`}
          >
            {tab.label}
            {statusCounts[tab.key] ? (
              <span
                className={`ml-1.5 rounded-full px-1.5 py-0.5 text-xs ${
                  statusFilter === tab.key
                    ? "bg-brand-100 text-brand-700"
                    : "bg-gray-100 text-gray-500"
                }`}
              >
                {statusCounts[tab.key]}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
          />
        </svg>
        <input
          type="text"
          placeholder="Search by customer or order ID..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="input pl-10"
        />
      </div>

      {/* Orders table */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5V6a3.75 3.75 0 1 0-7.5 0v4.5m11.356-1.993 1.263 12c.07.665-.45 1.243-1.119 1.243H4.25a1.125 1.125 0 0 1-1.12-1.243l1.264-12A1.125 1.125 0 0 1 5.513 7.5h12.974c.576 0 1.059.435 1.119 1.007ZM8.625 10.5a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm7.5 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
            </svg>
          }
          title={
            search || statusFilter !== "all"
              ? "No orders match your filters"
              : "No orders yet"
          }
          description="Orders from the open commerce network will appear here."
        />
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="px-5 py-3 text-left font-medium text-gray-500">
                    Order ID
                  </th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">
                    Customer
                  </th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">
                    Total
                  </th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">
                    Status
                  </th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">
                    Date
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((order) => (
                  <tr
                    key={order.id}
                    className="group hover:bg-gray-50/50 transition-colors cursor-pointer"
                    onClick={() =>
                      (window.location.href = `/orders/${order.id}`)
                    }
                  >
                    <td className="px-5 py-3.5">
                      <span className="font-mono text-xs text-brand-600 group-hover:text-brand-700 font-medium">
                        #
                        {order.beckn_order_id
                          ? order.beckn_order_id.slice(0, 8)
                          : order.id.slice(0, 8)}
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <div>
                        <p className="font-medium text-gray-900">
                          {order.buyer_name || "Unknown"}
                        </p>
                        {order.buyer_phone && (
                          <p className="text-xs text-gray-400">
                            {order.buyer_phone}
                          </p>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3.5 font-semibold text-gray-900">
                      {formatIDR(order.total)}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={order.status} />
                    </td>
                    <td className="px-5 py-3.5 text-gray-500">
                      {formatDate(order.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
