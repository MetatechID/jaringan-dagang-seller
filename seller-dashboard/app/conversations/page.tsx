"use client";

/**
 * Empty state for /conversations. The InboxList in the layout renders the
 * left pane; the middle and right of the grid sit here until the user
 * selects a row.
 *
 * `col-span` fills both the center and (on xl) right panes so the empty
 * state can center inside the available area.
 */
export default function ConversationsIndexPage() {
  return (
    <section className="hidden md:flex md:col-span-1 xl:col-span-2 h-full items-center justify-center bg-gray-50/40 text-center px-6">
      <div className="max-w-sm">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-500">
          <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 9.75a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375m-13.5 3.01c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.184-4.183a1.14 1.14 0 0 1 .778-.332 48.294 48.294 0 0 0 5.83-.498c1.585-.233 2.708-1.626 2.708-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
          </svg>
        </div>
        <h2 className="text-base font-semibold text-gray-900">Select a conversation</h2>
        <p className="mt-1.5 text-sm text-gray-500">
          Pick a thread from the inbox on the left to see messages, customer
          context, and take over from the bot.
        </p>
      </div>
    </section>
  );
}
