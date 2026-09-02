import {
  BanIcon,
  BuildingIcon,
  ClockIcon,
  LinkIcon,
  MailIcon,
  RefreshCwIcon,
  ShieldOffIcon,
  Trash2Icon,
  UserCheckIcon,
  UserPlusIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { CopyLink } from "@/components/copy-link";
import { PageHeader } from "@/components/page-header";
import { PendingBadge, RoleBadge } from "@/components/role-badge";
import { WorkingHoursGrid } from "@/components/working-hours-grid";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToastManager } from "@/components/ui/toast";
import { forgetOrg } from "@/lib/current-org";
import {
  ROLE_HELP,
  ROLE_LABEL,
  canActOn,
  canManageMembers,
  grantableRoles,
  type InviteCreated,
  type Member,
  type Role,
  type WorkingHours,
} from "@/lib/types";
import { convertWeek } from "@/lib/working-hours";

/**
 * Who is in this organisation, and getting more people into it.
 *
 * Everyone can read the roster — once projects are private by default, this is
 * the only place that answers "who could I share this with", so hiding it
 * would make the access model unusable rather than more private. What changes
 * with role is what you can *do*: the controls simply aren't rendered for
 * someone who can't use them, based on the role the API resolved.
 */
export default function OrganisationDetail() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations, me, reload } = useOutletContext<Shell>();
  const navigate = useNavigate();
  const toast = useToastManager();

  const org = organisations.find((o) => o.id === orgId) ?? null;
  const [members, setMembers] = useState<Member[] | null>(null);
  const [inviting, setInviting] = useState(false);
  const [lastInvite, setLastInvite] = useState<InviteCreated | null>(null);
  // A real member (active or disabled) is a person whose projects and tasks
  // get reassigned on removal — an outstanding invitation never had any of
  // that, so revoking one stays instant below rather than routing through
  // this.
  const [confirmRemove, setConfirmRemove] = useState<Member | null>(null);
  const [whMember, setWhMember] = useState<Member | null>(null);

  const loadMembers = useCallback(async () => {
    if (!orgId) return;
    try {
      setMembers(await api<Member[]>(`/organisations/${orgId}/members`));
    } catch {
      setMembers([]);
    }
  }, [orgId]);

  useEffect(() => {
    void loadMembers();
  }, [loadMembers]);

  // The shell only renders its children once `/organisations` has come back,
  // so a miss here is not "still loading" — it means this organisation was
  // deleted, or you were removed from it, or it was never yours. Say so.
  // Spinning forever is what this did before, and it's indistinguishable from
  // the app being broken. Reachable in normal use: signing in returns you to
  // the organisation you were last in, which may be gone by now.
  if (!org) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BuildingIcon />
          </EmptyMedia>
          <EmptyTitle>You don&rsquo;t have access to this organisation</EmptyTitle>
          <EmptyDescription>
            It may have been deleted, or you may have been removed from it.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button render={<Link to="/" />} nativeButton={false}>
            Your organisations
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  const manage = canManageMembers(org.role);

  const act = async (fn: () => Promise<unknown>, success: string) => {
    try {
      await fn();
      await Promise.all([loadMembers(), reload()]);
      toast.add({ title: success });
    } catch (err) {
      // 409 carries a real explanation from the server — the last-owner rule,
      // usually — and it's more useful than anything generic we'd invent.
      const detail =
        err instanceof ApiError && err.status === 409
          ? (JSON.parse(err.body).detail as string)
          : "Try again in a moment.";
      toast.add({ title: "That didn't work", description: detail });
    }
  };

  return (
    <>
      <PageHeader
        crumbs={[
          { label: "Organisations", to: "/" },
          { label: org.name, to: `/orgs/${org.id}` },
          { label: "People" },
        ]}
        title={org.name}
        description={
          <>
            <span className="font-mono text-xs">{org.slug}</span> · you are{" "}
            {ROLE_LABEL[org.role].toLowerCase()}
          </>
        }
        actions={
          manage && (
            <Button onClick={() => setInviting(true)}>
              <UserPlusIcon />
              Invite
            </Button>
          )
        }
      />

      {lastInvite && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LinkIcon className="size-4" />
              Invitation for {lastInvite.member.email}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {lastInvite.emailed
                ? "We've emailed them this link. You can also send it yourself."
                : "Email isn't configured on this server, so nothing was sent — copy this link to them."}
            </p>
            <CopyLink value={lastInvite.invite_url} label="Invitation link" />
            <p className="text-xs text-muted-foreground">
              Anyone who opens this joins as {ROLE_LABEL[lastInvite.member.role].toLowerCase()}.
              It stops working once used, and you can revoke it below.
            </p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>People</CardTitle>
        </CardHeader>
        <CardContent>
          {members === null ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Person</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((member) => {
                  const isMe = member.user_id != null && member.user_id === me?.id;
                  const mayAct = manage && canActOn(org.role, member.role);
                  return (
                    <TableRow key={member.id}>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="flex items-center gap-2">
                            {member.display_name || member.email || "—"}
                            {isMe && (
                              <span className="text-xs text-muted-foreground">(you)</span>
                            )}
                            <PendingBadge status={member.status} />
                          </span>
                          {member.display_name && member.email && (
                            <span className="font-mono text-xs text-muted-foreground">
                              {member.email}
                            </span>
                          )}
                          {member.status === "invited" && member.invited_by && (
                            <span className="text-xs text-muted-foreground">
                              invited by {member.invited_by}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        {mayAct ? (
                          <RoleSelect
                            value={member.role}
                            options={grantableRoles(org.role)}
                            onChange={(role) =>
                              act(
                                () =>
                                  api(`/organisations/${org.id}/members/${member.id}`, {
                                    method: "PATCH",
                                    body: JSON.stringify({ role }),
                                  }),
                                "Role updated",
                              )
                            }
                          />
                        ) : (
                          <RoleBadge role={member.role} />
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {member.accepted_at
                          ? new Date(member.accepted_at).toLocaleDateString()
                          : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          {member.user_id && (
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`Working hours for ${
                                member.display_name || member.email
                              }`}
                              onClick={() => setWhMember(member)}
                            >
                              <ClockIcon />
                            </Button>
                          )}
                          {member.invite_url && (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label="Copy invitation link"
                                onClick={() =>
                                  setLastInvite({
                                    member,
                                    invite_url: member.invite_url!,
                                    emailed: false,
                                  })
                                }
                              >
                                <LinkIcon />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label="Issue a new link"
                                onClick={() =>
                                  act(async () => {
                                    const fresh = await api<Member>(
                                      `/organisations/${org.id}/members/${member.id}/invite-link`,
                                      { method: "POST" },
                                    );
                                    setLastInvite({
                                      member: fresh,
                                      invite_url: fresh.invite_url!,
                                      emailed: false,
                                    });
                                  }, "New link issued — the old one no longer works")
                                }
                              >
                                <RefreshCwIcon />
                              </Button>
                            </>
                          )}
                          {mayAct && member.status !== "invited" && (
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={member.status === "disabled" ? "Enable" : "Disable"}
                              onClick={() =>
                                act(
                                  () =>
                                    api(
                                      `/organisations/${org.id}/members/${member.id}/${
                                        member.status === "disabled" ? "enable" : "disable"
                                      }`,
                                      { method: "POST" },
                                    ),
                                  member.status === "disabled" ? "Enabled" : "Disabled",
                                )
                              }
                            >
                              {member.status === "disabled" ? <UserCheckIcon /> : <BanIcon />}
                            </Button>
                          )}
                          {mayAct && member.status === "active" && (
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label="Reset their two-factor authentication"
                              onClick={() =>
                                act(
                                  () =>
                                    api(
                                      `/organisations/${org.id}/members/${member.id}/reset-mfa`,
                                      { method: "POST" },
                                    ),
                                  "They'll be asked to set up two-factor authentication again next time they sign in",
                                )
                              }
                            >
                              <ShieldOffIcon />
                            </Button>
                          )}
                          {(mayAct || isMe) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={
                                isMe
                                  ? "Leave"
                                  : member.status === "invited"
                                    ? "Revoke invitation"
                                    : "Remove"
                              }
                              onClick={() => {
                                // A pending invitation has no real presence
                                // yet — nothing to reassign, nothing at risk
                                // — so revoking one stays a single click.
                                if (member.status === "invited") {
                                  void act(
                                    () =>
                                      api(`/organisations/${org.id}/members/${member.id}`, {
                                        method: "DELETE",
                                      }),
                                    "Invitation revoked",
                                  );
                                  return;
                                }
                                setConfirmRemove(member);
                              }}
                            >
                              <Trash2Icon />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <InviteDialog
        open={inviting}
        onOpenChange={setInviting}
        orgId={org.id}
        roles={grantableRoles(org.role)}
        onInvited={async (created) => {
          setLastInvite(created);
          await loadMembers();
        }}
      />

      <Dialog
        open={confirmRemove !== null}
        onOpenChange={(open) => !open && setConfirmRemove(null)}
      >
        <DialogContent>
          {confirmRemove && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {confirmRemove.user_id === me?.id
                    ? "Leave this organisation?"
                    : `Remove ${confirmRemove.display_name || confirmRemove.email}?`}
                </DialogTitle>
                <DialogDescription>
                  {confirmRemove.user_id === me?.id
                    ? "You lose access immediately. Any project or task you own here is reassigned to another owner — re-inviting yourself later doesn't undo that."
                    : "They lose access immediately. Any project or task they own is reassigned to another owner. You can invite them again later, but this doesn't undo by itself."}
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
                <Button
                  variant="destructive"
                  onClick={() => {
                    const member = confirmRemove;
                    const isSelf = member.user_id === me?.id;
                    setConfirmRemove(null);
                    void act(async () => {
                      await api(`/organisations/${org.id}/members/${member.id}`, {
                        method: "DELETE",
                      });
                      if (isSelf) {
                        forgetOrg(org.id);
                        navigate("/");
                      }
                    }, isSelf ? "You've left" : "Removed");
                  }}
                >
                  {confirmRemove.user_id === me?.id ? "Leave" : "Remove"}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <WorkingHoursDialog
        member={whMember}
        orgId={org.id}
        myTimezone={me?.timezone ?? null}
        onOpenChange={(open) => !open && setWhMember(null)}
      />
    </>
  );
}

function WorkingHoursDialog({
  member,
  orgId,
  myTimezone,
  onOpenChange,
}: {
  member: Member | null;
  orgId: string;
  myTimezone: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [data, setData] = useState<WorkingHours | null>(null);

  useEffect(() => {
    if (!member?.user_id) return;
    setData(null);
    void api<WorkingHours>(`/organisations/${orgId}/members/${member.user_id}/working-hours`)
      .then(setData)
      .catch(() => setData({ timezone: null, cells: [] }));
  }, [member, orgId]);

  // Only worth a second, converted grid when both timezones are known and
  // actually differ — nothing honest to convert to otherwise.
  const converted =
    data?.timezone && myTimezone && data.timezone !== myTimezone
      ? convertWeek(data.cells, data.timezone, myTimezone)
      : null;

  return (
    <Dialog open={member !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        {member && (
          <>
            <DialogHeader>
              <DialogTitle>
                {member.display_name || member.email}&rsquo;s working hours
              </DialogTitle>
              <DialogDescription>
                {data?.timezone
                  ? `Recorded in ${data.timezone}.`
                  : "No timezone on record — shown as entered."}
              </DialogDescription>
            </DialogHeader>
            {data === null ? (
              <div className="flex justify-center py-8">
                <Spinner />
              </div>
            ) : (
              <div className="space-y-4">
                <WorkingHoursGrid cells={data.cells} />
                {data.cells.length === 0 && (
                  <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>
                )}
                {converted && (
                  <div className="space-y-1 border-t pt-3">
                    <p className="text-xs font-medium text-muted-foreground">
                      In your timezone ({myTimezone})
                    </p>
                    <WorkingHoursGrid cells={converted} />
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function RoleSelect({
  value,
  options,
  onChange,
}: {
  value: Role;
  options: Role[];
  onChange: (role: Role) => void;
}) {
  // The current role may be above anything this actor can grant — an owner
  // listed by another owner, say. Keep it in the list or the select renders
  // blank and looks broken.
  const items = Array.from(new Set([value, ...options])).map((r) => ({
    value: r,
    label: ROLE_LABEL[r],
  }));
  return (
    <Select
      items={items}
      value={value}
      onValueChange={(v) => onChange(String(v) as Role)}
    >
      <SelectTrigger size="sm" aria-label="Role">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

function InviteDialog({
  open,
  onOpenChange,
  orgId,
  roles,
  onInvited,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  roles: Role[];
  onInvited: (created: InviteCreated) => void | Promise<void>;
}) {
  const toast = useToastManager();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!email.trim() || busy) return;
    setBusy(true);
    try {
      const created = await api<InviteCreated>(`/organisations/${orgId}/invites`, {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), role }),
      });
      setEmail("");
      onOpenChange(false);
      await onInvited(created);
    } catch (err) {
      const detail =
        err instanceof ApiError && (err.status === 409 || err.status === 422)
          ? (JSON.parse(err.body).detail as string)
          : "Try again in a moment.";
      toast.add({
        title: "Couldn't send that invitation",
        description: typeof detail === "string" ? detail : "Check the address.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite someone</DialogTitle>
          <DialogDescription>
            They don&rsquo;t need an account yet — the invitation waits for them.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              autoFocus
              value={email}
              placeholder="them@example.com"
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-role">Role</Label>
            <RoleSelect value={role} options={roles} onChange={setRole} />
            <p className="text-xs text-muted-foreground">{ROLE_HELP[role]}</p>
          </div>
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <MailIcon className="mt-0.5 size-3.5 shrink-0" />
            You&rsquo;ll get a copyable link either way, so this works even with no email
            configured.
          </p>
        </div>

        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
          <Button onClick={submit} disabled={busy || !email.trim()}>
            Send invitation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
