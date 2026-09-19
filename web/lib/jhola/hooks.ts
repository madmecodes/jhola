"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { errorMessage } from "./client";

// ---- Admin key (localStorage, per viewer) ----

const KEY = "jhola.adminKey";
const keyListeners = new Set<() => void>();

function readKey(): string {
  try {
    return window.localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

let memoryKey: string | null = null;

export function setAdminKey(value: string) {
  memoryKey = value;
  try {
    if (value) window.localStorage.setItem(KEY, value);
    else window.localStorage.removeItem(KEY);
  } catch {
    // Storage blocked: keep the key in memory for this tab.
  }
  keyListeners.forEach((l) => l());
}

export function useAdminKey(): string {
  return useSyncExternalStore(
    (l) => {
      keyListeners.add(l);
      return () => keyListeners.delete(l);
    },
    () => memoryKey ?? readKey(),
    () => "",
  );
}

// ---- Polling fetch ----

export type Resource<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
};

export function usePolling<T>(fetcher: () => Promise<T>, intervalMs = 5000, deps: unknown[] = []): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const refresh = useCallback(async () => {
    try {
      const d = await fetcherRef.current();
      setData(d);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      if (cancelled) return;
      if (typeof document === "undefined" || document.visibilityState !== "hidden") await refresh();
      if (!cancelled && intervalMs > 0) timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, intervalMs, ...deps]);

  return { data, error, loading, refresh };
}
