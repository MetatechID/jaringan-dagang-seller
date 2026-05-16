"use client";

import { getApps, initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

// Defaults match the Beli Aman production Firebase project — the same one the
// buyer storefront admin uses, so one Google account works across both apps.
// These are NEXT_PUBLIC values (baked into the bundle on every Vercel build),
// not secrets. Override per env if you want a separate project for dev.
const DEFAULTS = {
  apiKey: "AIzaSyB8ZTKFoecIcKuPnjnStvnfbeQSByEAxOE",
  authDomain: "beli-aman-prod.firebaseapp.com",
  projectId: "beli-aman-prod",
  storageBucket: "beli-aman-prod.firebasestorage.app",
  messagingSenderId: "25545873372",
  appId: "1:25545873372:web:db5c292d1be76062636119",
};

const config = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || DEFAULTS.apiKey,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || DEFAULTS.authDomain,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || DEFAULTS.projectId,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET || DEFAULTS.storageBucket,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID || DEFAULTS.messagingSenderId,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || DEFAULTS.appId,
};

export const firebaseConfigured = !!config.apiKey;

let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;

export function getFirebaseApp(): FirebaseApp | null {
  if (typeof window === "undefined") return null;
  if (!firebaseConfigured) return null;
  if (_app) return _app;
  const existing = getApps().find((a) => a.name === "jaringan-dagang-seller");
  _app = existing || initializeApp(config, "jaringan-dagang-seller");
  return _app;
}

export function getFirebaseAuth(): Auth | null {
  if (_auth) return _auth;
  const app = getFirebaseApp();
  if (!app) return null;
  _auth = getAuth(app);
  return _auth;
}
