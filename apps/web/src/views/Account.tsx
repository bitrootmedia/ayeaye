import {
  BellIcon,
  CopyIcon,
  KeyRoundIcon,
  MailIcon,
  PlaneIcon,
  SendIcon,
  ShieldCheckIcon,
  Trash2Icon,
  WebhookIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { TotpEnroll } from "@/components/mfa-enroll";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToastManager } from "@/components/ui/toast";
import { ago } from "@/lib/format";
import {
  NOTIFICATION_KIND_LABEL,
  type Absence,
  type AccessToken,
  type NotificationChannel,
} from "@/lib/types";

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
  const [dailySummary, setDailySummary] = useState(me?.daily_summary_enabled ?? true);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api("/me", {
        method: "PATCH",
        body: JSON.stringify({
          display_name: displayName,
          status_message: status,
          daily_summary_enabled: dailySummary,
        }),
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
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={dailySummary}
                  onChange={(e) => setDailySummary(e.target.checked)}
                />
                Daily summary
              </label>
              <p className="text-xs text-muted-foreground">
                A morning nudge, per organisation, with what&rsquo;s planned for today and what
                closed yesterday. On by default; turn it off here any time.
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
        <TwoFactorCard />
        <OutOfOfficeCard />
        <AccessTokensCard />
        <NotificationsSection />
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

function TwoFactorCard() {
  const toast = useToastManager();
  const [enrolled, setEnrolled] = useState<boolean | null>(null);
  const [codesRemaining, setCodesRemaining] = useState(0);
  const [enrolling, setEnrolling] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [freshCodes, setFreshCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const status = await api<{ enrolled: boolean; codes_remaining: number }>("/me/mfa/status");
    setEnrolled(status.enrolled);
    setCodesRemaining(status.codes_remaining);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const disable = async () => {
    if (busy || !window.confirm("Turn off two-factor authentication? This removes your device and your backup codes.")) return;
    setBusy(true);
    try {
      await api("/me/mfa/totp", { method: "DELETE" });
      await load();
      toast.add({ title: "Two-factor authentication turned off" });
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    setBusy(true);
    try {
      const { codes } = await api<{ codes: string[] }>("/me/mfa/backup-codes", {
        method: "POST",
      });
      setFreshCodes(codes);
      setRegenerating(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheckIcon className="size-4" />
          Two-factor authentication
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {enrolled === null ? null : enrolled ? (
          <>
            <p className="text-sm">
              <span className="font-medium text-foreground">Enabled.</span>{" "}
              <span className="font-mono text-muted-foreground">{codesRemaining}</span> backup
              code{codesRemaining === 1 ? "" : "s"} left.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={regenerate} disabled={busy}>
                Regenerate backup codes
              </Button>
              <Button size="sm" variant="ghost" onClick={disable} disabled={busy}>
                Turn off
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              Not enabled. Turning it on requires a code from your authenticator app every time
              you sign in — unless an organisation you&rsquo;re in already requires it, in which
              case you&rsquo;ll be asked to set this up at your next sign-in regardless.
            </p>
            <Button size="sm" onClick={() => setEnrolling(true)}>
              Turn on
            </Button>
          </>
        )}
      </CardContent>

      <Dialog open={enrolling} onOpenChange={setEnrolling}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Set up two-factor authentication</DialogTitle>
            <DialogDescription>
              Scan the code with an authenticator app, then confirm it works.
            </DialogDescription>
          </DialogHeader>
          <TotpEnroll
            onDone={() => {
              setEnrolling(false);
              void load();
              toast.add({ title: "Two-factor authentication turned on" });
            }}
          />
        </DialogContent>
      </Dialog>

      <Dialog open={regenerating} onOpenChange={setRegenerating}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New backup codes</DialogTitle>
            <DialogDescription>
              Your old codes stop working the moment these are generated.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <ul className="grid grid-cols-2 gap-1.5 rounded-lg border bg-muted/30 p-3 font-mono text-sm">
              {(freshCodes ?? []).map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  void navigator.clipboard.writeText((freshCodes ?? []).join("\n"));
                  toast.add({ title: "Copied" });
                }}
              >
                <CopyIcon />
                Copy all
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setRegenerating(false);
                  setFreshCodes(null);
                  void load();
                }}
              >
                Done
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
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

function AccessTokensCard() {
  const toast = useToastManager();
  const [rows, setRows] = useState<AccessToken[]>([]);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "write">("read");
  const [fresh, setFresh] = useState<string | null>(null);

  const load = useCallback(async () => {
    setRows(await api<AccessToken[]>("/me/tokens").catch(() => []));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    if (!name.trim()) return;
    try {
      const made = await api<AccessToken & { token: string }>("/me/tokens", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), scope }),
      });
      setFresh(made.token);
      setName("");
      await load();
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't create that", description: detail });
    }
  };

  return (
    <Card className="lg:col-span-2" role="region" aria-label="Access tokens">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRoundIcon className="size-4" />
          Access tokens
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Connect your own assistant over MCP. A token acts as <em>you</em> — it can reach exactly
          what you can reach, and nothing more.
        </p>

        {/* Shown once, and the copy says so. There is no endpoint that could
            show it again: only a hash is stored. */}
        {fresh && (
          <div className="space-y-2 rounded-lg border border-primary/40 bg-primary/5 p-3">
            <p className="text-sm font-medium">Copy it now — it won&rsquo;t be shown again.</p>
            <code className="block overflow-x-auto rounded bg-background px-2 py-1 font-mono text-xs">
              {fresh}
            </code>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() => {
                  void navigator.clipboard.writeText(fresh);
                  toast.add({ title: "Copied" });
                }}
              >
                <CopyIcon />
                Copy token
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  void navigator.clipboard.writeText(
                    `claude mcp add --transport http ayeayecaptain ${window.location.origin}/mcp --header "Authorization: Bearer ${fresh}"`,
                  );
                  toast.add({ title: "Copied the command" });
                }}
              >
                <CopyIcon />
                Copy the `claude mcp add` command
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setFresh(null)}>
                Done
              </Button>
            </div>
          </div>
        )}

        {rows.map((row) => (
          <div key={row.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-2 pl-3">
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{row.name}</span>
            <Badge variant="outline">{row.scope === "write" ? "Can change things" : "Read only"}</Badge>
            <span className="font-mono text-xs text-muted-foreground">{row.prefix}…</span>
            <span className="text-xs text-muted-foreground">
              {row.last_used_at ? `used ${ago(row.last_used_at)}` : "never used"}
            </span>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Revoke ${row.name}`}
              onClick={async () => {
                await api(`/me/tokens/${row.id}`, { method: "DELETE" });
                await load();
              }}
            >
              <Trash2Icon />
            </Button>
          </div>
        ))}

        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-2">
            <Label htmlFor="token-name">What is it for</Label>
            <Input
              id="token-name"
              className="w-56"
              placeholder="Claude on my laptop"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && create()}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="token-scope">Access</Label>
            <select
              id="token-scope"
              className="h-8 rounded-lg border bg-background px-2 text-sm"
              value={scope}
              onChange={(e) => setScope(e.target.value as "read" | "write")}
            >
              <option value="read">Read only</option>
              <option value="write">Can change things</option>
            </select>
          </div>
          <Button disabled={!name.trim()} onClick={create}>
            Create token
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Start with read-only. A write token lets an assistant create tasks and comment as you —
          useful, and worth deciding on purpose.
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * Notification channels and their routing.
 *
 * Two cards sharing one list, lifted up here rather than each fetching its
 * own — adding a webhook changes what the routing matrix has columns for,
 * and two independent fetches would mean one card going stale until its own
 * next reload caught up.
 */
function NotificationsSection() {
  const [channels, setChannels] = useState<NotificationChannel[]>([]);

  const load = useCallback(async () => {
    setChannels(await api<NotificationChannel[]>("/me/notification-channels").catch(() => []));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <NotificationChannelsCard channels={channels} onChanged={load} />
      <NotificationRoutingCard channels={channels} onChanged={load} />
    </>
  );
}

const CHANNEL_ICON = { email: MailIcon, telegram: SendIcon, webhook: WebhookIcon } as const;

function NotificationChannelsCard({
  channels,
  onChanged,
}: {
  channels: NotificationChannel[];
  onChanged: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [deepLink, setDeepLink] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookLabel, setWebhookLabel] = useState("");
  const [freshSecret, setFreshSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const linkTelegram = async () => {
    setBusy(true);
    try {
      const { deep_link } = await api<{ deep_link: string }>(
        "/me/notification-channels/telegram/link-start",
        { method: "POST" },
      );
      setDeepLink(deep_link);
    } catch (err) {
      fail(err, "Couldn't start the Telegram link");
    } finally {
      setBusy(false);
    }
  };

  const addWebhook = async () => {
    if (!webhookUrl.trim() || busy) return;
    setBusy(true);
    try {
      const made = await api<NotificationChannel & { secret: string }>(
        "/me/notification-channels/webhook",
        {
          method: "POST",
          body: JSON.stringify({ url: webhookUrl.trim(), label: webhookLabel.trim() }),
        },
      );
      setFreshSecret(made.secret);
      setWebhookUrl("");
      setWebhookLabel("");
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't add that webhook");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (channel: NotificationChannel) => {
    try {
      await api(`/me/notification-channels/${channel.id}`, { method: "DELETE" });
      await onChanged();
    } catch (err) {
      fail(err, `Couldn't remove ${channel.label}`);
    }
  };

  const telegram = channels.find((c) => c.kind === "telegram");

  return (
    <Card className="lg:col-span-2" role="region" aria-label="Notification channels">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BellIcon className="size-4" />
          Notification channels
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Where a notification can reach you, beyond the inbox here. Pick which kinds go where in
          the table below.
        </p>

        {channels.map((channel) => {
          const Icon = CHANNEL_ICON[channel.kind];
          return (
            <div
              key={channel.id}
              className="flex flex-wrap items-center gap-3 rounded-lg border p-2 pl-3"
            >
              <Icon className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{channel.label}</span>
              {channel.url && (
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
                  {channel.url}
                </span>
              )}
              {channel.kind === "telegram" && !channel.verified_at && (
                <Badge variant="outline" className="text-muted-foreground">
                  Waiting for /start
                </Badge>
              )}
              {channel.kind !== "email" && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Remove ${channel.label}`}
                  onClick={() => remove(channel)}
                >
                  <Trash2Icon />
                </Button>
              )}
            </div>
          );
        })}

        <div className="flex flex-wrap gap-2 border-t pt-4">
          <Button variant="outline" disabled={busy} onClick={linkTelegram}>
            <SendIcon />
            {telegram ? "Re-link Telegram" : "Link Telegram"}
          </Button>
        </div>

        {deepLink && (
          <div className="space-y-2 rounded-lg border border-primary/40 bg-primary/5 p-3">
            <p className="text-sm font-medium">Open this link and tap Start in Telegram.</p>
            <a
              href={deepLink}
              target="_blank"
              rel="noreferrer"
              className="block truncate font-mono text-xs text-primary underline"
            >
              {deepLink}
            </a>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() => {
                  void navigator.clipboard.writeText(deepLink);
                  toast.add({ title: "Copied" });
                }}
              >
                <CopyIcon />
                Copy link
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDeepLink(null)}>
                Done
              </Button>
            </div>
          </div>
        )}

        {freshSecret && (
          <div className="space-y-2 rounded-lg border border-primary/40 bg-primary/5 p-3">
            <p className="text-sm font-medium">
              Copy the signing secret now — it won&rsquo;t be shown again.
            </p>
            <code className="block overflow-x-auto rounded bg-background px-2 py-1 font-mono text-xs">
              {freshSecret}
            </code>
            <p className="text-xs text-muted-foreground">
              Every delivery carries{" "}
              <code className="font-mono">X-Ayeaye-Signature: sha256=…</code>, signed over the raw
              body with this secret.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() => {
                  void navigator.clipboard.writeText(freshSecret);
                  toast.add({ title: "Copied" });
                }}
              >
                <CopyIcon />
                Copy secret
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setFreshSecret(null)}>
                Done
              </Button>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-2 border-t pt-4">
          <div className="space-y-2">
            <Label htmlFor="webhook-url">Webhook URL</Label>
            <Input
              id="webhook-url"
              className="w-64"
              placeholder="https://…"
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addWebhook()}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="webhook-label">Label</Label>
            <Input
              id="webhook-label"
              className="w-40"
              placeholder="My relay"
              value={webhookLabel}
              onChange={(e) => setWebhookLabel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addWebhook()}
            />
          </div>
          <Button disabled={!webhookUrl.trim() || busy} onClick={addWebhook}>
            <WebhookIcon />
            Add webhook
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function NotificationRoutingCard({
  channels,
  onChanged,
}: {
  channels: NotificationChannel[];
  onChanged: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [busy, setBusy] = useState<string | null>(null);

  const toggle = async (channel: NotificationChannel, kind: string, checked: boolean) => {
    const key = `${channel.id}:${kind}`;
    setBusy(key);
    const next = checked
      ? [...channel.enabled_kinds, kind]
      : channel.enabled_kinds.filter((k) => k !== kind);
    try {
      await api(`/me/notification-channels/${channel.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled_kinds: next }),
      });
      await onChanged();
    } catch {
      toast.add({ title: "Couldn't update that", description: "Try again in a moment." });
    } finally {
      setBusy(null);
    }
  };

  if (channels.length === 0) return null;

  return (
    <Card className="lg:col-span-2" role="region" aria-label="Notification routing">
      <CardHeader>
        <CardTitle>Which notification goes where</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 pr-4 font-normal">Notification</th>
                {channels.map((c) => (
                  <th key={c.id} className="px-2 py-2 text-center font-normal">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(NOTIFICATION_KIND_LABEL).map(([kind, label]) => (
                <tr key={kind} className="border-b last:border-0">
                  <td className="py-2 pr-4">{label}</td>
                  {channels.map((channel) => (
                    <td key={channel.id} className="px-2 py-2">
                      {/* A `<td>` is not a flex container and Base UI's
                          Checkbox root is a plain inline `<span>` — without
                          this wrapper it collapses to a hairline. See
                          CLAUDE.md's Sheets section. */}
                      <div className="flex justify-center">
                        <Checkbox
                          aria-label={`${label} via ${channel.label}`}
                          checked={channel.enabled_kinds.includes(kind)}
                          disabled={busy === `${channel.id}:${kind}`}
                          onCheckedChange={(checked) => toggle(channel, kind, checked === true)}
                        />
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
