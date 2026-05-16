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
      const [r1, r2] = await Promise.all([
        fetch(`${API_BASE}/api/me`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_BASE}/api/me/stores`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (r1.ok) {
        const j = await r1.json();
        setMe(j.data || null);
      } else {
        setMe(null);
      }
      if (r2.ok) {
        const j = await r2.json();
        setMyStores(j.data || []);
      } else {
        setMyStores([]);
      }
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
