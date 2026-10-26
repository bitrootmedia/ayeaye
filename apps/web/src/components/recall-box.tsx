import {
  BookOpenIcon,
  CircleDotIcon,
  LightbulbIcon,
  SearchIcon,
  SparklesIcon,
  TagIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ago } from "@/lib/format";
import type { Recalled, RecallResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_ICON = { fact: LightbulbIcon, article: BookOpenIcon, task: CircleDotIcon } as const;
const KIND_LABEL = { fact: "Fact", article: "Article", task: "Task" } as const;

/**
 * "What do we already know about this?" — recall, on the knowledge base's
 * own screen. The same question an assistant asks over MCP, with the same
 * answer: facts, articles and tasks, by meaning as well as by text, only
 * what you can open.
 *
 * **On Enter, not as-you-type**, unlike ⌘K. Every question is embedded by
 * the model before it can be compared, which on a CPU is a few hundred
 * milliseconds; a request per keystroke would queue those behind each
 * other and behind the sweep. ⌘K stays the as-you-type jump to a thing by
 * name; this is for asking.
 *
 * **The question lives in the URL** (`?recall=`), for the reason sorting
 * and filtering do on the task list: what somebody found is something they
 * can send to a colleague.
 */
export function RecallBox({ orgId }: { orgId: string }) {
  const [params, setParams] = useSearchParams();
  const asked = params.get("recall") ?? "";
  const [query, setQuery] = useState(asked);
  const [result, setResult] = useState<RecallResult | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    const q = asked.trim();
    if (!q) {
      setResult(null);
      return;
    }
    // The newest question wins — a slow answer to the last one must not
    // replace the answer to this one, the palette's own discipline.
    const mine = ++seq.current;
    setLoading(true);
    void api<RecallResult>(
      `/organisations/${orgId}/kb/recall?q=${encodeURIComponent(q)}&limit=15`,
    )
      .then((r) => mine === seq.current && setResult(r))
      .catch(() => mine === seq.current && setResult({ items: [], semantic: false, unknown_tags: [] }))
      .finally(() => mine === seq.current && setLoading(false));
  }, [orgId, asked]);

  const ask = (q: string) => {
    const next = new URLSearchParams(params);
    if (q.trim()) next.set("recall", q.trim());
    else next.delete("recall");
    setParams(next, { replace: false });
  };

  return (
    <section aria-label="Recall" className="space-y-3">
      <form
        className="relative"
        onSubmit={(e) => {
          e.preventDefault();
          ask(query);
        }}
      >
        <SparklesIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          aria-label="Ask what the team knows"
          placeholder="Ask what the team knows — “why do the celery workers stop after a Redis restart?”"
          className="h-11 pr-20 pl-9"
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="absolute top-1/2 right-1.5 flex -translate-y-1/2 items-center gap-1">
          {asked && (
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label="Clear"
              onClick={() => {
                setQuery("");
                ask("");
              }}
            >
              <XIcon />
            </Button>
          )}
          <Button type="submit" size="icon-sm" variant="ghost" aria-label="Recall">
            {loading ? <Spinner /> : <SearchIcon />}
          </Button>
        </div>
      </form>

      {result && (
        <div className="rounded-xl border bg-card">
          {result.items.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">
              Nothing you can see answers that.
              {!result.semantic && " (Searched by text only — meaning-based search is unavailable.)"}
            </p>
          ) : (
            <ul className="divide-y">
              {result.items.map((item) => (
                <RecalledRow key={`${item.kind}-${item.id}`} orgId={orgId} item={item} />
              ))}
            </ul>
          )}
          {result.items.length > 0 && !result.semantic && (
            <p className="border-t px-4 py-2 text-xs text-muted-foreground">
              Searched by text only — meaning-based search is unavailable right now.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function href(orgId: string, item: Recalled): string {
  if (item.kind === "fact") return `/orgs/${orgId}/kb/books/${item.parent_id}?fact=${item.id}`;
  if (item.kind === "article") return `/orgs/${orgId}/kb/articles/${item.id}`;
  return `/orgs/${orgId}/tasks/${item.id}`;
}

function RecalledRow({ orgId, item }: { orgId: string; item: Recalled }) {
  const Icon = KIND_ICON[item.kind];
  const inactiveLabel =
    item.kind === "fact" ? "Superseded" : item.kind === "task" ? "Closed" : "Archived";
  return (
    <li>
      <Link to={href(orgId, item)} className="flex gap-3 px-4 py-3 hover:bg-accent/50">
        <Icon
          className="mt-0.5 size-4 shrink-0 text-muted-foreground"
          aria-label={KIND_LABEL[item.kind]}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex min-w-0 items-baseline gap-2">
            <span
              className={cn(
                "min-w-0 truncate text-sm font-medium",
                item.inactive && "text-muted-foreground line-through",
              )}
            >
              {item.title || "Untitled"}
            </span>
            {item.inactive && (
              <Badge variant="outline" className="shrink-0">
                {inactiveLabel}
              </Badge>
            )}
          </div>
          {item.snippet && item.snippet !== item.title && (
            <p className="line-clamp-2 text-sm text-muted-foreground">{item.snippet}</p>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{KIND_LABEL[item.kind]}</span>
            {item.context && <span className="truncate">{item.context}</span>}
            <span className="font-mono tabular-nums" title={item.when}>
              {ago(item.when)}
            </span>
            {item.by && <span>{item.via ? `${item.by} via ${item.via}` : item.by}</span>}
            {item.tags.map((tag) => (
              <span key={tag} className="inline-flex items-center gap-1">
                <TagIcon className="size-3" />
                {tag}
              </span>
            ))}
            {item.matched === "meaning" && (
              // Said, because a result that shares no word with the question
              // otherwise reads like a mistake.
              <span className="inline-flex items-center gap-1">
                <SparklesIcon className="size-3" />
                similar meaning
              </span>
            )}
          </div>
        </div>
      </Link>
    </li>
  );
}
