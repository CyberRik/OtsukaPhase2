"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Pencil, Search, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import type { ConversationHeader } from "@/lib/types";
import type { Role } from "@/lib/session";

// Compact relative time ("just now", "3h ago", "2d ago"). Falls back to a date for
// anything older than a week so the list stays scannable without a heavy dep.
function timeAgo(iso: string, lang: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  const ja = lang === "ja";
  if (secs < 60) return ja ? "たった今" : "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return ja ? `${mins}分前` : `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return ja ? `${hrs}時間前` : `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return ja ? `${days}日前` : `${days}d ago`;
  return new Date(then).toLocaleDateString(ja ? "ja-JP" : undefined);
}

/**
 * The chat History slide-over. Lists a user's saved copilot conversations
 * (newest first, role-scoped so junior chats never surface in the manager
 * workspace), and lets them reopen, rename, or delete one. Mounted inside the
 * Workspace so it works identically on the Junior home (Command Center) and the
 * bare Manager workspace. Fetches on open and whenever `reloadSignal` changes
 * (bumped after each autosave) so the list reflects the live conversation.
 */
export function HistoryDrawer({
  open,
  onClose,
  employeeId,
  role,
  activeId,
  reloadSignal,
  onSelect,
  onDeletedActive,
}: {
  open: boolean;
  onClose: () => void;
  employeeId: string | null;
  role: Role;
  activeId: string;
  reloadSignal: number;
  onSelect: (id: string) => void;
  onDeletedActive: () => void;
}) {
  const { t, lang } = useT();
  const [items, setItems] = useState<ConversationHeader[]>([]);
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState(true);
  const [q, setQ] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const editRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open || !employeeId) return;
    let cancelled = false;
    setLoading(true);
    api.listConversations(employeeId, role).then(({ data, live }) => {
      if (cancelled) return;
      setItems(data.conversations);
      setLive(live);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [open, employeeId, role, reloadSignal]);

  useEffect(() => {
    if (editingId) editRef.current?.focus();
  }, [editingId]);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return items;
    return items.filter((c) => c.title.toLowerCase().includes(query));
  }, [items, q]);

  function beginRename(c: ConversationHeader) {
    setEditingId(c.conversation_id);
    setEditTitle(c.title);
  }

  async function commitRename(id: string) {
    const title = editTitle.trim();
    setEditingId(null);
    if (!title) return;
    setItems((prev) => prev.map((c) => (c.conversation_id === id ? { ...c, title } : c)));
    await api.renameConversation(id, title);
  }

  async function remove(id: string) {
    setItems((prev) => prev.filter((c) => c.conversation_id !== id));
    await api.deleteConversation(id);
    if (id === activeId) onDeletedActive();
  }

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 transition-opacity",
        open ? "opacity-100" : "pointer-events-none opacity-0",
      )}
      aria-hidden={!open}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Left panel */}
      <aside
        className={cn(
          "absolute inset-y-0 left-0 flex w-[320px] max-w-[85vw] flex-col border-r border-border bg-card shadow-xl transition-transform duration-200",
          open ? "translate-x-0" : "-translate-x-full",
        )}
        role="dialog"
        aria-label={lang === "ja" ? "チャット履歴" : "Chat history"}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="text-[13px] font-semibold">{lang === "ja" ? "チャット履歴" : "Chat history"}</div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
            title={lang === "ja" ? "閉じる" : "Close"}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-3 pt-3">
          <label className="flex items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={lang === "ja" ? "履歴を検索" : "Search chats"}
              className="w-full bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
            />
          </label>
        </div>

        <div className="flex-1 space-y-2 overflow-y-auto p-3">
          {loading && (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          )}

          {!loading && !live && (
            <p className="px-1 py-8 text-center text-[12.5px] text-muted-foreground">
              {lang === "ja" ? "履歴を利用できません" : "History unavailable"}
            </p>
          )}

          {!loading && live && filtered.length === 0 && (
            <p className="px-1 py-8 text-center text-[12.5px] text-muted-foreground">
              {lang === "ja" ? "保存された会話はまだありません" : "No saved chats yet"}
            </p>
          )}

          {!loading &&
            filtered.map((c) => {
              const active = c.conversation_id === activeId;
              const editing = editingId === c.conversation_id;
              return (
                <Card
                  key={c.conversation_id}
                  role={editing ? undefined : "button"}
                  tabIndex={editing ? undefined : 0}
                  onClick={editing ? undefined : () => onSelect(c.conversation_id)}
                  onKeyDown={(e) => {
                    if (editing) return;
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(c.conversation_id);
                    }
                  }}
                  className={cn(
                    "group cursor-pointer transition-colors",
                    active ? "ring-2 ring-primary/40" : "hover:border-primary/40",
                  )}
                >
                  <CardContent className="flex items-center justify-between gap-2 p-3">
                    {editing ? (
                      <input
                        ref={editRef}
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename(c.conversation_id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        className="min-w-0 flex-1 rounded-md border border-input bg-background px-2 py-1 text-[13px] outline-none"
                      />
                    ) : (
                      <div className="min-w-0">
                        <div className="truncate text-[13.5px] font-medium">{c.title}</div>
                        <div className="truncate text-[11.5px] text-muted-foreground">
                          {timeAgo(c.updated_at, lang)} · {c.message_count} {lang === "ja" ? "件" : "msgs"}
                        </div>
                      </div>
                    )}

                    <div className="flex shrink-0 items-center gap-1">
                      {editing ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            commitRename(c.conversation_id);
                          }}
                          className="rounded-md p-1.5 text-primary hover:bg-primary/5"
                          title={lang === "ja" ? "保存" : "Save"}
                        >
                          <Check className="h-3.5 w-3.5" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            beginRename(c);
                          }}
                          className="rounded-md p-1.5 text-muted-foreground opacity-0 transition hover:text-foreground group-hover:opacity-100"
                          title={lang === "ja" ? "名前を変更" : "Rename"}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          remove(c.conversation_id);
                        }}
                        className="rounded-md p-1.5 text-muted-foreground opacity-0 transition hover:text-destructive group-hover:opacity-100"
                        title={lang === "ja" ? "削除" : "Delete"}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
        </div>
      </aside>
    </div>
  );
}
