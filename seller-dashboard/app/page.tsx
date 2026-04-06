"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchProducts, fetchOrders, type Product, type Order } from "@/lib/api";
import { formatIDR, formatRelative } from "@/lib/format";
import StatusBadge from "@/components/StatusBadge";
import LoadingSpinner from "@/components/LoadingSpinner";

export default function DashboardPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [p, o] = await Promise.all([fetchProducts(), fetchOrders()]);
        setProducts(p);
        setOrders(o);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load data");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <LoadingSpinner />;

  const totalProducts = products.length;
  const totalOrders = orders.length;
  const revenue = orders
    .filter((o) => o.status === "completed")
    .reduce((sum, o) => sum + o.total, 0);
  const activeSkus = products
    .filter((p) => p.status === "active")
    .reduce((sum, p) => sum + Math.max(p.skus.length, 1), 0);
  const recentOrders = [...orders]
    .sort(
      (a, b) =>
        new Date(b.created_at || 0).getTime() -
        new Date(a.created_at || 0).getTime()
    )
    .slice(0, 5);

  // Fee savings: marketplace takes ~20%, Jaringan Dagang takes ~2%
  const marketplaceFee = revenue * 0.2;
  const jdFee = revenue * 0.02;
  const savings = marketplaceFee - jdFee;

  const stats = [
    {
      label: "Total Products",
      value: totalProducts.toString(),
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
        </svg>
      ),
      color: "bg-violet-50 text-violet-600",
    },
    {
      label: "Total Orders",
      value: totalOrders.toString(),
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5V6a3.75 3.75 0 1 0-7.5 0v4.5m11.356-1.993 1.263 12c.07.665-.45 1.243-1.119 1.243H4.25a1.125 1.125 0 0 1-1.12-1.243l1.264-12A1.125 1.125 0 0 1 5.513 7.5h12.974c.576 0 1.059.435 1.119 1.007ZM8.625 10.5a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm7.5 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z" />
        </svg>
      ),
      color: "bg-blue-50 text-blue-600",
    },
    {
      label: "Revenue (IDR)",
      value: formatIDR(revenue),
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 0 1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3 0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z" />
        </svg>
      ),
      color: "bg-emerald-50 text-emerald-600",
    },
    {
      label: "Active SKUs",
      value: activeSkus.toString(),
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z" />
        </svg>
      ),
      color: "bg-amber-50 text-amber-600",
    },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Welcome header */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900">
          Matchamu Seller Dashboard
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          Manage your products, orders, and store on the open commerce network.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Stats cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="card p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-500">{s.label}</p>
                <p className="mt-1.5 text-2xl font-bold text-gray-900">{s.value}</p>
              </div>
              <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${s.color}`}>
                {s.icon}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Recent orders */}
        <div className="card xl:col-span-2">
          <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
            <h3 className="text-sm font-semibold text-gray-900">Recent Orders</h3>
            <Link href="/orders" className="text-sm font-medium text-brand-600 hover:text-brand-700">
              View all
            </Link>
          </div>
          {recentOrders.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-gray-400">
              No orders yet
            </div>
          ) : (
            <div className="divide-y divide-gray-50">
              {recentOrders.map((order) => (
                <Link
                  key={order.id}
                  href={`/orders/${order.id}`}
                  className="flex items-center justify-between px-5 py-3.5 hover:bg-gray-50/50 transition-colors"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {order.buyer_name || "Unknown Customer"}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {order.beckn_order_id
                        ? `#${order.beckn_order_id.slice(0, 8)}`
                        : `#${order.id.slice(0, 8)}`}
                      {" \u00b7 "}
                      {formatRelative(order.created_at)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0 ml-4">
                    <StatusBadge status={order.status} />
                    <span className="text-sm font-semibold text-gray-900">
                      {formatIDR(order.total)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Right column */}
        <div className="space-y-6">
          {/* Quick actions */}
          <div className="card p-5 space-y-3">
            <h3 className="text-sm font-semibold text-gray-900">Quick Actions</h3>
            <div className="space-y-2">
              <Link href="/products" className="btn-primary w-full text-center">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                Add Product
              </Link>
              <Link href="/orders" className="btn-secondary w-full text-center">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                </svg>
                View Orders
              </Link>
              <button className="btn-ghost w-full border border-dashed border-gray-300">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
                </svg>
                Sync from TikTok Shop
              </button>
            </div>
          </div>

          {/* Fee savings card */}
          <div className="card overflow-hidden">
            <div className="bg-gradient-to-br from-brand-600 to-violet-700 px-5 py-5 text-white">
              <div className="flex items-center gap-2 text-brand-200">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456Z" />
                </svg>
                <span className="text-xs font-semibold uppercase tracking-wider">Fee Savings</span>
              </div>
              <p className="mt-3 text-3xl font-bold">
                {formatIDR(savings)}
              </p>
              <p className="mt-1 text-sm text-brand-200">
                saved this month vs marketplace fees
              </p>
            </div>
            <div className="px-5 py-4 space-y-2.5">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Marketplace fee (20%)</span>
                <span className="font-medium text-gray-400 line-through">{formatIDR(marketplaceFee)}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Jaringan Dagang fee (2%)</span>
                <span className="font-medium text-gray-900">{formatIDR(jdFee)}</span>
              </div>
              <div className="border-t border-gray-100 pt-2.5 flex items-center justify-between text-sm">
                <span className="font-semibold text-emerald-600">You keep more</span>
                <span className="font-bold text-emerald-600">+{formatIDR(savings)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
