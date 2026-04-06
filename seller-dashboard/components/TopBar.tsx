"use client";

import { usePathname } from "next/navigation";

const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/products": "Products",
  "/orders": "Orders",
  "/settings": "Store Settings",
};

function getTitle(pathname: string): string {
  if (pathname.startsWith("/products/")) return "Edit Product";
  if (pathname.startsWith("/orders/")) return "Order Detail";
  return PAGE_TITLES[pathname] || "Dashboard";
}

export default function TopBar() {
  const pathname = usePathname();
  const title = getTitle(pathname);

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-gray-200 bg-white/80 px-6 backdrop-blur-md lg:px-8">
      {/* Left: page title (offset for mobile hamburger) */}
      <div className="flex items-center gap-4">
        <div className="w-8 lg:hidden" /> {/* spacer for hamburger */}
        <h1 className="text-lg font-bold text-gray-900">{title}</h1>
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-3">
        {/* Notification bell */}
        <button className="relative rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0" />
          </svg>
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-red-500" />
        </button>

        {/* Avatar */}
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-bold text-brand-700">
          M
        </div>
      </div>
    </header>
  );
}
