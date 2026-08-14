import { MegaphoneIcon, PinIcon, PlaneIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import { ago } from "@/lib/format";
import { personName, type DashboardData } from "@/lib/types";

/**
 * The organisation's landing screen.
 *
 * It answers one question — **what do I need to know before I ask anyone for
 * anything** — which is why it holds exactly two things: what the
 * organisation has been told, and who isn't here. Both come from one request,
 * because a landing page that renders in three stages looks broken.
 *
 * This replaced the people roster as the org's home. A roster is a reference
 * screen you visit on purpose; it was only the landing page by accident of
 * being built first.
 */
export default function Dashboard() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const [data, setData] = useState<DashboardData | null>(null);
  const [posting, setPosting] = useState(false);

  const load = useCallback(async () => {
    if (!orgId) return;
    setData(await api<DashboardData>(`/organisations/${orgId}/dashboard`).catch(() => null));
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!org) return null;
  if (!data) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <Spinner />
      </div>
    );
  }

  const awayNow = data.away.filter((a) => a.away_now);
  const awaySoon = data.away.filter((a) => !a.away_now);

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name }]}
        title={org.name}
        description="What everyone needs to know, and who isn't here."
        actions={
          data.can_announce && (
            <Button onClick={() => setPosting(true)}>
              <PlusIcon />
              Announcement
            </Button>
          )
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <Card role="region" aria-label="Announcements">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MegaphoneIcon className="size-4" />
              Announcements
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.announcements.length === 0 && (
              <p className="text-sm text-muted-foreground">
                {data.can_announce
                  ? "Nothing posted. Anything you put here is seen by everyone in the organisation."
                  : "Nothing posted."}
              </p>
            )}
            {data.announcements.map((a) => (
              <div key={a.id} className="rounded-lg border p-3">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  {/* Sticky is shape, not colour: red already means "this
                      needs you" everywhere else in the product. */}
                  {a.sticky && (
                    <Badge variant="outline" className="gap-1">
                      <PinIcon className="size-3" />
                      Pinned
                    </Badge>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {personName(a.author)} · {ago(a.created_at)}
                  </span>
                  {a.expires_on && (
                    <span className="font-mono text-xs text-muted-foreground">
                      until {a.expires_on}
                    </span>
                  )}
                  {data.can_announce && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto"
                      aria-label="Take this announcement down"
                      onClick={async () => {
                        await api(`/organisations/${org.id}/announcements/${a.id}`, {
                          method: "DELETE",
                        });
                        await load();
                      }}
                    >
                      <Trash2Icon />
                    </Button>
                  )}
                </div>
                {/* `whitespace-pre-wrap`, so the line breaks somebody typed
                    survive — the same as a comment. */}
                <p className="text-sm whitespace-pre-wrap">{a.body}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card role="region" aria-label="Out of office">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <PlaneIcon className="size-4" />
              Away
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {data.away.length === 0 && (
              <p className="text-muted-foreground">Everyone&rsquo;s here for the next fortnight.</p>
            )}
            {awayNow.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Right now</p>
                {awayNow.map((a) => (
                  <AwayRow key={a.id} absence={a} />
                ))}
              </div>
            )}
            {awaySoon.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Coming up</p>
                {awaySoon.map((a) => (
                  <AwayRow key={a.id} absence={a} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {posting && (
        <NewAnnouncement
          orgId={org.id}
          onClose={() => setPosting(false)}
          onPosted={async () => {
            setPosting(false);
            await load();
          }}
        />
      )}
    </>
  );
}

function AwayRow({ absence }: { absence: DashboardData["away"][number] }) {
  return (
    <div className="flex flex-wrap items-baseline gap-2">
      <span className="font-medium">{personName(absence.person)}</span>
      <span className="font-mono text-xs text-muted-foreground">
        {absence.starts_on} → {absence.ends_on}
      </span>
      {absence.note && <span className="text-xs text-muted-foreground">{absence.note}</span>}
    </div>
  );
}

function NewAnnouncement({
  orgId,
  onClose,
  onPosted,
}: {
  orgId: string;
  onClose: () => void;
  onPosted: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [body, setBody] = useState("");
  const [sticky, setSticky] = useState(false);
  const [expires, setExpires] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!body.trim() || busy) return;
    setBusy(true);
    try {
      await api(`/organisations/${orgId}/announcements`, {
        method: "POST",
        body: JSON.stringify({ body: body.trim(), sticky, expires_on: expires || null }),
      });
      await onPosted();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't post that", description: detail });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>New announcement</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          rows={3}
          autoFocus
          aria-label="Announcement"
          placeholder="Yard closed Friday…"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-2">
            {/* An end date is what stops a dashboard turning into a wall of
                last year's paper. Optional, but offered every time. */}
            <Label htmlFor="expires">Until (optional)</Label>
            <Input
              id="expires"
              type="date"
              className="w-40"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 pb-2 text-sm">
            <input
              type="checkbox"
              checked={sticky}
              onChange={(e) => setSticky(e.target.checked)}
            />
            Pin to the top
          </label>
          <span className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={!body.trim() || busy} onClick={submit}>
              Post
            </Button>
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
