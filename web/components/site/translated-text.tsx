"use client";

import { useT } from "@/lib/i18n";
import { useEffect, useState } from "react";
import { Languages } from "lucide-react";

export function TranslatedText({ text, className }: { text: string; className?: string }) {
  const { lang, incrementPending, decrementPending } = useT();
  const [translated, setTranslated] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);

  useEffect(() => {
    if (lang === "ja" || !text) {
      setTranslated(null);
      setShowOriginal(false);
      return;
    }
    
    let active = true;
    let registered = true;
    setLoading(true);
    incrementPending();
    
    fetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang: "en" })
    })
      .then(res => res.json())
      .then(data => {
        if (active) {
          setTranslated(data.translated || text);
          setLoading(false);
        }
        if (registered) {
          registered = false;
          decrementPending();
        }
      })
      .catch(() => {
        if (active) setLoading(false);
        if (registered) {
          registered = false;
          decrementPending();
        }
      });
      
    return () => {
      active = false;
      if (registered) {
        registered = false;
        decrementPending();
      }
    };
  }, [text, lang, incrementPending, decrementPending]);

  if (!text) return null;

  if (lang === "ja") {
    return <span className={className}>{text}</span>;
  }

  // English mode
  if (loading) {
    return (
      <span className={`inline-block animate-pulse rounded bg-muted/60 h-[1em] min-w-[80px] ${className || ""}`} />
    );
  }

  if (showOriginal) {
    return (
      <span className={className}>
        <span className="text-muted-foreground">{text}</span>
        <button 
          onClick={() => setShowOriginal(false)}
          className="ml-2 inline-flex items-center gap-1 rounded-full border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium leading-none text-muted-foreground hover:bg-secondary transition-colors"
          title="View Translated Text"
        >
          <Languages className="h-3 w-3" />
          EN
        </button>
      </span>
    );
  }

  return (
    <span className={className}>
      {translated || text}
      {translated && translated !== text && (
        <button 
          onClick={() => setShowOriginal(true)}
          className="ml-2 inline-flex items-center gap-1 rounded-full border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium leading-none text-muted-foreground hover:bg-secondary transition-colors"
          title="View Japanese Original"
        >
          <Languages className="h-3 w-3" />
          JP Original
        </button>
      )}
    </span>
  );
}
