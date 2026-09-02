import { useEffect, useState } from "react";
import { SparklesIcon } from "lucide-react";

import { api } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import type { Spark } from "@/lib/types";

/**
 * Bind the global "capture a spark" hotkey. ⌘J / Ctrl+J — ⌘K already
 * belongs to the search palette (`search-palette.tsx`'s own
 * `useSearchHotkey`), and this mirrors that hook's shape exactly.
 */
export function useSparkHotkey(onOpen: () => void) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "j" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpen();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onOpen]);
}

/** The header button — same shape as `SearchTrigger`, so the two read as a
 *  pair rather than one being an afterthought. */
export function SparkTrigger({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="New spark"
      title="New spark (⌘J)"
      className="flex size-9 items-center justify-center rounded-md hover:bg-accent"
    >
      <SparklesIcon className="size-4" />
    </button>
  );
}

/**
 * The capture dialog itself: type, save, and you're straight back to
 * whatever you were doing — no navigation away, and reachable from any
 * screen because it's mounted once at the shell level, not per-view.
 * Review and edit what piles up here on the Sparks screen instead.
 */
export function SparkCaptureDialog({
  open,
  onOpenChange,
  onCaptured,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCaptured?: (spark: Spark) => void;
}) {
  const toast = useToastManager();
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);

  // Always opens blank — this is a capture tool, not an editor reopening on
  // whatever the last spark said.
  useEffect(() => {
    if (open) setBody("");
  }, [open]);

  const submit = async () => {
    if (!body.trim() || saving) return;
    setSaving(true);
    try {
      const spark = await api<Spark>("/sparks", {
        method: "POST",
        body: JSON.stringify({ body }),
      });
      onCaptured?.(spark);
      onOpenChange(false);
    } catch {
      toast.add({ title: "Couldn't save that", description: "Try again in a moment." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New spark</DialogTitle>
          <DialogDescription>
            An idea, a link, anything worth catching before it&rsquo;s gone. Review them all
            under Sparks.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          autoFocus
          placeholder="What's on your mind?"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void submit();
            }
          }}
          className="min-h-32 resize-none"
        />
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">⌘Enter to save</span>
          <Button onClick={submit} disabled={!body.trim() || saving}>
            Save
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
