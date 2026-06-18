import { AppShell } from "@/components/site/app-shell";

export default function ManagerLayout({ children }: { children: React.ReactNode }) {
  return <AppShell role="manager">{children}</AppShell>;
}
