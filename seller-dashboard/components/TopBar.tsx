"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";

const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/products": "Products",
  "/orders": "Orders",
  "/conversations": "Conversations",
  "/settings": "Store Settings",
  "/settings/team": "Team",
  "/refunds": "Refunds",
};

function getTitle(pathname: string): string {
  if (pathname.startsWith("/products/")) return "Edit Product";
  if (pathname.startsWith("/orders/")) return "Order Detail";
  if (pathname.startsWith("/conversations/")) return "Conversations";
  return PAGE_TITLES[pathname] || "Dashboard";
}

export default function TopBar() {
  const pathname = usePathname();
  const title = getTitle(pathname);
  const { me, signOut, firebaseConfigured } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  const initial = (me?.display_name || me?.email || "?")[0].toUpperCase();

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-gray-200 bg-white/80 px-6 backdrop-blur-md lg:px-8">
      <div className="flex items-center gap-4">
        <div className="w-8 lg:hidden" />
        <h1 className="text-lg font-bold text-gray-900">{title}</h1>
      </div>

      <div className="flex items-center gap-3">
        <button className="relative rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0" />
          </svg>
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-red-500" />
        </button>

        {/* User menu */}
        <div className="relative">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="flex h-9 w-9 items-center justify-center rounded-full overflow-hidden bg-brand-100 text-sm font-bold text-brand-700 hover:ring-2 hover:ring-brand-300"
            aria-label="User menu"
          >
            {me?.photo_url ? (
              <img src={me.photo_url} alt="" className="h-full w-full object-cover" />
            ) : (
              initial
            )}
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 top-12 w-64 rounded-lg border border-gray-200 bg-white shadow-lg overflow-hidden z-40"
              onMouseLeave={() => setMenuOpen(false)}
            >
              <div className="px-4 py-3 border-b">
                <div className="text-sm font-medium text-gray-900 truncate">
                  {me?.display_name || me?.email || "—"}
                </div>
                {me?.email && me?.display_name && (
                  <div className="text-xs text-gray-500 truncate">{me.email}</div>
                )}
                {me?.is_super_admin && (
                  <span className="inline-block mt-1 px-1.5 py-0.5 text-[10px] bg-indigo-100 text-indigo-700 rounded">SUPER ADMIN</span>
                )}
              </div>
              {firebaseConfigured && (
                <button
                  onClick={() => { setMenuOpen(false); void signOut(); }}
                  className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  Sign out
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
