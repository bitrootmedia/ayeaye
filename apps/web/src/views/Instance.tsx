import { BuildingIcon, ServerCogIcon, ShieldCheckIcon, UsersIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";

import { ApiError, api, apiWithHeaders } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import { ago } from "@/lib/format";
import { lastView, rememberView } from "@/lib/view-preference";
import type { InstanceOrganisation, InstanceTotals, InstanceUser } from "@/lib/types";

const PAGE = 50;

const errorDetail = (err: unknown) =>
  err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";

/** "4m ago", or an em dash. Null is a real answer here — somebody who signed
 *  up and has done nothing at all, which is exactly the shape a registration
 *  script leaves behind and the thing this screen exists to spot. */
const seen = (iso: string | null) => (iso ? ago(iso) : "—");

/**
 * The instance operator's panel: who is on this installation, and stopping
 * abuse.
 *
 * **Reachable only by an account holding an `instance_admins` row**, granted
 * from the shell (`scripts/instance.sh grant-admin`) and never from here —
 * a panel that could appoint its own successors would turn one stolen
 * session into a permanent foothold. The server answers 404 rather than 403
 * to anybody else, so the surface isn't discoverable by guessing the URL;
 * the rail item is hidden for the same reason the Close button is hidden
 * from a non-owner, which is that a control that 403s is worse than no
 * control.
 *
 * **Metadata only, and that is the price of having this on the web at all.**
 * Counts, dates and names — no task title, no comment, no note, no file.
 * This product makes promises an admin deliberately cannot override (a
 * hidden task, a private note, an export that is the requester's alone), and
 * a browsing backoffice would quietly void every one of them. Being an
 * instance admin buys **no** additional access inside any organisation:
 * `services/access.py` never learns this table exists.
 */
export default function Instance() {
  const { me } = useOutletContext<Shell>();
  const [params, setParams] = useSearchParams();
  // Which list, in the URL like every other view toggle in the product. Absent
  // entirely, it falls back to the remembered one rather than a hardcoded
  // default — and remembering happens only on an explicit click, so following
  // a colleague's link doesn't silently become your own preference.
  const requested = params.get("tab") ?? lastView("instance");
  const tab = requested === "organisations" ? "organisations" : "users";
  const [totals, setTotals] = useState<InstanceTotals | null>(null);

  useEffect(() => {
    void api<InstanceTotals>("/instance/overview").then(setTotals).catch(() => setTotals(null));
  }, []);

  const show = (next: "users" | "organisations") => {
    rememberView("instance", next);
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("tab", next);
        p.delete("q");
        return p;
      },
      { replace: true },
    );
  };

  // A non-admin never reaches the API, but the route is still a real URL
  // somebody can type. Say so plainly rather than rendering an empty panel.
  if (me && !me.is_instance_admin) {
    return (
      <PageHeader
        title="Nothing here"
        description="This installation's operator panel isn't yours to see."
      />
    );
  }

  return (
    <>
      <PageHeader
        title="Instance"
        description="Who is on this installation. Counts, dates and names only — never anybody's tasks, comments or notes."
      />

      {totals && <Overview totals={totals} />}

      <div className="flex gap-2">
        <Button
          size="sm"
          variant={tab === "users" ? "default" : "outline"}
          onClick={() => show("users")}
        >
          <UsersIcon />
          People
        </Button>
        <Button
          size="sm"
          variant={tab === "organisations" ? "default" : "outline"}
          onClick={() => show("organisations")}
        >
          <BuildingIcon />
          Organisations
        </Button>
      </div>

      {tab === "users" ? <People meId={me?.id ?? null} /> : <Organisations />}
    </>
  );
}

