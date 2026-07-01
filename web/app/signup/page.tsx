"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Brand } from "@/components/site/brand";
import { LangToggle } from "@/components/site/lang-toggle";
import { Button } from "@/components/ui/button";

type Manager = { employee_id: string; name: string; role: string; department: string; division: string };

function SignupForm() {
  const { t } = useT();
  const router = useRouter();
  const { signup } = useSession();

  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [managerId, setManagerId] = useState("");
  const [managers, setManagers] = useState<Manager[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The manager pool a new junior reports to ("who's your manager?").
  useEffect(() => {
    api.managerReps().then(({ data }) => setManagers(data.managers));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !username.trim() || !password) {
      setError(t("signup.error"));
      return;
    }
    if (!managerId) {
      setError(t("signup.pickManager"));
      return;
    }
    setBusy(true);
    setError(null);
    const res = await signup(username, password, name, managerId);
    setBusy(false);
    if (res.ok) {
      router.replace("/junior");
    } else if (res.error === "username already taken") {
      setError(t("signup.taken"));
    } else {
      setError(t("signup.error"));
    }
  }

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
                <label className="eyebrow">{t("signup.name")}</label>
                <input
                  value={name}
                  onChange={(e) => { setName(e.target.value); setError(null); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>

              <div className="space-y-1.5">
                <label className="eyebrow">{t("signup.whichManager")}</label>
                <select
                  value={managerId}
                  onChange={(e) => { setManagerId(e.target.value); setError(null); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="">{t("signup.pickManager")}</option>
                  {managers.map((m) => (
                    <option key={m.employee_id} value={m.employee_id}>
                      {m.name} ({m.employee_id}) · {m.department} {m.division}
                    </option>
                  ))}
                </select>
              </div>

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
              <Link href="/login?role=junior" className="font-medium text-primary hover:underline">
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
