"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  fetchProduct,
  updateProduct,
  createProduct,
  type Product,
  type SKU,
} from "@/lib/api";
import { formatIDR } from "@/lib/format";
import LoadingSpinner from "@/components/LoadingSpinner";

interface SkuDraft {
  id?: string;
  variant_name: string;
  variant_value: string;
  sku_code: string;
  price: string;
  original_price: string;
  stock: string;
  weight_grams: string;
}

function emptySkuDraft(): SkuDraft {
  return {
    variant_name: "",
    variant_value: "",
    sku_code: "",
    price: "",
    original_price: "",
    stock: "0",
    weight_grams: "",
  };
}

export default function ProductDetailPage() {
  const params = useParams();
  const router = useRouter();
  const isNew = params.id === "new";
  const productId = isNew ? null : (params.id as string);

  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sku, setSku] = useState("");
  const [status, setStatus] = useState<string>("draft");
  const [attributes, setAttributes] = useState<string>("{}");
  const [imageUrls, setImageUrls] = useState<string[]>([""]);
  const [skus, setSkus] = useState<SkuDraft[]>([emptySkuDraft()]);

  useEffect(() => {
    if (!productId) return;
    fetchProduct(productId)
      .then((p) => {
        setName(p.name);
        setDescription(p.description || "");
        setSku(p.sku || "");
        setStatus(p.status);
        setAttributes(JSON.stringify(p.attributes || {}, null, 2));
        setImageUrls(
          p.images.length > 0 ? p.images.map((i) => i.url) : [""]
        );
        setSkus(
          p.skus.length > 0
            ? p.skus.map((s) => ({
                id: s.id,
                variant_name: s.variant_name || "",
                variant_value: s.variant_value || "",
                sku_code: s.sku_code,
                price: s.price.toString(),
                original_price: s.original_price?.toString() || "",
                stock: s.stock.toString(),
                weight_grams: s.weight_grams?.toString() || "",
              }))
            : [emptySkuDraft()]
        );
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [productId]);

  function addImageSlot() {
    setImageUrls([...imageUrls, ""]);
  }

  function removeImageSlot(index: number) {
    setImageUrls(imageUrls.filter((_, i) => i !== index));
  }

  function updateImageUrl(index: number, url: string) {
    const next = [...imageUrls];
    next[index] = url;
    setImageUrls(next);
  }

  function addSkuRow() {
    setSkus([...skus, emptySkuDraft()]);
  }

  function removeSkuRow(index: number) {
    setSkus(skus.filter((_, i) => i !== index));
  }

  function updateSku(index: number, field: keyof SkuDraft, value: string) {
    const next = [...skus];
    next[index] = { ...next[index], [field]: value };
    setSkus(next);
  }

  async function handleSave() {
    setError(null);
    setSuccess(false);
    setSaving(true);

    try {
      let parsedAttrs: Record<string, unknown> = {};
      try {
        parsedAttrs = JSON.parse(attributes);
      } catch {
        /* ignore parse errors, send empty */
      }

      if (isNew) {
        const body = {
          name,
          description: description || null,
          sku: sku || null,
          status,
          attributes: parsedAttrs,
          images: imageUrls
            .filter((u) => u.trim())
            .map((url, i) => ({
              url,
              position: i,
              is_primary: i === 0,
            })),
          skus: skus
            .filter((s) => s.sku_code.trim())
            .map((s) => ({
              variant_name: s.variant_name || null,
              variant_value: s.variant_value || null,
              sku_code: s.sku_code,
              price: parseFloat(s.price) || 0,
              original_price: s.original_price
                ? parseFloat(s.original_price)
                : null,
              stock: parseInt(s.stock) || 0,
              weight_grams: s.weight_grams
                ? parseInt(s.weight_grams)
                : null,
            })),
        };
        const created = await createProduct(body);
        router.push(`/products/${created.id}`);
      } else {
        await updateProduct(productId!, {
          name,
          description: description || null,
          sku: sku || null,
          status,
          attributes: parsedAttrs,
        });
        setSuccess(true);
        setTimeout(() => setSuccess(false), 3000);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <LoadingSpinner />;

  return (
    <div className="p-6 lg:p-8 max-w-4xl space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <Link href="/products" className="text-gray-500 hover:text-gray-700">
          Products
        </Link>
        <svg className="w-4 h-4 text-gray-300" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
        </svg>
        <span className="text-gray-900 font-medium">
          {isNew ? "New Product" : name || "Edit"}
        </span>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          Product saved successfully.
        </div>
      )}

      {/* Basic info */}
      <div className="card p-6 space-y-5">
        <h3 className="text-base font-semibold text-gray-900">Basic Information</h3>

        <div>
          <label className="label">Product Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Matchamu Latte 250ml"
            className="input"
          />
        </div>

        <div>
          <label className="label">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Product description..."
            rows={4}
            className="input resize-y"
          />
        </div>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
          <div>
            <label className="label">SKU Code</label>
            <input
              type="text"
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              placeholder="MCH-001"
              className="input font-mono"
            />
          </div>
          <div>
            <label className="label">Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="input"
            >
              <option value="draft">Draft</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </select>
          </div>
          <div>
            <label className="label">Category</label>
            <input
              type="text"
              placeholder="Category ID (optional)"
              className="input"
              disabled
            />
          </div>
        </div>

        <div>
          <label className="label">Attributes (JSON)</label>
          <textarea
            value={attributes}
            onChange={(e) => setAttributes(e.target.value)}
            rows={3}
            className="input font-mono text-xs resize-y"
          />
        </div>
      </div>

      {/* Images */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900">Images</h3>
          <button onClick={addImageSlot} className="btn-ghost text-xs">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Add Image
          </button>
        </div>

        <div className="space-y-3">
          {imageUrls.map((url, i) => (
            <div key={i} className="flex items-center gap-3">
              {url && (
                <img
                  src={url}
                  alt=""
                  className="h-12 w-12 rounded-lg object-cover border border-gray-100 shrink-0"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                  }}
                />
              )}
              <input
                type="text"
                value={url}
                onChange={(e) => updateImageUrl(i, e.target.value)}
                placeholder="https://example.com/image.jpg"
                className="input flex-1"
              />
              {imageUrls.length > 1 && (
                <button
                  onClick={() => removeImageSlot(i)}
                  className="rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
              {i === 0 && (
                <span className="badge bg-brand-50 text-brand-700 shrink-0">Primary</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Variants / SKUs */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900">
            Variants (SKUs)
          </h3>
          <button onClick={addSkuRow} className="btn-ghost text-xs">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Add Variant
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="pb-2 text-left font-medium text-gray-500">Variant</th>
                <th className="pb-2 text-left font-medium text-gray-500">Value</th>
                <th className="pb-2 text-left font-medium text-gray-500">SKU Code</th>
                <th className="pb-2 text-left font-medium text-gray-500">Price (IDR)</th>
                <th className="pb-2 text-left font-medium text-gray-500">Stock</th>
                <th className="pb-2 text-left font-medium text-gray-500">Weight (g)</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {skus.map((s, i) => (
                <tr key={i}>
                  <td className="py-2 pr-2">
                    <input
                      type="text"
                      value={s.variant_name}
                      onChange={(e) => updateSku(i, "variant_name", e.target.value)}
                      placeholder="Size"
                      className="input text-xs"
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="text"
                      value={s.variant_value}
                      onChange={(e) => updateSku(i, "variant_value", e.target.value)}
                      placeholder="250ml"
                      className="input text-xs"
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="text"
                      value={s.sku_code}
                      onChange={(e) => updateSku(i, "sku_code", e.target.value)}
                      placeholder="MCH-001-S"
                      className="input text-xs font-mono"
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="number"
                      value={s.price}
                      onChange={(e) => updateSku(i, "price", e.target.value)}
                      placeholder="35000"
                      className="input text-xs"
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="number"
                      value={s.stock}
                      onChange={(e) => updateSku(i, "stock", e.target.value)}
                      placeholder="100"
                      className="input text-xs w-20"
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="number"
                      value={s.weight_grams}
                      onChange={(e) => updateSku(i, "weight_grams", e.target.value)}
                      placeholder="300"
                      className="input text-xs w-20"
                    />
                  </td>
                  <td className="py-2">
                    {skus.length > 1 && (
                      <button
                        onClick={() => removeSkuRow(i)}
                        className="rounded-lg p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                        </svg>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between">
        <Link href="/products" className="btn-ghost">
          Cancel
        </Link>
        <button onClick={handleSave} disabled={saving || !name.trim()} className="btn-primary">
          {saving ? (
            <>
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Saving...
            </>
          ) : isNew ? (
            "Create Product"
          ) : (
            "Save Changes"
          )}
        </button>
      </div>
    </div>
  );
}
