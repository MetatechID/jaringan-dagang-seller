"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, useAuth } from "@/lib/auth-context";
import { getSelectedStoreId } from "@/lib/api";

interface Member {
  membership_id: string;
  store_id: string;
  email: string;
  role: "owner" | "staff";
  accepted_at: string | null;
  created_at: string | null;
  pending: boolean;
  user: {
    id: string;
    email: string;
    display_name: string | null;
    photo_url: string | null;
  } | null;
}

export default function TeamPage() {
  const { me, myStores, getIdToken } = useAuth();
  const storeId = getSelectedStoreId();
  const currentStore = myStores.find((s) => s.id === storeId);
  const isOwner = me?.is_super_admin || currentStore?.role === "owner";

  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"owner" | "staff">("staff");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const token = await getIdToken();
      const res = await fetch(`${API_BASE}/api/stores/${storeId}/members`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const j = await res.json();
        setMembers(j.data || []);
      } else if (res.status === 403) {
        setMembers([]);
      }
    } finally {
      setLoading(false);
    }
  }, [storeId, getIdToken]);

  useEffect(() => { load(); }, [load]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    if (!storeId || !inviteEmail.trim()) return;
    setBusy(true);
    try {
      const token = await getIdToken();
      const res = await fetch(`${API_BASE}/api/stores/${storeId}/members`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });
      if (!res.ok) {
        const t = await res.text();
        alert(`Invite failed: ${t}`);
        return;
      }
      setInviteEmail("");
      setInviteRole("staff");
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function revoke(membershipId: string) {
    if (!storeId) return;
    if (!confirm("Remove this member from the store?")) return;
    const token = await getIdToken();
    const res = await fetch(
      `${API_BASE}/api/stores/${storeId}/members/${membershipId}`,
      { method: "DELETE", headers: token ? { Authorization: `Bearer ${token}` } : {} }
    );
    if (!res.ok) {
      alert(`Remove failed: ${await res.text()}`);
      return;
    }
    await load();
  }

  if (!storeId) {
    return <div className="p-6 text-slate-500">Select a store first.</div>;
  }

  return (
    <div className="p-6 max-w-4xl">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Team</h1>
        <p className="text-sm text-slate-500 mt-1">
          Manage who can access <span className="font-medium">{currentStore?.name || "this store"}</span>.
          {isOwner ? " You are an owner — you can invite or remove members." : " You have view access only."}
        </p>
      </header>

      {isOwner && (
        <form
          onSubmit={invite}
          className="mb-8 flex flex-wrap items-end gap-3 p-4 bg-white border rounded-lg"
        >
          <div className="flex-1 min-w-[220px]">
            <label className="block text-xs font-medium text-slate-600 mb-1">Email</label>
            <input
              type="email"
              required
              placeholder="teammate@example.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className="w-full px-3 py-2 border rounded text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Role</label>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as "owner" | "staff")}
              className="px-3 py-2 border rounded text-sm bg-white"
            >
              <option value="staff">Staff</option>
              <option value="owner">Owner</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={busy || !inviteEmail.trim()}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? "Inviting…" : "Invite"}
          </button>
        </form>
      )}

      <div className="bg-white border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Member</th>
              <th className="text-left px-4 py-3">Role</th>
              <th className="text-left px-4 py-3">Status</th>
              {isOwner && <th className="px-4 py-3"></th>}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">Loading…</td></tr>
            )}
            {!loading && members.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">No members yet.</td></tr>
            )}
            {members.map((m) => (
              <tr key={m.membership_id} className="border-t">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    {m.user?.photo_url ? (
                      <img src={m.user.photo_url} alt="" className="w-8 h-8 rounded-full" />
                    ) : (
                      <div className="w-8 h-8 rounded-full bg-slate-200 grid place-items-center text-xs text-slate-600">
                        {m.email[0]?.toUpperCase() || "?"}
                      </div>
                    )}
                    <div>
                      <div className="font-medium">{m.user?.display_name || m.email}</div>
                      <div className="text-xs text-slate-500">{m.email}</div>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${m.role === "owner" ? "bg-indigo-100 text-indigo-700" : "bg-slate-100 text-slate-700"}`}>
                    {m.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500">
                  {m.pending ? (
                    <span className="text-amber-600">Pending — invite will auto-claim on first sign-in</span>
                  ) : (
                    <span>Active{m.accepted_at ? ` since ${new Date(m.accepted_at).toLocaleDateString()}` : ""}</span>
                  )}
                </td>
                {isOwner && (
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => revoke(m.membership_id)}
                      className="text-xs px-2 py-1 text-red-600 hover:bg-red-50 rounded"
                    >
                      Remove
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
