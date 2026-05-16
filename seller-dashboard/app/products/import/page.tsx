"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  fetchImportSources,
  uploadImport,
  confirmImport,
  type ImportSourceInfo,
  type ImportSourceName,
  type ImportJobView,
  type ImportItemPreview,
} from "@/lib/api";
import LoadingSpinner from "@/components/LoadingSpinner";
import { formatIDR } from "@/lib/format";

type Step = "source" | "upload" | "review";

export default function ImportWizardPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("source");
  const [sources, setSources] = useState<ImportSourceInfo[]>([]);
  const [picked, setPicked] = useState<ImportSourceInfo | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [job, setJob] = useState<ImportJobView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchImportSources()
      .then(setSources)
      .catch((e) => setError(e.message));
  }, []);

  async function handleUpload(f: File) {
    if (!picked) return;
    setUploading(true);
    setError(null);
    try {
      const j = await uploadImport(picked.name, f);
      setJob(j);
      setStep("review");
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setUploading(false);
    }
  }

  async function handleConfirm() {
    if (!job) return;
    setConfirming(true);
    setError(null);
    try {
      const j = await confirmImport(job.id);
      setJob(j);
      router.push(`/products?imported=${j.id}`);
    } catch (e: any) {
      setError(e?.message || String(e));
      setConfirming(false);
    }
  }

  return (
    <div className="p-6 lg:p-8 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Import products</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Bring your existing catalog from BigSeller, Shopee, Tokopedia, Lazada, or a spreadsheet.
          </p>
        </div>
        <Link href="/products" className="text-sm text-gray-500 hover:text-gray-900">
          ← Back to products
        </Link>
      </div>

      <StepIndicator current={step} />

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {step === "source" && (
        <SourcePicker
          sources={sources}
          onPick={(s) => {
            setPicked(s);
            setStep("upload");
          }}
        />
      )}

      {step === "upload" && picked && (
        <Uploader
          source={picked}
          onBack={() => setStep("source")}
          onFile={(f) => {
            setFile(f);
            handleUpload(f);
          }}
          uploading={uploading}
        />
      )}

      {step === "review" && job && (
        <Review
          job={job}
          fileName={file?.name ?? job.filename}
          onBack={() => {
            setJob(null);
            setStep("upload");
          }}
          onConfirm={handleConfirm}
          confirming={confirming}
        />
      )}
    </div>
  );
}

function StepIndicator({ current }: { current: Step }) {
  const order: Step[] = ["source", "upload", "review"];
  const labels: Record<Step, string> = {
    source: "1. Pick source",
    upload: "2. Upload file",
    review: "3. Review & confirm",
  };
  const idx = order.indexOf(current);
  return (
    <ol className="flex items-center gap-2 text-sm">
      {order.map((s, i) => {
        const done = i < idx;
        const active = i === idx;
        return (
          <li key={s} className="flex items-center gap-2">
            <span
              className={
                done
                  ? "inline-flex h-6 w-6 items-center justify-center rounded-full bg-brand-600 text-white"
                  : active
                  ? "inline-flex h-6 w-6 items-center justify-center rounded-full border-2 border-brand-600 text-brand-600 font-semibold"
                  : "inline-flex h-6 w-6 items-center justify-center rounded-full border border-gray-300 text-gray-400"
              }
            >
              {done ? "✓" : i + 1}
            </span>
            <span className={active ? "font-medium text-gray-900" : "text-gray-500"}>
              {labels[s]}
            </span>
            {i < order.length - 1 && <span className="text-gray-300">›</span>}
          </li>
        );
      })}
    </ol>
  );
}

function SourcePicker({
  sources,
  onPick,
}: {
  sources: ImportSourceInfo[];
  onPick: (s: ImportSourceInfo) => void;
}) {
  if (sources.length === 0) return <LoadingSpinner />;
  const order: ImportSourceName[] = ["bigseller", "shopee", "tokopedia", "lazada", "generic"];
  const sorted = order
    .map((n) => sources.find((s) => s.name === n))
    .filter((s): s is ImportSourceInfo => Boolean(s));
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {sorted.map((s) => (
        <button
          key={s.name}
          onClick={() => onPick(s)}
          className="card text-left p-5 hover:shadow-md hover:border-brand-300 transition-all"
        >
          <div className="flex items-start gap-3">
            <SourceLogo source={s} />
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold text-gray-900 truncate">{s.display_name}</h3>
                <span className="text-xs text-gray-400 font-mono shrink-0">
                  {s.file_extensions.join(" / ")}
                </span>
              </div>
              <p className="mt-1.5 text-sm text-gray-500">{s.hint}</p>
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}

function SourceLogo({ source }: { source: ImportSourceInfo }) {
  const [errored, setErrored] = useState(false);
  if (!source.logo_url || errored) {
    return (
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-500">
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 5.25h16.5m-16.5 4.5h16.5m-16.5 4.5h16.5m-16.5 4.5h16.5" />
        </svg>
      </div>
    );
  }
  return (
    <img
      src={source.logo_url}
      alt={`${source.display_name} logo`}
      onError={() => setErrored(true)}
      className="h-10 w-10 shrink-0 rounded-lg border border-gray-100 bg-white object-contain p-1"
    />
  );
}

function Uploader({
  source,
  onBack,
  onFile,
  uploading,
}: {
  source: ImportSourceInfo;
  onBack: () => void;
  onFile: (f: File) => void;
  uploading: boolean;
}) {
  const [dragOver, setDragOver] = useState(false);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <button onClick={onBack} className="hover:text-gray-900">
          ← Change source
        </button>
        <span className="text-gray-300">·</span>
        <span>
          Importing as <span className="font-medium text-gray-700">{source.display_name}</span>
        </span>
      </div>

      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onFile(f);
        }}
        className={
          "block cursor-pointer rounded-xl border-2 border-dashed p-12 text-center transition " +
          (dragOver
            ? "border-brand-500 bg-brand-50"
            : "border-gray-200 bg-gray-50 hover:border-gray-300 hover:bg-gray-100")
        }
      >
        <input
          type="file"
          accept={source.file_extensions.join(",")}
          className="hidden"
          disabled={uploading}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
          }}
        />
        {uploading ? (
          <div className="space-y-2">
            <LoadingSpinner />
            <p className="text-sm text-gray-500">Parsing your file…</p>
          </div>
        ) : (
          <div className="space-y-2">
            <svg className="mx-auto h-10 w-10 text-gray-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
            <p className="text-sm font-medium text-gray-900">
              Drop your {source.display_name} file here, or click to browse
            </p>
            <p className="text-xs text-gray-500">
              {source.file_extensions.join(" or ")} · max 10 MB
            </p>
          </div>
        )}
      </label>
    </div>
  );
}

