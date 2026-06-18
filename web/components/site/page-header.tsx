import { cn } from "@/lib/utils";

export function PageHeader({
  eyebrow,
  title,
  lead,
  children,
  className,
}: {
  eyebrow: string;
  title: string;
  lead?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-4 border-b border-border pb-6 md:flex-row md:items-end md:justify-between", className)}>
      <div className="max-w-2xl space-y-2">
        <div className="eyebrow">{eyebrow}</div>
        <h1 className="font-serif text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-[34px]">
          {title}
        </h1>
        {lead && <p className="text-[15px] leading-relaxed text-muted-foreground">{lead}</p>}
      </div>
      {children && <div className="flex shrink-0 items-center gap-3">{children}</div>}
    </header>
  );
}
