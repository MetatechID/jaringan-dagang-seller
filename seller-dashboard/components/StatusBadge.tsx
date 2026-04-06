import type { OrderStatus } from "@/lib/api";

const STATUS_STYLES: Record<
  OrderStatus,
  { bg: string; text: string; dot: string; label: string }
> = {
  created: {
    bg: "bg-gray-100",
    text: "text-gray-700",
    dot: "bg-gray-400",
    label: "Created",
  },
  accepted: {
    bg: "bg-blue-50",
    text: "text-blue-700",
    dot: "bg-blue-500",
    label: "Accepted",
  },
  in_progress: {
    bg: "bg-amber-50",
    text: "text-amber-700",
    dot: "bg-amber-500",
    label: "In Progress",
  },
  completed: {
    bg: "bg-emerald-50",
    text: "text-emerald-700",
    dot: "bg-emerald-500",
    label: "Completed",
  },
  cancelled: {
    bg: "bg-red-50",
    text: "text-red-700",
    dot: "bg-red-500",
    label: "Cancelled",
  },
};

export default function StatusBadge({ status }: { status: OrderStatus }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.created;

  return (
    <span
      className={`badge gap-1.5 ${s.bg} ${s.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
