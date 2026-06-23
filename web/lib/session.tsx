"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type Role = "junior" | "manager";

// DEMO ONLY — not real authentication. The point is to demonstrate two distinct
// product experiences over the same backend. No database, no security.
const CREDENTIALS: Record<Role, { username: string; password: string }> = {
  junior: { username: "junior", password: "demo123" },
  manager: { username: "manager", password: "demo123" },
};

export function demoCreds(role: Role) {
  return CREDENTIALS[role];
}

type Ctx = {
  role: Role | null;
  ready: boolean;
  login: (role: Role, username: string, password: string) => boolean;
  logout: () => void;
};

const SessionContext = createContext<Ctx | null>(null);

function readCookieRole(): Role | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|;\s*)senpai\.role=(junior|manager)/);
  return (m?.[1] as Role) ?? null;
}

export function SessionProvider({ initial, children }: { initial: Role | null; children: React.ReactNode }) {
  const [role, setRole] = useState<Role | null>(initial);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setRole(readCookieRole());
    setReady(true);
  }, []);

  const login = (r: Role, username: string, password: string) => {
    const c = CREDENTIALS[r];
    if (username.trim() !== c.username || password !== c.password) return false;
    setRole(r);
    document.cookie = `senpai.role=${r};path=/;max-age=86400;samesite=lax`;
    return true;
  };

  const logout = () => {
    setRole(null);
    document.cookie = "senpai.role=;path=/;max-age=0;samesite=lax";
  };

  return (
    <SessionContext.Provider value={{ role, ready, login, logout }}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
