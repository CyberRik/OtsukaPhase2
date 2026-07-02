import { AdminShell } from "@/components/site/admin-shell";

// Internal admin portal shell. No role guard by design — this is an internal-only
// surface (see the implementation plan's security caveat).
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
