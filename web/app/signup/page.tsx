"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, LayoutDashboard, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useSession, type Role } from "@/lib/session";
import { Brand } from "@/components/site/brand";
import { LangToggle } from "@/components/site/lang-toggle";
import { Button } from "@/components/ui/button";

function SignupForm() {
  const { t } = useT();
  const router = useRouter();
  const { signup } = useSession();
  const params = useSearchParams();
  const initialRole: Role = params.get("role") === "manager" ? "manager" : "junior";

  const [role, setRole] = useState<Role>(initialRole);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [empId, setEmpId] = useState("");
  const [juniors, setJuniors] = useState<{ employee_id: string; name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The roster a junior adopts a rep from ("which salesperson am I?").
  useEffect(() => {
    api.juniorReps().then(({ data }) => setJuniors(data.juniors));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (role === "junior" && !empId) {
      setError(t("signup.pickRep"));
      return;
    }
    setBusy(true);
    setError(null);
    const res = await signup(role, username, password, role === "junior" ? empId : undefined);
    setBusy(false);
    if (res.ok && res.role) {
      router.replace(res.role === "manager" ? "/manager" : "/junior");
    } else {
      setError(res.error === "username already taken" ? t("signup.taken") : t("signup.error"));
    }
  }

  const roles: { value: Role; label: string; icon: typeof UserRound; accent: string }[] = [
    { value: "junior", label: t("role.junior"), icon: UserRound, accent: "text-primary" },
    { value: "manager", label: t("role.manager"), icon: LayoutDashboard, accent: "text-navy" },
  ];

  return (
    <div className="hero-wash flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-5">
        <Brand fullMark tagline={t("app.tagline")} />
        <LangToggle />
      </header>

      <main className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-sm">
          <Link href="/" className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> {t("login.switchRole")}
          </Link>

          <div className="rounded-2xl border border-border bg-card p-7 shadow-[0_8px_40px_-24px_rgba(16,24,40,0.4)]">
            <div>
              <h1 className="text-lg font-semibold tracking-tight">{t("signup.title")}</h1>
              <p className="text-[12px] text-muted-foreground">{t("signup.subtitle")}</p>
            </div>

            <form onSubmit={submit} className="mt-6 space-y-3">
              <div className="space-y-1.5">
                <label className="eyebrow">{t("signup.role")}</label>
                <div className="grid grid-cols-2 gap-2">
                  {roles.map((r) => {
                    const Icon = r.icon;
                    const selected = role === r.value;
                    return (
                      <button
                        key={r.value}
                        type="button"
                        onClick={() => setRole(r.value)}
                        className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-[13px] font-medium transition-colors ${
                          selected
                            ? "border-primary bg-primary/5 text-foreground"
                            : "border-input bg-card text-muted-foreground hover:border-primary/40"
                        }`}
                      >
                        <Icon className={`h-4 w-4 ${r.accent}`} /> {r.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {role === "junior" && (
                <div className="space-y-1.5">
                  <label className="eyebrow">{t("signup.whichRep")}</label>
                  <select
                    value={empId}
                    onChange={(e) => { setEmpId(e.target.value); setError(null); }}
                    className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <option value="">{t("signup.pickRep")}</option>
                    {juniors.map((r) => (
                      <option key={r.employee_id} value={r.employee_id}>
                        {r.name} ({r.employee_id})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="space-y-1.5">
                <label className="eyebrow">{t("signup.username")}</label>
                <input
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); setError(null); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-1.5">
                <label className="eyebrow">{t("signup.password")}</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(null); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>
              {error && <p className="text-[12px] text-band-red">{error}</p>}
              <Button type="submit" variant="seal" className="w-full" disabled={busy}>
                {t("signup.submit")}
              </Button>
            </form>

            <p className="mt-5 text-center text-[12px] text-muted-foreground">
              {t("signup.haveAccount")}{" "}
              <Link href={`/login?role=${role}`} className="font-medium text-primary hover:underline">
                {t("signup.signin")}
              </Link>
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <SignupForm />
    </Suspense>
  );
}
