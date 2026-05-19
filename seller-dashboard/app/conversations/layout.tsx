"use client";

import InboxList from "@/components/conversations/InboxList";

/**
 * Three-pane CRM shell. Always renders the left `InboxList`; center + right
 * panes are rendered by child routes (`page.tsx` for empty, `[id]/page.tsx`
 * for a selected conversation).
 *
 * The outer container sits inside the existing dashboard chrome (Sidebar +
 * TopBar provide the lg:pl-64 + h-16 offsets, so we subtract 4rem here so the
 * thread+composer can scroll within the viewport).
 */
export default function ConversationsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="h-[calc(100vh-4rem)] w-full">
      <div className="grid h-full grid-cols-1 md:grid-cols-[320px_1fr] xl:grid-cols-[320px_1fr_360px]">
        <aside className="border-r border-gray-200 bg-white overflow-hidden h-full min-h-0">
          <InboxList />
        </aside>
        {children}
      </div>
    </div>
  );
}
