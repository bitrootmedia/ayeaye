import { PlusIcon, SearchIcon, SparklesIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/api";
import { PageHeader } from "@/components/page-header";
import { SparkCaptureDialog } from "@/components/spark-capture";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { ago } from "@/lib/format";
import type { Spark } from "@/lib/types";

/** Splits on a bare URL and turns each one into a real link. Plain text in,
 *  so this is safe without sanitising anything — React escapes every
 *  non-matched segment as a text node the same as it would the whole
 *  string, and only the matched segments become `<a>` elements. */
const URL_RE = /(https?:\/\/\S+)/;

function Linkified({ text }: { text: string }) {
  return (
    <>
      {text.split(URL_RE).map((part, i) =>
        i % 2 === 1 ? (
          <a
            key={i}
            href={part}
            target="_blank"
            rel="noreferrer noopener"
            className="text-primary underline underline-offset-2"
            onClick={(e) => e.stopPropagation()}
          >
            {part}
          </a>
        ) : (
          part
        ),
      )}
    </>
  );
}

/**
 * Sparks: quick capture, reviewed. Everything here also lives behind the
 * ⌘J dialog reachable from any screen — this is where it piles up
 * afterwards, not the only way in.
 *
 * **Cross-organisation and yours alone** — no title, no sharing, no admin
 * override, the identical shape `services/personal_notes.py` and
 * `services/notes.py` already hold for their own private data.
 *
 * The filter box is client-side, the same call the Projects list already
 * makes for its own name filter: this was never a paged fetch to begin
 * with, so narrowing what's on screen doesn't earn a round trip.
 */
export default function Sparks() {
  const [sparks, setSparks] = useState<Spark[] | null>(null);
  const [query, setQuery] = useState("");
  const [capturing, setCapturing] = useState(false);

  const load = useCallback(async () => {
    setSparks(await api<Spark[]>("/sparks").catch(() => []));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (id: string) => {
    // Optimistic — a delete here isn't worth a round trip before the card
    // leaves the list, and a failed request just means it reappears on the
    // next load.
    setSparks((rows) => rows?.filter((s) => s.id !== id) ?? rows);
    await api(`/sparks/${id}`, { method: "DELETE" });
  };

  const save = async (id: string, body: string) => {
    const updated = await api<Spark>(`/sparks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ body }),
    });
    setSparks((rows) => rows?.map((s) => (s.id === id ? updated : s)) ?? rows);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !sparks) return sparks;
    return sparks.filter((s) => s.body.toLowerCase().includes(q));
  }, [sparks, query]);

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Sparks" }]}
        title="Sparks"
        description="Quick captures — ideas, links, anything not worth a task yet. Yours alone."
        actions={
          <Button onClick={() => setCapturing(true)}>
            <PlusIcon />
            New spark
          </Button>
        }
      />

      {sparks !== null && sparks.length > 0 && (
        <div className="relative max-w-sm">
          <SearchIcon className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search your sparks"
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-8"
          />
        </div>
      )}

      {sparks === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : sparks.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <SparklesIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing captured yet</EmptyTitle>
            <EmptyDescription>
              ⌘J from anywhere to jot something down without losing your place.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : filtered?.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Nothing matches &ldquo;{query}&rdquo;.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered?.map((spark) => (
            <SparkCard key={spark.id} spark={spark} onSave={save} onDelete={remove} />
          ))}
        </div>
      )}

      <SparkCaptureDialog
        open={capturing}
        onOpenChange={setCapturing}
        onCaptured={(spark) => setSparks((rows) => (rows ? [spark, ...rows] : [spark]))}
      />
    </>
  );
}

function SparkCard({
  spark,
  onSave,
  onDelete,
}: {
  spark: Spark;
  onSave: (id: string, body: string) => Promise<void>;
  onDelete: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(spark.body);

  useEffect(() => {
    setBody(spark.body);
  }, [spark.body]);

  const commit = async () => {
    setEditing(false);
    const trimmed = body.trim();
    if (trimmed && trimmed !== spark.body) await onSave(spark.id, trimmed);
    else setBody(spark.body);
  };

  return (
    <Card className="h-full">
      <CardContent className="flex h-full flex-col gap-2 p-4">
        {editing ? (
          <Textarea
            autoFocus
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setBody(spark.body);
                setEditing(false);
              }
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void commit();
              }
            }}
            className="min-h-24 flex-1 resize-none text-sm"
          />
        ) : (
          // A click enters edit mode, the same "the card is the trigger"
          // shape the notepad's own card uses — but this one has no title
          // to click instead, so the body itself is it.
          <p
            className="line-clamp-6 flex-1 cursor-text text-sm whitespace-pre-wrap"
            onClick={() => setEditing(true)}
          >
            <Linkified text={spark.body} />
          </p>
        )}
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs text-muted-foreground">{ago(spark.updated_at)}</span>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Delete this spark"
            onClick={() => onDelete(spark.id)}
          >
            <Trash2Icon />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