function Overview({ totals }: { totals: InstanceTotals }) {
  const cells: { label: string; value: number; hint?: string }[] = [
    { label: "Accounts", value: totals.users, hint: `${totals.users_last_24h} in the last 24h` },
    { label: "Suspended", value: totals.disabled_users },
    {
      label: "Organisations",
      value: totals.organisations,
      hint: `${totals.organisations_last_24h} in the last 24h`,
    },
    { label: "Suspended orgs", value: totals.suspended_organisations },
    { label: "Tasks", value: totals.tasks },
  ];
  return (
    <div className="space-y-3">
      {/* A named region, so "Organisations" here is addressable apart from
          the rail link and the tab button that share the word — the same
          reason the task screen's Files and Comments cards are named. */}
      <div
        role="region"
        aria-label="Instance totals"
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5"
      >
        {cells.map((cell) => (
          <Card key={cell.label}>
            <CardContent className="p-3">
              <p className="text-xs text-muted-foreground">{cell.label}</p>
              <p className="font-mono text-2xl tabular-nums">{cell.value}</p>
              {cell.hint && <p className="text-xs text-muted-foreground">{cell.hint}</p>}
            </CardContent>
          </Card>
        ))}
      </div>
      {/* Prevention beats cleanup, and the panel says so — the same note the
          CLI prints, resolved server-side so the two can't disagree. If this
          reads routinely, the gate is open too wide and closing signup or
          turning on EMAIL_VERIFICATION is cheaper than suspending people
          weekly. */}
      {totals.signups_outpacing_organisations && (
        <Card>
          <CardContent className="flex items-start gap-2 p-3 text-sm">
            <ShieldCheckIcon className="mt-0.5 size-4 shrink-0 text-status-review" />
            <span>
              Signups are well ahead of organisations created. That gap is the shape spam takes
              here &mdash; worth a look, and cheaper to close at the door than to clean up
              afterwards.
            </span>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** The search box both lists share. Debounced into the URL, so a lookup an
 *  operator arrived at is one they can paste into a ticket. */
function Filter({ label }: { label: string }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);

  useEffect(() => setDraft(q), [q]);

  useEffect(() => {
    if (draft === q) return;
    const timer = setTimeout(() => {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          if (draft.trim()) p.set("q", draft.trim());
          else p.delete("q");
          return p;
        },
        { replace: true },
      );
    }, 250);
    return () => clearTimeout(timer);
  }, [draft, q, setParams]);

  return (
    <Input
      aria-label={label}
      placeholder={label}
      className="max-w-sm"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
    />
  );
}

function People({ meId }: { meId: string | null }) {
  const toast = useToastManager();
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  const [rows, setRows] = useState<InstanceUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE);
  const [confirming, setConfirming] = useState<InstanceUser | null>(null);

  const load = useCallback(async () => {
    const res = await apiWithHeaders<InstanceUser[]>(
      `/instance/users?limit=${limit}&q=${encodeURIComponent(q)}`,
    ).catch(() => null);
    if (!res) return setRows([]);
    setRows(res.data);
    setTotal(Number(res.headers.get("X-Total-Count") ?? res.data.length));
  }, [limit, q]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setLimit(PAGE);
  }, [q]);

  const restore = async (row: InstanceUser) => {
    try {
      await api(`/instance/users/${row.id}/suspended`, {
        method: "POST",
        body: JSON.stringify({ suspended: false }),
      });
      await load();
      toast.add({ title: `${row.email} can sign in again` });
    } catch (err) {
      toast.add({ title: "Couldn't do that", description: errorDetail(err) });
    }
  };

  return (
    <div className="space-y-3">
      <Filter label="Find an account by address or name" />
      {rows === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : (
        <>
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b text-xs text-muted-foreground">
                  <tr>
                    <th className="p-3 text-left font-medium">Account</th>
                    <th className="p-3 text-right font-medium">Orgs</th>
                    <th className="p-3 text-right font-medium">Tasks</th>
                    <th className="p-3 text-right font-medium">Joined</th>
                    <th className="p-3 text-right font-medium">Last active</th>
                    <th className="p-3 text-right font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id} className="border-b last:border-0">
                      <td className="p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{row.email}</span>
                          {row.is_instance_admin && (
                            <Badge variant="outline" className="font-normal">
                              <ShieldCheckIcon className="size-3" />
                              Instance admin
                            </Badge>
                          )}
                          {row.disabled_at && (
                            <Badge variant="outline" className="font-normal">
                              <span className="size-2 rounded-full bg-status-blocker" />
                              Suspended
                            </Badge>
                          )}
                        </div>
                        {row.display_name && (
                          <p className="text-xs text-muted-foreground">{row.display_name}</p>
                        )}
                        {row.disabled_reason && (
                          <p className="text-xs text-muted-foreground">{row.disabled_reason}</p>
                        )}
                      </td>
                      <td className="p-3 text-right font-mono tabular-nums">{row.organisations}</td>
                      <td className="p-3 text-right font-mono tabular-nums">{row.tasks}</td>
                      <td className="p-3 text-right font-mono text-xs text-muted-foreground">
                        {ago(row.created_at)}
                      </td>
                      <td className="p-3 text-right font-mono text-xs text-muted-foreground">
                        {seen(row.last_active_at)}
                      </td>
                      <td className="p-3 text-right">
                        {/* Absent for your own row rather than disabled-with-a-
                            tooltip: the server refuses it outright, because
                            locking yourself out of the panel you are standing
                            in is recoverable only from a shell you may not
                            have to hand. */}
                        {row.id !== meId &&
                          (row.disabled_at ? (
                            <Button size="sm" variant="outline" onClick={() => restore(row)}>
                              Restore
                            </Button>
                          ) : (
                            <Button size="sm" variant="ghost" onClick={() => setConfirming(row)}>
                              Suspend
                            </Button>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Pager shown={rows.length} total={total} onMore={() => setLimit((n) => n + PAGE)} />
        </>
      )}

      {/* Mounted only while there is something to confirm, and keyed by it.
          The obvious alternative — keep it mounted and clear the fields in an
          effect when the target changes — shipped and was caught by a browser
          test: the target was a fresh object literal on every parent render,
          so the effect refired and wiped the reason somebody had just typed,
          and the suspension landed with no note at all. */}
      {confirming && (
        <SuspendDialog
          key={confirming.id}
          target={{ name: confirming.email, id: confirming.id }}
          kind="account"
          onClose={() => setConfirming(null)}
          onDone={load}
        />
      )}
    </div>
  );
}

function Organisations() {
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  const toast = useToastManager();
  const [rows, setRows] = useState<InstanceOrganisation[] | null>(null);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE);
  const [confirming, setConfirming] = useState<InstanceOrganisation | null>(null);

  const load = useCallback(async () => {
    const res = await apiWithHeaders<InstanceOrganisation[]>(
      `/instance/organisations?limit=${limit}&q=${encodeURIComponent(q)}`,
    ).catch(() => null);
    if (!res) return setRows([]);
    setRows(res.data);
    setTotal(Number(res.headers.get("X-Total-Count") ?? res.data.length));
  }, [limit, q]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setLimit(PAGE);
  }, [q]);

  const restore = async (row: InstanceOrganisation) => {
    try {
      await api(`/instance/organisations/${row.id}/suspended`, {
        method: "POST",
        body: JSON.stringify({ suspended: false }),
      });
      await load();
      toast.add({ title: `${row.name} is open again` });
    } catch (err) {
      toast.add({ title: "Couldn't do that", description: errorDetail(err) });
    }
  };

  return (
    <div className="space-y-3">
      <Filter label="Find an organisation by name or slug" />
      {rows === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : (
        <>
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b text-xs text-muted-foreground">
                  <tr>
                    <th className="p-3 text-left font-medium">Organisation</th>
                    <th className="p-3 text-left font-medium">Owner</th>
                    <th className="p-3 text-right font-medium">People</th>
                    <th className="p-3 text-right font-medium">Tasks</th>
                    <th className="p-3 text-right font-medium">Made</th>
                    <th className="p-3 text-right font-medium">Last active</th>
                    <th className="p-3 text-right font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id} className="border-b last:border-0">
                      <td className="p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{row.name}</span>
                          {row.suspended_at && (
                            <Badge variant="outline" className="font-normal">
                              <span className="size-2 rounded-full bg-status-blocker" />
                              Suspended
                            </Badge>
                          )}
                        </div>
                        <p className="font-mono text-xs text-muted-foreground">{row.slug}</p>
                        {row.suspended_reason && (
                          <p className="text-xs text-muted-foreground">{row.suspended_reason}</p>
                        )}
                      </td>
                      <td className="p-3 text-muted-foreground">{row.owner_email ?? "—"}</td>
                      <td className="p-3 text-right font-mono tabular-nums">{row.members}</td>
                      <td className="p-3 text-right font-mono tabular-nums">{row.tasks}</td>
                      <td className="p-3 text-right font-mono text-xs text-muted-foreground">
                        {ago(row.created_at)}
                      </td>
                      <td className="p-3 text-right font-mono text-xs text-muted-foreground">
                        {seen(row.last_active_at)}
                      </td>
                      <td className="p-3 text-right">
                        {row.suspended_at ? (
                          <Button size="sm" variant="outline" onClick={() => restore(row)}>
                            Restore
                          </Button>
                        ) : (
                          <Button size="sm" variant="ghost" onClick={() => setConfirming(row)}>
                            Suspend
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Pager shown={rows.length} total={total} onMore={() => setLimit((n) => n + PAGE)} />
        </>
      )}

      {confirming && (
        <SuspendDialog
          key={confirming.id}
          target={{ name: confirming.name, id: confirming.id }}
          kind="organisation"
          onClose={() => setConfirming(null)}
          onDone={load}
        />
      )}
    </div>
  );
}

function Pager({
  shown,
  total,
  onMore,
}: {
  shown: number;
  total: number;
  onMore: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="font-mono text-xs text-muted-foreground">
        Showing {shown} of {total}
      </span>
      {shown < total && (
        <Button variant="outline" size="sm" onClick={onMore}>
          Show more
        </Button>
      )}
    </div>
  );
}

/**
 * Suspending asks first, and takes a reason.
 *
 * Not because the server needs one — the field is optional — but because the
 * person who reads this next is usually not the person who typed it, and
 * "suspended" with no note is a decision nobody can review. Restoring gets no
 * dialog: it is the undo, and an undo that interrogates you is friction in
 * the direction you want to be easy.
 */
function SuspendDialog({
  target,
  kind,
  onClose,
  onDone,
}: {
  target: { name: string; id: string };
  kind: "account" | "organisation";
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const toast = useToastManager();
  // Initialised at mount and never reset afterwards. The caller mounts one
  // per target (keyed by id), so "fresh fields for a fresh target" falls out
  // of the component's own lifecycle instead of an effect that can fire again
  // at the worst moment — see the caller's comment.
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const path = kind === "account" ? "users" : "organisations";
      await api(`/instance/${path}/${target.id}/suspended`, {
        method: "POST",
        body: JSON.stringify({ suspended: true, reason: reason.trim() || null }),
      });
      onClose();
      await onDone();
      toast.add({ title: `${target.name} suspended` });
    } catch (err) {
      toast.add({ title: "Couldn't suspend that", description: errorDetail(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Suspend {target.name}?</DialogTitle>
          <DialogDescription>
            {kind === "account" ? (
              <>
                They stop being able to sign in and every session they have open is ended. Nothing
                is deleted, and restoring puts them straight back.
              </>
            ) : (
              <>
                Everybody in it is locked out and told why. Nothing is deleted, nobody is signed
                out of the rest of the product, and restoring puts them all back exactly where
                they were.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="suspend-reason">Reason</Label>
          <Input
            id="suspend-reason"
            autoFocus
            value={reason}
            placeholder={kind === "account" ? "Bulk signups from one IP" : "Spam"}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void submit()}
          />
          <p className="text-xs text-muted-foreground">
            {kind === "account"
              ? "For whoever reviews this later. Not shown to them."
              : "Shown to its members when they try to open it."}
          </p>
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost">Cancel</Button>} />
          <Button onClick={submit} disabled={busy}>
            <ServerCogIcon />
            Suspend
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
