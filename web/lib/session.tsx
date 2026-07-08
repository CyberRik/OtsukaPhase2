"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";

export type Role = "junior" | "manager";

// Built-in demo accounts. Real signup/login now go through the FastAPI bridge
// (persisted, hashed users); these stay as an OFFLINE FALLBACK so the showcase
// still works with the backend down — mirroring how api.ts falls back to fixtures.
// These are REAL seeded reps (see scripts/seed_rep_logins.py): 伊藤翔 (R05,
// junior) and 田中健太 (R01, manager), so the fallback shows the same person
// the backend account resolves to.
const CREDENTIALS: Record<Role, { username: string; password: string; employeeId: string; name: string }> = {
  junior: { username: "itoushou", password: "demo123", employeeId: "R05", name: "伊藤翔" },
  manager: { username: "tanakakenta", password: "demo123", employeeId: "R01", name: "田中健太" },
};

export function demoCreds(role: Role) {
  return CREDENTIALS[role];
}

type Ctx = {
  role: Role | null;
  username: string | null;
  // The seed rep this account is; scopes the data (a junior's own rep, or a
  // manager's identity).
  employeeId: string | null;
  ready: boolean;
  // Resolve to the account's role on success, or null on failure. `roleHint`
  // (from the login page URL) is only used to pick the demo account when the
  // backend is unreachable; a real login's role comes from the account itself.
  login: (roleHint: Role, username: string, password: string) => Promise<Role | null>;
  // Register a new junior: creates a fresh rep assigned to `managerId`.
  signup: (
    username: string,
    password: string,
    name: string,
    managerId: string,
  ) => Promise<{ ok: boolean; role?: Role; error?: string }>;
  logout: () => void;
};

const SessionContext = createContext<Ctx | null>(null);

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

function writeCookie(name: string, value: string, maxAge = 86400) {
  document.cookie = `${name}=${encodeURIComponent(value)};path=/;max-age=${maxAge};samesite=lax`;
}

function clearCookie(name: string) {
  document.cookie = `${name}=;path=/;max-age=0;samesite=lax`;
}

function readCookieRole(): Role | null {
  const r = readCookie("senpai.role");
  return r === "junior" || r === "manager" ? r : null;
}

export function SessionProvider({ initial, children }: { initial: Role | null; children: React.ReactNode }) {
  const [role, setRole] = useState<Role | null>(initial);
  const [username, setUsername] = useState<string | null>(null);
  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setRole(readCookieRole());
    setUsername(readCookie("senpai.user"));
    setEmployeeId(readCookie("senpai.emp"));
    setReady(true);
  }, []);

  const persist = (r: Role, user: string, emp?: string | null, token?: string) => {
    setRole(r);
    setUsername(user);
    setEmployeeId(emp ?? null);
    writeCookie("senpai.role", r);
    writeCookie("senpai.user", user);
    // The server reads senpai.emp to scope a junior's data (see lib/server-session).
    if (emp) writeCookie("senpai.emp", emp);
    else clearCookie("senpai.emp");
    if (token) writeCookie("senpai.token", token);
  };

  const login = async (roleHint: Role, user: string, password: string): Promise<Role | null> => {
    const res = await api.login(user.trim(), password);
    if (res.ok && res.role) {
      persist(res.role, res.username ?? user.trim(), res.employee_id, res.token);
      return res.role;
    }
    // Backend unreachable/unknown user: fall back to the built-in demo account
    // for the role the user was signing in as, so the demo works offline.
    if (res.error === "network") {
      const demo = CREDENTIALS[roleHint];
      if (user.trim() === demo.username && password === demo.password) {
        persist(roleHint, demo.username, demo.employeeId);
        return roleHint;
      }
    }
    return null;
  };

  const signup = async (user: string, password: string, name: string, managerId: string) => {
    const res = await api.signup(user.trim(), password, name.trim(), managerId);
    if (res.ok && res.role) {
      persist(res.role, res.username ?? user.trim(), res.employee_id, res.token);
      return { ok: true, role: res.role };
    }
    return { ok: false, error: res.error };
  };

  const logout = () => {
    setRole(null);
    setUsername(null);
    setEmployeeId(null);
    clearCookie("senpai.role");
    clearCookie("senpai.user");
    clearCookie("senpai.emp");
    clearCookie("senpai.token");
  };

  return (
    <SessionContext.Provider value={{ role, username, employeeId, ready, login, signup, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
