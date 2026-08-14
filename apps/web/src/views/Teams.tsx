import {
  ArchiveIcon,
  FolderIcon,
  PlusIcon,
  TagIcon,
  Trash2Icon,
  UsersIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
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
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";
import {
  canManageMembers,
  personName,
  type Member,
  type ProjectGroup,
  type Tag,
  type TeamDetail,
} from "@/lib/types";

/**
 * Teams and project groups — the organisation's shared structure.
 *
 * Both are readable by everyone and editable by admins. A team is a grant
 * target, so a project owner who can't see the list of teams can't share with
 * one; a members-only roster would make the access model unusable.
 */
export default function Teams() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  const [teams, setTeams] = useState<TeamDetail[] | null>(null);
  const [groups, setGroups] = useState<ProjectGroup[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);

  const load = useCallback(async () => {
    if (!orgId) return;
    const [list, gs, ms, ts] = await Promise.all([
      api<{ id: string }[]>(`/organisations/${orgId}/teams`),
      api<ProjectGroup[]>(`/organisations/${orgId}/project-groups`),
      api<Member[]>(`/organisations/${orgId}/members`),
      api<Tag[]>(`/organisations/${orgId}/tags`),
    ]);
    // The list endpoint returns headcounts; the detail endpoint returns who.
    // Fetched per team because a roster is what this screen is *for* — the
    // list view elsewhere deliberately doesn't pay for it.
    const detailed = await Promise.all(
      list.map((t) => api<TeamDetail>(`/organisations/${orgId}/teams/${t.id}`)),
    );
    setTeams(detailed);
    setGroups(gs);
    setMembers(ms);
    setTags(ts);
  }, [orgId]);

  useEffect(() => {
    void load().catch(() => setTeams([]));
  }, [load]);

  if (!org) return null;
  const manage = canManageMembers(org.role);

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Structure" }]}
        title="Teams and groups"
        description="Teams are who you share with. Groups are how projects are filed."
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <UsersIcon className="size-4" />
              Teams
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {teams === null ? (
              <div className="flex justify-center py-6">
                <Spinner />
              </div>
            ) : teams.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No teams yet. A team lets you grant a project to a group of people once, instead
                of to each of them every time somebody joins.
              </p>
            ) : (
              teams.map((team) => (
                <TeamCard
                  key={team.id}
                  orgId={org.id}
                  team={team}
                  members={members}
                  manage={manage}
                  onChanged={load}
                />
              ))
            )}
            {manage && (
              <CreateRow
                label="New team"
                placeholder="Design"
                onCreate={(name) =>
                  api(`/organisations/${org.id}/teams`, {
                    method: "POST",
                    body: JSON.stringify({ name }),
                  }).then(load)
                }
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FolderIcon className="size-4" />
              Project groups
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Said plainly, because "folder" strongly implies "shared folder"
                and here it does not. */}
            <p className="text-sm text-muted-foreground">
              Groups are labels for tidiness. Filing a project in one grants nobody access to it.
            </p>
            {groups.map((group) => (
              <div
                key={group.id}
                className="flex items-center justify-between gap-2 rounded-lg border p-2 pl-3"
              >
                <span className="truncate text-sm">{group.name}</span>
                {manage && (
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Delete ${group.name}`}
                    onClick={async () => {
                      await api(`/organisations/${org.id}/project-groups/${group.id}`, {
                        method: "DELETE",
                      });
                      await load();
                    }}
                  >
                    <Trash2Icon />
                  </Button>
                )}
              </div>
            ))}
            {manage && (
              <CreateRow
                label="New group"
                placeholder="Q3"
                onCreate={(name) =>
                  api(`/organisations/${org.id}/project-groups`, {
                    method: "POST",
                    body: JSON.stringify({ name }),
                  }).then(load)
                }
              />
            )}
          </CardContent>
        </Card>
        <Card role="region" aria-label="Tags">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TagIcon className="size-4" />
              Tags
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Anyone can add a tag to a task, and typing one that already exists finds it rather
              than making a second. Renaming or deleting one here changes it everywhere.
            </p>
            {tags.map((tag) => (
              <div
                key={tag.id}
                className="flex items-center justify-between gap-2 rounded-lg border p-2 pl-3"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm">{tag.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {tag.task_count}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  {/* The property that changes behaviour, so it's a control
                      rather than a label — and it says what it does. */}
                  {manage ? (
                    <Button
                      variant={tag.off_board ? "secondary" : "ghost"}
                      size="sm"
                      aria-label={
                        tag.off_board
                          ? `Put ${tag.name} back on the board`
                          : `Keep ${tag.name} off the board`
                      }
                      onClick={async () => {
                        await api(`/organisations/${org.id}/tags/${tag.id}`, {
                          method: "PATCH",
                          body: JSON.stringify({ off_board: !tag.off_board }),
                        });
                        await load();
                      }}
                    >
                      <ArchiveIcon />
                      {tag.off_board ? "Off the board" : "On the board"}
                    </Button>
                  ) : (
                    tag.off_board && (
                      <Badge variant="outline" className="gap-1">
                        <ArchiveIcon className="size-3" />
                        Off the board
                      </Badge>
                    )
                  )}
                  {manage && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Delete ${tag.name}`}
                      onClick={async () => {
                        await api(`/organisations/${org.id}/tags/${tag.id}`, { method: "DELETE" });
                        await load();
                      }}
                    >
                      <Trash2Icon />
                    </Button>
                  )}
                </span>
              </div>
            ))}
            {tags.length === 0 && (
              <p className="text-sm text-muted-foreground">
                None yet. They&rsquo;re made from a task, where they get used.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              A tag kept <span className="font-medium">off the board</span> takes its tasks out of
              the board and the list — that&rsquo;s how a knowledge-base item stops queueing for
              attention. It stays searchable and shows up when you filter for the tag.
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function CreateRow({
  label,
  placeholder,
  onCreate,
}: {
  label: string;
  placeholder: string;
  onCreate: (name: string) => Promise<unknown>;
}) {
  const toast = useToastManager();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await onCreate(name.trim());
      setName("");
    } catch (err) {
      const detail =
        err instanceof ApiError && err.status === 409
          ? (JSON.parse(err.body).detail as string)
          : "Try again.";
      toast.add({ title: `Couldn't create that`, description: detail });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex gap-2 border-t pt-3">
      <Input
        value={name}
        placeholder={placeholder}
        aria-label={label}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      <Button variant="outline" onClick={submit} disabled={busy || !name.trim()}>
        <PlusIcon />
        {label}
      </Button>
    </div>
  );
}

function TeamCard({
  orgId,
  team,
  members,
  manage,
  onChanged,
}: {
  orgId: string;
  team: TeamDetail;
  members: Member[];
  manage: boolean;
  onChanged: () => Promise<void>;
}) {
  const [adding, setAdding] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const onTeam = new Set(team.members.map((m) => m.id));
  const candidates = members
    .filter((m) => m.status === "active" && m.user_id && !onTeam.has(m.user_id))
    .map((m) => ({ value: m.user_id!, label: m.display_name || m.email || "Unknown" }));

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium">{team.name}</span>
          <Badge variant="outline" className="font-mono">
            {team.members.length}
          </Badge>
        </div>
        {manage && (
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Delete ${team.name}`}
            onClick={() => setConfirmingDelete(true)}
          >
            <Trash2Icon />
          </Button>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {team.members.length === 0 && (
          <span className="text-xs text-muted-foreground">Nobody on this team yet.</span>
        )}
        {team.members.map((person) => (
          <Badge key={person.id} variant="outline" className="gap-1 pr-1">
            {personName(person)}
            {manage && (
              <button
                type="button"
                aria-label={`Remove ${personName(person)}`}
                className="rounded-sm p-0.5 hover:bg-muted"
                onClick={async () => {
                  await api(`/organisations/${orgId}/teams/${team.id}/members/${person.id}`, {
                    method: "DELETE",
                  });
                  await onChanged();
                }}
              >
                <XIcon className="size-3" />
              </button>
            )}
          </Badge>
        ))}
      </div>

      {manage && candidates.length > 0 && (
        <div className="flex gap-2">
          <Select items={candidates} value={adding} onValueChange={(v) => setAdding(String(v))}>
            <SelectTrigger size="sm" className="flex-1" aria-label={`Add to ${team.name}`}>
              <SelectValue placeholder="Add someone" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {candidates.map((c) => (
                  <SelectItem key={c.value} value={c.value}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            disabled={!adding}
            onClick={async () => {
              await api(`/organisations/${orgId}/teams/${team.id}/members`, {
                method: "POST",
                body: JSON.stringify({ user_id: adding }),
              });
              setAdding("");
              await onChanged();
            }}
          >
            Add
          </Button>
        </div>
      )}

      <Dialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {team.name}?</DialogTitle>
            {/* The consequence people don't think about: grants made to this
                team disappear with it, and nothing records that they existed. */}
            <DialogDescription>
              Every project shared with this team stops being shared with it, and its{" "}
              {team.members.length} member{team.members.length === 1 ? "" : "s"} lose that access
              unless they have it another way.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              variant="destructive"
              onClick={async () => {
                await api(`/organisations/${orgId}/teams/${team.id}`, { method: "DELETE" });
                setConfirmingDelete(false);
                await onChanged();
              }}
            >
              Delete team
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
