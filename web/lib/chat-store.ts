"use client";

// External transcript store that survives client-side navigation. Next.js
// unmounts a page's components when you switch routes (e.g. Assistant ↔ Review
// Coach), which throws away their local state — and, worse, orphans any
// in-flight streaming fetch so its updates can never reach the new mount.
//
// The fix: keep chat state in a module-level store keyed by a *string*, not by a
// component instance, and expose it through useSyncExternalStore. Because the
// setter writes to the store (and notifies by key), a stream started in one
// mount keeps updating the store after that mount unmounts, and the *remounted*
// component — subscribed to the same key — re-renders live. So generation
// continues seamlessly across tab switches instead of dying with an error.
//
// A full page reload reinitialises the module (the expected "start fresh").
// State is only ever written from client code, so the store is empty during SSR
// and on the first client render — no hydration mismatch.

import { useCallback, useRef, useSyncExternalStore, type Dispatch, type SetStateAction } from "react";

const values = new Map<string, unknown>();
const listeners = new Map<string, Set<() => void>>();

function emit(key: string): void {
  listeners.get(key)?.forEach((l) => l());
}
function subscribeKey(key: string, cb: () => void): () => void {
  let set = listeners.get(key);
  if (!set) {
    set = new Set();
    listeners.set(key, set);
  }
  set.add(cb);
  return () => {
    set!.delete(cb);
  };
}

export function getCached<T>(key: string): T | undefined {
  return values.get(key) as T | undefined;
}
export function setCached<T>(key: string, value: T): void {
  values.set(key, value);
  emit(key);
}
export function clearCached(key: string): void {
  values.delete(key);
  emit(key);
}

/**
 * Like `useState`, but the value lives in the keyed external store, so it is
 * shared across every mount that uses the same `key` — and survives unmount
 * (navigation). The setter notifies subscribers, so a write from a still-running
 * stream (started in a previous mount) updates the current mount live.
 */
export function useCachedState<T>(
  key: string,
  initial: T | (() => T),
): [T, Dispatch<SetStateAction<T>>] {
  // Stable initial value, used until the store has an entry for this key. Held
  // in a ref so getSnapshot returns a stable reference (no render loop).
  const initialRef = useRef<{ v: T } | null>(null);
  if (initialRef.current === null) {
    initialRef.current = { v: typeof initial === "function" ? (initial as () => T)() : initial };
  }

  const subscribe = useCallback((cb: () => void) => subscribeKey(key, cb), [key]);
  const getSnapshot = useCallback<() => T>(() => {
    return values.has(key) ? (values.get(key) as T) : initialRef.current!.v;
  }, [key]);
  const value = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const setValue = useCallback<Dispatch<SetStateAction<T>>>(
    (action) => {
      const prev = (values.has(key) ? values.get(key) : initialRef.current!.v) as T;
      const next = typeof action === "function" ? (action as (p: T) => T)(prev) : action;
      values.set(key, next);
      emit(key);
    },
    [key],
  );

  return [value, setValue];
}

/**
 * A stable conversation id that persists across remounts (so the backend keeps
 * the same conversation cache). `reset()` mints a fresh one (e.g. on "Clear").
 */
export function useCachedConversationId(key: string): { current: string; reset: () => string } {
  const ref = useRef<string>("");
  if (!ref.current) {
    ref.current = getCached<string>(key) ?? makeId();
    setCached(key, ref.current);
  }
  return {
    get current() {
      return ref.current;
    },
    reset() {
      ref.current = makeId();
      setCached(key, ref.current);
      return ref.current;
    },
  };
}

function makeId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
