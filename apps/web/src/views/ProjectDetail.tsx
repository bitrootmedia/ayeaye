import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  ArrowRightIcon,
  LockIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import { ApiError, api } from "@/api";
import type { Shell } from "@/App";
import { AccessPanel } from "@/components/access-panel";
import { CommentThread } from "@/components/comment-thread";
import { ExportCard } from "@/components/export-card";
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
import {
  Empty,
  EmptyContent,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
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
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import {
  LEVEL_LABEL,
  canAdminister,
  canEdit,
  personName,
  type Member,
  type Project,
  type ProjectAccess,
  type Team,
} from "@/lib/types";

export default function ProjectDetail() {
  const { orgId, projectId } = useParams<{ orgId: string; projectId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const navigate = useNavigate();
  const toast = useToastManager();

  const org = organisations.find((o) => o.id === orgId) ?? null;
  const [project, setProject] = useState<Project | null>(null);
  const [accessInfo, setAccessInfo] = useState<ProjectAccess | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [gone, setGone] = useState(false);

  const load = useCallback(async () => {
    if (!orgId || !projectId) return;
    try {
      const p = await api<Project>(`/organisations/${orgId}/projects/${projectId}`);
      setProject(p);
      const [acc, ms, ts] = await Promise.all([
        api<ProjectAccess>(`/organisations/${orgId}/projects/${projectId}/access`),
        api<Member[]>(`/organisations/${orgId}/members`),
        api<Team[]>(`/organisations/${orgId}/teams`),
      ]);
      setAccessInfo(acc);
      setMembers(ms);
      setTeams(ts);
    } catch (err) {
      // 404 here is the access model working: no route in is indistinguishable
      // from not existing. It's also what you get right after handing the
      // project to someone else.
      if (err instanceof ApiError && err.status === 404) setGone(true);
    }
  }, [orgId, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!org) return null;

  if (gone) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LockIcon />
          </EmptyMedia>
          <EmptyTitle>You don&rsquo;t have access to this project</EmptyTitle>
          <EmptyDescription>
            It may have been deleted, or never shared with you. Projects are private to whoever
            owns them.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button render={<Link to={`/orgs/${org.id}/projects`} />} nativeButton={false}>
            Back to projects
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (!project || !accessInfo) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <Spinner />
        <span className="sr-only">Loading</span>
      </div>
    );
  }

  const editable = canEdit(project.access);
  const admin = canAdminister(project.access);

  const act = async (fn: () => Promise<unknown>, success: string) => {
    try {
      await fn();
      await load();
      toast.add({ title: success });
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: "That didn't work", description: detail });
    }
  };

  return (
    <>
      <PageHeader
        crumbs={[
          { label: org.name, to: `/orgs/${org.id}` },
          { label: "Projects", to: `/orgs/${org.id}/projects` },
          { label: project.name },
        ]}
        title={project.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{LEVEL_LABEL[project.access]}</Badge>
            {project.archived && <Badge variant="outline">Archived</Badge>}
            {project.project_group_name && (
              <span className="text-muted-foreground">in {project.project_group_name}</span>
            )}
            <span className="text-muted-foreground">
              owned by {personName(project.owner)}
            </span>
          </span>
        }
        actions={
          admin && (
            <Button
              variant="ghost"
              onClick={() =>
                act(
                  () =>
                    api(`/organisations/${org.id}/projects/${project.id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ archived: !project.archived }),
                    }),
                  project.archived ? "Restored" : "Archived",
                )
              }
            >
              {project.archived ? <ArchiveRestoreIcon /> : <ArchiveIcon />}
              {project.archived ? "Restore" : "Archive"}
            </Button>
          )
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>About</CardTitle>
            </CardHeader>
            <CardContent>
              <Details project={project} orgId={org.id} editable={editable} onSaved={load} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Tasks</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Tasks in this project inherit its access — whoever can see the project can see
                its tasks, at the same level.
              </p>
              <Button
                variant="outline"
                render={<Link to={`/orgs/${org.id}/tasks?project=${project.id}`} />}
                nativeButton={false}
              >
                Open the board
                <ArrowRightIcon data-icon="inline-end" />
              </Button>
            </CardContent>
          </Card>
          <CommentThread orgId={org.id} anchor="projects" anchorId={project.id} />
        </div>

        <div className="space-y-4">
          <AccessPanel
            orgId={org.id}
            projectId={project.id}
            access={accessInfo}
            members={members}
            teams={teams}
            onChanged={load}
          />

          <ExportCard orgId={org.id} projectId={project.id} />

          {admin && (
            <DangerZone
              orgId={org.id}
              project={project}
              members={members}
              onDeleted={() => navigate(`/orgs/${org.id}/projects`)}
              onTransferred={load}
            />
          )}
        </div>
      </div>
    </>
  );
}

function Details({
  project,
  orgId,
  editable,
  onSaved,
}: {
  project: Project;
  orgId: string;
  editable: boolean;
  onSaved: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");

  if (!editable) {
    return (
      <div className="space-y-2 text-sm">
        <p className={project.description ? "" : "text-muted-foreground"}>
          {project.description || "No description."}
        </p>
        <p className="text-xs text-muted-foreground">
          You have view-only access, so this can&rsquo;t be edited here.
        </p>
      </div>
    );
  }

  const dirty = name !== project.name || description !== (project.description ?? "");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          rows={4}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <Button
        disabled={!dirty || !name.trim()}
        onClick={async () => {
          await api(`/organisations/${orgId}/projects/${project.id}`, {
            method: "PATCH",
            body: JSON.stringify({ name: name.trim(), description }),
          });
          await onSaved();
          toast.add({ title: "Saved" });
        }}
      >
        Save
      </Button>
    </div>
  );
}

function DangerZone({
  orgId,
  project,
  members,
  onDeleted,
  onTransferred,
}: {
  orgId: string;
  project: Project;
  members: Member[];
  onDeleted: () => void;
  onTransferred: () => Promise<void>;
}) {
  const toast = useToastManager();
  const [newOwner, setNewOwner] = useState("");
  const [confirmingTransfer, setConfirmingTransfer] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const candidates = members
    .filter((m) => m.status === "active" && m.user_id && m.user_id !== project.owner?.id)
    .map((m) => ({ value: m.user_id!, label: m.display_name || m.email || "Unknown" }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ownership</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="new-owner">Hand over to</Label>
          <Select items={candidates} value={newOwner} onValueChange={(v) => setNewOwner(String(v))}>
            <SelectTrigger id="new-owner" className="w-full">
              <SelectValue placeholder="Choose someone" />
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
            disabled={!newOwner}
            onClick={() => setConfirmingTransfer(true)}
          >
            Hand over
          </Button>
        </div>

        <div className="space-y-2 rounded-lg border border-destructive/30 p-3">
          <div className="font-medium">Delete this project</div>
          <p className="text-sm text-muted-foreground">
            Everything in it goes too, for everyone it&rsquo;s shared with.
          </p>
          <Button variant="destructive" onClick={() => setConfirmingDelete(true)}>
            <Trash2Icon />
            Delete
          </Button>
        </div>
      </CardContent>

      <Dialog open={confirmingTransfer} onOpenChange={setConfirmingTransfer}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Hand over {project.name}?</DialogTitle>
            {/* The warning that matters: unless you're an org admin or hold a
                separate grant, ownership is your only route in — so handing it
                over removes it from your list entirely. */}
            <DialogDescription>
              They become the owner and take control of who can see it.{" "}
              <strong>You will lose access</strong> unless you administer the organisation or
              someone shares it back with you.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              onClick={async () => {
                await api(`/organisations/${orgId}/projects/${project.id}/owner`, {
                  method: "POST",
                  body: JSON.stringify({ owner_user_id: newOwner }),
                });
                setConfirmingTransfer(false);
                await onTransferred();
                toast.add({ title: "Handed over" });
              }}
            >
              Hand over
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {project.name}?</DialogTitle>
            <DialogDescription>
              This cannot be undone. Type the name to confirm.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={confirmText}
            placeholder={project.name}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              variant="destructive"
              disabled={confirmText !== project.name}
              onClick={async () => {
                await api(`/organisations/${orgId}/projects/${project.id}`, { method: "DELETE" });
                setConfirmingDelete(false);
                toast.add({ title: `${project.name} deleted` });
                onDeleted();
              }}
            >
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
