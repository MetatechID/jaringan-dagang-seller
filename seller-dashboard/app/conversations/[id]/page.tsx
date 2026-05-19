"use client";

import { useParams } from "next/navigation";
import ConversationThread from "@/components/conversations/ConversationThread";
import ContactPanel from "@/components/conversations/ContactPanel";

export default function ConversationDetailPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <>
      <section className="h-full min-h-0 overflow-hidden bg-gray-50/40">
        <ConversationThread conversationId={id} />
      </section>
      <aside className="hidden xl:block h-full min-h-0 overflow-y-auto border-l border-gray-200 bg-white">
        <ContactPanel conversationId={id} />
      </aside>
    </>
  );
}
