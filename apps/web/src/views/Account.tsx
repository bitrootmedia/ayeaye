import { KeyRoundIcon, PlaneIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToastManager } from "@/components/ui/toast";
import type { Absence } from "@/lib/types";

/**
 * Your account: who you are, how to reach you, and when you aren't here.
 *
 * Three cards, and the split matters. **Profile** is what colleagues see.
 * **Password** is the only thing on this screen that can lock you out, so it
 * asks for the current one and lives on its own. **Out of office** is the one
 * personal setting that is deliberately not private — the whole point is that
 * somebody checks before asking you for something.
 */
export default function Account() {
  const { me, reload } = useOutletContext<Shell>();
  const toast = useToastManager();
  const [displayName, setDisplayName] = useState(me?.display_name ?? "");
  const [status, setStatus] = useState(me?.status_message ?? "");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api("/me", {
        method: "PATCH",
        body: JSON.stringify({ display_name: displayName, status_message: status }),
      });
      await reload();
      toast.add({ title: "Saved" });
    } catch {
      toast.add({ title: "Couldn't save that", description: "Try again in a moment." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Account" }]}
        title="Your account"
        description="How you appear to everyone you work with."
      />

      <div className="grid max-w-4xl gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="display-name">Display name</Label>
              <Input
                id="display-name"
                value={displayName}
                placeholder="How your name appears to your team"
                onChange={(e) => setDisplayName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && save()}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="status-message">Status</Label>
              <Input
                id="status-message"
                value={status}
                maxLength={140}
                placeholder="Heads-down on the refit today"
                onChange={(e) => setStatus(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && save()}
              />
              {/* Said plainly, because "status" could as easily mean an
                  organisation-wide notice — which is a different feature,
                  written by admins, and lives on the dashboard. */}
              <p className="text-xs text-muted-foreground">
                A line about what you&rsquo;re on with. Yours to set, and anyone you work with
                can see it.
              </p>
            </div>
            <Button onClick={save} disabled={saving}>
              Save
            </Button>

            {/* Machine values in the mono voice — see the type note in
                index.css. Every id in this product reads this way. */}
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 border-t pt-4 text-sm">
              <dt className="text-muted-foreground">Email</dt>
              <dd className="truncate font-mono">{me?.email ?? "—"}</dd>
              <dt className="text-muted-foreground">Timezone</dt>
              <dd className="truncate font-mono">{me?.timezone ?? "UTC"}</dd>
              <dt className="text-muted-foreground">User id</dt>
              <dd className="truncate font-mono text-xs">{me?.id ?? "—"}</dd>
            </dl>
            <p className="text-xs text-muted-foreground">
              Your timezone is detected from this browser and decides when a reminder set for a
              date actually reaches you. Your email is how invitations find you, so it
              can&rsquo;t be changed here yet.
            </p>
          </CardContent>
        </Card>

        <PasswordCard />
        <OutOfOfficeCard />
      </div>
    </>
  );
}

function PasswordCard() {
  const toast = useToastManager();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!current || !next || busy) return;
    setBusy(true);
    try {
      await api("/me/password", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setCurrent("");
      setNext("");
      toast.add({ title: "Password changed" });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't change it", description: detail });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRoundIcon className="size-4" />
          Password
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="current-password">Current password</Label>
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-password">New password</Label>
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </div>
        <Button onClick={submit} disabled={!current || !next || busy}>
          Change password
        </Button>
        {/* Why it asks twice over, in one sentence. */}
        <p className="text-xs text-muted-foreground">
          The current one is asked for because a signed-in session left open on a shared machine
          shouldn&rsquo;t be enough to lock you out of your own account.
        </p>
      </CardContent>
    </Card>
  );
}

function OutOfOfficeCard() {
  const toast = useToastManager();
  const [rows, setRows] = useState<Absence[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setRows(await api<Absence[]>("/me/out-of-office").catch(() => []));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    if (!from || !to) return;
    try {
      await api("/me/out-of-office", {
        method: "POST",
        body: JSON.stringify({ starts_on: from, ends_on: to, note: note.trim() || null }),
      });
      setFrom("");
      setTo("");
      setNote("");
      await load();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't add that", description: detail });
    }
  };

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PlaneIcon className="size-4" />
          Out of office
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {rows.map((a) => (
          <div key={a.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-2 pl-3">
            <span className="font-mono text-xs text-muted-foreground">
              {a.starts_on} → {a.ends_on}
            </span>
            {a.away_now && <Badge variant="outline">Away now</Badge>}
            <span className="min-w-0 flex-1 truncate text-sm">{a.note ?? ""}</span>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Remove ${a.starts_on} to ${a.ends_on}`}
              onClick={async () => {
                await api(`/me/out-of-office/${a.id}`, { method: "DELETE" });
                await load();
              }}
            >
              <Trash2Icon />
            </Button>
          </div>
        ))}

        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-2">
            <Label htmlFor="ooo-from">From</Label>
            <Input
              id="ooo-from"
              type="date"
              className="w-40"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            {/* Inclusive, and it says so — an exclusive end date gets entered
                wrong every single time. */}
            <Label htmlFor="ooo-to">Until (included)</Label>
            <Input
              id="ooo-to"
              type="date"
              className="w-40"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </div>
          <Input
            aria-label="Why"
            placeholder="Sailing, annual leave…"
            className="min-w-40 flex-1"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
          />
          <Button disabled={!from || !to} onClick={add}>
            Add
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Everyone in your organisations sees this on their dashboard. That&rsquo;s the point of
          recording it rather than remembering it.
        </p>
      </CardContent>
    </Card>
  );
}
