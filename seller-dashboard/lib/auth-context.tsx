"use client";

import {
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
  type User as FirebaseUser,
} from "firebase/auth";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { firebaseConfigured, getFirebaseAuth } from "./firebase";
import { setIdTokenGetter } from "./api";

export interface MeUser {
  id: string;
  email: string;
  display_name: string | null;
  photo_url: string | null;
  is_super_admin: boolean;
}

export interface MyStore {
  id: string;
  subscriber_id: string;
  name: string;
  description: string | null;
  logo_url: string | null;
  domain: string | null;
  city: string | null;
  status: string;
  role: "owner" | "staff" | "super_admin";
  membership_id: string | null;
}

interface AuthCtx {
  ready: boolean;            // initial state resolved
  firebaseConfigured: boolean;
  firebaseUser: FirebaseUser | null;
  me: MeUser | null;
  myStores: MyStore[];
  loadingMe: boolean;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  getIdToken: () => Promise<string | null>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

const API_BASE =
  process.env.NEXT_PUBLIC_BPP_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:8001";

// Beli Aman is the network Identity Provider. Identity + ACL (who am I, which
// stores can I manage) is resolved here. Store *details* (name/logo) still
// come from the seller catalog API (API_BASE).
const IDENTITY_BASE =
  process.env.NEXT_PUBLIC_IDENTITY_API_URL ||
  "https://api.beli-aman.metatech.id";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<MeUser | null>(null);
  const [myStores, setMyStores] = useState<MyStore[]>([]);
  const [loadingMe, setLoadingMe] = useState(false);

  const getIdToken = useCallback(async () => {
    const auth = getFirebaseAuth();
    if (!auth?.currentUser) return null;
    return auth.currentUser.getIdToken();
  }, []);

  const fetchMe = useCallback(async () => {
    setLoadingMe(true);
    try {
      const token = await getIdToken();
      if (!token) {
        setMe(null);
        setMyStores([]);
        return;
      }
      const authH = { Authorization: `Bearer ${token}` };

      // 1. Identity + ACL from Beli Aman (the IdP).
      const [meRes, aclRes] = await Promise.all([
        fetch(`${IDENTITY_BASE}/api/v1/me`, { headers: authH }),
        fetch(`${IDENTITY_BASE}/api/v1/me/stores`, { headers: authH }),
      ]);

      let profile: MeUser | null = null;
      if (meRes.ok) {
        const j = await meRes.json();
        // Beli Aman /api/v1/me returns the profile object directly (not {data})
        profile = {
          id: j.id,
          email: j.email,
          display_name: j.display_name ?? null,
          photo_url: j.photo_url ?? null,
          is_super_admin: !!j.is_super_admin,
        };
      }
      setMe(profile);

      let acl: { store_id: string; role: string }[] = [];
      let isSuper = false;
      if (aclRes.ok) {
        const j = await aclRes.json();
        isSuper = !!j.is_super_admin;
        acl = j.data || [];
      }

      // 2. Store details from the seller catalog API, then join with ACL.
      let allStores: any[] = [];
      try {
        const sRes = await fetch(`${API_BASE}/api/stores`);
        if (sRes.ok) {
          const sj = await sRes.json();
          allStores = sj.data || [];
        }
      } catch {
        /* seller API optional for the list; ACL is authoritative */
      }

      let stores: MyStore[];
      if (isSuper || profile?.is_super_admin) {
        stores = allStores.map((s) => ({
          id: s.id,
          subscriber_id: s.subscriber_id,
          name: s.name,
          description: s.description ?? null,
          logo_url: s.logo_url ?? null,
          domain: s.domain ?? null,
          city: s.city ?? null,
          status: s.status,
          role: "super_admin" as const,
          membership_id: null,
        }));
      } else {
        const byId = new Map(allStores.map((s) => [s.id, s]));
        stores = acl
          .map((m) => {
            const s = byId.get(m.store_id);
            if (!s) return null;
            return {
              id: s.id,
              subscriber_id: s.subscriber_id,
              name: s.name,
              description: s.description ?? null,
              logo_url: s.logo_url ?? null,
              domain: s.domain ?? null,
              city: s.city ?? null,
              status: s.status,
              role: (m.role as "owner" | "staff"),
              membership_id: (m as any).membership_id ?? null,
            } as MyStore;
          })
          .filter(Boolean) as MyStore[];
      }
      setMyStores(stores);
    } finally {
      setLoadingMe(false);
    }
  }, [getIdToken]);

  useEffect(() => {
    // Register the token getter so lib/api.ts can attach Authorization headers
    // on every API call made from anywhere in the app.
    setIdTokenGetter(getIdToken);
    return () => setIdTokenGetter(null);
  }, [getIdToken]);

  useEffect(() => {
    if (!firebaseConfigured) {
      setReady(true);
      return;
    }
    const auth = getFirebaseAuth();
    if (!auth) {
      setReady(true);
      return;
    }
    const unsub = onAuthStateChanged(auth, async (u) => {
      setFirebaseUser(u);
      setReady(true);
      if (u) {
        await fetchMe();
      } else {
        setMe(null);
        setMyStores([]);
      }
    });
    return () => unsub();
  }, [fetchMe]);

  const signInWithGoogle = useCallback(async () => {
    const auth = getFirebaseAuth();
    if (!auth) throw new Error("Firebase not configured");
    const provider = new GoogleAuthProvider();
    await signInWithPopup(auth, provider);
  }, []);

  const signOut = useCallback(async () => {
    const auth = getFirebaseAuth();
    if (auth) await firebaseSignOut(auth);
    setMe(null);
    setMyStores([]);
  }, []);

  const value: AuthCtx = useMemo(
    () => ({
      ready,
      firebaseConfigured,
      firebaseUser,
      me,
      myStores,
      loadingMe,
      signInWithGoogle,
      signOut,
      getIdToken,
      refresh: fetchMe,
    }),
    [ready, firebaseUser, me, myStores, loadingMe, signInWithGoogle, signOut, getIdToken, fetchMe]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}

/** Convenience wrapper for authed fetches. Adds the Bearer token header. */
export async function authedFetch(
  path: string,
  init: RequestInit = {},
  getToken: () => Promise<string | null>
): Promise<Response> {
  const token = await getToken();
  const headers = new Headers(init.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_BASE}${path}`, { ...init, headers });
}

export { API_BASE };
