import { AppShell } from "@/components/site/app-shell";

export default function JuniorLayout({ children }: { children: React.ReactNode }) {
  return <AppShell role="junior">{children}</AppShell>;
}
