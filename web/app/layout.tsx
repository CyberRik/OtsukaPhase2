import type { Metadata } from "next";
import { Inter, Noto_Sans_JP } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { Providers } from "@/components/providers";
import type { Lang } from "@/lib/i18n";
import type { Role } from "@/lib/session";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const notoJp = Noto_Sans_JP({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-jp",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Senpai — Sales Knowledge & Onboarding Platform",
  description:
    "Onboard new sales reps with a senior's reasoning. Source-traceable principles, computed confidence, deal-health that explains itself.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const jar = await cookies();
  const initialLang = (jar.get("senpai.lang")?.value as Lang) || "ja";
  const initialRole = (jar.get("senpai.role")?.value as Role) || null;

  return (
    <html lang={initialLang} className={`${inter.variable} ${notoJp.variable}`} suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <Providers initialLang={initialLang} initialRole={initialRole}>
          {children}
        </Providers>
      </body>
    </html>
  );
}
