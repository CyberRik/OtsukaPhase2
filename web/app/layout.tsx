import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "@fontsource/noto-sans-jp/400.css";
import "@fontsource/noto-sans-jp/500.css";
import "@fontsource/noto-sans-jp/700.css";
import "@fontsource/noto-sans-jp/900.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
import "@fontsource/ibm-plex-sans-jp/400.css";
import "@fontsource/ibm-plex-sans-jp/500.css";
import "@fontsource/ibm-plex-sans-jp/600.css";
import "@fontsource/ibm-plex-sans-jp/700.css";

import { cookies } from "next/headers";
import "./globals.css";
import { Providers } from "@/components/providers";
import type { Lang } from "@/lib/i18n";
import type { Role } from "@/lib/session";

export const metadata: Metadata = {
  title: "Senpai — Sales Knowledge & Onboarding Platform",
  description:
    "Onboard new sales reps with a senior's reasoning. Source-traceable principles, computed confidence, deal-health that explains itself.",
  icons: {
    icon: [
      { url: '/icon.svg', type: 'image/svg+xml' },
      { url: '/icon.png', type: 'image/png' },
    ]
  }
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const jar = await cookies();
  const initialLang = (jar.get("senpai.lang")?.value as Lang) || "ja";
  const initialRole = (jar.get("senpai.role")?.value as Role) || null;

  return (
    <html lang={initialLang} className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <Providers initialLang={initialLang} initialRole={initialRole}>
          {children}
        </Providers>
      </body>
    </html>
  );
}
