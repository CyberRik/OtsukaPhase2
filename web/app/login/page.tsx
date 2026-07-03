"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, KeyRound, LayoutDashboard, UserRound } from "lucide-react";
import { useT } from "@/lib/i18n";
import { demoCreds, useSession, type Role } from "@/lib/session";
import { Brand } from "@/components/site/brand";
import { ClientBadge } from "@/components/site/client-badge";
import { LangToggle } from "@/components/site/lang-toggle";
import { Button } from "@/components/ui/button";

function LoginForm() {
  const { t } = useT();
  const router = useRouter();
  const { login } = useSession();
  const params = useSearchParams();
  const role: Role = params.get("role") === "manager" ? "manager" : "junior";
  const creds = demoCreds(role);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(false);

  const Icon = role === "manager" ? LayoutDashboard : UserRound;
  const accent = role === "manager" ? "text-navy" : "text-primary";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const resolved = await login(role, username, password);
    if (resolved) {
      router.replace(resolved === "manager" ? "/manager" : "/junior");
    } else {
      setError(true);
    }
  }

  return (
    <div className="hero-wash flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-5">
        <Brand fullMark tagline={t("app.tagline")} />
        <div className="flex items-center gap-3 sm:gap-4">
          <ClientBadge />
          <div className="hidden h-5 w-px bg-border sm:block" />
          <LangToggle />
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-sm">
          <Link href="/" className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> {t("login.switchRole")}
          </Link>

          <div className="rounded-2xl border border-border bg-card p-7 shadow-[0_8px_40px_-24px_rgba(16,24,40,0.4)]">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted">
                <Icon className={`h-5 w-5 ${accent}`} />
              </div>
              <div>
                <h1 className="text-lg font-semibold tracking-tight">
                  {t("login.title", { role: t(role === "manager" ? "role.manager" : "role.junior") })}
                </h1>
                <p className="text-[12px] text-muted-foreground">{t("login.subtitle")}</p>
              </div>
            </div>

            <form onSubmit={submit} className="mt-6 space-y-3">
              <div className="space-y-1.5">
                <label className="eyebrow">{t("login.username")}</label>
                <input
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); setError(false); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-1.5">
                <label className="eyebrow">{t("login.password")}</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(false); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>
              {error && <p className="text-[12px] text-band-red">{t("login.error")}</p>}
              <Button type="submit" variant="seal" className="w-full">{t("login.submit")}</Button>
            </form>

            <div className="mt-5 rounded-lg border border-dashed border-border bg-muted/40 p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                  <KeyRound className="h-3.5 w-3.5" /> {t("login.demo")}
                </div>
                <button
                  onClick={() => { setUsername(creds.username); setPassword(creds.password); setError(false); }}
                  className="text-[11px] font-medium text-primary hover:underline"
                >
                  {t("login.useThese")}
                </button>
              </div>
              <div className="mt-2 font-mono text-[12px] text-foreground">
                {creds.username} / {creds.password}
              </div>
            </div>

            {role === "junior" && (
              <p className="mt-5 text-center text-[12px] text-muted-foreground">
                {t("login.noAccount")}{" "}
                <Link href="/signup" className="font-medium text-primary hover:underline">
                  {t("login.createAccount")}
                </Link>
              </p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
