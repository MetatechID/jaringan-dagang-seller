"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { fetchProducts, type Product } from "@/lib/api";
import { formatIDR } from "@/lib/format";
import ProductStatusBadge from "@/components/ProductStatusBadge";
import LoadingSpinner from "@/components/LoadingSpinner";
import EmptyState from "@/components/EmptyState";

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");

  useEffect(() => {
    fetchProducts()
      .then(setProducts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    return products.filter((p) => {
      const matchSearch =
        !search ||
        p.name.toLowerCase().includes(search.toLowerCase()) ||
        (p.sku && p.sku.toLowerCase().includes(search.toLowerCase()));
      const matchStatus = statusFilter === "all" || p.status === statusFilter;
      return matchSearch && matchStatus;
    });
  }, [products, search, statusFilter]);

  function getPrimaryImage(p: Product): string | null {
    const primary = p.images.find((i) => i.is_primary);
    return primary?.url || p.images[0]?.url || null;
  }

  function getPrice(p: Product): number {
    if (p.skus.length > 0) return Math.min(...p.skus.map((s) => s.price));
    return 0;
  }

  function getTotalStock(p: Product): number {
    return p.skus.reduce((sum, s) => sum + s.stock, 0);
  }

  if (loading) return <LoadingSpinner />;

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Products</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            {products.length} product{products.length !== 1 ? "s" : ""} in your catalog
          </p>
        </div>
        <Link href="/products/new" className="btn-primary shrink-0">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          Add Product
        </Link>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="card px-4 py-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3 flex-1">
          {/* Search */}
          <div className="relative flex-1 max-w-sm">
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
              placeholder="Search products..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input pl-10"
            />
          </div>

          {/* Status filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="input w-auto"
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="draft">Draft</option>
            <option value="archived">Archived</option>
          </select>
        </div>

        {/* View toggle */}
        <div className="flex items-center rounded-lg border border-gray-200 p-0.5">
          <button
            onClick={() => setViewMode("table")}
            className={`rounded-md px-2.5 py-1.5 transition-colors ${
              viewMode === "table"
                ? "bg-gray-100 text-gray-900"
                : "text-gray-400 hover:text-gray-600"
            }`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 5.25h16.5m-16.5 4.5h16.5m-16.5 4.5h16.5m-16.5 4.5h16.5" />
            </svg>
          </button>
          <button
            onClick={() => setViewMode("grid")}
            className={`rounded-md px-2.5 py-1.5 transition-colors ${
              viewMode === "grid"
                ? "bg-gray-100 text-gray-900"
                : "text-gray-400 hover:text-gray-600"
            }`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Content */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
            </svg>
          }
          title={search || statusFilter !== "all" ? "No products match your filters" : "No products yet"}
          description="Add your first product to get started selling on the open commerce network."
          action={
            <Link href="/products/new" className="btn-primary">
              Add Product
            </Link>
          }
        />
      ) : viewMode === "table" ? (
        /* Table view */
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Product</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">SKU</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Price</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Stock</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Status</th>
                  <th className="px-5 py-3 text-left font-medium text-gray-500">Variants</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((p) => (
                  <tr
                    key={p.id}
                    className="group hover:bg-gray-50/50 transition-colors cursor-pointer"
                    onClick={() => (window.location.href = `/products/${p.id}`)}
                  >
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        {getPrimaryImage(p) ? (
                          <img
                            src={getPrimaryImage(p)!}
                            alt={p.name}
                            className="h-10 w-10 rounded-lg object-cover border border-gray-100"
                          />
                        ) : (
                          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100 text-gray-400">
                            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0 0 22.5 18.75V5.25A2.25 2.25 0 0 0 20.25 3H3.75A2.25 2.25 0 0 0 1.5 5.25v13.5A2.25 2.25 0 0 0 3.75 21Z" />
                            </svg>
                          </div>
                        )}
                        <span className="font-medium text-gray-900 group-hover:text-brand-600 transition-colors">
                          {p.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-gray-500 font-mono text-xs">
                      {p.sku || p.skus[0]?.sku_code || "-"}
                    </td>
                    <td className="px-5 py-3.5 font-medium text-gray-900">
                      {getPrice(p) > 0 ? formatIDR(getPrice(p)) : "-"}
                    </td>
                    <td className="px-5 py-3.5 text-gray-600">
                      {getTotalStock(p)}
                    </td>
                    <td className="px-5 py-3.5">
                      <ProductStatusBadge status={p.status} />
                    </td>
                    <td className="px-5 py-3.5 text-gray-500">
                      {p.skus.length} variant{p.skus.length !== 1 ? "s" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Grid view */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((p) => (
            <Link
              key={p.id}
              href={`/products/${p.id}`}
              className="card group overflow-hidden hover:shadow-md transition-shadow"
            >
              <div className="aspect-square bg-gray-50 relative">
                {getPrimaryImage(p) ? (
                  <img
                    src={getPrimaryImage(p)!}
                    alt={p.name}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-gray-300">
                    <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0 0 22.5 18.75V5.25A2.25 2.25 0 0 0 20.25 3H3.75A2.25 2.25 0 0 0 1.5 5.25v13.5A2.25 2.25 0 0 0 3.75 21Z" />
                    </svg>
                  </div>
                )}
                <div className="absolute top-2 right-2">
                  <ProductStatusBadge status={p.status} />
                </div>
              </div>
              <div className="p-4">
                <h3 className="text-sm font-semibold text-gray-900 group-hover:text-brand-600 transition-colors truncate">
                  {p.name}
                </h3>
                <p className="mt-1 text-sm font-bold text-gray-900">
                  {getPrice(p) > 0 ? formatIDR(getPrice(p)) : "-"}
                </p>
                <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
                  <span>{getTotalStock(p)} in stock</span>
                  <span>{p.skus.length} variant{p.skus.length !== 1 ? "s" : ""}</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
