"use client";

import { useEffect, useRef, useState } from "react";
import {
  fetchStores,
  getSelectedStoreId,
  setSelectedStoreId,
  type StoreSettings,
} from "@/lib/api";

export default function StoreSwitcher() {
  const [stores, setStores] = useState<StoreSettings[]>([]);
  const [current, setCurrent] = useState<StoreSettings | null>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchStores()
      .then((list) => {
        setStores(list);
        const selectedId = getSelectedStoreId();
        const match = list.find((s) => s.id === selectedId);
        setCurrent(match || list[0] || null);
        // Ensure localStorage is set if it wasn't already
        if (!selectedId && list[0]) {
          setSelectedStoreId(list[0].id);
        }
      })
      .catch(() => {
        // Silently fail - sidebar will show fallback
      });
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 50);
    }
  }, [open]);

  function handleSelect(store: StoreSettings) {
    setSelectedStoreId(store.id);
    setCurrent(store);
    setOpen(false);
    setSearch("");
    // Reload to re-fetch all data for the new store
    window.location.reload();
  }

  const filtered = stores.filter((s) =>
    s.name.toLowerCase().includes(search.toLowerCase())
  );

  const initials = (name: string) =>
    name
      .split(/\s+/)
      .map((w) => w[0])
      .join("")
      .toUpperCase()
      .slice(0, 2);

  return (
    <div ref={dropdownRef} className="relative">
      {/* Trigger button */}
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-white/[0.06]"
      >
        {current?.logo_url ? (
          <img
            src={current.logo_url}
            alt={current.name}
            className="h-9 w-9 rounded-lg object-cover border border-white/10 shrink-0"
          />
        ) : (
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white font-bold text-sm shrink-0">
            {current ? initials(current.name) : "?"}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold text-white leading-tight truncate">
            {current?.name || "Loading..."}
          </p>
          <p className="text-[11px] text-gray-400 leading-tight">
            Seller Dashboard
          </p>
        </div>
        <svg
          className={`w-4 h-4 text-gray-400 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m19.5 8.25-7.5 7.5-7.5-7.5"
          />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-lg border border-white/10 bg-sidebar-light shadow-xl overflow-hidden">
          {/* Search input */}
          <div className="p-2">
            <div className="relative">
              <svg
                className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500"
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
                ref={searchRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search stores..."
                className="w-full rounded-md bg-white/[0.06] border border-white/10 py-2 pl-8 pr-3 text-sm text-white placeholder-gray-500 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500/30"
              />
            </div>
          </div>

          {/* Store list */}
          <div className="max-h-52 overflow-y-auto px-1 pb-1">
            {filtered.length === 0 ? (
              <p className="px-3 py-4 text-center text-sm text-gray-500">
                No stores found
              </p>
            ) : (
              filtered.map((store) => {
                const isSelected = store.id === current?.id;
                return (
                  <button
                    key={store.id}
                    onClick={() => handleSelect(store)}
                    className={`flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors ${
                      isSelected
                        ? "bg-brand-600/20 text-brand-300"
                        : "text-gray-300 hover:bg-white/[0.06] hover:text-white"
                    }`}
                  >
                    {store.logo_url ? (
                      <img
                        src={store.logo_url}
                        alt={store.name}
                        className="h-8 w-8 rounded-lg object-cover border border-white/10 shrink-0"
                      />
                    ) : (
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.06] text-xs font-bold text-gray-300 shrink-0">
                        {initials(store.name)}
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">
                        {store.name}
                      </p>
                      {store.city && (
                        <p className="text-[11px] text-gray-500 truncate">
                          {store.city}
                        </p>
                      )}
                    </div>
                    {isSelected && (
                      <svg
                        className="w-4 h-4 text-brand-400 shrink-0"
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={2.5}
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="m4.5 12.75 6 6 9-13.5"
                        />
                      </svg>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