function Review({
  job,
  fileName,
  onBack,
  onConfirm,
  confirming,
}: {
  job: ImportJobView;
  fileName: string;
  onBack: () => void;
  onConfirm: () => void;
  confirming: boolean;
}) {
  const summary = job.summary || { new: 0, update: 0, warn: 0, error: 0, total: 0 };
  const rows = job.preview_rows || [];
  const visibleRows = rows.slice(0, 20);
  const blocking = summary.error > 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <button onClick={onBack} className="hover:text-gray-900">
          ← Upload different file
        </button>
        <span className="text-gray-300">·</span>
        <span className="font-mono text-xs">{fileName}</span>
      </div>

      <div className="card p-4 grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
        <Stat label="Total rows" value={summary.total} />
        <Stat label="New" value={summary.new} tone="green" />
        <Stat label="Updates" value={summary.update} tone="blue" />
        <Stat label="Warnings" value={summary.warn} tone="yellow" />
        <Stat label="Errors" value={summary.error} tone="red" />
      </div>

      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/50">
          <h3 className="font-medium text-gray-900">Preview (first {visibleRows.length} rows)</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                <th className="px-4 py-2 text-left font-medium text-gray-500">Row</th>
                <th className="px-4 py-2 text-left font-medium text-gray-500">Status</th>
                <th className="px-4 py-2 text-left font-medium text-gray-500">Name</th>
                <th className="px-4 py-2 text-left font-medium text-gray-500">SKU</th>
                <th className="px-4 py-2 text-left font-medium text-gray-500">Variant</th>
                <th className="px-4 py-2 text-right font-medium text-gray-500">Price</th>
                <th className="px-4 py-2 text-right font-medium text-gray-500">Stock</th>
                <th className="px-4 py-2 text-left font-medium text-gray-500">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {visibleRows.map((r) => (
                <PreviewRow key={r.row_number} row={r} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3">
        <Link href="/products" className="btn-secondary">
          Cancel
        </Link>
        <button
          onClick={onConfirm}
          disabled={blocking || confirming}
          className={
            blocking
              ? "btn-primary opacity-50 cursor-not-allowed"
              : "btn-primary"
          }
          title={blocking ? "Fix errors before confirming" : ""}
        >
          {confirming ? "Importing…" : `Confirm import (${summary.total - summary.error})`}
        </button>
      </div>
    </div>
  );
}

function PreviewRow({ row }: { row: ImportItemPreview }) {
  const hasErr = row.errors.length > 0;
  const hasWarn = row.warnings.length > 0;
  const badge = hasErr ? "error" : hasWarn ? "warn" : "new";
  const badgeText = hasErr ? "Error" : hasWarn ? "Warn" : "New";
  const badgeClass =
    badge === "error"
      ? "bg-red-50 text-red-700 border-red-200"
      : badge === "warn"
      ? "bg-yellow-50 text-yellow-700 border-yellow-200"
      : "bg-green-50 text-green-700 border-green-200";
  return (
    <tr className={hasErr ? "bg-red-50/30" : ""}>
      <td className="px-4 py-2 text-gray-400 font-mono text-xs">{row.row_number}</td>
      <td className="px-4 py-2">
        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${badgeClass}`}>
          {badgeText}
        </span>
      </td>
      <td className="px-4 py-2 text-gray-900 max-w-xs truncate" title={row.name}>
        {row.name || <span className="text-gray-300">—</span>}
      </td>
      <td className="px-4 py-2 text-gray-500 font-mono text-xs">{row.sku_code || "—"}</td>
      <td className="px-4 py-2 text-gray-500 text-xs">
        {row.variant_value ? `${row.variant_name ?? ""}: ${row.variant_value}` : "—"}
      </td>
      <td className="px-4 py-2 text-right text-gray-900 font-medium">
        {row.price && Number(row.price) > 0 ? formatIDR(Number(row.price)) : "—"}
      </td>
      <td className="px-4 py-2 text-right text-gray-600">{row.stock}</td>
      <td className="px-4 py-2 text-xs text-gray-500 max-w-sm">
        {[...row.errors, ...row.warnings].join(" · ")}
      </td>
    </tr>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "green" | "blue" | "yellow" | "red";
}) {
  const color =
    tone === "green"
      ? "text-green-700"
      : tone === "blue"
      ? "text-blue-700"
      : tone === "yellow"
      ? "text-yellow-700"
      : tone === "red"
      ? "text-red-700"
      : "text-gray-900";
  return (
    <div>
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}
