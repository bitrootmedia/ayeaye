import { CrownIcon, ShieldIcon, Trash2Icon, UserPlusIcon, UsersIcon } from "lucide-react";
import { useState } from "react";

import { ApiError, api } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToastManager } from "@/components/ui/toast";
import {
  LEVEL_LABEL,
  personName,
  type GrantLevel,
  type Member,
  type Person,
  type ProjectAccess,
  type Team,
} from "@/lib/types";

/**
 * Who can see this project — the whole answer, on one screen.
 *
 * The design requirement is that access is never something you have to reason
 * about. So all three routes in are listed as first-class rows:
 *
 *   * the owner, who controls the other two;
 *   * explicit grants, by person or by team;
 *   * organisation admins, who see everything whether or not anyone shared it.
 *
 * That last group is the one products usually leave implicit, and leaving it
 * implicit makes this screen a comforting lie. It's rendered greyed and
 * unremovable, which is exactly what it is.
 */
export function AccessPanel({
  basePath,
  access,
  members,
  teams,
  onChanged,
}: {
  /** `/organisations/{orgId}/projects/{projectId}` or
   *  `/organisations/{orgId}/tasks/{taskId}` — both resources expose the
   *  identical `POST/PATCH/DELETE {basePath}/access[/...]` shape, so this
   *  panel doesn't need to know which one it's sharing. */
  basePath: string;
  access: ProjectAccess;
  members: Member[];
  teams: Team[];
  onChanged: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<unknown>, success: string) => {
    setBusy(true);
    try {
      await fn();
      await onChanged();
      toast.add({ title: success });
    } catch (err) {
      const detail =
        err instanceof ApiError && [403, 404, 409, 422].includes(err.status)
          ? (JSON.parse(err.body).detail as string)
          : "Try again in a moment.";
      toast.add({ title: "That didn't work", description: detail });
    } finally {
      setBusy(false);
    }
  };

  // Everyone already accounted for, so the "share with" picker doesn't offer
  // people who would just 409.
  const spokenFor = new Set(
    [
      access.owner?.id,
      ...access.grants.map((g) => g.user?.id),
      ...access.organisation_admins.map((a) => a.id),
    ].filter(Boolean) as string[],
  );
  const grantedTeams = new Set(access.grants.map((g) => g.team?.id).filter(Boolean) as string[]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Who can see this</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Row
          icon={<CrownIcon className="size-4" />}
          title={personName(access.owner)}
          subtitle={access.owner?.display_name ? access.owner.email : undefined}
          badge="Owner"
        />

        {access.grants.map((grant) => (
          <Row
            key={grant.id}
            icon={
              grant.team ? <UsersIcon className="size-4" /> : <ShieldIcon className="size-4" />
            }
            title={grant.team ? grant.team.name : personName(grant.user)}
            subtitle={grant.team ? "Team" : grant.user?.display_name ? grant.user.email : undefined}
            control={
              access.can_manage ? (
                <div className="flex items-center gap-1">
                  <LevelSelect
                    value={grant.level}
                    disabled={busy}
                    onChange={(level) =>
                      act(
                        () =>
                          api(`${basePath}/access/${grant.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({ level }),
                          }),
                        "Access updated",
                      )
                    }
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label="Remove access"
                    disabled={busy}
                    onClick={() =>
                      act(
                        () =>
                          api(`${basePath}/access/${grant.id}`, {
                            method: "DELETE",
                          }),
                        "Access removed",
                      )
                    }
                  >
                    <Trash2Icon />
                  </Button>
                </div>
              ) : (
                <Badge variant="outline">{LEVEL_LABEL[grant.level]}</Badge>
              )
            }
          />
        ))}

        {access.organisation_admins.length > 0 && (
          <div className="space-y-2 rounded-lg border border-dashed p-3">
            <p className="text-xs text-muted-foreground">
              These people administer the organisation, so they can see every project in it. That
              isn&rsquo;t something a project owner can change.
            </p>
            {access.organisation_admins.map((admin) => (
              <Row
                key={admin.id}
                muted
                icon={<ShieldIcon className="size-4" />}
                title={personName(admin)}
                badge="Organisation admin"
              />
            ))}
          </div>
        )}

        {access.can_manage && (
          <ShareRow
            basePath={basePath}
            busy={busy}
            people={members
              .filter((m) => m.status === "active" && m.user_id && !spokenFor.has(m.user_id))
              .map((m) => ({
                id: m.user_id!,
                email: m.email,
                display_name: m.display_name,
              }))}
            teams={teams.filter((t) => !grantedTeams.has(t.id))}
            // Distinguishes "nobody else is here" from "everyone already has
            // it" when the picker comes back empty.
            alreadyShared={members.filter((m) => m.status === "active").length > 1}
            onChanged={onChanged}
          />
        )}
      </CardContent>
    </Card>
  );
}

function Row({
  icon,
  title,
  subtitle,
  badge,
  control,
  muted,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string | null;
  badge?: string;
  control?: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <span
          className={`flex size-8 shrink-0 items-center justify-center rounded-full ${
            muted ? "bg-muted text-muted-foreground" : "bg-accent text-accent-foreground"
          }`}
        >
          {icon}
        </span>
        <div className="min-w-0">
          <div className={`truncate text-sm ${muted ? "text-muted-foreground" : ""}`}>{title}</div>
          {subtitle && (
            <div className="truncate font-mono text-xs text-muted-foreground">{subtitle}</div>
          )}
        </div>
      </div>
      {control ?? (badge && <Badge variant="outline">{badge}</Badge>)}
    </div>
  );
}

function LevelSelect({
  value,
  disabled,
  onChange,
}: {
  value: GrantLevel;
  disabled?: boolean;
  onChange: (level: GrantLevel) => void;
}) {
  const items = [
    { value: "read", label: LEVEL_LABEL.read },
    { value: "write", label: LEVEL_LABEL.write },
  ];
  return (
    <Select
      items={items}
      value={value}
      disabled={disabled}
      onValueChange={(v) => onChange(String(v) as GrantLevel)}
    >
      <SelectTrigger size="sm" aria-label="Access level">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((i) => (
            <SelectItem key={i.value} value={i.value}>
              {i.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

function ShareRow({
  basePath,
  people,
  teams,
  busy,
  alreadyShared,
  onChanged,
}: {
  basePath: string;
  people: Person[];
  teams: Team[];
  busy: boolean;
  alreadyShared: boolean;
  onChanged: () => Promise<void>;
}) {
  const toast = useToastManager();
  // One picker for both principals: values are prefixed so a person and a team
  // with the same name can't collide.
  const items = [
    ...people.map((p) => ({ value: `u:${p.id}`, label: personName(p) })),
    ...teams.map((t) => ({ value: `t:${t.id}`, label: `${t.name} (team)` })),
  ];
  const [who, setWho] = useState("");
  const [level, setLevel] = useState<GrantLevel>("read");

  const share = async () => {
    if (!who) return;
    const [kind, id] = who.split(":");
    const label = items.find((i) => i.value === who)?.label ?? "them";
    try {
      await api(`${basePath}/access`, {
        method: "POST",
        body: JSON.stringify({
          [kind === "u" ? "user_id" : "team_id"]: id,
          level,
        }),
      });
      setWho("");
      await onChanged();
      toast.add({ title: `Shared with ${label}` });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "Couldn't share that", description: detail });
    }
  };

  if (items.length === 0) {
    // Two very different situations, and conflating them was actively
    // misleading: in a one-person organisation this used to read "everyone in
    // this organisation already has access", which flatly contradicts the
    // promise that a project is private to its owner.
    return (
      <p className="border-t pt-4 text-xs text-muted-foreground">
        {alreadyShared
          ? "Everyone else in this organisation already has access. Create a team, or invite more people, to share further."
          : "There's nobody else here yet. Invite people to the organisation and you'll be able to share this with them."}
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-end gap-2 border-t pt-4">
      <div className="min-w-48 flex-1 space-y-2">
        <label className="text-sm font-medium" htmlFor="share-with">
          Share with
        </label>
        <Select items={items} value={who} onValueChange={(v) => setWho(String(v))}>
          <SelectTrigger id="share-with" className="w-full">
            <SelectValue placeholder="Someone, or a team" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {items.map((i) => (
                <SelectItem key={i.value} value={i.value}>
                  {i.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <LevelSelect value={level} onChange={setLevel} />
      <Button onClick={share} disabled={busy || !who}>
        <UserPlusIcon />
        Share
      </Button>
    </div>
  );
}
