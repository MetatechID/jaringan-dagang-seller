"use client";

import { useEffect, useState } from "react";
import { fetchStore, updateStore, type StoreSettings } from "@/lib/api";
import LoadingSpinner from "@/components/LoadingSpinner";

export default function SettingsPage() {
  const [store, setStore] = useState<StoreSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [domain, setDomain] = useState("");
  const [city, setCity] = useState("");

  useEffect(() => {
    fetchStore()
      .then((s) => {
        setStore(s);
        setName(s.name);
        setDescription(s.description || "");
        setLogoUrl(s.logo_url || "");
        setDomain(s.domain);
        setCity(s.city);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function handleSave() {
    setError(null);
    setSuccess(false);
    setSaving(true);
    try {
      const updated = await updateStore({
        name,
        description: description || null,
        logo_url: logoUrl || null,
        domain,
        city,
      });
      setStore(updated);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <LoadingSpinner />;

  return (
    <div className="p-6 lg:p-8 max-w-3xl space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900">Store Settings</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Manage your store profile and integration settings.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          Settings saved successfully.
        </div>
      )}

      {/* Store profile */}
      <div className="card p-6 space-y-5">
        <h3 className="text-base font-semibold text-gray-900">Store Profile</h3>

        <div className="flex items-start gap-5">
          {logoUrl ? (
            <img
              src={logoUrl}
              alt="Store logo"
              className="h-16 w-16 rounded-xl object-cover border border-gray-200 shrink-0"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-brand-50 text-brand-600 shrink-0">
              <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 21v-7.5a.75.75 0 0 1 .75-.75h3a.75.75 0 0 1 .75.75V21m-4.5 0H2.36m11.14 0H18m0 0h3.64m-1.39 0V9.349M3.75 21V9.349m0 0a3.001 3.001 0 0 0 3.75-.615A2.993 2.993 0 0 0 9.75 9.75c.896 0 1.7-.393 2.25-1.016a2.993 2.993 0 0 0 2.25 1.016c.896 0 1.7-.393 2.25-1.015a3.001 3.001 0 0 0 3.75.614m-16.5 0a3.004 3.004 0 0 1-.621-4.72l1.189-1.19A1.5 1.5 0 0 1 5.378 3h13.243a1.5 1.5 0 0 1 1.06.44l1.19 1.189a3 3 0 0 1-.621 4.72M6.75 18h3.75a.75.75 0 0 0 .75-.75V13.5a.75.75 0 0 0-.75-.75H6.75a.75.75 0 0 0-.75.75v3.75c0 .414.336.75.75.75Z" />
              </svg>
            </div>
          )}
          <div className="flex-1 space-y-1">
            <label className="label">Logo URL</label>
            <input
              type="text"
              value={logoUrl}
              onChange={(e) => setLogoUrl(e.target.value)}
              placeholder="https://example.com/logo.png"
              className="input"
            />
          </div>
        </div>

        <div>
          <label className="label">Store Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your store name"
            className="input"
          />
        </div>

        <div>
          <label className="label">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Tell customers about your store..."
            rows={3}
            className="input resize-y"
          />
        </div>
      </div>

      {/* Beckn subscriber info */}
      <div className="card p-6 space-y-5">
        <h3 className="text-base font-semibold text-gray-900">
          Beckn Network Configuration
        </h3>
        <p className="text-sm text-gray-500 -mt-2">
          Your store&apos;s identity on the open commerce network.
        </p>

        <div>
          <label className="label">Subscriber ID</label>
          <input
            type="text"
            value={store?.subscriber_id || ""}
            disabled
            className="input bg-gray-50 text-gray-500 cursor-not-allowed"
          />
          <p className="mt-1 text-xs text-gray-400">
            This is set during onboarding and cannot be changed.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <div>
            <label className="label">Domain</label>
            <input
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="nic2004:52110"
              className="input font-mono text-sm"
            />
          </div>
          <div>
            <label className="label">City Code</label>
            <input
              type="text"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="ID:JKT"
              className="input font-mono text-sm"
            />
          </div>
        </div>

        {store?.signing_public_key && (
          <div>
            <label className="label">Signing Public Key</label>
            <div className="rounded-lg bg-gray-50 p-3 font-mono text-xs text-gray-500 break-all">
              {store.signing_public_key}
            </div>
          </div>
        )}
      </div>

      {/* Integration status */}
      <div className="card p-6 space-y-5">
        <h3 className="text-base font-semibold text-gray-900">Integrations</h3>

        <div className="space-y-4">
          {/* Xendit */}
          <div className="flex items-center justify-between rounded-lg border border-gray-200 px-4 py-3.5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50">
                <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 0 0 2.25-2.25V6.75A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25v10.5A2.25 2.25 0 0 0 4.5 19.5Z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">Xendit</p>
                <p className="text-xs text-gray-500">Payment gateway</p>
              </div>
            </div>
            <span className="badge bg-emerald-50 text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mr-1.5" />
              Connected
            </span>
          </div>

          {/* Biteship */}
          <div className="flex items-center justify-between rounded-lg border border-gray-200 px-4 py-3.5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-50">
                <svg className="w-5 h-5 text-orange-600" fill="none" viewBox="0 0 24 24" strokeWidth={1.75} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 18.75a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m3 0h6m-9 0H3.375a1.125 1.125 0 0 1-1.125-1.125V14.25m17.25 4.5a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m3 0h1.125c.621 0 1.129-.504 1.09-1.124a17.902 17.902 0 0 0-3.213-9.193 2.056 2.056 0 0 0-1.58-.86H14.25M16.5 18.75h-2.25m0-11.177v-.958c0-.568-.422-1.048-.987-1.106a48.554 48.554 0 0 0-10.026 0 1.106 1.106 0 0 0-.987 1.106v7.635m12-6.677v6.677m0 4.5v-4.5m0 0h-12" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">Biteship</p>
                <p className="text-xs text-gray-500">Shipping & logistics</p>
              </div>
            </div>
            <span className="badge bg-emerald-50 text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mr-1.5" />
              Connected
            </span>
          </div>
        </div>
      </div>

      {/* Save button */}
      <div className="flex items-center justify-end">
        <button
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="btn-primary"
        >
          {saving ? (
            <>
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Saving...
            </>
          ) : (
            "Save Settings"
          )}
        </button>
      </div>
    </div>
  );
}
