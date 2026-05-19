"use client";

import { useEffect, useRef } from "react";

/**
 * Run `tick` on a `delayMs` interval, but pause whenever the tab is hidden
 * and resume on visibility-change. Resets if `delayMs` or `enabled` change.
 *
 * `tick` is wrapped in a ref so callers don't need to memoise it.
 */
export function useVisiblePolling(
  tick: () => void | Promise<void>,
  delayMs: number,
  enabled: boolean = true
): void {
  const tickRef = useRef(tick);
  useEffect(() => {
    tickRef.current = tick;
  }, [tick]);

  useEffect(() => {
    if (!enabled) return;
    if (typeof document === "undefined") return;

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    function start() {
      if (timer != null) return;
      timer = setInterval(() => {
        if (cancelled) return;
        void tickRef.current();
      }, delayMs);
    }

    function stop() {
      if (timer != null) {
        clearInterval(timer);
        timer = null;
      }
    }

    function onVisibility() {
      if (document.visibilityState === "visible") {
        start();
      } else {
        stop();
      }
    }

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [delayMs, enabled]);
}
