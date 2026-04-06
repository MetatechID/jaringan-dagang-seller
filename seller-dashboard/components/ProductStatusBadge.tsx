const PRODUCT_STATUS_STYLES: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  active: {
    bg: "bg-emerald-50",
    text: "text-emerald-700",
    label: "Active",
  },
  draft: {
    bg: "bg-gray-100",
    text: "text-gray-600",
    label: "Draft",
  },
  archived: {
    bg: "bg-orange-50",
    text: "text-orange-700",
    label: "Archived",
  },
};

export default function ProductStatusBadge({ status }: { status: string }) {
  const s = PRODUCT_STATUS_STYLES[status] ?? PRODUCT_STATUS_STYLES.draft;

  return (
    <span className={`badge ${s.bg} ${s.text}`}>
      {s.label}
    </span>
  );
}
