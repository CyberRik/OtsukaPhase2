import type { Metadata } from "next";
import { Inter, Spectral, Noto_Sans_JP } from "next/font/google";
import "./globals.css";
import { Sidebar, MobileTopbar } from "@/components/site/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const spectral = Spectral({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-serif",
  display: "swap",
});
const notoJp = Noto_Sans_JP({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-jp",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Senpai — Sales Knowledge & Onboarding Platform",
  description:
    "Transfer a senior rep's reasoning to new salespeople. Source-traceable principles, computed confidence, deal-health that explains itself.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${spectral.variable} ${notoJp.variable}`}>
      <body className="min-h-screen bg-background font-sans antialiased">
        <TooltipProvider delayDuration={150}>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <MobileTopbar />
              <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 md:px-10 md:py-12">
                {children}
              </main>
              <footer className="border-t border-border px-5 py-6 md:px-10">
                <p className="mx-auto max-w-6xl text-[11px] text-muted-foreground">
                  Senpai · Phase 2 prototype · deterministic core, optional exp3 narration ·
                  deal data is synthetic; interview knowledge is real and fully cited.
                </p>
              </footer>
            </div>
          </div>
        </TooltipProvider>
      </body>
    </html>
  );
}
